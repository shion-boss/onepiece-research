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

from collections import Counter

from .ai import GreedyAI
from .core import Phase
from .game import EndPhase, legal_actions
from .plan_library import (
    _CELL_AXES_COARSE,
    PlanBonusTable,
    cell_key_from_state,
    multiset_key,
)
from .plan_search import _apply_with_defense, fast_clone


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
        def_table: Optional[PlanBonusTable] = None,
        def_eps: float = 0.0,
        record_def_choices: bool = False,
        **kwargs,
    ):
        super().__init__(rng=rng, deck_analysis=deck_analysis, **kwargs)
        self.bonus_table = bonus_table if bonus_table is not None else PlanBonusTable()
        self._node_cap = node_cap
        self._cell_axes = cell_axes
        # 相手ターン防御 (= ブロック/カウンター) の学習 bonus (= 別テーブル)。
        self.def_table = def_table if def_table is not None else PlanBonusTable()
        self._def_eps = float(def_eps)
        self._record_def = record_def_choices
        # plan_eps = プランレベル ε 探索 (= 収集時のみ >0、 未学習プランへ sample 注入)。
        self._plan_eps = float(plan_eps)
        self._min_n = min_n
        self._record_choices = record_choices
        # commit 状態 (= ターンごとに reset)
        self._turn_key: Optional[tuple] = None
        self._committed: list = []
        self._greedy_rest = False
        self._chosen: Optional[tuple] = None  # (cell, mk) of 採用プラン (= 直近)
        # greedy anchor 用 (= cold-start prior。 board_eval は死に手 prior なので使わない)。
        self._anchor_ai = GreedyAI(rng=self.rng, deck_analysis=self.deck_analysis)
        self.debug = False
        self.debug_log: list = []

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

    def _greedy_anchor(self, state: Any, me_idx: int) -> tuple:
        """GreedyAI のターンを sim → (multiset_key, 具体 action 列)。

        cold-start prior = 「greedy が打つプラン」。 board_eval prior は end-of-turn の
        失効 DON / 場 power を過大評価し死に手を選ぶ (= 実測 vs Greedy 2%) ので使わない。
        """
        from .turn_plan_enumerator import abstract_token

        sim = fast_clone(state)
        g = self._anchor_ai
        tokens: list = []
        seq: list = []
        guard = 0
        while (not sim.game_over and sim.turn_player_idx == me_idx
               and sim.phase == Phase.MAIN and guard < 40):
            try:
                a = g.choose_action(sim)
            except Exception:
                break
            if isinstance(a, EndPhase):
                break
            tokens.append(abstract_token(a, sim, me_idx))
            seq.append(a)
            try:
                _apply_with_defense(sim, a, g)
            except Exception:
                break
            guard += 1
        return frozenset(Counter(tokens).items()), seq

    def _select_plan(self, state: Any, me_idx: int) -> list:
        """enumerate → greedy-anchor prior + 学習 bonus で argmax → commit 列。"""
        from .turn_plan_enumerator import enumerate_turn_plans

        try:
            plans, _stats = enumerate_turn_plans(state, me_idx, node_cap=self._node_cap)
        except Exception:
            plans = []

        opp_arch = self._opp_archetype(state, me_idx)
        cell = cell_key_from_state(state, me_idx, opp_arch, self._cell_axes)
        anchor_mk, anchor_seq = self._greedy_anchor(state, me_idx)

        n = len(plans)
        mks = [multiset_key(p.signature) for p in plans]
        mkset = set(mks)

        # anchor が enumerate に無い (= rare) → greedy 実シーケンスをそのまま commit (= base 保証)。
        if not plans or anchor_mk not in mkset:
            self._chosen = (cell, anchor_mk)
            self._record_choice(state, me_idx, cell, anchor_mk)
            if getattr(self, "debug", False):
                self.debug_log.append({
                    "turn": state.turn_number, "n_plans": n, "is_anchor": True,
                    "chosen_sig": ["<greedy-anchor>"], "n_attacks": -1,
                    "chosen_n_learned": self.bonus_table.get_counts(cell, anchor_mk)[0],
                    "value": -1})
            return list(anchor_seq)

        # prior: anchor=1.0、 その他=board_eval percentile×0.01 (= 微弱 tiebreak のみ、 学習が主)。
        order = sorted(range(n), key=lambda i: plans[i].eval_score)
        ev_pct = [0.0] * n
        for rank, i in enumerate(order):
            ev_pct[i] = rank / (n - 1) if n > 1 else 0.5
        prior = [1.0 if mks[i] == anchor_mk else 0.01 * ev_pct[i] for i in range(n)]
        scores = [self.bonus_table.value_with_prior(cell, mks[i], prior[i]) for i in range(n)]

        if self._plan_eps > 0 and self.rng.random() < self._plan_eps:
            ci = self.rng.randrange(n)
        else:
            best = max(scores)
            top = [i for i in range(n) if scores[i] >= best - 1e-9]
            ci = top[0] if len(top) == 1 else self.rng.choice(top)
        chosen = plans[ci]
        mk = mks[ci]
        self._chosen = (cell, mk)
        self._record_choice(state, me_idx, cell, mk)
        if getattr(self, "debug", False):
            n_tot, _ = self.bonus_table.get_counts(cell, mk)
            n_atk = sum(1 for t in chosen.signature if t and t[0] == "attack")
            self.debug_log.append({
                "turn": state.turn_number, "n_plans": n, "is_anchor": (mk == anchor_mk),
                "chosen_sig": [list(t) for t in chosen.signature], "n_attacks": n_atk,
                "chosen_n_learned": n_tot, "value": round(scores[ci], 3)})
        # anchor を選んだ時は greedy の実シーケンス (= 順序/対象も忠実) を commit。
        if mk == anchor_mk:
            return list(anchor_seq)
        return list(chosen.concrete_template)

    def _main_active(self) -> bool:
        """自ターン塊プランの学習/探索が有効か。 無効なら enumerate を skip して greedy 動作。"""
        return len(self.bonus_table) > 0 or self._record_choices or self._plan_eps > 0

    def choose_action(self, state: Any):
        me_idx = state.turn_player_idx
        actions = legal_actions(state)
        if not actions:
            return EndPhase()
        if len(actions) == 1:
            return actions[0]

        # main table 空 + 非記録 + eps0 = main は純 greedy → enumerate を skip して高速化
        # (= defense のみ学習する実験で 列挙コストを払わない。 choose_defense は別途学習適用)。
        if not self._main_active():
            return super().choose_action(state)

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

    # ===================================================================
    # 相手ターン防御 (= ブロック/カウンター) の学習 bonus (= ohtsuki 2026-06-04)
    # enumerate 防御応手 → greedy-anchor prior + 学習 bonus で argmax。
    # 「greedy の受けの甘さ」 を学習で突けば beam(59%) 超えの候補。
    # ===================================================================

    @staticmethod
    def _atk_bucket(p: int) -> str:
        if p <= 3000:
            return "lo"
        if p <= 5000:
            return "mid"
        if p <= 7000:
            return "hi"
        return "xhi"

    @staticmethod
    def _def_mk(sig: tuple) -> frozenset:
        """防御 signature を PlanBonusTable 互換の multiset key に (= 単元素)。"""
        return frozenset([(sig, 1)])

    def _defense_cell(self, state: Any, defender: Any, is_leader_attack: bool,
                      atk_p: int) -> tuple:
        from .axis_compute import life_bucket
        opp_leader = state.players[state.turn_player_idx].leader.card.card_id
        return (
            ("is_leader", bool(is_leader_attack)),
            ("atk_bucket", self._atk_bucket(atk_p)),
            ("self_life", life_bucket(len(defender.life))),
            ("opp_leader", opp_leader),
        )

    def _enum_defense(self, state: Any, attacker: Any, target: Any,
                      is_leader_attack: bool, defender: Any, atk_p: int) -> list:
        """防御応手を列挙: take / counter-survive / block_safe / block_sac / block_counter。"""
        tp = defender.leader.power if is_leader_attack else target.power
        gap = atk_p - tp
        cands = [(None, (), ("take",))]
        if gap >= 0:
            combo = self._optimal_counter_combo(defender.hand, gap)
            if combo:
                cands.append((None, tuple(combo), ("counter", len(combo))))
        can_block = (
            is_leader_attack
            and not getattr(attacker, "has_no_block_now", False)
            and not getattr(attacker, "attacker_prevents_blocker_until_turn_end", False)
        )
        if can_block:
            lock = getattr(attacker, "attacker_prevents_blocker_power_le", -1)
            avail = [
                c for c in defender.characters
                if not c.rested and not c.summoning_sickness and c.is_blocker_now
                and not (lock >= 0 and c.power <= lock)
            ]
            safe = [c for c in avail if c.power > atk_p]
            if safe:
                b = max(safe, key=lambda c: c.power)
                cands.append((b.instance_id, (), ("block_safe",)))
            if avail:
                b = max(avail, key=lambda c: c.power)
                cands.append((b.instance_id, (), ("block_sac",)))
                bgap = atk_p - b.power
                if bgap >= 0:
                    combo = self._optimal_counter_combo(defender.hand, bgap)
                    if combo:
                        cands.append((b.instance_id, tuple(combo), ("block_counter", len(combo))))
        seen: set = set()
        out: list = []
        for c in cands:
            if c[2] in seen:
                continue
            seen.add(c[2])
            out.append(c)
        return out

    def _defense_sig_of(self, g_block, g_counters, defender: Any, atk_p: int) -> tuple:
        """GreedyAI の防御 (= anchor) を signature に写像。"""
        if g_block is None:
            return ("counter", len(g_counters)) if g_counters else ("take",)
        if g_counters:
            return ("block_counter", len(g_counters))
        blk = next((c for c in defender.characters if c.instance_id == g_block), None)
        if blk is not None and blk.power > atk_p:
            return ("block_safe",)
        return ("block_sac",)

    def _record_def_choice(self, state: Any, defender_idx: int, cell: tuple, sig: tuple) -> None:
        if not self._record_def:
            return
        store = getattr(state, "_defense_choices", None)
        if store is None:
            store = {0: [], 1: []}
            try:
                state._defense_choices = store  # type: ignore[attr-defined]
            except Exception:
                return
        store.setdefault(defender_idx, []).append((cell, self._def_mk(sig)))

    def choose_defense(self, state: Any, attacker: Any, target: Any,
                       is_leader_attack: bool, defender: Any):
        # greedy anchor (= cold-start)。 必ず先に取得 (= matchup override 等の副作用込み)。
        g_block, g_counters = super().choose_defense(
            state, attacker, target, is_leader_attack, defender)
        g_counters = tuple(g_counters)

        est_buff = 0
        if state.effects_overlay:
            try:
                from .effects import estimate_attacker_self_buff
                est_buff = estimate_attacker_self_buff(state, attacker, state.effects_overlay)
            except Exception:
                est_buff = 0
        atk_p = attacker.power + est_buff

        try:
            cands = self._enum_defense(state, attacker, target, is_leader_attack, defender, atk_p)
        except Exception:
            return g_block, g_counters
        if len(cands) <= 1:
            return g_block, g_counters

        defender_idx = 1 - state.turn_player_idx
        anchor_sig = self._defense_sig_of(g_block, g_counters, defender, atk_p)
        cell = self._defense_cell(state, defender, is_leader_attack, atk_p)
        sigs = [c[2] for c in cands]
        if anchor_sig not in set(sigs):
            cands.append((g_block, g_counters, anchor_sig))
            sigs.append(anchor_sig)
        n = len(cands)
        prior = [1.0 if sigs[i] == anchor_sig else 0.01 for i in range(n)]
        scores = [self.def_table.value_with_prior(cell, self._def_mk(sigs[i]), prior[i])
                  for i in range(n)]

        if self._def_eps > 0 and self.rng.random() < self._def_eps:
            ci = self.rng.randrange(n)
        else:
            best = max(scores)
            top = [i for i in range(n) if scores[i] >= best - 1e-9]
            ci = top[0] if len(top) == 1 else self.rng.choice(top)
        chosen = cands[ci]
        self._record_def_choice(state, defender_idx, cell, sigs[ci])
        return chosen[0], tuple(chosen[1])
