#!/usr/bin/env python3
"""層1 検証: ターンプラン網羅列挙が「爆発しない」か実測 (= ohtsuki 仮説)。

GreedyAI 同士の self-play を回し、 各ターンの MAIN 開始 state で
enumerate_turn_plans を呼んで「到達可能な相異盤面の数 (= プラン数)」を実測。
turn 別に分布 (mean / max / capped) を集計して、 DON 制約で爆発しないことを確認する。

使い方:
  .venv/bin/python -u scripts/measure_plan_enumeration.py
  .venv/bin/python -u scripts/measure_plan_enumeration.py --decks cardrush_1342 tcgportal_op11_luffy --games 6
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import Phase, setup_game, play_until_main
from engine.ai import GreedyAI, play_one_action
from engine.turn_plan_enumerator import enumerate_turn_plans

_REPO = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(REPO_ROOT / "db" / "card_effects.json")
_DECKS_DIR = REPO_ROOT / "decks"


def _load_deck(slug: str):
    d = json.loads((_DECKS_DIR / f"{slug}.json").read_text(encoding="utf-8"))
    return make_deck_from_dict(d, _REPO)


def measure_game(slug_a: str, slug_b: str, seed: int, node_cap: int,
                 max_turns_measured: int, rows: list) -> None:
    deck_a = _load_deck(slug_a)
    deck_b = _load_deck(slug_b)
    rng = random.Random(seed)
    first_player = seed % 2
    state = setup_game(deck_a, deck_b, rng=rng, first_player=first_player,
                       effects_overlay=_OVERLAY)
    play_until_main(state)

    ais = [GreedyAI(random.Random(seed * 7 + 1)), GreedyAI(random.Random(seed * 7 + 2))]
    enum_defender = GreedyAI(random.Random(seed * 13 + 3))

    measured: set = set()
    max_actions = 600
    n_actions = 0
    while not state.game_over and n_actions < max_actions:
        me = state.turn_player_idx
        key = (state.turn_number, me)
        if (
            state.phase == Phase.MAIN
            and key not in measured
            and state.turn_number <= max_turns_measured
        ):
            measured.add(key)
            t0 = time.perf_counter()
            try:
                plans, st = enumerate_turn_plans(
                    state, me, defender_ai=enum_defender, node_cap=node_cap,
                )
                elapsed = time.perf_counter() - t0
                row = {
                    "turn": state.turn_number,
                    "actor": me,
                    "n_plans": len(plans),
                    "distinct_boards": st["distinct_boards"],
                    "nodes": st["nodes_expanded"],
                    "capped": st["capped"],
                    "start_legal": st["start_legal"],
                    "ms": round(elapsed * 1000, 1),
                    "don": int(getattr(state.players[me], "don_active", 0)),
                }
                rows.append(row)
                print(f"    T{row['turn']:>2} actor={me} don={row['don']:>2} "
                      f"legal={row['start_legal']:>2} -> plans={row['n_plans']:>6} "
                      f"nodes={row['nodes']:>7} {row['ms']:>8.1f}ms "
                      f"{'CAPPED' if row['capped'] else ''}", flush=True)
            except Exception as e:
                rows.append({"turn": state.turn_number, "actor": me, "error": repr(e)})
        play_one_action(state, ais[me], ais[1 - me])
        n_actions += 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--decks", nargs="+",
                    default=["cardrush_1342", "tcgportal_op11_luffy", "cardrush_1392"])
    ap.add_argument("--games", type=int, default=6, help="matchup あたり game 数 (seed 違い)")
    ap.add_argument("--node-cap", type=int, default=80000)
    ap.add_argument("--max-turns", type=int, default=14)
    args = ap.parse_args()

    # matchup = 各 deck の mirror + 隣接 deck との cross
    decks = args.decks
    matchups = []
    for i, a in enumerate(decks):
        matchups.append((a, a))                       # mirror
        matchups.append((a, decks[(i + 1) % len(decks)]))  # cross

    rows: list = []
    errors: list = []
    t_start = time.perf_counter()
    for (a, b) in matchups:
        for g in range(args.games):
            seed = 1000 + g
            print(f"[measure] {a} vs {b} seed={seed} ...", flush=True)
            try:
                measure_game(a, b, seed, args.node_cap, args.max_turns, rows)
            except Exception as e:
                errors.append((a, b, seed, repr(e)))
                print(f"  ERROR: {e!r}", flush=True)

    good = [r for r in rows if "error" not in r]
    bad = [r for r in rows if "error" in r]

    # turn 別集計
    by_turn = defaultdict(list)
    for r in good:
        by_turn[r["turn"]].append(r)

    print("\n================= ターン別 プラン数 分布 =================")
    print(f"{'turn':>4} {'n':>4} {'don~':>5} {'plans_mean':>11} {'plans_max':>10} "
          f"{'boards_max':>11} {'nodes_max':>10} {'ms_mean':>8} {'ms_max':>8} {'capped':>7}")
    overall_max = 0
    any_capped = False
    for turn in sorted(by_turn):
        rs = by_turn[turn]
        plans = [r["n_plans"] for r in rs]
        boards = [r["distinct_boards"] for r in rs]
        nodes = [r["nodes"] for r in rs]
        ms = [r["ms"] for r in rs]
        dons = [r["don"] for r in rs]
        capped_n = sum(1 for r in rs if r["capped"])
        any_capped = any_capped or capped_n > 0
        overall_max = max(overall_max, max(plans))
        print(f"{turn:>4} {len(rs):>4} {statistics.mean(dons):>5.1f} "
              f"{statistics.mean(plans):>11.1f} {max(plans):>10} "
              f"{max(boards):>11} {max(nodes):>10} "
              f"{statistics.mean(ms):>8.1f} {max(ms):>8.1f} "
              f"{capped_n:>4}/{len(rs)}")

    print("\n================= サマリ =================")
    print(f"総測定点: {len(good)}  (error {len(bad)}, game error {len(errors)})")
    print(f"全 turn 通じての最大プラン数: {overall_max}")
    print(f"node_cap ({args.node_cap}) に当たった測定: {'あり' if any_capped else 'なし'}")
    print(f"総経過: {time.perf_counter() - t_start:.1f}s")
    if bad:
        print("\n--- enumerate エラー (最大5件) ---")
        for r in bad[:5]:
            print(f"  turn={r['turn']} actor={r['actor']}: {r['error']}")
    if any_capped:
        print("\n⚠ capped あり = この cap では全列挙し切れていない turn がある "
              "(= 高 turn で budget 化が必要かを示唆)")
    else:
        print("\n✅ 全測定点で cap 未到達 = 完全列挙できている "
              "(= ohtsuki 仮説『DON 制約で爆発しない』を支持)")


if __name__ == "__main__":
    main()
