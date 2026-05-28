# -*- coding: utf-8 -*-
"""
強化後 (= GoalDirectedAI strong=True) vs 強化前 (= strong=False) の 比較 eval (= 2026-05-28)。

実行モード:
  --mode mirror : 同 deck × N games で strong vs baseline。 default deck=16。
  --mode cross  : 異 deck pair (= M × N seeds) で 強化後 deck1 vs 強化前 deck2。
                  cross では baseline matrix と 比較 で 上回ったか 確認。

使い方:
  # 単一 deck mirror (= cardrush_1456 だけ、 デフォルト n_games=4)
  .venv/bin/python scripts/eval_strong_vs_baseline.py --mode mirror --decks cardrush_1456

  # 16 deck 全 mirror、 n_games=4 each
  .venv/bin/python scripts/eval_strong_vs_baseline.py --mode mirror --n-games 4

  # cross eval (= deck1 strong vs deck2 baseline 全 pair)
  .venv/bin/python scripts/eval_strong_vs_baseline.py --mode cross --n-games 4

出力:
  - stdout summary
  - db/strong_vs_baseline_<mode>.json (= raw results)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.deck import CardRepository, DeckList
from engine.harness import (
    _baseline_ai_factory,
    _default_ai_factory,
    run_matchup,
)


DECKS_16 = [
    "cardrush_1342",
    "cardrush_1385",
    "cardrush_1392",
    "cardrush_1399",
    "cardrush_1439",
    "cardrush_1453",
    "cardrush_1454",
    "cardrush_1455",
    "cardrush_1456",
    "tcgportal_bonney",
    "tcgportal_calgara",
    "tcgportal_coby",
    "tcgportal_corazon",
    "tcgportal_hancock",
    "tcgportal_op11_luffy",
    "tcgportal_op13_luffy",
]


def _load_deck(repo: CardRepository, slug: str) -> DeckList:
    return DeckList.from_json(str(ROOT / "decks" / f"{slug}.json"), repo)


def _run_pair(
    deck_a: DeckList, deck_b: DeckList, n_games: int, seed: int,
    a_strong: bool, b_strong: bool,
    on_game=None,
) -> dict:
    """deck_a (ai_factory_1) vs deck_b (ai_factory_2)。 strong=True で 強化後 AI。

    n_games を 1 試合ずつ run_matchup(n_games=1) で 回し、 game 単位 で 進捗 を 出す
    (= on_game callback)。 各 game の seed は seed+g で deterministic。
    """
    f_a = _default_ai_factory if a_strong else _baseline_ai_factory
    f_b = _default_ai_factory if b_strong else _baseline_ai_factory
    a_wins = b_wins = draws = violations = 0
    t0 = time.time()
    for g in range(n_games):
        gt0 = time.time()
        report = run_matchup(
            deck_a, deck_b, n_games=1, seed=seed + g,
            ai_factory_1=f_a, ai_factory_2=f_b,
            keep_logs=False, enforce_rules=True,
        )
        a_wins += report.deck1_wins
        b_wins += report.deck2_wins
        draws += report.draws
        gviol = sum(len(gm.rule_violations) for gm in report.games)
        violations += gviol
        if on_game is not None:
            on_game(g + 1, n_games, report.deck1_wins, report.deck2_wins,
                    gviol, time.time() - gt0, a_wins, b_wins)
    elapsed = time.time() - t0
    total = a_wins + b_wins + draws
    return {
        "deck_a": deck_a.slug or deck_a.name,
        "deck_b": deck_b.slug or deck_b.name,
        "n_games": n_games,
        "seed": seed,
        "a_strong": a_strong,
        "b_strong": b_strong,
        "a_wins": a_wins,
        "b_wins": b_wins,
        "draws": draws,
        "a_winrate": (a_wins / total) if total else 0.0,
        "violations": violations,
        "elapsed_s": elapsed,
    }


def mode_mirror(decks: list[str], n_games: int, seed: int, output: Path) -> None:
    """各 deck で strong (= AI 1) vs baseline (= AI 2)。 strong が 勝ち越し が 期待。

    incremental save 各 deck 後 (= kill 損失 最小化)。
    """
    repo = CardRepository.from_json(str(ROOT / "db" / "cards.json"))
    results = []
    for i, slug in enumerate(decks):
        d1 = _load_deck(repo, slug)
        d2 = _load_deck(repo, slug)
        print(f"[{i+1}/{len(decks)}] {slug} (strong vs baseline)... ", flush=True)

        def _on_game(g, n, ga, gb, gviol, gsec, cum_a, cum_b):
            res = "strong" if ga > gb else ("baseline" if gb > ga else "draw")
            print(f"    game {g}/{n}: {res} win  (cum {cum_a}-{cum_b})  [{gsec:.0f}s, viol={gviol}]", flush=True)
            # game 単位 で 部分結果 を save (= kill 損失 を 1 game に 抑える)
            output.write_text(json.dumps(
                {"mode": "mirror", "n_games": n_games,
                 "results": results + [{"deck_a": slug, "deck_b": slug,
                                        "partial": True, "g_done": g, "g_total": n,
                                        "cum_a_wins": cum_a, "cum_b_wins": cum_b}]},
                ensure_ascii=False, indent=2))

        row = _run_pair(d1, d2, n_games, seed, a_strong=True, b_strong=False, on_game=_on_game)
        results.append(row)
        wr = row["a_winrate"] * 100
        verdict = "WIN" if row["a_wins"] > row["b_wins"] else ("TIE" if row["a_wins"] == row["b_wins"] else "LOSE")
        print(f"  -> strong {row['a_wins']}-{row['b_wins']} baseline ({wr:.0f}%) {verdict}  [{row['elapsed_s']:.0f}s, viol={row['violations']}]", flush=True)
        output.write_text(json.dumps({"mode": "mirror", "n_games": n_games, "results": results}, ensure_ascii=False, indent=2))
    total_a = sum(r["a_wins"] for r in results)
    total_b = sum(r["b_wins"] for r in results)
    total_g = sum(r["n_games"] for r in results)
    n_win = sum(1 for r in results if r["a_wins"] > r["b_wins"])
    n_tie = sum(1 for r in results if r["a_wins"] == r["b_wins"])
    n_lose = sum(1 for r in results if r["a_wins"] < r["b_wins"])
    print(f"\n=== MIRROR SUMMARY ({len(decks)} decks, {total_g} games) ===", flush=True)
    print(f"  strong: {total_a}-{total_b} baseline ({100*total_a/(total_a+total_b):.1f}% over all)", flush=True)
    print(f"  decks WIN/TIE/LOSE = {n_win}/{n_tie}/{n_lose}", flush=True)


def mode_cross(decks: list[str], n_games: int, seed: int, output: Path) -> None:
    """deck1 strong vs deck2 baseline の N×N matrix を 計算 (= mirror cell skip)。"""
    repo = CardRepository.from_json(str(ROOT / "db" / "cards.json"))
    deck_objs = {slug: _load_deck(repo, slug) for slug in decks}
    results = []
    total_pairs = len(decks) * (len(decks) - 1)
    idx = 0
    for slug_a in decks:
        for slug_b in decks:
            if slug_a == slug_b:
                continue
            idx += 1
            print(f"[{idx}/{total_pairs}] {slug_a} (strong) vs {slug_b} (baseline)... ", flush=True)
            row = _run_pair(
                deck_objs[slug_a], deck_objs[slug_b],
                n_games, seed, a_strong=True, b_strong=False,
            )
            results.append(row)
            wr = row["a_winrate"] * 100
            print(f"  → {row['a_wins']}-{row['b_wins']} ({wr:.0f}%)  [{row['elapsed_s']:.0f}s]")
            output.write_text(json.dumps({"mode": "cross", "n_games": n_games, "results": results}, ensure_ascii=False, indent=2))
    total_a = sum(r["a_wins"] for r in results)
    total_g = sum(r["n_games"] for r in results)
    print(f"\n=== CROSS SUMMARY ({len(decks)}x{len(decks)-1} pairs, {total_g} games) ===")
    print(f"  strong avg winrate: {100*total_a/total_g:.1f}%")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["mirror", "cross"], default="mirror")
    ap.add_argument("--decks", nargs="+", default=DECKS_16)
    ap.add_argument("--n-games", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    output = Path(args.output) if args.output else ROOT / "db" / f"strong_vs_baseline_{args.mode}.json"
    output.parent.mkdir(parents=True, exist_ok=True)

    if args.mode == "mirror":
        mode_mirror(args.decks, args.n_games, args.seed, output)
    else:
        mode_cross(args.decks, args.n_games, args.seed, output)


if __name__ == "__main__":
    main()
