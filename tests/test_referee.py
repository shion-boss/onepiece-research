# -*- coding: utf-8 -*-
"""RuleReferee のテスト: 不変条件違反を意図的に起こして検出されることを確認。"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from engine.core import Category, GameState, InPlay, Phase, Player
from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.game import (
    AttachDonToLeader,
    AttackLeader,
    PlayCharacter,
    apply_action,
    setup_game,
)
from engine.referee import RuleReferee, RuleViolation

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _make_state(repo, leader_id, overlay=None) -> GameState:
    leader = repo.get(leader_id)
    p1 = Player(name="P0", leader=InPlay.of(leader, sickness=False))
    p2 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1.deck = [repo.get("OP01-013")] * 30
    p2.deck = [repo.get("OP01-013")] * 30
    return GameState(
        players=[p1, p2],
        phase=Phase.MAIN,
        rng=random.Random(1),
        effects_overlay=overlay or {},
    )


def test_referee_detects_field_overflow():
    """フィールド超過 (>5 キャラ) を検出"""
    repo = _repo()
    state = _make_state(repo, "OP01-001")
    me = state.players[0]
    # 6 キャラを直接置く (engine 経由ではここまで起きない、referee の単体テスト)
    for i in range(6):
        me.characters.append(InPlay.of(repo.get("OP01-013"), sickness=False))

    ref = RuleReferee(strict=False)
    ref.after_action(state)
    assert any("キャラエリア超過" in v for v in ref.violations), \
        f"フィールド 6 枚で違反検出されるはず ({ref.violations})"


def test_referee_detects_don_total_mismatch():
    """DON 総数 != 10 を検出"""
    repo = _repo()
    state = _make_state(repo, "OP01-001")
    me = state.players[0]
    me.don_active = 11  # 異常: total = 11 + 0 + 0 + 10 = 21
    me.don_remaining_in_deck = 10

    ref = RuleReferee(strict=False)
    ref.after_action(state)
    assert any("DON 総数" in v for v in ref.violations), \
        f"DON 総数違反検出されるはず ({ref.violations})"


def test_referee_detects_negative_don():
    """負の DON を検出"""
    repo = _repo()
    state = _make_state(repo, "OP01-001")
    me = state.players[0]
    me.don_active = -1
    me.don_remaining_in_deck = 11  # 合計 10 にする

    ref = RuleReferee(strict=False)
    ref.after_action(state)
    assert any("don_active" in v and "負" in v for v in ref.violations), \
        f"負 DON 違反検出されるはず ({ref.violations})"


def test_referee_strict_raises_on_violation():
    """strict=True で違反検出時 RuleViolation を投げる"""
    repo = _repo()
    state = _make_state(repo, "OP01-001")
    state.players[0].don_active = 100  # 異常

    ref = RuleReferee(strict=True)
    with pytest.raises(RuleViolation):
        ref.after_action(state)


def test_referee_pre_action_legal_check():
    """非合法アクションを before_action で検出"""
    repo = _repo()
    state = _make_state(repo, "OP01-001")

    # legal_actions に存在しない attacker_iid を持つ AttackLeader を作る
    illegal = AttackLeader(attacker_iid=999999)

    ref = RuleReferee(strict=False)
    ref.before_action(state, illegal)
    assert any("非合法アクション" in v for v in ref.violations), \
        f"非合法 action 違反検出されるはず ({ref.violations})"


def test_referee_passes_normal_match():
    """正常な対戦では違反 0 件 (短い試合)"""
    from engine.harness import run_matchup

    repo = _repo()
    overlay = _overlay()
    d1 = DeckList.from_json(ROOT / "decks" / "cardrush_1424.json", repo)  # 紫エネル
    d2 = DeckList.from_json(ROOT / "decks" / "cardrush_1437.json", repo)  # 緑ミホーク

    from engine.ai import GreedyAI
    report = run_matchup(
        d1, d2, n_games=3, seed=42,
        effects_overlay=overlay,
        enforce_rules=True,
        referee_strict=False,
        verbose=False,
        ai_factory_1=GreedyAI, ai_factory_2=GreedyAI,  # smoke なので fast を明示
    )
    total_v = sum(len(g.rule_violations) for g in report.games)
    assert total_v == 0, \
        f"正常対戦で違反 0 件のはず: {total_v} 件 (例: {report.games[0].rule_violations[:3]})"


def test_referee_detects_duplicate_iid():
    """instance_id 重複を検出"""
    repo = _repo()
    state = _make_state(repo, "OP01-001")
    me = state.players[0]
    opp = state.players[1]
    # 同じ instance_id を持つキャラを両プレイヤーに置く
    iid_dupe = 12345
    a = InPlay.of(repo.get("OP01-013"), sickness=False)
    a.instance_id = iid_dupe
    b = InPlay.of(repo.get("OP01-013"), sickness=False)
    b.instance_id = iid_dupe
    me.characters = [a]
    opp.characters = [b]

    ref = RuleReferee(strict=False)
    ref.after_action(state)
    assert any("重複 instance_id" in v for v in ref.violations), \
        f"重複 iid 違反検出されるはず ({ref.violations})"
