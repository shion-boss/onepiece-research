# -*- coding: utf-8 -*-
"""
効果付きシミュレーション: 効果あり vs 効果なしで平均ターン数の違いを比較
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
from engine.effects import load_effect_overlay
from engine.harness import run_matchup
from engine.ai import GreedyAI
from engine.game import setup_game, play_until_main
from engine.ai import play_one_action


def main():
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    print(f"effect overlay 登録カード: {len(overlay)}")

    deck1 = auto_build_deck("OP01-001", repo, rng=random.Random(1), name="赤ゾロ")
    deck2 = auto_build_deck("OP02-001", repo, rng=random.Random(2), name="赤白ひげ")

    n = 50

    print(f"\n=== 効果なし {n}戦 ===")
    t0 = time.time()
    rep_off = run_matchup(deck1, deck2, n_games=n, seed=42, effects_overlay={})
    t_off = time.time() - t0
    print(rep_off.summary())
    print(f"  経過: {t_off:.2f}s")

    print(f"\n=== 効果あり {n}戦 (overlay {len(overlay)} カード) ===")
    rng_master = random.Random(42)
    deck1_wins = 0
    deck2_wins = 0
    draws = 0
    turns_list = []
    actions_list = []
    on_play_fires = 0
    activate_fires = 0
    t0 = time.time()
    for g in range(n):
        first_player = g % 2
        rng = random.Random(rng_master.randrange(2**31))
        if first_player == 0:
            d_first, d_second = deck1, deck2
        else:
            d_first, d_second = deck2, deck1
        state = setup_game(d_first, d_second, rng=rng, first_player=0, effects_overlay=overlay)
        play_until_main(state)
        ai0 = GreedyAI(rng); ai1 = GreedyAI(rng)
        ais = [ai0, ai1]
        actions = 0
        while not state.game_over and actions < 1500:
            me = state.turn_player_idx
            opp = 1 - me
            try:
                play_one_action(state, ais[me], ais[opp])
            except Exception as e:
                state.declare_winner(opp, f"engine error: {e}")
                break
            actions += 1
        if state.winner is None:
            draws += 1
        else:
            deck1_won = (state.winner == 0 and first_player == 0) or (state.winner == 1 and first_player == 1)
            if deck1_won:
                deck1_wins += 1
            else:
                deck2_wins += 1
        turns_list.append(state.turn_number)
        actions_list.append(actions)
        on_play_fires += sum("効果: ドロー" in line or "効果: KO" in line or "効果: サーチ" in line for line in state.log)
        activate_fires += sum("起動メイン:" in line for line in state.log)

    t_on = time.time() - t0
    import statistics
    print(f"  {deck1.name} 勝率: {deck1_wins/n:.1%} ({deck1_wins}/{n})")
    print(f"  draws: {draws}")
    print(f"  平均ターン: {statistics.mean(turns_list):.1f} (中央値 {statistics.median(turns_list):.1f})")
    print(f"  効果発動回数(全試合合計): on_play系={on_play_fires}, 起動メイン={activate_fires}")
    print(f"  経過: {t_on:.2f}s")

    print("\n=== 比較 ===")
    print(f"  効果なし 平均ターン: {rep_off.avg_turns:.1f}")
    print(f"  効果あり 平均ターン: {statistics.mean(turns_list):.1f}")


if __name__ == "__main__":
    main()
