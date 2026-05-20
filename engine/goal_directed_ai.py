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
        **kwargs,
    ):
        """
        Args:
            goal_target_w: target.bonus に かける スケール係数 (= default 1.0)。
            target_spec: 明示指定の target spec dict。 None なら deck_slug or auto-load。
            deck_slug: target spec を load する deck slug。 None なら state から auto-detect。
            spec_version: "v1" (= default refined) or "v2" (= cross-trained、 2026-05-20)
        """
        kwargs.setdefault("beam_width", 4)
        kwargs.setdefault("max_depth", 6)
        kwargs.setdefault("adaptive", False)
        super().__init__(*args, **kwargs)
        self._goal_target_w = goal_target_w
        self._explicit_target_spec = target_spec
        self._deck_slug = deck_slug
        self._spec_version = spec_version

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
        # auto-detect from state.players[me_idx].deck_slug
        me_idx = state.turn_player_idx
        try:
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

    def choose_action(self, state: GameState):
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
        # target spec を state に attach (= search_turn_plan の auto-load で 拾う)。
        # 既存 attached spec が あれば 上書きしない (= 多重呼出し対応)
        target_spec = self._resolve_target_spec(state)
        attached = False
        if target_spec is not None and not getattr(state, "_goal_target_spec", None):
            state._goal_target_spec = target_spec  # type: ignore[attr-defined]
            attached = True
        try:
            return super().choose_action(state)
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
            if attached:
                try:
                    delattr(state, "_goal_target_spec")
                except Exception:
                    pass
