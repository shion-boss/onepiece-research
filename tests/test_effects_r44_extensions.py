# -*- coding: utf-8 -*-
"""R44 効果 DSL 拡張テスト (sev≥5 解消用)。

R44 で追加:
1. set_base_power_copy primitive (= EB01-061 Mr.2 「元々のパワーは選んだキャラと同じパワーになる」)
2. turn_base_power_override フィールド (= turn-duration base power override)
3. on_self_event_played trigger (= OP04-053 ページワン 「自分がイベントを発動した時」)
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import CardDef, Category, GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    CardEffectBundle,
    execute_effect,
    trigger_main_event,
)
from engine.game import _reset_turn_buff

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _make_state(repo, leader_id="OP01-003", opp_leader_id="OP01-001"):
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
# 1. set_base_power_copy
# --------------------------------------------------------------------------- #
def test_set_base_power_copy_copies_opp_chara_power():
    """Mr.2 パターン: self の base power が選んだ opp chara の current power になる。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    # self = Mr.2 想定 (元 power 1000)。 適当な低 power カードで代用
    self_card = CardDef(
        card_id="TEST-MR2",
        name="Mr.2",
        category=Category.CHARACTER,
        color=("紫",),
        cost=4,
        power=1000,
        counter=1000,
        features=(),
        text="",
    )
    me.characters.append(InPlay.of(self_card, sickness=False))
    mr2 = me.characters[-1]
    # opp chara: 強キャラ 7000
    opp_card = CardDef(
        card_id="TEST-STRONG",
        name="StrongOne",
        category=Category.CHARACTER,
        color=("赤",),
        cost=7,
        power=7000,
        counter=1000,
        features=(),
        text="",
    )
    opp.characters.append(InPlay.of(opp_card, sickness=False))

    execute_effect(
        {"set_base_power_copy": {
            "from_target": "one_opponent_character_any",
            "to_target": "self",
            "duration": "turn",
        }},
        state, me, opp, mr2,
    )
    assert mr2.turn_base_power_override == 7000
    assert mr2.power == 7000  # base = 7000, no buffs


def test_set_base_power_copy_no_target_returns_false():
    """対象なしの場合は不発 (空 opp characters)。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    self_card = CardDef(
        card_id="TEST-MR2",
        name="Mr.2",
        category=Category.CHARACTER,
        color=("紫",),
        cost=4,
        power=1000,
        counter=1000,
        features=(),
        text="",
    )
    me.characters.append(InPlay.of(self_card, sickness=False))
    mr2 = me.characters[-1]
    # opp characters 空 → 不発
    ret = execute_effect(
        {"set_base_power_copy": {
            "from_target": "one_opponent_character_any",
            "to_target": "self",
            "duration": "turn",
        }},
        state, me, opp, mr2,
    )
    assert ret is False
    assert mr2.turn_base_power_override is None


def test_turn_base_power_override_cleared_on_turn_end():
    """ターン終了時に turn_base_power_override がクリアされる。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    # leader に turn_base_power_override をセット
    me.leader.turn_base_power_override = 9999
    assert me.leader.base_power == 9999
    # turn end でクリア
    _reset_turn_buff(state)
    assert me.leader.turn_base_power_override is None
    assert me.leader.base_power == me.leader.card.power


def test_turn_base_power_override_takes_priority_over_static():
    """turn_base_power_override は base_power_override より優先。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    me.leader.base_power_override = 3000  # 静的
    me.leader.turn_base_power_override = 8000  # ターン
    assert me.leader.base_power == 8000  # turn が勝つ


# --------------------------------------------------------------------------- #
# 2. on_self_event_played trigger
# --------------------------------------------------------------------------- #
def test_on_self_event_played_fires_on_main_event():
    """自分のキャラが on_self_event_played を持っていれば、 自分がイベント発動時に発火。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    # 自キャラ: on_self_event_played で draw 1 する効果を持つ (= ページワン 簡略版)
    chara_card = CardDef(
        card_id="TEST-PAGEONE",
        name="Page One",
        category=Category.CHARACTER,
        color=("赤",),
        cost=2,
        power=3000,
        counter=1000,
        features=(),
        text="",
    )
    me.characters.append(InPlay.of(chara_card, sickness=False))
    # bundle 登録
    overlay = {
        "TEST-PAGEONE": CardEffectBundle(
            card_id="TEST-PAGEONE",
            effects=[
                {
                    "when": "on_self_event_played",
                    "do": [{"draw": 1}],
                },
            ],
        ),
    }
    state.effects_overlay = overlay

    # 自分が任意のイベントを発動 → trigger_main_event を直接呼ぶ
    event_card = CardDef(
        card_id="TEST-EVENT",
        name="DummyEvent",
        category=Category.EVENT,
        color=("赤",),
        cost=1,
        power=0,
        counter=0,
        features=(),
        text="",
    )
    initial_hand = len(me.hand)
    initial_deck = len(me.deck)
    trigger_main_event(state, me, opp, event_card, overlay)
    # ページワンの on_self_event_played が発火 → draw 1
    assert len(me.hand) == initial_hand + 1
    assert len(me.deck) == initial_deck - 1


