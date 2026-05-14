# -*- coding: utf-8 -*-
"""PlanningAI の (beam_width, max_depth) grid search。

3 デッキ (= 旧 cross matrix で +59 / +41 / -2pt と振れた代表) を baseline 用に選び、
各 (beam, depth) 組合せで Planning vs Greedy を n=8 戦回す。
強さ (= winrate delta vs Greedy baseline) と速度 (= s/game) を出して
default 採用案を決める。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.harness import run_matchup
from engine.ai import GreedyAI, PlanningAI


# 計測デッキ (= 多様な強弱配置): ルーシー (弱+59pt) / エネル (中+16) / ミホーク (弱+41) / ナミ (強+31)
# 同じ deck も a/b 反転で 4 配置 (= Planning が弱側 / 強側 / 互角 を網羅)
TEST_DECKS = [
    ("cardrush_1399", "cardrush_1424"),  # 赤青ルーシー (弱) vs 紫エネル (中)
    ("cardrush_1424", "cardrush_1437"),  # 紫エネル (強) vs 緑ミホーク (弱) — 元 profile
    ("cardrush_1439", "cardrush_1424"),  # 青黄ナミ (強) vs 紫エネル (中)
    ("cardrush_1437", "cardrush_1439"),  # 緑ミホーク (弱) vs 青黄ナミ (強)
]


def planning_factory(beam: int, depth: int):
    def _f(rng=None, deck_analysis=None):
        return PlanningAI(
            rng=rng, deck_analysis=deck_analysis,
            beam_width=beam, max_depth=depth,
        )
    return _f


def run_pair(deck_a_slug: str, deck_b_slug: str, ai_a, ai_b, n_games: int, seed: int):
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    deck_a = DeckList.from_json(ROOT / "decks" / f"{deck_a_slug}.json", repo)
    deck_b = DeckList.from_json(ROOT / "decks" / f"{deck_b_slug}.json", repo)
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    t0 = time.perf_counter()
    report = run_matchup(
        deck_a, deck_b, n_games=n_games, seed=seed,
        ai_factory_1=ai_a, ai_factory_2=ai_b,
        effects_overlay=overlay,
    )
    elapsed = time.perf_counter() - t0
    return {
        "winrate": report.deck1_winrate,
        "elapsed": elapsed,
        "per_game": elapsed / n_games,
    }


def main():
    n_games = 8
    seed = 42

    # Greedy vs Greedy baseline
    print("=== Greedy baseline ===")
    baselines = {}
    for (a, b) in TEST_DECKS:
        r = run_pair(a, b, GreedyAI, GreedyAI, n_games, seed)
        baselines[(a, b)] = r["winrate"]
        print(f"  {a} vs {b}: winrate={r['winrate']:.1%} ({r['per_game']:.1f}s/g)")

    # Planning configs
    configs = [
        (2, 4),
        (2, 6),
        (3, 4),
        (3, 6),
        (4, 4),
        (4, 6),
        (4, 8),  # 現 default
    ]
    print("\n=== Planning configs ===")
    print(f"{'beam':>5} {'depth':>6} {'avg Δ':>8} {'avg s/g':>9}")
    rows = []
    for beam, depth in configs:
        ai = planning_factory(beam, depth)
        deltas = []
        per_games = []
        for (a, b) in TEST_DECKS:
            r = run_pair(a, b, ai, GreedyAI, n_games, seed)
            delta = (r["winrate"] - baselines[(a, b)]) * 100
            deltas.append(delta)
            per_games.append(r["per_game"])
        avg_delta = sum(deltas) / len(deltas)
        avg_pg = sum(per_games) / len(per_games)
        print(f"{beam:>5} {depth:>6} {avg_delta:>+7.1f}pt {avg_pg:>8.1f}s")
        rows.append({
            "beam": beam, "depth": depth,
            "avg_delta_pt": avg_delta, "avg_s_per_game": avg_pg,
            "deltas": deltas, "per_games": per_games,
        })

    out = ROOT / "db" / "planning_grid_search.json"
    out.write_text(json.dumps({"baselines": {f"{a}|{b}": v for (a, b), v in baselines.items()}, "rows": rows}, indent=2, ensure_ascii=False))
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    main()
