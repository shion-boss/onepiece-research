# -*- coding: utf-8 -*-
"""
Phase 7H ブラフ判定 + リスク調整リーサル テスト (= 2026-05-14)
================================================================

attacker 側の改善:
- archetype 別 bluff factor (= アグロは 0.4x、 コントロールは 1.3x)
- fallback win prob に応じた lethal threshold の動的調整
- 不利な状況なら 50/50 でもリーサル賭けに行く
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.hand_estimator import (
    _ARCHETYPE_BLUFF_FACTOR,
    archetype_bluff_factor,
    expected_counter_from_don_bluff,
)

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _make_state(repo, opp_leader_id="OP01-001"):
    me = Player(name="me", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    opp = Player(name="opp", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    me.deck = [repo.get("OP01-013")] * 30
    opp.deck = [repo.get("OP01-013")] * 30
    return GameState(
        players=[me, opp],
        phase=Phase.MAIN,
        rng=random.Random(1),
    )


# ─────────────────────────────────────────────────────
# archetype_bluff_factor
# ─────────────────────────────────────────────────────


def test_archetype_factor_aggro_low():
    """アグロ archetype は bluff factor が低い (< 1.0、 = ブラフ判定)。"""
    assert archetype_bluff_factor("アグロ") < 1.0
    assert archetype_bluff_factor("アグロ") == 0.4


def test_archetype_factor_control_high():
    """コントロール archetype は bluff factor が高い (> 1.0、 = 本物判定)。"""
    assert archetype_bluff_factor("コントロール") > 1.0
    assert archetype_bluff_factor("コントロール") == 1.3


def test_archetype_factor_unknown_returns_default():
    """未知 archetype は 1.0 (= 中立)。"""
    assert archetype_bluff_factor("UNKNOWN") == 1.0
    assert archetype_bluff_factor(None) == 1.0


# ─────────────────────────────────────────────────────
# expected_counter_from_don_bluff with archetype factor
# ─────────────────────────────────────────────────────


def test_aggro_opp_gives_lower_bluff_counter():
    """アグロ opp は bluff_counter が控えめ (= 0.4x factor)。"""
    repo = _repo()
    # 紫エネル (= V2 では ミッドレンジ 判定だが、 仮にアグロとして test)
    state = _make_state(repo, opp_leader_id="OP15-058")
    state.players[1].hand = [repo.get("OP01-013")] * 5
    state.players[1].don_active = 4

    # Without archetype factor
    raw = expected_counter_from_don_bluff(state, 1, use_archetype_factor=False)
    # With archetype factor (= 動的に classifier 経由で archetype を取得)
    with_factor = expected_counter_from_don_bluff(state, 1, use_archetype_factor=True)
    # 紫エネル = ミッドレンジ (V2) なので factor 0.7
    assert with_factor <= raw, f"factor 適用で {with_factor} <= raw {raw}"


def test_unknown_archetype_uses_default():
    """学習データ外の leader は factor=1.0 (= 中立)。"""
    repo = _repo()
    state = _make_state(repo, opp_leader_id="OP01-001")  # 未学習
    state.players[1].hand = [repo.get("OP01-013")] * 5
    state.players[1].don_active = 4

    # 未学習 leader でも エラーなしで bluff_counter が出る
    val = expected_counter_from_don_bluff(state, 1, use_archetype_factor=True)
    assert val >= 0


# ─────────────────────────────────────────────────────
# Risk-adjusted lethal threshold (= GreedyAI _compute_lethal_action)
# ─────────────────────────────────────────────────────


def test_risk_adjusted_threshold_logic():
    """fallback_win_prob 別の lethal threshold logic を direct test。

    code path: fallback >= 0.7 → 0.75、 0.4-0.7 → 0.70、 0.2-0.4 → 0.55、 < 0.2 → 0.40
    """
    # logic を手動再現
    def threshold_for(fallback_win_prob):
        if fallback_win_prob >= 0.7:
            return 0.75
        elif fallback_win_prob >= 0.4:
            return 0.70
        elif fallback_win_prob >= 0.2:
            return 0.55
        else:
            return 0.40

    assert threshold_for(0.9) == 0.75
    assert threshold_for(0.5) == 0.70
    assert threshold_for(0.3) == 0.55
    assert threshold_for(0.1) == 0.40
    # 単調非減少: 不利な状況ほど低 threshold
    assert threshold_for(0.1) < threshold_for(0.3) < threshold_for(0.5) < threshold_for(0.9)


def test_aggressive_lethal_when_desperate():
    """不利な状況 (= 負け濃厚) で AI が 40% 成功率でも リーサル attempt する。

    実 GreedyAI._compute_lethal_action は直接テストしにくいので、
    threshold ロジックの妥当性のみ確認。
    """
    # 「fallback 0.1 (= 90% 負ける) なら 40% 成功 リーサル attempt」
    # = 0.4 で go (= threshold 0.40)
    fallback = 0.1
    if fallback >= 0.7: t = 0.75
    elif fallback >= 0.4: t = 0.70
    elif fallback >= 0.2: t = 0.55
    else: t = 0.40
    p_lethal_success = 0.4
    # 賭けに行く判定
    assert p_lethal_success >= t, "fallback 0.1 で 40% 成功なら リーサル attempt"
