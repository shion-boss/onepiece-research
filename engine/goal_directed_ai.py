# -*- coding: utf-8 -*-
"""Plan H (= 2026-05-19): Goal-directed Turn Planner AI。

Claude が 書いた target spec (= `decks/<slug>.target_v1.json`) で
「ターン終了時の 目標盤面」 を 先決め、 plan_search の leaf eval で
target match leaf に bonus 加算 する AI。

既存 reactive PlanningAI (= 各 action ごと argmax 局所最適) と 違い、
「ターン目標 駆動」 = proactive goal-directed thinking。

# 使い方

```python
from engine.goal_directed_ai import GoalDirectedAI

# deck slug を渡すと auto-load
ai = GoalDirectedAI(deck_slug="cardrush_1456")

# あるいは target spec を 直接渡す
ai = GoalDirectedAI(target_spec={"deck_slug": ..., "entries": [...]})

# default は env から auto-detect (= state.players[me].deck_slug 経由)
ai = GoalDirectedAI()
```

# env 制御

- `ONEPIECE_GOAL_TARGET_W` : スケール 係数 (= default 1.0、 target.bonus × 1.0 = 直接 加算)
- `ONEPIECE_GOAL_TARGET_W=0` で disable (= 既存 default 維持)

# 設計

- target.bonus (= Claude が 500-2000 で 書く) を 直接 score に 加算
- W_GOAL_TARGET=1.0 なら target.bonus そのまま、 2.0 なら 倍率 ×2
- 既存 W_TURN_PLAN (= 3000 fixed) と 違って、 target ごと に bonus を 変えられる
- これで 「ターン 4 で 必達 (= bonus 2000)」 vs 「fallback (= bonus 500)」 を 表現可能
"""

from __future__ import annotations

import os
from typing import Optional

from .ai_experimental import _NoNNPlanningBase
from .core import GameState
from .target_dsl import load_target_spec


