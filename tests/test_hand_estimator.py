# -*- coding: utf-8 -*-
"""
hand_estimator の単体テスト
==========================

公開 API のテスト:
- expected_counter_per_card / expected_counter_total
- probability_of_blocker_in_hand
- estimate_hand
- 情報感度: トラッシュへの移動でプール組成が変わると推定値も変わる
- 既存 API (estimate_counter_total / sample_opponent_hand) との後方互換
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import CardDef, Category, GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.hand_estimator import (
    EstimatedHand,
    estimate_counter_total,
    estimate_hand,
    expected_counter_per_card,
    expected_counter_total,
    probability_of_blocker_in_hand,
    sample_opponent_hand,
)

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _state_with_opp(repo, opp_hand, opp_deck, opp_trash=()):
    """opp 視点のハンド/デッキ/トラッシュを指定して state を組み立てる。"""
    p1 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p2 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p2.hand = list(opp_hand)
    p2.deck = list(opp_deck)
    p2.trash = list(opp_trash)
    return GameState(
        players=[p1, p2],
        phase=Phase.MAIN,
        rng=random.Random(0),
        effects_overlay={},
    )


def _make_card(card_id: str, counter: int, text: str = "") -> CardDef:
    return CardDef(
        card_id=card_id,
        name=card_id,
        category=Category.CHARACTER,
        counter=counter,
        text=text,
    )


# -----------------------------------------------------------------------------
# expected_counter_per_card
# -----------------------------------------------------------------------------

def test_expected_counter_per_card_basic_mean():
    """deck+hand プール上の単純平均が返る。"""
    c0 = _make_card("X0", 0)
    c1 = _make_card("X1", 1000)
    c2 = _make_card("X2", 2000)
    repo = _repo()
    state = _state_with_opp(
        repo, opp_hand=[c0, c1], opp_deck=[c1, c2, c2]
    )
    # pool counters = [0, 1000, 1000, 2000, 2000] → mean = 1200
    assert expected_counter_per_card(state, 1) == 1200.0


def test_expected_counter_per_card_empty_pool():
    """プールが空なら 0.0。"""
    repo = _repo()
    state = _state_with_opp(repo, opp_hand=[], opp_deck=[])
    assert expected_counter_per_card(state, 1) == 0.0


def test_expected_counter_per_card_excludes_trash():
    """トラッシュにあるカードはプールに含まれない (= 推定値が変わる)。

    AI 側にとって重要: 高カウンター持ちが既に切られたなら、 opp の手札 counter 推定は下がる。
    """
    high = _make_card("HIGH", 2000)
    low = _make_card("LOW", 0)
    repo = _repo()
    # ケース A: 全部がプール内 → mean (4*2000 + 4*0) / 8 = 1000
    state_a = _state_with_opp(
        repo, opp_hand=[high, low], opp_deck=[high] * 3 + [low] * 3
    )
    mean_a = expected_counter_per_card(state_a, 1)
    # ケース B: 高カウンター 2 枚がトラッシュへ → mean (2*2000 + 4*0) / 6 = 666.67
    state_b = _state_with_opp(
        repo, opp_hand=[high, low], opp_deck=[high] + [low] * 3, opp_trash=[high, high]
    )
    mean_b = expected_counter_per_card(state_b, 1)
    assert mean_a == 1000.0
    assert mean_b < mean_a, "トラッシュ済み高カウンターを除いたら平均は下がる"


# -----------------------------------------------------------------------------
# expected_counter_total
# -----------------------------------------------------------------------------

def test_expected_counter_total_scales_with_hand_count():
    """hand_count に線形比例する。"""
    c = _make_card("X", 1000)
    repo = _repo()
    state1 = _state_with_opp(repo, opp_hand=[c], opp_deck=[c] * 9)
    state2 = _state_with_opp(repo, opp_hand=[c, c, c], opp_deck=[c] * 7)
    # mean = 1000、 hand=1 → 1000、 hand=3 → 3000
    assert expected_counter_total(state1, 1) == 1000
    assert expected_counter_total(state2, 1) == 3000


def test_expected_counter_total_empty_hand():
    """空手札なら 0。"""
    c = _make_card("X", 1000)
    repo = _repo()
    state = _state_with_opp(repo, opp_hand=[], opp_deck=[c] * 10)
    assert expected_counter_total(state, 1) == 0


# -----------------------------------------------------------------------------
# probability_of_blocker_in_hand
# -----------------------------------------------------------------------------

def test_blocker_probability_no_blockers():
    """プール内にブロッカーゼロなら 0.0。"""
    c = _make_card("X", 1000)  # text 空 = ブロッカーなし
    repo = _repo()
    state = _state_with_opp(repo, opp_hand=[c, c], opp_deck=[c] * 8)
    assert probability_of_blocker_in_hand(state, 1) == 0.0


def test_blocker_probability_all_blockers():
    """プール全部ブロッカーなら 1.0。"""
    b = _make_card("B", 1000, text="【ブロッカー】")
    assert b.is_blocker
    repo = _repo()
    state = _state_with_opp(repo, opp_hand=[b, b], opp_deck=[b] * 8)
    assert probability_of_blocker_in_hand(state, 1) == 1.0


def test_blocker_probability_hypergeometric():
    """ハイパージオメトリック分布で確率を返す。

    プール 10 枚中ブロッカー 3 枚、 手札 2 枚:
    P(0 blockers in hand) = C(7,2)/C(10,2) = 21/45 = 0.4666...
    P(>=1 blocker) = 1 - 0.4666... = 0.5333...
    """
    b = _make_card("B", 1000, text="【ブロッカー】")
    n = _make_card("N", 1000)
    repo = _repo()
    state = _state_with_opp(repo, opp_hand=[n, n], opp_deck=[b] * 3 + [n] * 5)
    # pool: 3 blocker, 7 non-blocker (hand has the n's)
    p = probability_of_blocker_in_hand(state, 1)
    expected = 1.0 - (7 / 10) * (6 / 9)
    assert abs(p - expected) < 1e-9, f"p={p}, expected={expected}"


def test_blocker_probability_empty():
    """空ハンド or 空プールなら 0.0。"""
    b = _make_card("B", 1000, text="【ブロッカー】")
    repo = _repo()
    state = _state_with_opp(repo, opp_hand=[], opp_deck=[b] * 10)
    assert probability_of_blocker_in_hand(state, 1) == 0.0


# -----------------------------------------------------------------------------
# estimate_hand
# -----------------------------------------------------------------------------

def test_estimate_hand_combines_all():
    """EstimatedHand dataclass で 4 つのメトリクスを返す。"""
    b = _make_card("B", 2000, text="【ブロッカー】")
    n = _make_card("N", 1000)
    repo = _repo()
    state = _state_with_opp(repo, opp_hand=[b, n], opp_deck=[b, n, n])
    est = estimate_hand(state, 1)
    assert isinstance(est, EstimatedHand)
    assert est.hand_count == 2
    # mean counter = (2*2000 + 3*1000) / 5 = 1400
    assert est.counter_per_card == 1400.0
    assert est.counter_total == 2800
    # blocker_prob > 0 (2 of 5 are blockers)
    assert 0.0 < est.blocker_prob < 1.0


# -----------------------------------------------------------------------------
# Information sensitivity (= 公開情報を反映すると推定が変化)
# -----------------------------------------------------------------------------

def test_information_sensitivity_to_trash():
    """ブロッカーがトラッシュへ移動すると blocker_prob が下がる (= 情報感度)。"""
    b = _make_card("B", 1000, text="【ブロッカー】")
    n = _make_card("N", 0)
    repo = _repo()
    # ケース A: ブロッカー 3 枚プール内
    state_a = _state_with_opp(
        repo, opp_hand=[n, n], opp_deck=[b] * 3 + [n] * 5
    )
    # ケース B: ブロッカー 2 枚がトラッシュへ
    state_b = _state_with_opp(
        repo, opp_hand=[n, n], opp_deck=[b] + [n] * 5, opp_trash=[b, b]
    )
    p_a = probability_of_blocker_in_hand(state_a, 1)
    p_b = probability_of_blocker_in_hand(state_b, 1)
    assert p_b < p_a, "トラッシュ済ブロッカーを除外したら手札推定は下がる"


# -----------------------------------------------------------------------------
# 後方互換 (既存 API)
# -----------------------------------------------------------------------------

def test_estimate_counter_total_is_alias():
    """estimate_counter_total は expected_counter_total と同値 (後方互換)。"""
    c = _make_card("X", 1000)
    repo = _repo()
    state = _state_with_opp(repo, opp_hand=[c, c], opp_deck=[c] * 8)
    assert estimate_counter_total(state, 1) == expected_counter_total(state, 1)


def test_sample_opponent_hand_still_works():
    """既存 sample_opponent_hand が動作 (Phase 2 で MCTS が使う)。"""
    c0 = _make_card("X0", 0)
    c1 = _make_card("X1", 1000)
    repo = _repo()
    state = _state_with_opp(repo, opp_hand=[c0, c1], opp_deck=[c0] * 5 + [c1] * 3)
    rng = random.Random(42)
    sampled = sample_opponent_hand(state, 1, rng)
    assert len(sampled) == 2
    pool_ids = {"X0", "X1"}
    for c in sampled:
        assert c.card_id in pool_ids
