# -*- coding: utf-8 -*-
"""
hand_estimator Phase 7B 分布化テスト (= 2026-05-14)
====================================================

ハイパージオメトリック分布ベースの新 API を検証:
- counter_total_pmf: 確率分布
- probability_counter_total_at_least: 「合計 ≥ threshold」 の確率
- counter_total_quantile: 分位点
- EstimatedHand に counter_pmf / q50 / q90 を追加
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.hand_estimator import (
    counter_total_pmf,
    counter_total_quantile,
    estimate_hand,
    expected_counter_per_card,
    probability_counter_total_at_least,
)

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _make_state_with_hand(repo, hand_card_ids: list[str], deck_card_ids: list[str]):
    """opp に指定の hand/deck を持たせた state を作る。"""
    me = Player(name="me", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    opp = Player(name="opp", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    opp.hand = [repo.get(cid) for cid in hand_card_ids]
    opp.deck = [repo.get(cid) for cid in deck_card_ids]
    state = GameState(
        players=[me, opp],
        phase=Phase.MAIN,
        rng=random.Random(1),
    )
    return state


# ─────────────────────────────────────────────────────
# counter_total_pmf
# ─────────────────────────────────────────────────────


def test_pmf_sum_to_one():
    """pmf 全確率の総和は 1.0 になる。"""
    repo = _repo()
    # pool = 2000 counter x 3 + 1000 counter x 5 + 0 counter x 10
    state = _make_state_with_hand(
        repo,
        hand_card_ids=["OP03-044"] * 5,  # opp.hand 5 枚
        deck_card_ids=["OP03-044"] * 3 + ["OP01-016"] * 5 + ["OP02-013"] * 10,
    )
    pmf = counter_total_pmf(state, opp_idx=1)
    total_prob = sum(pmf.values())
    assert abs(total_prob - 1.0) < 1e-9, f"pmf 総和は 1.0 のはず ({total_prob})"


def test_pmf_empty_hand_returns_zero():
    """opp.hand が空なら pmf = {0: 1.0}。"""
    repo = _repo()
    state = _make_state_with_hand(
        repo,
        hand_card_ids=[],
        deck_card_ids=["OP03-044"] * 5,
    )
    pmf = counter_total_pmf(state, opp_idx=1)
    assert pmf == {0: 1.0}


def test_pmf_single_counter_value_deterministic():
    """pool 全部 同 counter なら、 合計は手札枚数 × counter 値で確定 (= 確率 1.0)。"""
    repo = _repo()
    # pool 全部 OP01-016 (= 1000 counter)、 手札 5 枚
    state = _make_state_with_hand(
        repo,
        hand_card_ids=["OP01-016"] * 5,
        deck_card_ids=["OP01-016"] * 30,
    )
    pmf = counter_total_pmf(state, opp_idx=1)
    # 5 枚 × 1000 = 5000 だけが確率 1.0
    assert pmf == {5000: 1.0}, f"確定的に 5000 のはず ({pmf})"


# ─────────────────────────────────────────────────────
# probability_counter_total_at_least
# ─────────────────────────────────────────────────────


def test_probability_at_least_zero_is_one():
    """threshold ≤ 0 なら確率 1.0 (= 常に成立)。"""
    repo = _repo()
    state = _make_state_with_hand(
        repo,
        hand_card_ids=["OP01-016"] * 3,
        deck_card_ids=["OP01-016"] * 30,
    )
    assert probability_counter_total_at_least(state, 1, threshold=0) == 1.0
    assert probability_counter_total_at_least(state, 1, threshold=-100) == 1.0


def test_probability_at_least_inverse_monotone():
    """threshold 増加で P(>= threshold) は減少。"""
    repo = _repo()
    # pool 多様な counter 値
    state = _make_state_with_hand(
        repo,
        hand_card_ids=["OP01-016"] * 5,  # hand 5 枚
        deck_card_ids=["OP03-044"] * 5 + ["OP01-016"] * 10 + ["OP02-013"] * 15,
    )
    p_low = probability_counter_total_at_least(state, 1, threshold=1000)
    p_mid = probability_counter_total_at_least(state, 1, threshold=5000)
    p_high = probability_counter_total_at_least(state, 1, threshold=15000)
    assert p_low >= p_mid >= p_high, f"単調減少のはず: {p_low}, {p_mid}, {p_high}"
    # p_low が 1.0 に近い (= 殆ど 1000 以上)、 p_high は 0 に近い
    assert p_low > 0.9
    assert p_high < 0.1


def test_probability_deterministic_case():
    """確定的 pool での合計判定。"""
    repo = _repo()
    # pool 全部 1000 counter、 手札 3 枚 → 合計 = 3000 確定
    state = _make_state_with_hand(
        repo,
        hand_card_ids=["OP01-016"] * 3,
        deck_card_ids=["OP01-016"] * 30,
    )
    # threshold = 3000 → 確率 1.0 (= ちょうど 3000)
    assert probability_counter_total_at_least(state, 1, threshold=3000) == 1.0
    # threshold = 3001 → 確率 0.0 (= 3000 を超えない)
    assert probability_counter_total_at_least(state, 1, threshold=3001) == 0.0


# ─────────────────────────────────────────────────────
# counter_total_quantile
# ─────────────────────────────────────────────────────


def test_quantile_in_pmf_range():
    """quantile は pmf 内の値を返す (= pmf に含まれない値は出さない)。"""
    repo = _repo()
    state = _make_state_with_hand(
        repo,
        hand_card_ids=["OP01-016"] * 3,
        deck_card_ids=["OP03-044"] * 3 + ["OP01-016"] * 10 + ["OP02-013"] * 10,
    )
    pmf = counter_total_pmf(state, 1)
    pmf_keys = set(pmf.keys())
    for q in [0.1, 0.25, 0.5, 0.75, 0.9]:
        result = counter_total_quantile(state, 1, q)
        assert result in pmf_keys, f"q={q} で {result} は pmf に無い"


def test_quantile_monotone():
    """quantile は q について単調非減少。"""
    repo = _repo()
    state = _make_state_with_hand(
        repo,
        hand_card_ids=["OP01-016"] * 5,
        deck_card_ids=["OP03-044"] * 3 + ["OP01-016"] * 10 + ["OP02-013"] * 15,
    )
    qs = [0.1, 0.3, 0.5, 0.7, 0.9]
    vals = [counter_total_quantile(state, 1, q) for q in qs]
    for i in range(len(vals) - 1):
        assert vals[i] <= vals[i + 1], f"q={qs[i]} → {vals[i]} vs q={qs[i+1]} → {vals[i+1]} 単調減少 NG"


# ─────────────────────────────────────────────────────
# EstimatedHand 統合
# ─────────────────────────────────────────────────────


def test_estimate_hand_includes_pmf_and_quantiles():
    """EstimatedHand に pmf / q50 / q90 が入る。"""
    repo = _repo()
    state = _make_state_with_hand(
        repo,
        hand_card_ids=["OP01-016"] * 4,
        deck_card_ids=["OP03-044"] * 5 + ["OP01-016"] * 10 + ["OP02-013"] * 15,
    )
    est = estimate_hand(state, 1)
    assert est.hand_count == 4
    assert len(est.counter_pmf) > 0
    assert abs(sum(est.counter_pmf.values()) - 1.0) < 1e-9
    assert est.counter_q50 <= est.counter_q90, "q50 <= q90 のはず"
    # counter_total (= 期待値) は q50 と q90 の間の orderly な値
    assert 0 <= est.counter_total <= est.counter_q90 * 2  # 緩い check


# ─────────────────────────────────────────────────────
# 旧 API (expected_counter_per_card) 互換性
# ─────────────────────────────────────────────────────


def test_expected_counter_per_card_unchanged():
    """旧 API (expected_counter_per_card) は引き続き機能 (= 期待値ベース、 Phase 7B 互換)。"""
    repo = _repo()
    # 全部 1000 counter pool → 期待値 = 1000
    state = _make_state_with_hand(
        repo,
        hand_card_ids=["OP01-016"] * 3,
        deck_card_ids=["OP01-016"] * 30,
    )
    assert expected_counter_per_card(state, 1) == 1000.0
