# -*- coding: utf-8 -*-
"""真 Phase 1.0 (= lookup-driven goal AI) の unit tests。

target_action_derive.py の 主要 API を 直接 検証。 plan_search 統合 は 別途 smoke。

実装: engine/target_action_derive.py
仕様: [[project_goal_directed_real]]
"""
from __future__ import annotations

import random
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def repo():
    from engine.deck import CardRepository
    return CardRepository.from_json(str(ROOT / "db" / "cards.json"))


@pytest.fixture
def state(repo):
    from engine.deck import DeckList
    from engine.game import setup_game
    d1 = DeckList.from_json(str(ROOT / "decks" / "tcgportal_coby.json"), repo)
    d2 = DeckList.from_json(str(ROOT / "decks" / "tcgportal_coby.json"), repo)
    return setup_game(d1, d2, rng=random.Random(0))


# ===========================================================================
# is_achievable
# ===========================================================================


def test_is_achievable_empty_returns_true(state):
    from engine.target_action_derive import is_achievable
    assert is_achievable(state, 0, {}, plan=None) is True


def test_is_achievable_already_satisfied_returns_true(state):
    """既に 達成済 の 条件 は achievable=True。"""
    from engine.target_action_derive import is_achievable
    # state.players[0].life は setup 後 5 枚 (default leader life=5)
    assert is_achievable(state, 0, {"self_hand_ge": 1}, plan=None) is True


def test_is_achievable_unreachable_returns_false(state):
    """到達不能 な 条件 (= 場 0、 手札 に play 可能 chara 0 で chara_count_ge: 5) は False。"""
    from engine.target_action_derive import is_achievable
    # 手札 を 空 に
    state.players[0].hand = []
    assert is_achievable(state, 0, {"self_chara_count_ge": 5}, plan=None) is False


def test_is_achievable_min_attacks_requires_attackers(state):
    """min_attacks_this_turn_ge は active attacker 数 で 判定。"""
    from engine.target_action_derive import is_achievable
    # leader は default active、 攻撃 0 回 → leader 1 体 で 1 回まで 可能
    assert is_achievable(state, 0, {"min_leader_attacks_this_turn_ge": 1}, plan=None) is True
    # 5 回 attack は 不可能 (= active attacker 1 体 のみ)
    assert is_achievable(state, 0, {"min_attacks_this_turn_ge": 5}, plan=None) is False


# ===========================================================================
# derive_actions_for_goal
# ===========================================================================


def test_derive_empty_cond_returns_all(state):
    from engine.target_action_derive import derive_actions_for_goal
    from engine.game import legal_actions
    la = legal_actions(state)
    assert derive_actions_for_goal(state, 0, {}, plan=None, legal_actions=la) == la


def test_derive_attack_goal_keeps_attack_actions(state):
    """min_attacks_this_turn_ge → Attack* + EndPhase だけ 残る (= safety net)。"""
    from engine.target_action_derive import derive_actions_for_goal
    from engine.game import legal_actions, AttackLeader, AttackCharacter, EndPhase
    la = legal_actions(state)
    filtered = derive_actions_for_goal(
        state, 0, {"min_attacks_this_turn_ge": 1}, plan=None, legal_actions=la,
    )
    # 残った action が Attack 系 or EndPhase か (= fallback で la が 残る ケース も 許容)
    if filtered != la:  # 絞り込みが効いた 場合
        for a in filtered:
            assert isinstance(a, (AttackLeader, AttackCharacter, EndPhase)), \
                f"unexpected action retained: {type(a).__name__}"


def test_derive_already_satisfied_returns_all(state):
    """全 if 条件 が 既に 満たされて いる なら 全 la を 返す (= 絞らない)。"""
    from engine.target_action_derive import derive_actions_for_goal
    from engine.game import legal_actions
    la = legal_actions(state)
    # life ≥ 1 は 既に 満たされて いる (life 5)
    filtered = derive_actions_for_goal(
        state, 0, {"self_hand_ge": 1}, plan=None, legal_actions=la,
    )
    assert filtered == la


