# -*- coding: utf-8 -*-
"""Quick smoke test: strong vs baseline mirror on cardrush_1342 × 2 games.

各 game の 開始/終了 で 進捗 print + flush。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.deck import CardRepository, DeckList
from engine.harness import (
    _baseline_ai_factory,
    _default_ai_factory,
    run_matchup,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="cardrush_1342")
    ap.add_argument("--n", type=int, default=2)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    repo = CardRepository.from_json(str(ROOT / "db" / "cards.json"))
    deck1 = DeckList.from_json(str(ROOT / "decks" / f"{args.deck}.json"), repo)
    deck2 = DeckList.from_json(str(ROOT / "decks" / f"{args.deck}.json"), repo)

    print(f"START smoke: strong vs baseline, {args.deck} × {args.n}g (seed={args.seed})", flush=True)
    t0 = time.time()
    report = run_matchup(
        deck1, deck2, n_games=args.n, seed=args.seed,
        ai_factory_1=_default_ai_factory,   # strong
        ai_factory_2=_baseline_ai_factory,  # baseline
        keep_logs=False, enforce_rules=True, verbose=True,
    )
    elapsed = time.time() - t0
    print(f"\nDONE: {elapsed:.0f}s ({elapsed/args.n:.0f}s/game)", flush=True)
    print(report.summary(), flush=True)
    violations = sum(len(g.rule_violations) for g in report.games)
    print(f"Rule violations: {violations}", flush=True)


if __name__ == "__main__":
    main()
