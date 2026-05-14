# -*- coding: utf-8 -*-
"""PlanningAI 動作スモーク + fast_clone 効果計測 (R70+ / Step 3 検証用)。

Greedy vs PlanningAI で 1 試合動かして、 動くこと / 1 ターン平均時間 / 勝者を確認。
"""

from __future__ import annotations

import copy
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main, Phase
from engine.ai import GreedyAI, PlanningAI, play_one_action
from engine.plan_search import fast_clone


def measure_fast_clone(state) -> tuple[float, float]:
    """deepcopy vs fast_clone の時間比較 (ms 単位)。"""
    times_dc: list[float] = []
    times_fc: list[float] = []
    for _ in range(10):
        t0 = time.perf_counter()
        _ = copy.deepcopy(state)
        times_dc.append((time.perf_counter() - t0) * 1000)
        t0 = time.perf_counter()
        _ = fast_clone(state)
        times_fc.append((time.perf_counter() - t0) * 1000)
    return statistics.mean(times_dc), statistics.mean(times_fc)


def run_one_game(deck_a_path, deck_b_path, ai_factory_a, ai_factory_b, seed=42, verbose=False):
    import random
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    deck_a = DeckList.from_json(deck_a_path, repo)
    deck_b = DeckList.from_json(deck_b_path, repo)
    rng = random.Random(seed)
    state = setup_game(deck_a, deck_b, rng=rng, first_player=0, effects_overlay=overlay)
    play_until_main(state)
    ai_a = ai_factory_a(rng=rng)
    ai_b = ai_factory_b(rng=rng)
    if hasattr(ai_a, "set_ai_opp"):
        ai_a.set_ai_opp(ai_b)
    if hasattr(ai_b, "set_ai_opp"):
        ai_b.set_ai_opp(ai_a)
    ais = [ai_a, ai_b]

    action_count = 0
    turn_times: list[float] = []
    current_turn = state.turn_number
    turn_start = time.perf_counter()
    max_iter = 1500
    for _ in range(max_iter):
        if state.game_over:
            break
        try:
            play_one_action(state, ais[state.turn_player_idx], ais[1 - state.turn_player_idx])
        except Exception as e:
            print(f"  error at action {action_count}: {e}")
            break
        action_count += 1
        if state.turn_number != current_turn:
            elapsed = time.perf_counter() - turn_start
            turn_times.append(elapsed * 1000)
            if verbose:
                print(f"    T{current_turn} ({state.turn_player_idx ^ 1 if state.turn_number > current_turn else state.turn_player_idx}): {elapsed*1000:.0f} ms")
            current_turn = state.turn_number
            turn_start = time.perf_counter()

    return {
        "winner": state.winner,
        "actions": action_count,
        "turns": state.turn_number,
        "turn_times_ms": turn_times,
        "p0_life": len(state.players[0].life),
        "p1_life": len(state.players[1].life),
    }


def main():
    print("=== PlanningAI smoke + fast_clone 比較 ===\n")

    # fast_clone vs deepcopy
    import random
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    deck_a = DeckList.from_json(ROOT / "decks" / "cardrush_1342.json", repo)
    deck_b = DeckList.from_json(ROOT / "decks" / "cardrush_1385.json", repo)
    state = setup_game(deck_a, deck_b, rng=random.Random(42), first_player=0, effects_overlay=overlay)
    play_until_main(state)
    dc_ms, fc_ms = measure_fast_clone(state)
    print(f"deepcopy: {dc_ms:.2f} ms")
    print(f"fast_clone: {fc_ms:.2f} ms  ({(1 - fc_ms/dc_ms)*100:.0f}% 削減)")
    print()

    # Greedy vs Greedy (baseline)
    print("--- Greedy vs Greedy ---")
    r1 = run_one_game(
        ROOT / "decks" / "cardrush_1342.json",
        ROOT / "decks" / "cardrush_1385.json",
        GreedyAI, GreedyAI, seed=42,
    )
    print(f"winner={r1['winner']}, turns={r1['turns']}, actions={r1['actions']}, life={r1['p0_life']}/{r1['p1_life']}")
    if r1["turn_times_ms"]:
        print(f"  avg turn time: {statistics.mean(r1['turn_times_ms']):.0f} ms")
    print()

    # Planning (deck_a 側 = 紫エネル) vs Greedy
    print("--- Planning (deck_a) vs Greedy ---")
    t0 = time.perf_counter()
    r2 = run_one_game(
        ROOT / "decks" / "cardrush_1342.json",
        ROOT / "decks" / "cardrush_1385.json",
        lambda rng=None: PlanningAI(rng=rng, beam_width=4, max_depth=8),
        GreedyAI, seed=42, verbose=True,
    )
    print(f"winner={r2['winner']}, turns={r2['turns']}, actions={r2['actions']}, life={r2['p0_life']}/{r2['p1_life']}, total={time.perf_counter()-t0:.1f}s")
    if r2["turn_times_ms"]:
        print(f"  avg turn time: {statistics.mean(r2['turn_times_ms']):.0f} ms")


if __name__ == "__main__":
    main()
