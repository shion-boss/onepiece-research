# -*- coding: utf-8 -*-
"""
MAIN フェーズの branching factor / ターン行動数を計測。

Step 0 (PlanningAI 設計): beam width / max_depth の初期値決定用。
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
from engine.game import GameState, setup_game, play_until_main, Phase, apply_action, legal_actions
from engine.ai import GreedyAI, play_one_action


def measure(deck_a_path: Path, deck_b_path: Path, n_games: int = 5, seed: int = 0):
    """Greedy vs Greedy で n_games sim し、 MAIN フェーズの branching を計測。"""
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    deck_a = DeckList.from_json(deck_a_path, repo)
    deck_b = DeckList.from_json(deck_b_path, repo)

    branchings: list[int] = []        # 各 MAIN action 直前の len(legal_actions)
    turn_action_counts: list[int] = []  # 各 ターンの MAIN フェーズ行動回数
    deepcopy_times: list[float] = []

    import random, copy
    rng_master = random.Random(seed)
    for g in range(n_games):
        rng = random.Random(rng_master.randrange(2**31))
        state = setup_game(
            deck_a, deck_b, rng=rng, first_player=0,
            effects_overlay=overlay,
        )
        play_until_main(state)
        ai_a = GreedyAI(rng=rng)
        ai_b = GreedyAI(rng=rng)
        ais = [ai_a, ai_b]

        prev_turn = state.turn_number
        prev_phase = state.phase
        actions_this_turn = 0
        max_iter = 1500
        for _ in range(max_iter):
            if state.game_over:
                break
            if state.phase == Phase.MAIN:
                la = legal_actions(state)
                branchings.append(len(la))
                # deepcopy 時間計測 (= サンプル数本だけ)
                if len(deepcopy_times) < 50:
                    t0 = time.perf_counter()
                    _ = copy.deepcopy(state)
                    deepcopy_times.append(time.perf_counter() - t0)
                actions_this_turn += 1
            try:
                play_one_action(state, ais[state.turn_player_idx], ais[1 - state.turn_player_idx])
            except Exception as e:
                break
            # ターン跨ぎ検出 (= MAIN action 数を flush)
            if state.turn_number != prev_turn:
                turn_action_counts.append(actions_this_turn)
                actions_this_turn = 0
                prev_turn = state.turn_number

    print(f"=== Branching / Depth measure ===")
    print(f"対戦: {deck_a.name} vs {deck_b.name}, n_games={n_games}")
    print(f"")
    print(f"MAIN フェーズ legal_actions (= branching factor):")
    print(f"  サンプル数: {len(branchings)}")
    print(f"  mean: {statistics.mean(branchings):.1f}")
    print(f"  median: {statistics.median(branchings):.1f}")
    print(f"  p90: {sorted(branchings)[int(len(branchings)*0.9)]}")
    print(f"  max: {max(branchings)}")
    print(f"")
    print(f"ターンあたり MAIN 行動数 (= 最大探索 depth):")
    print(f"  サンプル数: {len(turn_action_counts)}")
    print(f"  mean: {statistics.mean(turn_action_counts):.1f}")
    print(f"  median: {statistics.median(turn_action_counts):.1f}")
    print(f"  p90: {sorted(turn_action_counts)[int(len(turn_action_counts)*0.9)]}")
    print(f"  max: {max(turn_action_counts)}")
    print(f"")
    print(f"deepcopy(state) コスト:")
    print(f"  サンプル数: {len(deepcopy_times)}")
    print(f"  mean: {statistics.mean(deepcopy_times)*1000:.2f} ms")
    print(f"  median: {statistics.median(deepcopy_times)*1000:.2f} ms")
    print(f"")
    # 推定: beam=4, depth=8 で 1 turn 計算量
    b_mean = statistics.mean(branchings)
    d_mean = statistics.mean(turn_action_counts)
    dc_mean = statistics.mean(deepcopy_times) * 1000
    print(f"=== 推定: beam=4, depth={d_mean:.0f} ===")
    # beam search の deepcopy 回数: 各 step で beam 個保持 → step ごとに beam * branch 個展開 → beam に枝刈り
    est_copies = 4 * b_mean * d_mean  # おおまかに
    est_time_ms = est_copies * dc_mean
    print(f"  推定 deepcopy 回数/ターン: {est_copies:.0f}")
    print(f"  推定計算時間/ターン: {est_time_ms:.0f} ms (= {est_time_ms/1000:.1f} s)")


if __name__ == "__main__":
    measure(
        Path("decks/cardrush_1424.json"),  # 紫エネル
        Path("decks/cardrush_1437.json"),  # 緑ミホーク
        n_games=5,
        seed=42,
    )
