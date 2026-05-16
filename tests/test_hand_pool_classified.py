# -*- coding: utf-8 -*-
"""
hand_estimator classified pool テスト (Phase 7E / 2026-05-14)
=============================================================

`_USE_CLASSIFIER_FOR_POOL = True` で:
- 高信頼度 (= 0.5+): classifier 推定 archetype の recipe - 観測済 を pool に
- 低信頼度: 旧挙動 (opp.deck + opp.hand) に fallback

`set_pool_mode(False)` で旧挙動 (= opp.deck + opp.hand 直読) に戻せる。
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.deck_classifier import reset_default_classifier
from engine.hand_estimator import (
    _archetype_pool,
    _opponent_pool,
    counter_total_pmf,
    expected_counter_per_card,
    reset_pool_cache_for_testing,
    set_pool_mode,
)

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _make_state_with_opp_leader(
    repo,
    opp_leader_id: str,
    opp_hand_ids: list[str] = (),
    opp_deck_ids: list[str] = (),
    opp_trash_ids: list[str] = (),
    opp_field_ids: list[str] = (),
):
    """opp に指定 leader + 手札 / デッキ / トラッシュ / 場 を持たせた state を作る。"""
    me = Player(name="me", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    opp = Player(name="opp", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    opp.hand = [repo.get(cid) for cid in opp_hand_ids]
    opp.deck = [repo.get(cid) for cid in opp_deck_ids]
    opp.trash = [repo.get(cid) for cid in opp_trash_ids]
    opp.characters = [InPlay.of(repo.get(cid), sickness=False) for cid in opp_field_ids]
    return GameState(
        players=[me, opp],
        phase=Phase.MAIN,
        rng=random.Random(1),
    )


# ─────────────────────────────────────────────────────
# pool mode toggle
# ─────────────────────────────────────────────────────


def test_set_pool_mode_legacy_uses_opp_deck_hand():
    """set_pool_mode(False) で 旧挙動 (= opp.deck + opp.hand を直読)。"""
    repo = _repo()
    reset_pool_cache_for_testing()
    reset_default_classifier()
    set_pool_mode(use_classifier=False)
    try:
        state = _make_state_with_opp_leader(
            repo,
            opp_leader_id="OP15-058",
            opp_hand_ids=["OP15-066"] * 3,
            opp_deck_ids=["OP15-066"] * 5,
        )
        pool = _opponent_pool(state, opp_idx=1)
        # 旧挙動: hand 3 + deck 5 = 8 枚
        assert len(pool) == 8
        for c in pool:
            assert c.card_id == "OP15-066"
    finally:
        set_pool_mode(use_classifier=True)


def test_pool_mode_classifier_high_confidence_uses_recipe():
    """高信頼 classifier (= 紫エネル leader) で archetype recipe pool に切替。"""
    repo = _repo()
    reset_pool_cache_for_testing()
    reset_default_classifier()
    set_pool_mode(use_classifier=True, min_confidence=0.5)
    state = _make_state_with_opp_leader(
        repo,
        opp_leader_id="OP15-058",  # 紫エネル
        opp_hand_ids=[],
        opp_deck_ids=[],
    )
    pool = _opponent_pool(state, opp_idx=1)
    # 紫エネル recipe = 50 枚、 公開済なし → pool = 50
    assert len(pool) == 50, f"recipe minus observed (= 0) = 50 のはず ({len(pool)})"


def test_classifier_pool_subtracts_observed():
    """場 / トラッシュにあるカードが pool から引かれる。"""
    repo = _repo()
    reset_pool_cache_for_testing()
    reset_default_classifier()
    set_pool_mode(use_classifier=True, min_confidence=0.5)
    # 紫エネル の典型カード OP15-066 (= サトリ) を 1 枚 trash、 1 枚 場に
    state = _make_state_with_opp_leader(
        repo,
        opp_leader_id="OP15-058",
        opp_trash_ids=["OP15-066"],
        opp_field_ids=["OP15-066"],
    )
    pool = _opponent_pool(state, opp_idx=1)
    # 紫エネル recipe = 50、 -2 (= 場 + trash の OP15-066) = 48
    assert len(pool) == 48, f"50 - 2 = 48 のはず ({len(pool)})"
    # pool に残る OP15-066 = recipe (= archetype or variant) 採用枚数 - 2
    # Phase 8 (= 2026-05-16) で variant pool が default 採用、 variant 別 recipe では
    # OP15-066 採用枚数が異なる (= variant 0 は 4 枚採用)。
    n_satori_pool = sum(1 for c in pool if c.card_id == "OP15-066")
    from engine.hand_estimator import _load_archetype_recipes, _load_variant_recipes
    arc_recipes = _load_archetype_recipes()
    var_recipes = _load_variant_recipes()
    arc_count = sum(1 for c in arc_recipes.get("紫エネル", []) if c.card_id == "OP15-066")
    # variant 候補 (= leader_id=OP15-058 の全 variant) のいずれかと一致するはず
    variant_counts = [
        sum(1 for c in cards if c.card_id == "OP15-066")
        for (lid, _vid), cards in var_recipes.items() if lid == "OP15-058"
    ]
    expected_counts = {max(0, c - 2) for c in [arc_count] + variant_counts}
    assert n_satori_pool in expected_counts, (
        f"got {n_satori_pool}, expected one of {expected_counts} "
        f"(arc={arc_count}, variants={variant_counts})"
    )


def test_classifier_pool_low_confidence_fallback():
    """未知 leader (= prior 分散) で fallback to opp.deck + opp.hand。"""
    repo = _repo()
    reset_pool_cache_for_testing()
    reset_default_classifier()
    set_pool_mode(use_classifier=True, min_confidence=0.5)
    # OP01-001 (= ロロノアゾロ leader、 active pool 外)
    state = _make_state_with_opp_leader(
        repo,
        opp_leader_id="OP01-001",
        opp_hand_ids=["OP01-016"] * 2,
        opp_deck_ids=["OP01-013"] * 5,
    )
    pool = _opponent_pool(state, opp_idx=1)
    # fallback で hand 2 + deck 5 = 7
    assert len(pool) == 7, f"fallback で len = 7 ({len(pool)})"


def test_archetype_pool_returns_none_for_unknown_leader():
    """_archetype_pool 単体で 未知 leader は None を返す。"""
    repo = _repo()
    reset_pool_cache_for_testing()
    reset_default_classifier()
    state = _make_state_with_opp_leader(
        repo,
        opp_leader_id="OP01-001",
    )
    pool = _archetype_pool(state, opp_idx=1)
    # confidence < min_confidence (0.5) → None
    assert pool is None


# ─────────────────────────────────────────────────────
# 確率計算が pool 切替に伴って動作変化
# ─────────────────────────────────────────────────────


def test_expected_counter_works_with_classifier_pool():
    """classifier-based pool でも expected_counter_per_card が動作。"""
    repo = _repo()
    reset_pool_cache_for_testing()
    reset_default_classifier()
    set_pool_mode(use_classifier=True, min_confidence=0.5)
    # 紫エネル の状態
    state = _make_state_with_opp_leader(
        repo,
        opp_leader_id="OP15-058",
        opp_hand_ids=[],
        opp_deck_ids=[],
    )
    state.players[1].hand = [repo.get("OP15-066")] * 5  # hand 5 枚 (= recipe 推定で外す)
    # pool は recipe 由来 (= 50 枚)、 平均 counter は紫エネル の recipe 平均
    avg = expected_counter_per_card(state, opp_idx=1)
    assert avg > 0, "紫エネル の recipe には counter 持ちカードがあるはず"
    assert avg < 2000, "平均は 2000 未満 (= 全部 2000 counter なら 2000)"


def test_pmf_works_with_classifier_pool():
    """classifier-based pool でも counter_total_pmf が動作。"""
    repo = _repo()
    reset_pool_cache_for_testing()
    reset_default_classifier()
    set_pool_mode(use_classifier=True, min_confidence=0.5)
    state = _make_state_with_opp_leader(
        repo,
        opp_leader_id="OP15-058",
    )
    state.players[1].hand = [repo.get("OP15-066")] * 5  # hand 5
    pmf = counter_total_pmf(state, opp_idx=1)
    total_prob = sum(pmf.values())
    assert abs(total_prob - 1.0) < 1e-9, f"pmf 総和 = 1.0 ({total_prob})"


# ─────────────────────────────────────────────────────
# cleanup: pool mode を default に戻す
# ─────────────────────────────────────────────────────


def teardown_function(_):
    """各テスト後に pool mode を default (= classifier on) に戻す。"""
    set_pool_mode(use_classifier=True, min_confidence=0.5)
