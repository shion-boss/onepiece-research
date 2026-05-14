# -*- coding: utf-8 -*-
"""engine/mutations.py のユニットテスト。"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from engine import card_role, mutations
from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


@pytest.fixture(scope="module")
def overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


@pytest.fixture(scope="module")
def deck(repo) -> DeckList:
    return DeckList.from_json(ROOT / "decks" / "cardrush_1454.json", repo)


@pytest.fixture(scope="module")
def role_db():
    return card_role.load_card_role_db()


@pytest.fixture(scope="module")
def eff_db():
    return card_role.load_effectiveness_db()


# ============================================================================ #
# 個別変異戦略
# ============================================================================ #

def test_swap_card_returns_valid_deck(deck, repo, role_db, eff_db):
    rng = random.Random(42)
    new_deck = mutations.mutate_swap_card(
        deck, "アグロ", repo, role_db, eff_db, rng,
    )
    assert new_deck is not None
    assert len(new_deck.main) == 50
    new_deck.validate()


def test_swap_card_respects_must_include(deck, repo, role_db, eff_db):
    rng = random.Random(42)
    must = {"OP15-076"}  # 雷獣
    # 100 試行で must_include がなくならないか
    for _ in range(50):
        new_deck = mutations.mutate_swap_card(
            deck, "アグロ", repo, role_db, eff_db, rng, must_include=must,
        )
        if new_deck is None:
            continue
        assert any(c.card_id == "OP15-076" for c in new_deck.main), \
            "must_include が swap で消失"


def test_count_adjust_returns_valid_deck(deck, repo, role_db, eff_db):
    rng = random.Random(42)
    new_deck = mutations.mutate_count_adjust(
        deck, "アグロ", repo, role_db, eff_db, rng,
    )
    assert new_deck is not None
    assert len(new_deck.main) == 50


def test_role_shift_returns_valid_deck(deck, repo, role_db, eff_db):
    rng = random.Random(42)
    # 何度か試行して成功するか
    success = False
    for seed in range(20):
        rng = random.Random(seed)
        new_deck = mutations.mutate_role_shift(
            deck, "ミッドレンジ", repo, role_db, eff_db, rng,
        )
        if new_deck is not None:
            assert len(new_deck.main) == 50
            success = True
            break
    assert success, "20 seed で role_shift 一度も成功せず"


def test_feature_pivot_returns_valid_deck(deck, repo, role_db, eff_db):
    rng = random.Random(42)
    success = False
    for seed in range(20):
        rng = random.Random(seed)
        new_deck = mutations.mutate_feature_pivot(
            deck, "ミッドレンジ", repo, role_db, eff_db, rng,
        )
        if new_deck is not None:
            assert len(new_deck.main) == 50
            success = True
            break
    # feature 1 つしか無いリーダーだと None も許容
    if not success:
        leader_features = list(deck.leader.features)
        assert len(leader_features) <= 1, "feature 2 つ以上あるのに pivot 失敗"


def test_leader_change_returns_different_leader(deck, repo, role_db, eff_db):
    rng = random.Random(42)
    new_deck = mutations.mutate_leader_change(
        deck, "ミッドレンジ", repo, role_db, eff_db, rng,
    )
    assert new_deck is not None
    assert new_deck.leader.card_id != deck.leader.card_id
    assert len(new_deck.main) == 50


# ============================================================================ #
# random_mutation 統合テスト
# ============================================================================ #

def test_random_mutation_returns_valid(deck, repo, role_db, eff_db):
    rng = random.Random(42)
    result = mutations.random_mutation(
        deck, "アグロ", repo, role_db, eff_db, rng,
    )
    assert result is not None
    new_deck, strategy = result
    assert strategy in ("swap_card", "count_adjust", "role_shift",
                        "feature_pivot", "leader_change")
    assert len(new_deck.main) == 50


def test_random_mutation_diverse_strategies(deck, repo, role_db, eff_db):
    """50 試行で複数戦略が選ばれる。"""
    strategies_used: set[str] = set()
    for seed in range(50):
        rng = random.Random(seed)
        result = mutations.random_mutation(
            deck, "アグロ", repo, role_db, eff_db, rng,
        )
        if result:
            strategies_used.add(result[1])
    # 5 戦略のうち 3 種以上は出現する
    assert len(strategies_used) >= 3, f"only {strategies_used}"


def test_random_mutation_with_allowed_strategies(deck, repo, role_db, eff_db):
    """allowed_strategies 指定で他戦略は使われない。"""
    rng = random.Random(42)
    result = mutations.random_mutation(
        deck, "アグロ", repo, role_db, eff_db, rng,
        allowed_strategies=["swap_card"],
    )
    assert result is not None
    _, strategy = result
    assert strategy == "swap_card"
