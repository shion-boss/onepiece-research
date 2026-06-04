# -*- coding: utf-8 -*-
"""【ドン‼×N】【KO時】 の don-gate が KO 後に評価できるかの回帰。

bug (2026-06-05、 効果意味ジャッジの条件充足 hunt が発見): self_attached_don_ge は
「自分の全キャラのドン合計」 を見ていたが、 KO 時は source が場から除去済 → そのドンが
合計に入らず常に False → 【ドン‼×N】【KO時】 (OP01-038/OP14-051/ST21-004) が永久不発。

修正: KO された キャラの付与ドン枚数を trigger_on_ko 経由で退避し、 self_inplay=None
(= source 不在) の self_attached_don_ge で足し戻す。
"""
from __future__ import annotations

from engine.core import InPlay
from engine.effects import execute_effect, trigger_on_attack

import tests.test_effects as T


def _ko_setup(repo, overlay, victim_id, victim_don):
    state = T._make_state(repo, "OP01-001", overlay=overlay)
    state.turn_player_idx = 1  # opp のターン (opp が KO する)
    me, opp = state.players[0], state.players[1]
    v = InPlay.of(repo.get(victim_id), sickness=False)
    v.attached_dons = victim_don
    me.characters = [v]
    me.hand = [repo.get("OP01-016") for _ in range(3)]
    return state, me, opp


def test_op14_051_draws_when_ko_with_2_don():
    """OP14-051 はっちゃん: ドン2付きでKOされたら 1 ドロー (= 修正対象)。"""
    repo, overlay = T._repo(), T._overlay()
    state, me, opp = _ko_setup(repo, overlay, "OP14-051", 2)
    dk0 = len(me.deck)
    execute_effect({"ko": "one_opponent_character_any"}, state, opp, me, None)
    assert len(me.deck) == dk0 - 1, "ドン2付きKOで1ドローしていない (= don-gate 評価バグ)"


def test_st21_004_draws_when_ko_with_2_don():
    """ST21-004 ジュエリー・ボニー: 同上。"""
    repo, overlay = T._repo(), T._overlay()
    state, me, opp = _ko_setup(repo, overlay, "ST21-004", 2)
    dk0 = len(me.deck)
    execute_effect({"ko": "one_opponent_character_any"}, state, opp, me, None)
    assert len(me.deck) == dk0 - 1, "ドン2付きKOで1ドローしていない"


def test_op14_051_no_draw_when_ko_without_don():
    """OP14-051: ドン0でKOされたら 条件 (don≥2) 未達でドローしない (= ゲート維持)。"""
    repo, overlay = T._repo(), T._overlay()
    state, me, opp = _ko_setup(repo, overlay, "OP14-051", 0)
    dk0 = len(me.deck)
    execute_effect({"ko": "one_opponent_character_any"}, state, opp, me, None)
    assert len(me.deck) == dk0, "ドン0なのにドローした (= 条件ゲートが壊れた)"


def test_non_ko_don_gate_unchanged():
    """回帰: 非KOの 【ドン‼×N】【アタック時】 (self_inplay 有り) は従来通り発火。"""
    repo, overlay = T._repo(), T._overlay()
    state = T._make_state(repo, "OP01-001", overlay=overlay)
    state.turn_player_idx = 0
    me, opp = state.players[0], state.players[1]
    atk = InPlay.of(repo.get("OP01-017"), sickness=False)  # 【ドン‼×1】【アタック時】KO
    atk.attached_dons = 1
    me.characters = [atk]
    opp.characters = [InPlay.of(repo.get("OP04-077"), sickness=False)]
    oc0 = len(opp.characters)
    trigger_on_attack(state, me, opp, atk, overlay)
    assert len(opp.characters) < oc0, "非KOの【ドン‼×1】が発火しない (= 回帰)"
