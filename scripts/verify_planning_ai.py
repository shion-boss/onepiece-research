# -*- coding: utf-8 -*-
"""PlanningAI 検証: 紫エネル vs 緑ミホーク を Greedy vs Greedy / Planning vs Greedy /
Greedy vs Planning / Planning vs Planning の 4 構成で 10-20 戦 sim。

勝率 / 平均試合時間 / bad_moves 率を比較。
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.harness import run_matchup
from engine.ai import GreedyAI, PlanningAI


def planning_factory(beam=4, depth=8):
    def _f(rng=None, deck_analysis=None):
        return PlanningAI(rng=rng, deck_analysis=deck_analysis, beam_width=beam, max_depth=depth)
    return _f


def compute_bad_move_rate(report) -> tuple[float, int]:
    """各 game の state.action_evals から delta_eval < -3000 の 非 EndPhase action 比率。"""
    total_actions = 0
    bad_actions = 0
    for game in report.games:
        for ev in game.action_evals:
            atype = ev.get("action_type", "")
            if atype == "EndPhase":
                continue
            total_actions += 1
            delta = ev.get("delta", 0)
            if delta < -3000:
                bad_actions += 1
    if total_actions == 0:
        return 0.0, 0
    return bad_actions / total_actions * 100, total_actions


def run_config(label: str, factory_a, factory_b, n_games: int, seed: int):
    print(f"\n--- {label} (n={n_games}) ---")
    t0 = time.perf_counter()
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    deck_a = DeckList.from_json(ROOT / "decks" / "cardrush_1424.json", repo)
    deck_b = DeckList.from_json(ROOT / "decks" / "cardrush_1437.json", repo)
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    report = run_matchup(
        deck_a, deck_b, n_games=n_games, seed=seed,
        ai_factory_1=factory_a, ai_factory_2=factory_b,
        effects_overlay=overlay,
    )
    elapsed = time.perf_counter() - t0
    bad_rate, total_acts = compute_bad_move_rate(report)
    print(f"  {report.deck1_name} winrate: {report.deck1_winrate:.1%} ({report.deck1_wins}/{n_games})")
    print(f"  draws: {report.draws}")
    print(f"  avg turns: {report.avg_turns:.1f}")
    print(f"  bad_move_rate: {bad_rate:.2f}% ({total_acts} non-End actions)")
    print(f"  total time: {elapsed:.1f}s ({elapsed/n_games:.1f}s/game)")
    return {
        "label": label,
        "winrate": report.deck1_winrate,
        "wins": report.deck1_wins,
        "n": n_games,
        "draws": report.draws,
        "avg_turns": report.avg_turns,
        "bad_rate": bad_rate,
        "elapsed": elapsed,
    }


def main():
    print("=== PlanningAI 検証: 紫エネル vs 緑ミホーク ===")
    print("(deck_a = 紫エネル, deck_b = 緑ミホーク)")

    n = 20
    seed = 42
    results = []
    # Baseline: Greedy vs Greedy (= matrix 計算済値 = 77%)
    results.append(run_config("Greedy_a vs Greedy_b", GreedyAI, GreedyAI, n, seed))
    # 片側 Planning
    results.append(run_config("Planning_a vs Greedy_b", planning_factory(beam=4, depth=8), GreedyAI, n, seed))
    results.append(run_config("Greedy_a vs Planning_b", GreedyAI, planning_factory(beam=4, depth=8), n, seed))
    # 両側 Planning (= 重いので少なめ)
    n2 = 10
    results.append(run_config("Planning_a vs Planning_b", planning_factory(beam=4, depth=8), planning_factory(beam=4, depth=8), n2, seed))

    print("\n=== Summary ===")
    print(f"{'config':<32} {'winrate':>8} {'time/game':>10} {'bad%':>6}")
    for r in results:
        print(f"  {r['label']:<30} {r['winrate']:>7.1%} {r['elapsed']/r['n']:>9.1f}s {r['bad_rate']:>5.2f}%")


if __name__ == "__main__":
    main()
