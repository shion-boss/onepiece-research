# -*- coding: utf-8 -*-
"""opp_hand_threat 指標 (R70 / Phase 3) のテスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.eval import (
    BoardEvalWeights,
    compute_breakdown,
    compute_score,
    opp_hand_threat_estimate,
)
from engine.game import setup_game


ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def repo():
    return CardRepository.from_json(ROOT / "db" / "cards.json")


@pytest.fixture(scope="module")
def overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


@pytest.fixture
def state(repo, overlay):
    deck_a = DeckList.from_json(ROOT / "decks" / "cardrush_1424.json", repo)  # 紫エネル
    deck_b = DeckList.from_json(ROOT / "decks" / "cardrush_1437.json", repo)  # 緑ミホーク
    import random
    return setup_game(deck_a, deck_b, rng=random.Random(42), first_player=0, effects_overlay=overlay)


def test_opp_hand_threat_returns_non_negative(state):
    """opp_hand_threat は常に >= 0 を返す。"""
    v0 = opp_hand_threat_estimate(state, 0)
    v1 = opp_hand_threat_estimate(state, 1)
    assert v0 >= 0
    assert v1 >= 0


def test_opp_hand_threat_zero_when_opp_hand_empty(state):
    """opp の手札が空なら 0。"""
    state.players[1].hand = []
    assert opp_hand_threat_estimate(state, 0) == 0.0


def test_opp_hand_threat_scales_with_hand_size(state):
    """opp の手札枚数に比例 (= 同じ avg_value で hand 倍)。"""
    import copy
    base = opp_hand_threat_estimate(state, 0)
    # 手札を倍にする (= deck からダミーで補充)
    s2 = copy.deepcopy(state)
    extra = list(s2.players[1].hand)
    s2.players[1].hand.extend(extra)
    doubled = opp_hand_threat_estimate(s2, 0)
    # 同じ pool 平均 × 2 倍の hand → doubled ≈ 2 * base (誤差 < 0.1)
    if base > 0:
        assert doubled >= base * 1.9 - 0.5
        assert doubled <= base * 2.1 + 0.5


def test_opp_hand_threat_in_breakdown(state):
    """compute_breakdown に opp_hand_threat 行が含まれる。"""
    bd = compute_breakdown(state, 0)
    assert "opp_hand_threat" in bd
    assert "self" in bd["opp_hand_threat"]
    assert "opp" in bd["opp_hand_threat"]
    assert "diff" in bd["opp_hand_threat"]
    assert "contribution" in bd["opp_hand_threat"]


def test_opp_hand_threat_contribution_uses_weight(state):
    """重み変更が contribution に正しく反映される。"""
    w1 = BoardEvalWeights(W_OPP_HAND_THREAT=0)
    w2 = BoardEvalWeights(W_OPP_HAND_THREAT=1000)
    bd1 = compute_breakdown(state, 0, w1)
    bd2 = compute_breakdown(state, 0, w2)
    # W=0 では contribution=0
    assert bd1["opp_hand_threat"]["contribution"] == 0
    # W=1000 で diff * 1000 になる
    diff = bd2["opp_hand_threat"]["diff"]
    assert bd2["opp_hand_threat"]["contribution"] == diff * 1000


def test_opp_hand_threat_symmetric_perspective(state):
    """me_idx=0 視点と me_idx=1 視点で self/opp が入れ替わる。"""
    bd0 = compute_breakdown(state, 0)
    bd1 = compute_breakdown(state, 1)
    # me=0 視点: self=plr0_hand_threat, opp=plr1_hand_threat
    # me=1 視点: self=plr1_hand_threat, opp=plr0_hand_threat
    assert bd0["opp_hand_threat"]["self"] == bd1["opp_hand_threat"]["opp"]
    assert bd0["opp_hand_threat"]["opp"] == bd1["opp_hand_threat"]["self"]


def test_compute_score_includes_opp_hand_threat(state):
    """compute_score が opp_hand_threat を含めて計算する。"""
    # 重み 0 と 1000 でスコアが変わるはず (= 指標が active)
    w0 = BoardEvalWeights(W_OPP_HAND_THREAT=0)
    w1000 = BoardEvalWeights(W_OPP_HAND_THREAT=1000)
    s0 = compute_score(state, 0, w0)
    s1000 = compute_score(state, 0, w1000)
    # 何らかの差があるべき (opp の手札が 0 でない限り)
    bd = compute_breakdown(state, 0, w0)
    if abs(bd["opp_hand_threat"]["diff"]) > 0:
        assert s0 != s1000
