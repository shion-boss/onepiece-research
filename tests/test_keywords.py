# -*- coding: utf-8 -*-
"""キーワード効果の検出・適用テスト。"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.game import AttackLeader, apply_action
from engine.effects import load_effect_overlay

ROOT = Path(__file__).resolve().parent.parent


def _repo():
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _state(repo, leader_id, atk_card_id, life_count=4):
    """攻撃側 P0 (leader_id) と防御側 P1 (リーダー = OP01-001 ライフ life_count 枚)。
    P0 のフィールドに atk_card_id を 1 体置く (アクティブ・召喚酔い無し)。
    """
    leader_a = repo.get(leader_id)
    leader_b = repo.get("OP01-001")
    p0 = Player(name="P0", leader=InPlay.of(leader_a, sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(leader_b, sickness=False))
    p0.deck = [repo.get("OP01-013")] * 30
    p1.deck = [repo.get("OP01-013")] * 30
    # ライフを差別化された card_id で詰める (発動時の追跡しやすさ)
    p1.life = [repo.get("OP01-013")] * life_count
    atk = repo.get(atk_card_id)
    p0.characters.append(InPlay.of(atk, sickness=False))
    state = GameState(
        players=[p0, p1],
        phase=Phase.MAIN,
        rng=random.Random(1),
        effects_overlay={},
    )
    state.turn_number = 5  # 1ターン目バトル禁止を回避
    return state


def test_keyword_detection():
    repo = _repo()
    # OP01-121 ヤマト = innate ダブルアタック + バニッシュ
    cd = repo.get("OP01-121")
    assert cd.is_double_attack, "OP01-121 は innate ダブルアタックを持つはず"
    assert cd.is_banish, "OP01-121 は innate バニッシュを持つはず"
    # 普通のサンジは持たない
    sanji = repo.get("OP01-013")
    assert not sanji.is_double_attack
    assert not sanji.is_banish
    assert not sanji.has_no_block
    # 条件付き 「【ダブルアタック】を得る」 は innate ではない
    conditional = repo.get("OP09-084_p1")
    assert not conditional.is_double_attack, "条件付き DA は innate=False"
    assert not conditional.is_banish, "条件付き バニッシュ は innate=False"


def test_double_attack_deals_2_damage():
    """ダブルアタック持ちが攻撃すると 2 ダメージ = ライフ 2 枚減る。"""
    repo = _repo()
    # OP01-121 ヤマト = innate DA + banish (P5000)
    state = _state(repo, leader_id="OP01-001", atk_card_id="OP01-121", life_count=4)
    atk = state.players[0].characters[0]
    atk.attached_dons = 5  # P5000+5000=10000、リーダー (P5000) を確実に倒せる
    life_before = len(state.players[1].life)
    apply_action(
        state,
        AttackLeader(attacker_iid=atk.instance_id, counter_card_idxs=()),
    )
    life_after = len(state.players[1].life)
    assert life_before - life_after == 2, f"ダブルアタックは 2 ライフ削るはず: {life_before}→{life_after}"


def test_banish_sends_life_to_trash():
    """バニッシュ持ちが攻撃通過時、ライフはトラッシュ (手札に来ない)。"""
    repo = _repo()
    # OP01-121 ヤマト = innate DA + banish
    state = _state(repo, leader_id="OP01-001", atk_card_id="OP01-121", life_count=4)
    atk = state.players[0].characters[0]
    atk.attached_dons = 5

    hand_before = len(state.players[1].hand)
    trash_before = len(state.players[1].trash)
    apply_action(
        state,
        AttackLeader(attacker_iid=atk.instance_id, counter_card_idxs=()),
    )
    hand_after = len(state.players[1].hand)
    trash_after = len(state.players[1].trash)
    # ライフは手札に行かずトラッシュへ
    assert hand_after - hand_before == 0, "バニッシュはライフを手札に渡さない"
    assert trash_after - trash_before == 2, "バニッシュ + ダブルアタックでライフ 2 枚がトラッシュへ"
