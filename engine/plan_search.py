# -*- coding: utf-8 -*-
"""
ターン全体プランの beam search (R70+ / Phase 4)
================================================

GreedyAI は 1 手ごとに局所最適を選ぶため、 「event → attack → event」 の
3 段コンボや、 「ハンド剥がし後に通すアタック」 のような行動列の連動が拾えない。

`search_turn_plan` は MAIN フェーズ開始時に「自ターン EndPhase までの行動列」 を
beam search し、 終端の `engine.eval.compute_score` でスコア付けし、 最良プランの
1 手目を返す。 次ターンは再計画 (receding horizon planning)。

設計の肝:
- 各候補 attack は sim 内で `ai_opp.choose_defense` を呼んで counter/blocker を反映
  (= ライフを取れる/取れないを正しく見る)
- deepcopy が重い (= 70ms/clone, 計測済) ため、 `fast_clone` で log/snapshots/
  effects_overlay を共有参照のまま除外して deepcopy 対象を絞る
- beam pruning: 各 depth で次世代候補を中間スコアで top-k に絞り、 指数爆発を抑える
- 終端: phase != MAIN (= EndPhase 到達 or ターン交代) / game_over / max_depth
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Optional

from .core import Phase
from .eval import compute_score
from .game import (
    AttackCharacter,
    AttackLeader,
    EndPhase,
    apply_action,
    legal_actions,
)

if TYPE_CHECKING:
    from .core import GameState


def fast_clone(state: "GameState") -> "GameState":
    """軽量 state clone。

    log / snapshots / action_evals / effects_overlay / event_order_hook は
    cloned 側で共有 (= log/snapshots は空 list で開始、 overlay/hook は元参照)。
    残りは deepcopy。 元 state は不変。

    deepcopy 計測 (70ms/clone) の大半が effects_overlay (4,518 カード) と
    log の deep clone なので、 これらを除外すれば桁レベルで高速化される。
    """
    # 一時退避: 共有 OK な (= 不変 or append-only) フィールド
    saved_log = state.log
    saved_snapshots = state.snapshots
    saved_evals = state.action_evals
    saved_overlay = state.effects_overlay
    saved_hook = state.event_order_hook
    saved_rec = state.record_snapshots

    # 元 state を一時的に空に置き換え → deepcopy → 復元
    state.log = []
    state.snapshots = []
    state.action_evals = []
    state.effects_overlay = {}
    state.event_order_hook = None
    state.record_snapshots = False
    try:
        cloned = copy.deepcopy(state)
    finally:
        # 元 state を完全復元
        state.log = saved_log
        state.snapshots = saved_snapshots
        state.action_evals = saved_evals
        state.effects_overlay = saved_overlay
        state.event_order_hook = saved_hook
        state.record_snapshots = saved_rec

    # cloned 側: overlay / hook は元参照を共有 (= 不変)。 log 系は空のまま (= plan 内では不要)
    cloned.effects_overlay = saved_overlay
    cloned.event_order_hook = saved_hook
    cloned.record_snapshots = False
    # cloned 内 apply_action での eval_before/after 記録を抑止 (= compute_score 二重実行カット)
    cloned.record_action_evals = False
    return cloned


def _apply_with_defense(state: "GameState", action, ai_opp) -> None:
    """attack 系なら ai_opp.choose_defense を呼んで counter/blocker を差し込み apply_action。

    play_one_action の defense 差し込み部分の抜粋。 plan_search 内では ai_self は
    呼ばず action を 直接渡すので、 defense 差し込みだけここで実施。
    """
    if isinstance(action, AttackLeader):
        from .game import _find_attacker

        attacker = _find_attacker(state.turn_player, action.attacker_iid)
        block_iid, counters = ai_opp.choose_defense(
            state, attacker, state.opponent.leader, True, state.opponent
        )
        action = AttackLeader(
            attacker_iid=action.attacker_iid,
            counter_card_idxs=counters,
            blocker_iid=block_iid,
        )
    elif isinstance(action, AttackCharacter):
        from .game import _find_attacker, _find_character

        attacker = _find_attacker(state.turn_player, action.attacker_iid)
        target = _find_character(state.opponent, action.target_iid)
        block_iid, counters = ai_opp.choose_defense(
            state, attacker, target, False, state.opponent
        )
        action = AttackCharacter(
            attacker_iid=action.attacker_iid,
            target_iid=action.target_iid,
            counter_card_idxs=counters,
            blocker_iid=block_iid,
        )
    apply_action(state, action)


def _is_terminal(state: "GameState", me_idx: int) -> bool:
    """このノードを終端 (= プラン完了) として扱うか。

    - ゲーム終了
    - 自分のターンが終わった (phase != MAIN or turn_player_idx 切替)
    """
    if state.game_over:
        return True
    if state.phase != Phase.MAIN:
        return True
    if state.turn_player_idx != me_idx:
        return True
    return False


def search_turn_plan(
    state: "GameState",
    ai_opp,
    beam_width: int = 4,
    max_depth: int = 8,
) -> tuple[list, float]:
    """MAIN フェーズ開始時に呼ぶ。 ターン全体プランを beam search。

    Args:
        state: 現在の GameState (= MAIN フェーズ想定、 副作用無く読むだけ)
        ai_opp: 攻撃 sim 時に choose_defense を呼ぶ相手 AI
        beam_width: 各 depth で残す候補数 (default 4)
        max_depth: 最大プラン長 (default 8)

    Returns:
        (best_plan, best_score): 最良プランの Action リスト + 終端 board_eval。
        best_plan が空の場合は呼出側で EndPhase をデフォルトに使う。
    """
    me_idx = state.turn_player_idx

    init = fast_clone(state)
    # frontier: list of (state, plan_actions, latest_score)
    frontier: list[tuple] = [(init, [], compute_score(init, me_idx))]
    completed: list[tuple] = []

    for _depth in range(max_depth):
        next_frontier: list[tuple] = []
        for cur_state, plan, _prev_score in frontier:
            if _is_terminal(cur_state, me_idx):
                completed.append((cur_state, plan))
                continue

            la = legal_actions(cur_state)
            # 機械的悪手 (= 過剰除去 event 等) を beam 展開前に剪定。
            # ai.prune_mechanical_waste は副作用なし、 全消えなら原リストを返す保険付き。
            from .ai import prune_mechanical_waste
            la = prune_mechanical_waste(cur_state, la)
            if not la:
                completed.append((cur_state, plan))
                continue

            for action in la:
                child = fast_clone(cur_state)
                try:
                    _apply_with_defense(child, action, ai_opp)
                except Exception:
                    # 不正手 / engine エラーはスキップ
                    continue
                score = compute_score(child, me_idx)
                next_frontier.append((child, plan + [action], score))

        if not next_frontier:
            break
        # beam pruning: 中間 score の高い順に top-k
        next_frontier.sort(key=lambda x: -x[2])
        frontier = next_frontier[:beam_width]

    # depth 上限到達分も完了扱い
    for cur_state, plan, _ in frontier:
        completed.append((cur_state, plan))

    if not completed:
        return [], -float("inf")

    # 終端 score でランク付け → 最良プランを返す
    best_plan: list = []
    best_score = -float("inf")
    for cur_state, plan in completed:
        s = compute_score(cur_state, me_idx)
        if s > best_score:
            best_score = s
            best_plan = plan
    return best_plan, best_score
