# -*- coding: utf-8 -*-
"""PlanningAI の cProfile による hot spot 抽出。

n=3 game の Planning vs Greedy を回し、 cumulative time top 30 を出す。
fast_clone の deepcopy 内訳と choose_defense sim 比率を見て、 次の最適化対象を決める。
"""

from __future__ import annotations

import cProfile
import io
import pstats
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
        return PlanningAI(
            rng=rng, deck_analysis=deck_analysis,
            beam_width=beam, max_depth=depth,
        )
    return _f


def run_once(n_games=3, seed=42):
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    deck_a = DeckList.from_json(ROOT / "decks" / "cardrush_1424.json", repo)
    deck_b = DeckList.from_json(ROOT / "decks" / "cardrush_1437.json", repo)
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    t0 = time.perf_counter()
    report = run_matchup(
        deck_a, deck_b, n_games=n_games, seed=seed,
        ai_factory_1=planning_factory(beam=4, depth=8),
        ai_factory_2=GreedyAI,
        effects_overlay=overlay,
    )
    elapsed = time.perf_counter() - t0
    print(f"elapsed: {elapsed:.1f}s ({elapsed/n_games:.1f}s/game)")
    print(f"winrate: {report.deck1_winrate:.1%}")


def main():
    pr = cProfile.Profile()
    pr.enable()
    run_once(n_games=3, seed=42)
    pr.disable()

    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats("cumulative")
    ps.print_stats(40)
    print("\n=== Top 40 cumulative ===")
    print(s.getvalue())

    s2 = io.StringIO()
    ps2 = pstats.Stats(pr, stream=s2).sort_stats("tottime")
    ps2.print_stats(30)
    print("\n=== Top 30 tottime ===")
    print(s2.getvalue())


if __name__ == "__main__":
    main()
