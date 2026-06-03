# -*- coding: utf-8 -*-
"""層5: PlanLibraryAI — 塊プランを選んで commit 実行する AI。

[[project_superhuman_ai_distillation]] の 6 層パイプラインの実体:

  ターン開始 (= 自分の MAIN 初手) で:
    1. enumerate_turn_plans で cost-feasible な全プランを列挙 (= 層1)
    2. 各プランを PlanBonusTable.value で採点 (= 勝率 bonus 主 + 盤面 value 補完、 層3)
    3. argmax プランを採用、 concrete_template を commit (= 層5)
  以降の choose_action で commit 済み行動列を順に消化。 盤面が乖離 (= opp 防御で
  攻撃対象消失 等) したら GreedyAI に委譲 (= 安全 fallback)。

学習 (= 層6 value iteration) は self-play で選んだ (cell, multiset_sig) を state に記録し、
試合結果で PlanBonusTable を更新する。 選択の記録は state._plan_choices[me_idx] に貯める。

binding (= 層4: 抽象スロットの role 別具体化) は Phase 2。 現状は enumerate の canonical 束縛
(= engine auto-pick) をそのまま commit する。
"""
from __future__ import annotations

import os
from typing import Any, Optional

from .ai import GreedyAI
from .game import EndPhase, legal_actions
from .plan_library import (
    _CELL_AXES_COARSE,
    PlanBonusTable,
    cell_key_from_state,
    multiset_key,
)


class PlanLibraryAI(GreedyAI):
    """塊プラン commit 型 AI (= GreedyAI を fallback に継承)。"""

    name = "PlanLibrary"

    def __init__(
        self,
        rng=None,
        deck_analysis: Optional[dict] = None,
        *,
        bonus_table: Optional[PlanBonusTable] = None,
        node_cap: int = 2500,
        plan_eps: float = 0.0,
        min_n: int = 1,
        record_choices: bool = True,
        cell_axes: tuple = _CELL_AXES_COARSE,
        **kwargs,
    ):
        super().__init__(rng=rng, deck_analysis=deck_analysis, **kwargs)
        self.bonus_table = bonus_table if bonus_table is not None else PlanBonusTable()
        self._node_cap = node_cap
        self._cell_axes = cell_axes
        # plan_eps = プランレベル ε 探索 (= 収集時のみ >0、 未学習プランへ sample 注入)。
        self._plan_eps = float(plan_eps)
        self._min_n = min_n
        self._record_choices = record_choices
        # commit 状態 (= ターンごとに reset)
        self._turn_key: Optional[tuple] = None
        self._committed: list = []
        self._greedy_rest = False
        self._chosen: Optional[tuple] = None  # (cell, mk) of 採用プラン (= 直近)

    # --- opp archetype (= cell 計算用) ---
    def _opp_archetype(self, state: Any, me_idx: int) -> str:
        opp = state.players[1 - me_idx]
        da = getattr(opp, "deck_analysis", None)
        if isinstance(da, dict):
            return da.get("archetype", "midrange")
        return "midrange"

    def _record_choice(self, state: Any, me_idx: int, cell: tuple, mk) -> None:
        if not self._record_choices:
            return
        store = getattr(state, "_plan_choices", None)
        if store is None:
            store = {0: [], 1: []}
            try:
                state._plan_choices = store  # type: ignore[attr-defined]
            except Exception:
                return
        store.setdefault(me_idx, []).append((cell, mk))

    def _select_plan(self, state: Any, me_idx: int) -> list:
        """enumerate → score → argmax。 採用プランの concrete action 列を返す。"""
        from .turn_plan_enumerator import enumerate_turn_plans

        try:
            plans, _stats = enumerate_turn_plans(
                state, me_idx, node_cap=self._node_cap,
            )
        except Exception:
            plans = []
        if not plans:
            self._chosen = None
            return []

        opp_arch = self._opp_archetype(state, me_idx)
        cell = cell_key_from_state(state, me_idx, opp_arch, self._cell_axes)

        def _score(p) -> float:
            mk = multiset_key(p.signature)
            return self.bonus_table.value(cell, mk, p.eval_score)

        # プランレベル ε 探索 (= 収集時のみ)。 未学習プランを試して corpus に多様性注入。
        if self._plan_eps > 0 and self.rng.random() < self._plan_eps:
            chosen = self.rng.choice(plans)
        else:
            best = max(_score(p) for p in plans)
            top = [p for p in plans if _score(p) >= best - 1e-9]
            chosen = top[0] if len(top) == 1 else self.rng.choice(top)

        mk = multiset_key(chosen.signature)
        self._chosen = (cell, mk)
        self._record_choice(state, me_idx, cell, mk)
        return list(chosen.concrete_template)

    def choose_action(self, state: Any):
        me_idx = state.turn_player_idx
        actions = legal_actions(state)
        if not actions:
            return EndPhase()
        if len(actions) == 1:
            return actions[0]

        turn_key = (state.turn_number, me_idx)
        if turn_key != self._turn_key:
            # 新ターン: プラン選択 (= commit 列を作る)
            self._turn_key = turn_key
            self._greedy_rest = False
            self._committed = self._select_plan(state, me_idx)

        # 乖離後 (= commit と実盤面がズレた) は GreedyAI で残りを打つ
        if self._greedy_rest:
            return super().choose_action(state)

        # commit 列を順に消化
        while self._committed:
            nxt = self._committed.pop(0)
            if nxt in actions:
                return nxt
            # 盤面乖離 (= 攻撃対象消失 等) → GreedyAI に委譲
            self._committed = []
            self._greedy_rest = True
            return super().choose_action(state)

        # プラン完遂 → ターン終了
        return EndPhase()
