# -*- coding: utf-8 -*-
"""
赤ゾロ vs 赤白ひげの 50 戦マッチアップを回す
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from engine.deck import CardRepository
from engine.deckbuilder import auto_build_deck
from engine.harness import run_matchup
from engine.ai import GreedyAI


def main():
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")

    deck1 = auto_build_deck("OP01-001", repo, rng=random.Random(1), name="赤ゾロ(自動)")
    deck2 = auto_build_deck("OP02-001", repo, rng=random.Random(2), name="赤白ひげ(自動)")

    print(f"D1: {deck1.name} {len(deck1.main)} 枚, 違反={deck1.validate()}")
    print(f"D2: {deck2.name} {len(deck2.main)} 枚, 違反={deck2.validate()}")

    n = 50
    print(f"\n>> {n} 戦開始 ...")
    t0 = time.time()
    report = run_matchup(
        deck1, deck2,
        n_games=n,
        seed=42,
        ai_factory_1=GreedyAI,
        ai_factory_2=GreedyAI,
        verbose=True,
    )
    dt = time.time() - t0
    print(f"\n>> 経過 {dt:.1f}s ({dt/n*1000:.0f}ms/game)\n")
    print(report.summary())

    # サンプル試合詳細
    print("\n=== 試合データ(先頭5件) ===")
    print(f"{'idx':>3} {'first':>5} {'winner':>6} {'turns':>5} {'P0L':>3} {'P1L':>3} {'acts':>5}")
    for i, g in enumerate(report.games[:5]):
        print(f"{i:>3} {g.first_player:>5} {g.winner:>6} {g.turns:>5} {g.p0_life_left:>3} {g.p1_life_left:>3} {g.actions:>5}")


if __name__ == "__main__":
    main()
