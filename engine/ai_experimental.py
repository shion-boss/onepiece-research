# -*- coding: utf-8 -*-
"""実験的 AI 集 (= 2026-05-17 overnight search)。

各 AI は PlanningAI を継承し、 strategy 1 つだけ変える設計。
mirror 対戦 (= 同デッキ vs baseline PlanningAI_NoNN) で 強さを評価。

NN 関連は default で OFF (= ベース動作は線形 eval、 比較用)。
NN-on / adaptive を試したい場合は別途 environment 制御。
"""

from __future__ import annotations

import copy
from typing import Optional

from .ai import GreedyAI, PlanningAI, legal_actions
from .core import GameState
from .game import EndPhase
from .nn_eval import nn_disabled


# ------------------------------------------------------------------ #
# Helper: NN-off ベースの PlanningAI 派生
# ------------------------------------------------------------------ #


class _NoNNPlanningBase(PlanningAI):
    """nn_disabled context を choose_action / choose_defense で常時適用する基底。

    実験 AI は全部 NN-off 動作にして 線形 eval の改良効果のみ測る (= 公平比較)。
    """

    def choose_action(self, state: GameState):
        with nn_disabled():
            return super().choose_action(state)

    def choose_defense(self, state, attacker, target, is_leader_attack, defender):
        with nn_disabled():
            return super().choose_defense(state, attacker, target, is_leader_attack, defender)


# ------------------------------------------------------------------ #
# C1: AggressivePlanningAI
#   - W_LETHAL / W_OPP_LIFE / W_FIELD_POWER を増幅
#   - 「殴って勝つ」 を強化する weights override
# ------------------------------------------------------------------ #


class AggressivePlanningAI(_NoNNPlanningBase):
    """攻撃重み増幅 PlanningAI。

    select_weights_for_player の結果を override し、 攻撃系 weight を multiplier 倍する。
    """

    name = "AggressivePlanning"

    def __init__(self, *args, lethal_mult: float = 2.0, opp_life_mult: float = 1.5,
                 field_power_mult: float = 1.5, **kwargs):
        super().__init__(*args, **kwargs)
        self.lethal_mult = lethal_mult
        self.opp_life_mult = opp_life_mult
        self.field_power_mult = field_power_mult

    def choose_action(self, state: GameState):
        # weights override (= state を deep copy せず global で eval 介入は重い、
        # シンプル戦略: ターン中の weights override を環境変数で eval.py に渡す。
        # eval.py の compute_score は select_weights_for_player を呼ぶ →
        # archetype 別 weights JSON 既存仕組みを流用するのが本道だが、
        # 実験では monkey patch で OK。)
        import os
        os.environ["ONEPIECE_AGGRO_LETHAL_MULT"] = str(self.lethal_mult)
        os.environ["ONEPIECE_AGGRO_OPP_LIFE_MULT"] = str(self.opp_life_mult)
        os.environ["ONEPIECE_AGGRO_FIELD_POWER_MULT"] = str(self.field_power_mult)
        try:
            return super().choose_action(state)
        finally:
            os.environ.pop("ONEPIECE_AGGRO_LETHAL_MULT", None)
            os.environ.pop("ONEPIECE_AGGRO_OPP_LIFE_MULT", None)
            os.environ.pop("ONEPIECE_AGGRO_FIELD_POWER_MULT", None)


# ------------------------------------------------------------------ #
# C2: DefensivePlanningAI
#   - W_LIFE / W_BLOCKER / W_ATTACHED_DON を増幅
#   - 「守って勝つ」 を強化
# ------------------------------------------------------------------ #


class DefensivePlanningAI(_NoNNPlanningBase):
    """守備重み増幅 PlanningAI。"""

    name = "DefensivePlanning"

    def __init__(self, *args, life_mult: float = 1.5, blocker_mult: float = 1.5,
                 attached_don_mult: float = 1.3, **kwargs):
        super().__init__(*args, **kwargs)
        self.life_mult = life_mult
        self.blocker_mult = blocker_mult
        self.attached_don_mult = attached_don_mult

    def choose_action(self, state: GameState):
        import os
        os.environ["ONEPIECE_DEF_LIFE_MULT"] = str(self.life_mult)
        os.environ["ONEPIECE_DEF_BLOCKER_MULT"] = str(self.blocker_mult)
        os.environ["ONEPIECE_DEF_ATTACHED_DON_MULT"] = str(self.attached_don_mult)
        try:
            return super().choose_action(state)
        finally:
            os.environ.pop("ONEPIECE_DEF_LIFE_MULT", None)
            os.environ.pop("ONEPIECE_DEF_BLOCKER_MULT", None)
            os.environ.pop("ONEPIECE_DEF_ATTACHED_DON_MULT", None)


