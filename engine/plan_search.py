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
import random
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
    # plan_search 内 シミュレーション は AI vs AI として 動作 する。
    # human_player_idx を 残すと、 simulated 人間ターン で self-side target_pick が
    # pending_choice を 立てて plan_search が halt する (= 2026-05-23 self-side target_pick 拡張 で 発覚)。
    cloned.human_player_idx = None
    cloned.forced_human_actor_idx = None
    return cloned


def _apply_with_defense(state: "GameState", action, ai_defender) -> None:
    """attack 系なら ai_defender.choose_defense を呼んで counter/blocker を差し込み apply_action。

    play_one_action の defense 差し込み部分の抜粋。 plan_search 内では ai_self は
    呼ばず action を 直接渡すので、 defense 差し込みだけここで実施。

    Note: パラメータ名が ai_defender なのは、 multi-turn sim で me が defender になる
    ケース (= opp 攻撃) があるため。 caller が場面に応じて適切な AI を渡す。
    """
    if isinstance(action, AttackLeader):
        from .game import _find_attacker

        attacker = _find_attacker(state.turn_player, action.attacker_iid)
        block_iid, counters = ai_defender.choose_defense(
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
        block_iid, counters = ai_defender.choose_defense(
            state, attacker, target, False, state.opponent
        )
        action = AttackCharacter(
            attacker_iid=action.attacker_iid,
            target_iid=action.target_iid,
            counter_card_idxs=counters,
            blocker_iid=block_iid,
        )
    apply_action(state, action)


def _simulate_opp_turn(
    state: "GameState",
    opp_idx: int,
    ai_opp_sim,
    ai_self_for_defense,
    hard_cap_actions: int = 30,
) -> None:
    """opp ターンを完走させて state を「自分の次の MAIN」 (= 自ターン or game_over) まで in-place で進める。

    - opp が攻撃する時は ai_self_for_defense.choose_defense を呼ぶ (= me が defender)
    - opp 行動は ai_opp_sim.choose_action で決定 (= GreedyAI 想定、 速度優先 + 無限再帰回避)
    - opp 自身の extra turn は同一ループで継続 (= turn_player_idx 切替で停止)
    - hard_cap_actions: 暴走対策の上限 (default 30)、 越えたら sim 中断 (= state はそのまま leaf 評価)

    caller は事前に fast_clone しておくこと。
    """
    actions_taken = 0
    while not state.game_over and state.turn_player_idx == opp_idx:
        if actions_taken >= hard_cap_actions:
            break
        try:
            action = ai_opp_sim.choose_action(state)
        except Exception:
            break
        try:
            _apply_with_defense(state, action, ai_self_for_defense)
        except Exception:
            break
        actions_taken += 1


def _is_terminal(
    state: "GameState",
    me_idx: int,
    start_turn_number: Optional[int] = None,
    max_turns: int = 1,
) -> bool:
    """このノードを終端 (= プラン完了) として扱うか。

    - ゲーム終了 → 常に終端
    - max_turns <= 1 (= 後方互換): 自ターン終了 (= phase != MAIN or turn_player_idx 切替) で終端。
      extra turn を同一プラン内に含めるための旧挙動を維持。
    - max_turns > 1: (state.turn_number - start_turn_number) >= max_turns で終端。
      multi-turn lookahead 用 (= Step 1B の opp 自動 sim と組合せて使う前提)。
    """
    if state.game_over:
        return True

    if max_turns <= 1:
        if state.phase != Phase.MAIN:
            return True
        if state.turn_player_idx != me_idx:
            return True
        return False

    if start_turn_number is None:
        start_turn_number = state.turn_number
    if (state.turn_number - start_turn_number) >= max_turns:
        return True
    return False


def search_turn_plan(
    state: "GameState",
    ai_opp,
    beam_width: int = 4,
    max_depth: int = 8,
    max_turns: int = 1,
    ai_self=None,
    me_deck_analysis: "Optional[dict]" = None,
    me_target_spec: "Optional[dict]" = None,
) -> tuple[list, float]:
    """MAIN フェーズ開始時に呼ぶ。 ターン全体プランを beam search。

    Args:
        state: 現在の GameState (= MAIN フェーズ想定、 副作用無く読むだけ)
        ai_opp: 攻撃 sim 時に choose_defense を呼ぶ相手 AI
        beam_width: 各 depth で残す候補数 (default 4)
        max_depth: 最大プラン長 (default 8)
        max_turns: 探索する自ターン数の上限 (default 1 = 後方互換、 1 ターンで打ち切り)
                   > 1 の場合は Step 1B の opp 自動 sim が前提 (= 単独では opp ターンを
                   me のアクションとして探索してしまうため意味のある探索にならない)
        ai_self: opp ターン中に opp 攻撃を防御する me 側 AI (Step 1B で使用、
                 1A では未使用)

    Returns:
        (best_plan, best_score): 最良プランの Action リスト + 終端 board_eval。
        best_plan が空の場合は呼出側で EndPhase をデフォルトに使う。
    """
    me_idx = state.turn_player_idx
    opp_idx = 1 - me_idx
    start_turn_number = state.turn_number

    # multi-turn 用 opp sim AI を準備 (= max_turns > 1 の時のみ)
    opp_sim_ai = None
    self_defense_ai = None
    from .ai import GreedyAI, LightDeepPlanningAI, LookaheadAI, PlanningAI
    # caller (= ai_self) の recursion_depth を伝播 (= 1 階層深く読ませる)。
    # main caller depth=0 → opp_sim depth=1 (= plan_search 動作) → 内部 opp_sim depth=2 (= GreedyAI fallback)
    caller_depth = getattr(ai_self, "recursion_depth", 0) if ai_self is not None else 0
    if max_turns > 1:
        # opp sim: 2026-05-18 ONEPIECE_LIGHT_OPP_SIM=1 で GreedyAI 固定 (= 大幅高速化)。
        # LightDeepPlanningAI は plan_search 内 plan_search で 1 opp sim あたり 1-2 sec、
        # max_turns=2 で 1 試合 30 分超 になる。 GreedyAI なら 0.1 sec、 10-20x 高速。
        import os as _os
        _light_opp = _os.environ.get("ONEPIECE_LIGHT_OPP_SIM") == "1"
        if _light_opp:
            opp_sim_ai = GreedyAI(rng=getattr(state, "rng", None))
        elif ai_opp is None or isinstance(ai_opp, PlanningAI):
            # 既存: LightDeepPlanningAI(recursion_depth=caller+1) で archetype-aware 多手読み。
            opp_sim_ai = LightDeepPlanningAI(
                rng=getattr(state, "rng", None),
                recursion_depth=caller_depth + 1,
            )
        else:
            opp_sim_ai = ai_opp
        # opp 攻撃時の me 側 defense AI も同様 (= 速度優先で GreedyAI 化)
        if ai_self is None or isinstance(ai_self, PlanningAI):
            self_defense_ai = GreedyAI(rng=getattr(state, "rng", None))
        else:
            self_defense_ai = ai_self
    # === plan_search 枝刈り (R72+): 攻撃 leaf の defense AI を GreedyAI 固定 ===
    # 元実装: ai_opp.choose_defense (= LookaheadAI / DeepPlanningAI 等の重い AI) が
    # leaf の attack 毎に呼ばれて、 plan_search の組合せ爆発を引き起こしてた。
    # GreedyAI に固定することで 各 leaf の defense 選択を高速化 (= 1 試合 10+ 分 → 数十秒)。
    # opp が「真の choose_defense」 を示すのは 実 試合中だけで OK。
    defense_ai_for_attacks = ai_opp
    if ai_opp is None or isinstance(ai_opp, (PlanningAI, LookaheadAI)):
        defense_ai_for_attacks = GreedyAI(rng=getattr(state, "rng", None))

    init = fast_clone(state)

    # multi-turn mode: opp.hand を determinize (= sample=1 で確定化、 fair sim)。
    # max_turns=1 (= 後方互換) では既存挙動 (= opp.hand 実値、 「cheat」 だが安定) を維持。
    if max_turns > 1:
        from .hand_estimator import determinize_state
        determ_rng = getattr(state, "rng", None) or random.Random(state.turn_number)
        try:
            determinize_state(init, opp_idx, rng=determ_rng)
        except Exception:
            # determinize 失敗時は実 hand のまま続行 (= 害はないが「cheat」 になる)
            pass

    # frontier: list of (state, plan_actions, latest_score)
    frontier: list[tuple] = [(init, [], compute_score(init, me_idx))]
    completed: list[tuple] = []

    # === Plan A (= NN policy-prior beam): 2026-05-17 ===
    # NN policy head 出力を beam selection に組み込む。
    # 各 action candidate の score に W_POLICY × log P(action_category | state) を加算。
    # ONEPIECE_PLAN_POLICY_W 環境変数で重み制御 (= default 0 で無効、 5000 等で有効化)。
    import math
    import os as _os
    _W_POLICY = float(_os.environ.get("ONEPIECE_PLAN_POLICY_W", "0"))
    _USE_POLICY = _W_POLICY > 0
    if _USE_POLICY:
        from .nn_eval import compute_policy_nn  # 動的 import (= NN 無効時 import skip)

    # === Plan Imit-3 (= 2026-05-18): imitation prior 注入 ===
    # 大会優勝レシピから抽出した「人間が選ぶカード」 prior を beam selection に組み込む。
    # PlayCharacter / PlayEvent action で その card の人間採用率 × W_IMIT を bonus 加算。
    # ONEPIECE_PLAN_IMITATION_W 環境変数で制御 (= default 0 無効、 1000+ で有効)。
    _W_IMIT = float(_os.environ.get("ONEPIECE_PLAN_IMITATION_W", "0"))
    _USE_IMIT = _W_IMIT > 0
    if _USE_IMIT:
        from .imitation_prior import get_card_play_prior

    # === Plan G (= 2026-05-18 夜): turn_plan-directed bonus ===
    # decks/<slug>.analysis.json の ideal_moves で 指定された「現 turn の candidate cards」 を
    # play する action に bonus。 人間プレイヤーの 「T1: 1 コスト、 T4: 中堅、 T6: フィニッシャー」
    # 的な goal-directed planning を 模擬。
    # ONEPIECE_TURN_PLAN_W 環境変数 (= default 0 無効、 3000+ で 強い goal-bias)。
    _W_TURN_PLAN = float(_os.environ.get("ONEPIECE_TURN_PLAN_W", "0"))
    _USE_TURN_PLAN = _W_TURN_PLAN > 0
    _me_deck_analysis = me_deck_analysis
    if _USE_TURN_PLAN:
        from .turn_plan import get_turn_plan_candidates
        # fallback: state や player から 取得 試行 (= caller が 渡さない場合)
        if _me_deck_analysis is None:
            if hasattr(state, "deck_analyses") and isinstance(state.deck_analyses, dict):
                _me_deck_analysis = state.deck_analyses.get(me_idx)
            elif hasattr(state, "players") and hasattr(state.players[me_idx], "deck_analysis"):
                _me_deck_analysis = state.players[me_idx].deck_analysis

    # === Plan H (= 2026-05-19): goal-directed target bonus ===
    # Claude が 書いた target spec (= decks/<slug>.target_v1.json) を 読み込み、
    # leaf state が target condition match で bonus 加算。
    # ONEPIECE_GOAL_TARGET_W 環境変数 (= default 0 無効、 1.0+ で 有効)。
    # bonus magnitude は target.bonus (= 500-2000) で 直接 表現、 W は スケール係数。
    _W_GOAL_TARGET = float(_os.environ.get("ONEPIECE_GOAL_TARGET_W", "0"))
    _USE_GOAL_TARGET = _W_GOAL_TARGET > 0
    _me_target_spec = me_target_spec
    if _USE_GOAL_TARGET:
        from .target_dsl import compute_target_match_bonus, load_target_spec
        # fallback: state._goal_target_spec → state.players[me_idx].deck_slug の順 で auto-load
        if _me_target_spec is None:
            _me_target_spec = getattr(state, "_goal_target_spec", None)
        if _me_target_spec is None:
            me_player = state.players[me_idx]
            me_deck_slug = getattr(me_player, "deck_slug", None)
            if me_deck_slug:
                _me_target_spec = load_target_spec(me_deck_slug)

    for _depth in range(max_depth):
        next_frontier: list[tuple] = []
        for cur_state, plan, _prev_score in frontier:
            if _is_terminal(cur_state, me_idx, start_turn_number, max_turns):
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

            # NN policy を 1 度だけ取得 (= 同 state なら同じ policy)
            policy_dict = compute_policy_nn(cur_state, me_idx) if _USE_POLICY else None

            for action in la:
                child = fast_clone(cur_state)
                try:
                    _apply_with_defense(child, action, defense_ai_for_attacks)
                except Exception:
                    # 不正手 / engine エラーはスキップ
                    continue

                # multi-turn mode: turn が opp に切替わったら opp ターンを sim で完走させる
                # (= 次の自分 MAIN まで進めて、 そこから plan 探索を継続する)
                if (
                    max_turns > 1
                    and not child.game_over
                    and child.turn_player_idx == opp_idx
                    and opp_sim_ai is not None
                ):
                    if (child.turn_number - start_turn_number) < max_turns:
                        try:
                            # plan_search 枝刈り: opp sim の hard_cap を env で可変化。
                            # default 5 (= 軽量)、 3-turn lookahead で 8 推奨 (= opp が攻撃完走)。
                            _opp_hard_cap = int(_os.environ.get("ONEPIECE_OPP_HARD_CAP", "5"))
                            _simulate_opp_turn(
                                child, opp_idx, opp_sim_ai, self_defense_ai,
                                hard_cap_actions=_opp_hard_cap,
                            )
                        except Exception:
                            pass

                score = compute_score(child, me_idx)

                # Plan A: policy bonus 加算 (= NN が好む action を beam に優先入れる)
                if policy_dict:
                    action_cls = type(action).__name__
                    prob = policy_dict.get(action_cls)
                    if prob is not None:
                        score = score + _W_POLICY * math.log(max(prob, 1e-6))

                # Plan Imit-3: imitation prior bonus (= 人間採用率の高いカードを beam に優先)
                if _USE_IMIT:
                    try:
                        card_id = None
                        # PlayCharacter / PlayEvent / PlayStage action は card 属性を持つ
                        if hasattr(action, "card") and action.card is not None:
                            card_id = getattr(action.card, "card_id", None)
                        if card_id:
                            me_leader_id = getattr(cur_state.players[me_idx].leader.card, "card_id", None)
                            if me_leader_id:
                                prior = get_card_play_prior(me_leader_id, card_id)
                                # adoption_rate 0.5 を baseline、 上振れで bonus / 下振れで penalty
                                score = score + _W_IMIT * (prior - 0.5)
                    except Exception:
                        pass  # imitation 失敗時は plan_search 止めない

                # Plan G: turn_plan bonus (= 現 turn の candidate_cards に bonus)
                if _USE_TURN_PLAN and _me_deck_analysis:
                    try:
                        card_id = None
                        if hasattr(action, "card") and action.card is not None:
                            card_id = getattr(action.card, "card_id", None)
                        if card_id:
                            cands = get_turn_plan_candidates(_me_deck_analysis, cur_state.turn_number)
                            if card_id in cands:
                                score = score + _W_TURN_PLAN
                    except Exception:
                        pass  # turn_plan 失敗時は plan_search 止めない

                # Plan H: goal-directed target bonus (= 2026-05-19)
                # Claude が 書いた target spec で 「ターン目標 達成 leaf」 に bonus 加算。
                # target.bonus (= 500-2000) を W_GOAL_TARGET で スケール。
                if _USE_GOAL_TARGET and _me_target_spec:
                    try:
                        target_bonus = compute_target_match_bonus(
                            child, me_idx, _me_target_spec, child.turn_number,
                            plan=plan + [action],
                        )
                        if target_bonus > 0:
                            score = score + _W_GOAL_TARGET * target_bonus
                    except Exception:
                        pass  # target match 失敗時は plan_search 止めない

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
