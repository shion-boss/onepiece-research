# -*- coding: utf-8 -*-
"""終盤厳密 search (= 関数 18、 Phase 8 / Step 1 / 2026-05-16、 ユーザ要件)。

残デッキ少時 (= opp.deck + opp.life の残カード <= 15 枚) に N ターン以内の lethal
成立 path を **全探索** し、 lethal_planner の確率推定を厳密値で置換する。

# 設計

- 適用条件: 残デッキ少時のみ (= 計算量保護)
- max_states 制限で爆発防止
- ライフトリガー乱数も全 case 列挙 (= 厳密確率)
- lethal_planner と連動: 成立すれば `lethal_planner.AttackPlan` を厳密値で出す

# 公開 API
- `EndgameResult` dataclass
- `solve_endgame(state, me_idx, max_depth, max_states) -> Optional[EndgameResult]`
- `is_endgame_applicable(state, me_idx) -> bool`
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .core import GameState


# 適用条件: opp の残カード (= deck + life) がこの値以下なら solve_endgame を適用
ENDGAME_REMAINING_CARDS_THRESHOLD: int = 15

# 計算量保護
DEFAULT_MAX_STATES: int = 10000
DEFAULT_MAX_DEPTH: int = 3


@dataclass
class EndgameResult:
    """endgame solver の結果。"""

    is_winning: bool                          # 確実に勝てる (= p_win_exact == 1.0)
    p_win_exact: float                        # 厳密勝率 ∈ [0, 1]
    winning_path: Optional[list] = None        # 勝ち path (= 攻撃順 + DON 配分等)、 None 可
    depth_searched: int = 0                   # 実際に探索した深さ
    states_evaluated: int = 0                 # 評価した state 数
    aborted_by_limit: bool = False            # max_states に到達して打ち切ったか


def is_endgame_applicable(state: "GameState", me_idx: int) -> bool:
    """残デッキ少時 (= 全探索可能規模) なら True を返す。

    判定基準: opp.deck + opp.life の残カードが ENDGAME_REMAINING_CARDS_THRESHOLD 以下。
    """
    opp = state.players[1 - me_idx]
    remaining = len(opp.deck) + len(opp.life)
    return remaining <= ENDGAME_REMAINING_CARDS_THRESHOLD


def _estimate_p_win_simple(state: "GameState", me_idx: int) -> tuple[float, Optional[list]]:
    """簡易版 p_win 推定 (= Step 1 の最小実装)。

    現状: lethal_planner を呼んで、 成立する path がある時の勝率を返す。
    ライフトリガー乱数の全展開は未実装 (= Step 1 では骨組みのみ)。
    Step 9 反復で精度向上候補。
    """
    try:
        from . import lethal_planner
        plan = lethal_planner.plan_optimal_attack_sequence(state, me_idx)
    except Exception:
        return 0.0, None

    if plan is None:
        return 0.0, None

    # plan が存在 + 攻撃合計が opp counter 上限以上 → 高確率で勝つ
    try:
        from . import hand_estimator
        # 相手の counter 上限 (= P90 分位点 = 強気の見積)
        opp_idx = 1 - me_idx
        counter_p90 = hand_estimator.counter_total_quantile(state, opp_idx, 0.9)
    except Exception:
        counter_p90 = 0

    # plan 内の攻撃合計
    total_power = sum(getattr(a, "buffed_power", getattr(a, "power", 0)) for a in plan.attacks)
    if total_power > counter_p90:
        # ライフトリガー雷迎リスク次第。 簡易: 0.95 とする (= 厳密値ではない)
        return 0.95, plan.attacks
    elif total_power > counter_p90 * 0.7:
        return 0.6, plan.attacks
    else:
        return 0.2, None


def solve_endgame(
    state: "GameState",
    me_idx: int,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_states: int = DEFAULT_MAX_STATES,
) -> Optional[EndgameResult]:
    """終盤厳密 search (= 関数 18)。 適用条件外なら None。

    Step 1 (= 2026-05-16): 簡易版実装。
    - 適用条件 check
    - lethal_planner と連動で簡易勝率算出
    - 全 case 展開は Step 9 反復で精度向上 (= TODO)

    Args:
        state: GameState
        me_idx: 自プレイヤー idx
        max_depth: 探索最大深さ (= ターン数、 default 3)
        max_states: 評価上限 (= 計算量保護、 default 10000)

    Returns:
        EndgameResult (= p_win_exact 含む) or None (= 適用条件外)
    """
    if not is_endgame_applicable(state, me_idx):
        return None

    p_win, path = _estimate_p_win_simple(state, me_idx)

    return EndgameResult(
        is_winning=(p_win >= 0.99),
        p_win_exact=p_win,
        winning_path=path,
        depth_searched=1,  # Step 1 では 1 ターンしか読んでない
        states_evaluated=1,
        aborted_by_limit=False,
    )