# ------------------------------------------------------------------ #
# C3: LethalRusherAI
#   - 自分のターン開始時に 「リーサルが見える」 か即チェック
#   - 見えたら plan_search を skip して 最短 リーサル 手筋を直接返す
#   - そうでなければ通常 PlanningAI
# ------------------------------------------------------------------ #


class LethalRusherAI(_NoNNPlanningBase):
    """リーサル検出時に強制実行する PlanningAI。

    GreedyAI に既にある lethal_planner.plan_optimal_attack_sequence を使う。
    """

    name = "LethalRusher"

    def choose_action(self, state: GameState):
        # GreedyAI が持つ lethal 検出を借りる
        try:
            from .lethal_planner import plan_optimal_attack_sequence
            attacks = plan_optimal_attack_sequence(state, state.turn_player_idx)
            if attacks:
                # 最初の attack action を返す (= 連続攻撃は次の choose_action で続く)
                # legal_actions に含まれていれば return
                la = legal_actions(state)
                la_repr = {repr(a): a for a in la}
                if repr(attacks[0]) in la_repr:
                    return la_repr[repr(attacks[0])]
        except Exception:
            pass
        return super().choose_action(state)


# ------------------------------------------------------------------ #
# C4: DynamicBeamAI
#   - ターン数で beam_width を変える
#   - 序盤 (T1-3): 軽量 (= beam=2、 plan_search の組合せ爆発を抑える)
#   - 中盤 (T4-8): 標準 (= beam=3)
#   - 終盤 (T9+): 広い (= beam=4、 リーサル可能性を見逃さない)
# ------------------------------------------------------------------ #


class DynamicBeamAI(_NoNNPlanningBase):
    """ターン数で beam_width を動的に変える PlanningAI。"""

    name = "DynamicBeam"

    def choose_action(self, state: GameState):
        turn = state.turn_number
        if turn <= 3:
            self.beam_width = 2
            self.max_depth = 3
        elif turn <= 8:
            self.beam_width = 3
            self.max_depth = 3
        else:
            self.beam_width = 4
            self.max_depth = 4
        return super().choose_action(state)


# ------------------------------------------------------------------ #
# C5: HybridGreedyPlanning
#   - GreedyAI で 候補を絞り込む (= top-K)
#   - top-K の中で PlanningAI が精査
#   - 計算コスト軽減 + plan_search の expand quality 向上
# ------------------------------------------------------------------ #


class HybridGreedyPlanning(_NoNNPlanningBase):
    """GreedyAI で候補絞り込み + PlanningAI で精査。

    実装は plan_search の expand 関数を override が本道だが、 軽量実装として
    choose_action の冒頭で GreedyAI に 1 手聞いて、 その手と +plan_search の結果を
    比較し、 評価が同等なら GreedyAI の手を採用 (= 速度向上)。

    完全な「top-K 絞り込み + plan_search」 は重いので skip、 fast-path として
    GreedyAI 推奨手の検証だけ実装。
    """

    name = "HybridGreedyPlanning"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._greedy = GreedyAI(rng=kwargs.get("rng"), deck_analysis=kwargs.get("deck_analysis"))

    def choose_action(self, state: GameState):
        # GreedyAI の手と PlanningAI の手を両方計算、 評価が +α 以上なら Planning を採用
        try:
            greedy_action = self._greedy.choose_action(state)
        except Exception:
            return super().choose_action(state)

        # PlanningAI の plan_search 結果
        plan_action = super().choose_action(state)

        # 同じ手なら return
        if repr(greedy_action) == repr(plan_action):
            return greedy_action

        # 違う手なら PlanningAI を採用 (= plan_search の方が深く読んでいる前提)
        return plan_action


# ------------------------------------------------------------------ #
# C6: AdaptiveBeamDepthAI
#   - phase + ハンド数で beam/depth を動的に
#   - ハンド多い (= 序盤?) → beam 広く
#   - ハンド少ない (= 終盤?) → depth 深く
# ------------------------------------------------------------------ #