def test_on_self_event_played_does_not_fire_on_opp_event():
    """相手がイベントを発動しても on_self_event_played は発火しない (= opp_event_or_trigger_fired 用)。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    # me が on_self_event_played 効果を持つキャラを場に出す
    chara_card = CardDef(
        card_id="TEST-PAGEONE2",
        name="Page Two",
        category=Category.CHARACTER,
        color=("赤",),
        cost=2,
        power=3000,
        counter=1000,
        features=(),
        text="",
    )
    me.characters.append(InPlay.of(chara_card, sickness=False))
    overlay = {
        "TEST-PAGEONE2": CardEffectBundle(
            card_id="TEST-PAGEONE2",
            effects=[
                {
                    "when": "on_self_event_played",
                    "do": [{"draw": 1}],
                },
            ],
        ),
    }
    state.effects_overlay = overlay

    event_card = CardDef(
        card_id="TEST-EVENT2",
        name="DummyEvent2",
        category=Category.EVENT,
        color=("赤",),
        cost=1,
        power=0,
        counter=0,
        features=(),
        text="",
    )
    initial_hand = len(me.hand)
    # opp 側がイベント発動 → me から見ると相手なので on_self_event_played 発火しない
    trigger_main_event(state, opp, me, event_card, overlay)
    # me の hand に変化なし
    assert len(me.hand) == initial_hand


# --------------------------------------------------------------------------- #
# 3. R45 追加: set_base_power_timed primitive
# --------------------------------------------------------------------------- #
def test_set_base_power_timed_next_opp_turn_end():
    """ST26-005 パターン: 自リーダーの 元々のパワー=7000 を 次の相手ターン終了時まで設定。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    # leader power: P0 が OP01-003 (リーダー power 5000 想定。 元値は repo から取得)
    original = me.leader.card.power
    # set_base_power_timed で 7000 へ
    execute_effect(
        {"set_base_power_timed": {
            "target": "self_leader",
            "amount": 7000,
            "duration": "next_opp_turn_end",
        }},
        state, me, opp, None,
    )
    assert me.leader.next_opp_turn_end_base_power_override == 7000
    assert me.leader.base_power == 7000  # next_opp_turn_end_base_power_override 反映
    assert me.leader.next_opp_turn_end_base_power_override_applier_idx == 0


def test_set_base_power_timed_turn_duration():
    """duration=turn: turn_base_power_override に格納。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    execute_effect(
        {"set_base_power_timed": {
            "target": "self_leader",
            "amount": 8000,
            "duration": "turn",
        }},
        state, me, opp, None,
    )
    assert me.leader.turn_base_power_override == 8000
    assert me.leader.base_power == 8000


# --------------------------------------------------------------------------- #
# 4. R45 追加: return_self_chara_to_hand cost
# --------------------------------------------------------------------------- #
def test_return_self_chara_to_hand_cost_payable():
    """OP01-047 ロー パターン: optional_cost_then で 自キャラ1枚を持ち主の手札に戻す cost。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    # 自キャラを 2 枚場へ
    chara_card = repo.get("OP01-013")
    me.characters.append(InPlay.of(chara_card, sickness=False))
    me.characters.append(InPlay.of(chara_card, sickness=False))
    initial_chars = len(me.characters)
    initial_hand = len(me.hand)
    # optional_cost_then で 1 体手札へ → draw 1
    execute_effect(
        {
            "optional_cost_then": {
                "cost": [{"return_self_chara_to_hand": {"count": 1}}],
                "effect": [{"draw": 1}],
            },
        },
        state, me, opp, None,
    )
    # 1 体減って手札に + cost で 1 枚増える + draw で 1 枚増える
    assert len(me.characters) == initial_chars - 1
    assert len(me.hand) == initial_hand + 2  # cost で 1 + draw で 1
