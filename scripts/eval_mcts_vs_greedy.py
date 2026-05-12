# -*- coding: utf-8 -*-
"""
MCTSAI vs GreedyAI の head-to-head 検証
====================================

同一デッキ (赤紫ロジャー = cardrush_1429 を default) で MCTSAI を deck1、
GreedyAI を deck2 に当てて N 試合実行。 MCTS が greedy より強ければ
勝率 > 50% になる (= ISMCTS + PUCT の効果)。

Phase 2 検証の主指標。 計画目標: 勝率 65% 以上。

実行:
    .venv/bin/python scripts/eval_mcts_vs_greedy.py
    .venv/bin/python scripts/eval_mcts_vs_greedy.py --deck cardrush_1429 --n-games 100
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.ai import GreedyAI, MCTSAI  # noqa: E402
from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.harness import run_matchup  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="cardrush_1429",
                    help="同一デッキの slug (default: cardrush_1429 赤紫ロジャー)")
    ap.add_argument("--n-games", type=int, default=100, help="試合数 (default: 100)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    deck_path = ROOT / "decks" / f"{args.deck}.json"
    if not deck_path.exists():
        print(f"ERROR: {deck_path} not found")
        return 1
    deck = DeckList.from_json(deck_path, repo)

    print(f"deck: {deck.name} ({args.deck})")
    print(f"n_games: {args.n_games}, seed: {args.seed}")
    print()

    t0 = time.time()
    report = run_matchup(
        deck, deck,
        n_games=args.n_games, seed=args.seed,
        ai_factory_1=MCTSAI,
        ai_factory_2=GreedyAI,
    )
    elapsed = time.time() - t0

    print(f"MCTS (deck1) wins: {report.deck1_wins}")
    print(f"Greedy (deck2) wins: {report.deck2_wins}")
    print(f"draws: {report.draws}")
    print(f"MCTS winrate: {report.deck1_winrate:.3f}")
    print(f"elapsed: {elapsed:.1f}s ({elapsed / args.n_games:.2f}s/game)")
    print()

    if report.deck1_winrate >= 0.65:
        print(f"PASS: MCTS winrate {report.deck1_winrate:.3f} >= 0.65 (Phase 2 target)")
        return 0
    elif report.deck1_winrate >= 0.55:
        print(f"PARTIAL: MCTS winrate {report.deck1_winrate:.3f} >= 0.55 (above random)")
        return 0
    else:
        print(f"FAIL: MCTS winrate {report.deck1_winrate:.3f} < 0.55")
        return 1


if __name__ == "__main__":
    sys.exit(main())