class TwoTurnPlanningAI(_NoNNPlanningBase):
    """2026-05-18: 自分ターン + 相手ターン sim + 自分ターン まで読む PlanningAI 派生。

    既存 beam=2,depth=3 (= 1 ターン読み) に対して max_turns=2 で 多ターン読み。
    plan_search が内部で opp ターン sim を行う (= 軽量 GreedyAI 固定で高速化)。

    リーサル準備手筋 (= 「いま DON 温存 → 次ターン大型キャラ → リーサル」) を発見可能。
    """

    name = "TwoTurnPlanning"

    def __init__(self, *args, **kwargs):
        # max_turns=2 を強制、 beam/depth は kwargs override 可能
        kwargs.setdefault("max_turns", 2)
        kwargs.setdefault("beam_width", 2)  # 軽量 default
        kwargs.setdefault("max_depth", 6)   # 2 turns × 3 actions = 6
        kwargs["adaptive"] = False  # max_turns_fixed が使われるよう adaptive 切る
        super().__init__(*args, **kwargs)

    def choose_action(self, state):
        # 高速化: opp sim を GreedyAI 固定 (= 50-100x 高速)
        # + dynamic weights (= OPTCG メカニクス対応、 ライフ受け OK 判断)
        import os
        saved_opp = os.environ.get("ONEPIECE_LIGHT_OPP_SIM")
        saved_dw = os.environ.get("ONEPIECE_DYNAMIC_WEIGHTS")
        os.environ["ONEPIECE_LIGHT_OPP_SIM"] = "1"
        os.environ["ONEPIECE_DYNAMIC_WEIGHTS"] = "1"
        try:
            return super().choose_action(state)
        finally:
            if saved_opp is None:
                del os.environ["ONEPIECE_LIGHT_OPP_SIM"]
            else:
                os.environ["ONEPIECE_LIGHT_OPP_SIM"] = saved_opp
            if saved_dw is None:
                del os.environ["ONEPIECE_DYNAMIC_WEIGHTS"]
            else:
                os.environ["ONEPIECE_DYNAMIC_WEIGHTS"] = saved_dw


class EndPhasePenaltyAI(_NoNNPlanningBase):
    """2026-05-18 bad_moves 対応: EndPhase penalty 有効化 PlanningAI。

    plan_search の leaf eval で 「自分ターン終了時に未消費リソース (= active chara / DON /
    leader unrested)」 を penalty 化、 「攻撃せず終わる」 を回避させる。
    """

    name = "EndPhasePenalty"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("beam_width", 2)
        kwargs.setdefault("max_depth", 3)
        kwargs.setdefault("adaptive", False)
        super().__init__(*args, **kwargs)

    def choose_action(self, state):
        import os
        saved = os.environ.get("ONEPIECE_END_PHASE_PENALTY")
        os.environ["ONEPIECE_END_PHASE_PENALTY"] = "1"
        try:
            return super().choose_action(state)
        finally:
            if saved is None:
                del os.environ["ONEPIECE_END_PHASE_PENALTY"]
            else:
                os.environ["ONEPIECE_END_PHASE_PENALTY"] = saved


class AlphaZeroMCTSAI(_NoNNPlanningBase):
    """Plan D + MCTS (= 2026-05-18 本格 AlphaZero 構造):

    既存 plan_search の beam search ではなく、 **真の MCTS** で探索。
    leaf state の eval を AlphaZero 風 value NN (= db/value_nn_alphazero.pt) で計算。

    既存 engine.ai.MCTSAI を継承して NN value 注入版を作る。
    rollout が NN value で置換 → 探索速度 + 評価質 両方アップ。
    """

    name = "AlphaZeroMCTS"

    def __init__(self, *args, n_simulations: int = 50, c_uct: float = 1.41, **kwargs):
        # PlanningAI 側は使わない、 MCTS を choose_action で直接呼ぶ
        super().__init__(*args, **kwargs)
        from .ai import MCTSAI
        self._mcts = MCTSAI(
            rng=kwargs.get("rng"),
            n_simulations=n_simulations,
            c_uct=c_uct,
            rollout_depth=6,  # 軽め (= NN value で leaf eval なら rollout 不要)
            deck_analysis=kwargs.get("deck_analysis"),
        )

    def choose_action(self, state):
        # MCTS で choose_action、 ただし leaf eval で NN value を使う
        # 既存 MCTSAI.choose_action は rollout で eval、 NN は別 path
        # ここでは ONEPIECE_AZ_VALUE_NN を立てて compute_score 経由で NN value 出すよう促す
        import os
        saved = os.environ.get("ONEPIECE_AZ_VALUE_NN")
        os.environ["ONEPIECE_AZ_VALUE_NN"] = "1"
        try:
            with nn_disabled():
                # nn_disabled で v1-v5 v5 NN は無効化、 AZ value NN のみ通る
                # ただし AZ NN 自体は別 module、 nn_disabled の影響受けない (= 別 path)
                return self._mcts.choose_action(state)
        finally:
            if saved is None:
                del os.environ["ONEPIECE_AZ_VALUE_NN"]
            else:
                os.environ["ONEPIECE_AZ_VALUE_NN"] = saved


class AlphaZeroValueAI(TwoTurnPlanningAI):
    """Plan D (= 2026-05-18): AlphaZero 風 value NN を leaf eval で使う TwoTurn AI。

    db/value_nn_alphazero.pt 必要。 学習方法は Plan D notebook (= colab)。
    plan_search の leaf eval で「NN(state) = P(win)」 → 2P-1 × magnify で score。
    """

    name = "AlphaZeroValue"

    def choose_action(self, state):
        import os
        saved = os.environ.get("ONEPIECE_AZ_VALUE_NN")
        os.environ["ONEPIECE_AZ_VALUE_NN"] = "1"
        try:
            return super().choose_action(state)
        finally:
            if saved is None:
                del os.environ["ONEPIECE_AZ_VALUE_NN"]
            else:
                os.environ["ONEPIECE_AZ_VALUE_NN"] = saved