class GoalDirectedAI(_NoNNPlanningBase):
    """Plan H Goal-directed Turn Planner (= Claude が 書いた target spec で 動く)。

    PlanningAI を継承、 NN-off 動作 (= 線形 eval の 比較 のため)。
    choose_action で `ONEPIECE_GOAL_TARGET_W` を 一時 set、 search_turn_plan に
    target spec を 渡す or auto-load させる。
    """

    name = "GoalDirected"

    def __init__(
        self,
        *args,
        goal_target_w: float = 1.0,
        target_spec: Optional[dict] = None,
        deck_slug: Optional[str] = None,
        spec_version: str = "v1",
        recursion_depth: int = 0,
        strong: bool = False,
        exploration_eps: float = 0.0,
        **kwargs,
    ):
        """
        Args:
            goal_target_w: target.bonus に かける スケール係数 (= default 1.0)。
            target_spec: 明示指定の target spec dict。 None なら deck_slug or auto-load。
            deck_slug: target spec を load する deck slug。 None なら state から auto-detect。
            spec_version: "v1" (= default refined) or "v2" (= cross-trained、 2026-05-20)
            recursion_depth: 0 = 通常 plan_search、 1 = 内部 opp_sim (= plan_search 動作)、
                            2+ = GreedyAI fallback (= 無限再帰回避)。 plan_search.py が
                            ONEPIECE_GOAL_MIRROR_OPP=1 で opp_sim_ai 生成時に
                            recursion_depth=1 で構築する。
            strong: True で v2 強化モード (= 2026-05-28)。 構造的 改善 (= 計算量 同等) のみ:
                    - eval.py: opp_life≤2 or self_life≤1 で W_OPP_NEXT_LETHAL × 1.5
                    - plan_search.py: opp_life≤2 で「active attacker 残し plan」 を -2000/未使用 で penalty
                    - ai.py choose_defense: defender life ≤ 2 で counter 閾値 ×1.5、 max_cards+1
                    choose_action 中 だけ ONEPIECE_GOAL_STRONG=1 を set (= eval.py / plan_search.py 用)。
                    choose_defense は opp ターン中 呼出 で env 未 set なので self._strong 直接参照。
                    default False = 既存 baseline 互換。
        """
        # strong mode は beam / depth 同じ (= 計算量 爆発 回避)。 強化 は eval boost /
        # defense threshold / plan penalty で 達成。
        self._strong = strong
        kwargs.setdefault("beam_width", 4)
        kwargs.setdefault("max_depth", 6)
        kwargs.setdefault("adaptive", False)
        super().__init__(*args, **kwargs)
        self._goal_target_w = goal_target_w
        self._explicit_target_spec = target_spec
        self._deck_slug = deck_slug
        self._spec_version = spec_version
        self.recursion_depth = recursion_depth
        # ε-greedy exploration (= 2026-05-29、 [[project_corpus_methodology_dead_end]])
        # 0.0 = 通常 (= argmax)、 0.05-0.10 = corpus 収集 中 の 探索 用。
        # base_eval が 推さない 行動 を ε で 試行 → corpus に 多様 性 注入 →
        # build_spec が 「base_eval-conflicting winning action」 を 学習 可能 に なる。
        self._exploration_eps = float(exploration_eps)

    # _compute_adaptive_params override は 削除 (= 2026-05-28)。
    # strong mode で beam+1 すると mid/late 計算量 倍以上 で 実用 不能。
    # 強化 は eval boost / defense threshold / plan penalty (= 構造的) のみ で 達成 する。

    def _resolve_target_spec(self, state: GameState) -> Optional[dict]:
        """target spec を 解決。 優先順位: 明示 > deck_slug 引数 > state から auto-detect。

        v3 (= NN value 統合) で target_v3.json なし の 場合、 v1 file を fallback load。
        """
        if self._explicit_target_spec is not None:
            return self._explicit_target_spec
        if self._deck_slug:
            spec = load_target_spec(self._deck_slug, version=self._spec_version)
            # v3 で .target_v3.json なし → v1 fallback (= NN value + v1 spec 統合)
            if spec is None and self._spec_version != "v1":
                spec = load_target_spec(self._deck_slug, version="v1")
            return spec
        # auto-detect: state.deck_slugs[me_idx] (= setup_game で 設定) を 優先、
        # fallback で state.players[me_idx].deck_slug (= 一部 path で 注入 される 可能性)
        me_idx = state.turn_player_idx
        try:
            slug: Optional[str] = None
            deck_slugs = getattr(state, "deck_slugs", None)
            if deck_slugs and me_idx < len(deck_slugs):
                slug = deck_slugs[me_idx] or None
            if not slug:
                me_player = state.players[me_idx]
                slug = getattr(me_player, "deck_slug", None)
            if slug:
                spec = load_target_spec(slug, version=self._spec_version)
                if spec is None and self._spec_version != "v1":
                    spec = load_target_spec(slug, version="v1")
                return spec
        except Exception:
            pass
        return None

    def _choose_action_pure_lookup(self, state: GameState):
        """pure lookup mode (= 2026-05-30、 ohtsuki さん 提 案):

        beam search 完 全 bypass、 spec の bonus argmax のみ で action 決 定。
        ONEPIECE_PURE_LOOKUP=1 で 有 効化。

        - rich axes (= 12 軸) で entry 絞 込 み
        - 各 legal action の matched target bonus を 計 算
        - argmax(bonus) で 採 用
        - ε-greedy exploration で 探 索
        - 推 論 ~50ms/decision (= beam の 100x 高 速)
        """
        from .game import legal_actions, EndPhase
        from .axis_compute import compute_axes_from_state
        from .target_dsl import find_matching_entries_v2

        me_idx = state.turn_player_idx

        # state axes 計 算
        try:
            # opp_archetype は deck_analysis から
            opp_arch = "midrange"
            opp_player = state.players[1 - me_idx]
            if hasattr(opp_player, "deck_analysis") and isinstance(opp_player.deck_analysis, dict):
                opp_arch = opp_player.deck_analysis.get("archetype", "midrange")
            state_axes = compute_axes_from_state(state, me_idx, opp_arch)
        except Exception:
            state_axes = {}

        # spec から match entries
        spec = self._resolve_target_spec(state) or {}
        entries = find_matching_entries_v2(spec, state_axes) if state_axes else []

        # legal_actions
        legal = legal_actions(state)
        if not legal:
            return EndPhase()
        if len(legal) == 1:
            return legal[0]

        # ε-greedy 探 索
        if self._exploration_eps > 0 and self.rng.random() < self._exploration_eps:
            return self.rng.choice(legal)

        # 各 action の bonus 計 算 (= matched targets の MAX)
        def _action_bonus(action) -> int:
            action_kind = action.__class__.__name__
            best = 0
            for entry, weight in entries:
                for tgt in entry.get("targets", []):
                    if tgt.get("action_kind") != action_kind:
                        continue
                    # action_card_id 一 致 を 優 先 (= 細 粒 度 一 致 で bonus 高)
                    tgt_cid = tgt.get("action_card_id")
                    act_cid = getattr(action, "card_id", None) or self._resolve_action_card_id(action, state, me_idx)
                    if tgt_cid and act_cid and tgt_cid != act_cid:
                        continue
                    contribution = int(tgt.get("bonus", 0) * weight)
                    if contribution > best:
                        best = contribution
            return best

        # argmax(bonus)、 同 値 なら rng 選 択
        action_scores = [(a, _action_bonus(a)) for a in legal]
        max_score = max(s for _, s in action_scores)
        best_actions = [a for a, s in action_scores if s == max_score]
        if len(best_actions) == 1:
            return best_actions[0]
        return self.rng.choice(best_actions)

    def _resolve_action_card_id(self, action, state, me_idx):
        """action に card_id が ない (= hand_idx のみ) 場合 解 決。"""
        hand_idx = getattr(action, "hand_idx", None)
        if hand_idx is None:
            return None
        me = state.players[me_idx]
        if 0 <= hand_idx < len(me.hand):
            return me.hand[hand_idx].card.card_id
        return None

    def choose_action(self, state: GameState):
        if self.recursion_depth >= 2:
            from .ai import GreedyAI
            return GreedyAI.choose_action(self, state)
        # pure lookup mode (= 2026-05-30): beam search bypass
        if os.environ.get("ONEPIECE_PURE_LOOKUP", "0") == "1":
            try:
                return self._choose_action_pure_lookup(state)
            except Exception as e:
                # 失 敗 時 は beam に fallback (= 安 全)
                pass
        saved = os.environ.get("ONEPIECE_GOAL_TARGET_W")
        os.environ["ONEPIECE_GOAL_TARGET_W"] = str(self._goal_target_w)
        # v3: Phase H-3 NN value 加算 path (= 2026-05-20)
        # spec_version="v3" で ONEPIECE_AZ_VALUE_NN=1 set、 plan_search の leaf eval で
        # compute_value_az 経由 P(win) を score 加算。 ONEPIECE_AZ_VALUE_NN_PATH で model 指定。
        saved_nn = os.environ.get("ONEPIECE_AZ_VALUE_NN")
        saved_nn_path = os.environ.get("ONEPIECE_AZ_VALUE_NN_PATH")
        if self._spec_version == "v3":
            os.environ["ONEPIECE_AZ_VALUE_NN"] = "1"
            os.environ["ONEPIECE_AZ_VALUE_NN_PATH"] = "db/value_nn_phase_h3.pt"
        # v2 強化モード (= 2026-05-28、 strong=True 時)。 ONEPIECE_GOAL_STRONG=1 で:
        # 1) ai.py の defense / prune 強化、 2) eval.py の dynamic weight boost、
        # 3) plan_search.py の plan-level penalty 追加。
        # choose_action 中 だけ set、 finally で restore (= 相手 AI への 漏れ 防止)。
        saved_strong = os.environ.get("ONEPIECE_GOAL_STRONG")
        if self._strong:
            os.environ["ONEPIECE_GOAL_STRONG"] = "1"
        # target spec を state に attach (= search_turn_plan の auto-load で 拾う)。
        # 既存 attached spec が あれば 上書きしない (= 多重呼出し対応)
        target_spec = self._resolve_target_spec(state)
        attached = False
        if target_spec is not None and not getattr(state, "_goal_target_spec", None):
            state._goal_target_spec = target_spec  # type: ignore[attr-defined]
            attached = True
        try:
            action = super().choose_action(state)
            # === ε-greedy exploration (= corpus 多様 化 用、 推論 時 は eps=0) ===
            if (self._exploration_eps > 0 and self.recursion_depth == 0
                    and self.rng.random() < self._exploration_eps):
                from .game import legal_actions
                try:
                    legal = legal_actions(state)
                    alts = [a for a in legal if a != action]
                    if alts:
                        action = self.rng.choice(alts)
                except Exception:
                    pass  # 探索 失敗 = 元 action を 使う
            return action
        finally:
            if saved is None:
                os.environ.pop("ONEPIECE_GOAL_TARGET_W", None)
            else:
                os.environ["ONEPIECE_GOAL_TARGET_W"] = saved
            # NN env restore
            if self._spec_version == "v3":
                if saved_nn is None:
                    os.environ.pop("ONEPIECE_AZ_VALUE_NN", None)
                else:
                    os.environ["ONEPIECE_AZ_VALUE_NN"] = saved_nn
                if saved_nn_path is None:
                    os.environ.pop("ONEPIECE_AZ_VALUE_NN_PATH", None)
                else:
                    os.environ["ONEPIECE_AZ_VALUE_NN_PATH"] = saved_nn_path
            # strong env restore (= 相手 AI / 次 turn AI が baseline なら 漏れ ない)
            if self._strong:
                if saved_strong is None:
                    os.environ.pop("ONEPIECE_GOAL_STRONG", None)
                else:
                    os.environ["ONEPIECE_GOAL_STRONG"] = saved_strong
            if attached:
                try:
                    delattr(state, "_goal_target_spec")
                except Exception:
                    pass
