# -*- coding: utf-8 -*-
"""効果 DSL 拡張ユニットテスト (X2: 条件評価器 拡張)。

追加条件:
- don_count_ge / don_count_le (alias of self_don_ge / self_don_le)
- opp_don_count_ge / opp_don_count_le (相手のドン合算)
- opp_leader_feature (leader_feature の opp 版)
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import eval_condition

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _make_state(repo, leader_id, opp_leader_id="OP01-001"):
    leader = repo.get(leader_id)
    p1 = Player(name="P0", leader=InPlay.of(leader, sickness=False))
    p2 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p1.deck = [repo.get("OP01-013")] * 30
    p2.deck = [repo.get("OP01-013")] * 30
    return GameState(
        players=[p1, p2],
        phase=Phase.MAIN,
        rng=random.Random(1),
        effects_overlay={},
    )


# --------------------------------------------------------------------------- #
# don_count_ge / don_count_le (自分)
# --------------------------------------------------------------------------- #
def test_don_count_ge_alias():
    """don_count_ge: 自分のドン!! 合算 (active+rested+attached) ≥ N"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    me.don_active = 3
    me.don_rested = 2
    # 合計 5
    assert eval_condition({"don_count_ge": 5}, state, me) is True
    assert eval_condition({"don_count_ge": 6}, state, me) is False
    # 既存 self_don_ge と一致
    assert eval_condition({"self_don_ge": 5}, state, me) is True


def test_don_count_le_alias():
    """don_count_le: 自分のドン!! 合算 ≤ N"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    me.don_active = 4
    me.don_rested = 0
    assert eval_condition({"don_count_le": 4}, state, me) is True
    assert eval_condition({"don_count_le": 3}, state, me) is False


def test_don_count_includes_attached():
    """don_count_ge は leader / character 付与ドンも合算する"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    me.don_active = 1
    me.don_rested = 1
    me.leader.attached_dons = 2
    me.characters.append(InPlay.of(repo.get("OP01-013"), sickness=False))
    me.characters[0].attached_dons = 3
    # 合計 7
    assert eval_condition({"don_count_ge": 7}, state, me) is True
    assert eval_condition({"don_count_ge": 8}, state, me) is False


# --------------------------------------------------------------------------- #
# opp_don_count_ge / opp_don_count_le (相手)
# --------------------------------------------------------------------------- #
def test_opp_don_count_ge():
    """opp_don_count_ge: 相手のドン合算 ≥ N"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    opp = state.players[1]
    opp.don_active = 2
    opp.don_rested = 3
    assert eval_condition({"opp_don_count_ge": 5}, state, me) is True
    assert eval_condition({"opp_don_count_ge": 6}, state, me) is False


def test_opp_don_count_le():
    """opp_don_count_le: 相手のドン合算 ≤ N"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    opp = state.players[1]
    opp.don_active = 1
    opp.don_rested = 1
    assert eval_condition({"opp_don_count_le": 2}, state, me) is True
    assert eval_condition({"opp_don_count_le": 1}, state, me) is False


# --------------------------------------------------------------------------- #
# opp_leader_feature
# --------------------------------------------------------------------------- #
def test_opp_leader_feature_str():
    """opp_leader_feature: 相手リーダーが指定特徴を持つか (str)"""
    repo = _repo()
    state = _make_state(repo, "OP01-003", opp_leader_id="OP01-001")
    me = state.players[0]
    opp = state.players[1]
    feats = opp.leader.card.features
    assert len(feats) > 0
    chosen = feats[0]
    assert eval_condition({"opp_leader_feature": chosen}, state, me) is True
    assert eval_condition({"opp_leader_feature": "存在しない特徴_XYZ"}, state, me) is False


def test_opp_leader_feature_list():
    """opp_leader_feature: list (OR) でいずれかの特徴を持つか"""
    repo = _repo()
    state = _make_state(repo, "OP01-003", opp_leader_id="OP01-001")
    me = state.players[0]
    opp = state.players[1]
    chosen = opp.leader.card.features[0]
    assert eval_condition(
        {"opp_leader_feature": [chosen, "存在しない_XYZ"]}, state, me
    ) is True
    assert eval_condition(
        {"opp_leader_feature": ["存在しない_A", "存在しない_B"]}, state, me
    ) is False