class MegaPlanningAI(TwoTurnPlanningAI):
    """Plan F + Plan D + adaptive 統合 (= 2026-05-18 集大成、 本気で人間越え狙う):

    - 2 ターン読み + 軽量 opp sim (= TwoTurnPlanningAI base)
    - AlphaZero 風 value NN を leaf eval (= Plan D)
    - 重み NN (= Plan F) で 動的重み (= Plan D NN 不在時の fallback)
    - per-deck NN preference 機構は existing DeepPlanningAI で自動

    優先順位: Plan D > Plan F > 線形 eval (= compute_score 内 path で自動 cascade)
    """

    name = "MegaPlanning"

    def choose_action(self, state):
        import os
        # 全ての NN を有効化、 compute_score 内で cascade (= AZ > WeightNN > 線形)
        saved = {
            k: os.environ.get(k)
            for k in ["ONEPIECE_AZ_VALUE_NN", "ONEPIECE_WEIGHT_NN", "ONEPIECE_DYNAMIC_WEIGHTS"]
        }
        os.environ["ONEPIECE_AZ_VALUE_NN"] = "1"
        os.environ["ONEPIECE_WEIGHT_NN"] = "1"
        os.environ["ONEPIECE_DYNAMIC_WEIGHTS"] = "1"
        try:
            return super().choose_action(state)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class WeightNNTwoTurnAI(TwoTurnPlanningAI):
    """Plan F TwoTurn 正規版 (= 2026-05-18 ユーザ示唆):

    対戦用 AI = TwoTurnPlanningAI (= 2 ターン読み + 軽量 opp sim) を **固定**、
    その AI の **専用** 評価関数を NN で学習する (= 共進化)。

    朝の WeightNNPlanningAI (= 1 ターン読み + NN) は順序が逆だった。
    本クラスが ユーザ示唆の正しい設計。
    """

    name = "WeightNNTwoTurn"

    def choose_action(self, state):
        import os
        saved_wnn = os.environ.get("ONEPIECE_WEIGHT_NN")
        os.environ["ONEPIECE_WEIGHT_NN"] = "1"
        try:
            # 親 TwoTurnPlanningAI が ONEPIECE_LIGHT_OPP_SIM=1 + DYNAMIC_WEIGHTS=1 を set、
            # WEIGHT_NN=1 を追加で set すれば eval が NN 重み path に流れる。
            return super().choose_action(state)
        finally:
            if saved_wnn is None:
                del os.environ["ONEPIECE_WEIGHT_NN"]
            else:
                os.environ["ONEPIECE_WEIGHT_NN"] = saved_wnn


class WeightNNPlanningAI(_NoNNPlanningBase):
    """Plan F (= 2026-05-18): 重み NN を使う PlanningAI。

    choose_action 中に ONEPIECE_WEIGHT_NN=1 を set、 compute_score が
    weight_nn.compute_weights_nn を呼んで state-dependent な 9 dim weights を取得。
    既存 9 dim eval は維持、 重みだけ NN 動的化 (= AlphaZero 風 評価関数学習)。
    """

    name = "WeightNNPlanning"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("beam_width", 2)
        kwargs.setdefault("max_depth", 3)
        kwargs.setdefault("adaptive", False)
        super().__init__(*args, **kwargs)

    def choose_action(self, state):
        import os
        saved = os.environ.get("ONEPIECE_WEIGHT_NN")
        os.environ["ONEPIECE_WEIGHT_NN"] = "1"
        try:
            return super().choose_action(state)
        finally:
            if saved is None:
                del os.environ["ONEPIECE_WEIGHT_NN"]
            else:
                os.environ["ONEPIECE_WEIGHT_NN"] = saved


class AdaptiveBeamDepthAI(_NoNNPlanningBase):
    """ハンド枚数 + ターン数で beam/depth を変える。"""

    name = "AdaptiveBeamDepth"

    def choose_action(self, state: GameState):
        me_idx = state.turn_player_idx
        hand_size = len(state.players[me_idx].hand)
        turn = state.turn_number

        if hand_size >= 6:
            # 序盤、 候補多い → beam 広く
            self.beam_width = 4
            self.max_depth = 3
        elif hand_size >= 3:
            # 中盤
            self.beam_width = 3
            self.max_depth = 3
        else:
            # 終盤、 候補少なく → depth 深く
            self.beam_width = 2
            self.max_depth = 5

        return super().choose_action(state)