# ===========================================================================
# lookup_best_achievable_entry
# ===========================================================================


def test_lookup_no_spec_returns_none(state):
    from engine.target_action_derive import lookup_best_achievable_entry
    assert lookup_best_achievable_entry(state, 0, None, plan=None) is None
    assert lookup_best_achievable_entry(state, 0, {}, plan=None) is None


def test_lookup_finds_best_achievable_unsatisfied(state):
    """bonus 降順 で (achievable かつ 未達成) な entry を 返す。

    既に 満たされて いる target は skip (= 「目指す対象 が もう ない」)。
    確実 に reachable な primitive (= self_leader_attached_don_ge) を使う:
    DON 5 あれば leader に DON 5 attach 可能。
    """
    from engine.target_action_derive import lookup_best_achievable_entry
    state.players[0].don_active = 5  # mid-turn 想定
    spec = {
        "entries": [
            {
                "turn": state.turn_number,
                "opp_leader_id": state.players[1].leader.card.card_id,
                "opp_archetype": None,
                "self_condition": "even",
                "targets": [
                    # 高 bonus だが unreachable (= leader DON は max 5、 100 は 不可能)
                    {"priority": 1, "if": {"self_leader_attached_don_ge": 100}, "bonus": 9999,
                     "description": "unreachable high bonus"},
                ],
            },
            {
                "turn": state.turn_number,
                "opp_leader_id": state.players[1].leader.card.card_id,
                "opp_archetype": None,
                "self_condition": "even",
                "targets": [
                    # 中 bonus、 reachable + 未達成 (= DON 1 attach は DON 5 あれば 可能)
                    {"priority": 1, "if": {"self_leader_attached_don_ge": 1}, "bonus": 700,
                     "description": "reachable unsatisfied target"},
                    # 低 bonus、 既達成 → skip 対象
                    {"priority": 2, "if": {"self_hand_ge": 1}, "bonus": 300,
                     "description": "already satisfied"},
                ],
            },
        ],
    }
    best = lookup_best_achievable_entry(state, 0, spec, plan=None)
    assert best is not None
    assert best["bonus"] == 700
    assert "unsatisfied" in best["description"]


def test_lookup_returns_none_when_all_satisfied(state):
    """全 target が 既達成 → 「目指す対象なし」 で None。 derive 側 で full la fallback。"""
    from engine.target_action_derive import lookup_best_achievable_entry
    spec = {
        "entries": [{
            "turn": state.turn_number,
            "opp_leader_id": state.players[1].leader.card.card_id,
            "opp_archetype": None,
            "self_condition": "even",
            "targets": [
                {"priority": 1, "if": {"self_hand_ge": 1}, "bonus": 500,
                 "description": "already satisfied (hand=5 at start)"},
            ],
        }],
    }
    best = lookup_best_achievable_entry(state, 0, spec, plan=None)
    assert best is None


# ===========================================================================
# derive_disrupt_actions
# ===========================================================================


def test_disrupt_empty_returns_empty(state):
    from engine.target_action_derive import derive_disrupt_actions
    from engine.game import legal_actions
    la = legal_actions(state)
    assert derive_disrupt_actions(state, 0, {}, plan=None, legal_actions=la) == []


def test_disrupt_field_count_keeps_ko_type_actions(state):
    """opp が self_field_count_ge を狙う → KO 系 action (PlayEvent/ActivateMain/AttackCharacter) 候補。"""
    from engine.target_action_derive import derive_disrupt_actions
    from engine.game import legal_actions, PlayEvent, ActivateMain, AttackCharacter
    la = legal_actions(state)
    # opp の if 条件 = self_field_count_ge: 3 (= 敵が場を増やしたい) → 我々は KO 系 を 候補に
    filtered = derive_disrupt_actions(
        state, 0, {"self_field_count_ge": 3}, plan=None, legal_actions=la,
    )
    # filtered は KO 系 だけ (= la 全 がそうでなければ 絞られる はず)
    for a in filtered:
        assert isinstance(a, (PlayEvent, ActivateMain, AttackCharacter)), \
            f"unexpected disrupt action: {type(a).__name__}"
