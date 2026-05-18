# -*- coding: utf-8 -*-
"""ゲーム phase 判定 (= 関数 6、 Phase 8 / Step 1 / 2026-05-16)。

ターン番号 + 評価関数の状態 + my/opp archetype から 5 段階の Phase を分類:
- EARLY: 序盤、 リソース準備
- MID: 中盤、 盤面有利化
- LATE: 終盤、 決め手
- LETHAL_WINDOW: 自リーサル成立可能 (= 攻め重視)
- DEFENSIVE: opp リーサル切迫 (= 守り重視)

各 archetype × phase の戦略は呼出側で参照する想定 (= 例: classifty_game_phase →
MatchupProfile の phase 別 threshold 切替)。

# 公開 API
- `Phase` enum
- `classify_game_phase(state, me_idx, my_archetype, opp_archetype) -> Phase`
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .core import GameState


class Phase(str, Enum):
    EARLY = "early"
    MID = "mid"
    LATE = "late"
    LETHAL_WINDOW = "lethal_window"  # 自 lethal ≥ 0.7
    DEFENSIVE = "defensive"          # opp_lethal ≥ 0.7


# archetype 別 EARLY/MID/LATE の turn 境界
# (= アグロは早期決着、 コントロールは長期戦、 等)
_PHASE_THRESHOLDS: dict[str, tuple[int, int]] = {
    "アグロ":         (2, 4),   # turn ≤2 EARLY、 ≤4 MID、 > 4 LATE
    "ミッドレンジ":    (3, 6),
    "コントロール":    (4, 7),
    "ランプ":         (3, 6),
}
_DEFAULT_THRESHOLDS: tuple[int, int] = (3, 6)


# リーサル threshold (= LETHAL_WINDOW / DEFENSIVE 判定用)
LETHAL_THRESHOLD_HIGH: float = 0.7


def classify_game_phase(
    state: "GameState",
    me_idx: int,
    my_archetype: Optional[str] = None,
    opp_archetype: Optional[str] = None,
) -> Phase:
    """ゲーム phase を分類。

    優先順位:
    1. 自分の lethal 推定 ≥ 0.7 → LETHAL_WINDOW (= 攻め重視 phase)
    2. 相手の lethal 推定 ≥ 0.7 → DEFENSIVE (= 守り重視 phase)
    3. ターン番号 + my_archetype に基づき EARLY / MID / LATE

    Args:
        state: 現在の game state
        me_idx: 自プレイヤー idx
        my_archetype: 自分の archetype (= "アグロ"/"ミッドレンジ"/"コントロール"/"ランプ")。
                      未指定なら default threshold (3, 6)
        opp_archetype: 相手の archetype。 現状未使用、 将来拡張用

    Returns:
        Phase enum
    """
    # 優先 1, 2: リーサル状況
    try:
        from . import eval as eval_module
        my_lethal = eval_module.lethal_estimate(state, me_idx)
        opp_lethal = eval_module.lethal_estimate(state, 1 - me_idx)
    except Exception:
        my_lethal = 0.0
        opp_lethal = 0.0

    if my_lethal >= LETHAL_THRESHOLD_HIGH:
        return Phase.LETHAL_WINDOW
    if opp_lethal >= LETHAL_THRESHOLD_HIGH:
        return Phase.DEFENSIVE

    # 優先 3: archetype 別 turn 境界
    turn = getattr(state, "turn_number", None)
    if turn is None:
        # core.GameState の attr 名は実装に依存、 fallback
        turn = getattr(state, "turn", 1)

    early_max, mid_max = _PHASE_THRESHOLDS.get(my_archetype or "", _DEFAULT_THRESHOLDS)
    if turn <= early_max:
        return Phase.EARLY
    elif turn <= mid_max:
        return Phase.MID
    else:
        return Phase.LATE
