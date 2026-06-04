# -*- coding: utf-8 -*-
"""OP10-072 ドンキホーテ・ロシナンテ の任意コスト (手札からイベント1枚捨てて2ドロー)。

公式: 【登場時】自分の手札からイベント1枚を捨てることができる：カード2枚を引く。

bug (2026-06-04 修正前、 ohtsuki 実プレイ報告): cost の discard_hand_with_filter が
_can_pay_counter_cost / _pay_counter_cost で未処理 → イベントを捨てずに 2 ドローできた
(= コスト踏み倒し)。
"""
from __future__ import annotations

from engine.core import InPlay
from engine.effects import trigger_on_play, resolve_pending_choice

import tests.test_effects as T


def _setup():
    repo, overlay = T._repo(), T._overlay()
    state = T._make_state(repo, "OP01-001", overlay=overlay)
    me, opp = state.players[0], state.players[1]
    state.turn_player_idx = 0
    ev = next(c for cid, c in repo._by_id.items() if c.category.name == "EVENT")
    ch = next(c for cid, c in repo._by_id.items()
              if c.category.name == "CHARACTER" and c.card_id != "OP10-072")
    me.deck = [repo.get(ch.card_id) for _ in range(10)]
    return state, me, opp, repo, ev, ch


def test_no_event_no_draw():
    """手札にイベントが無ければ コスト払えず → ドローしない (= 効果不発)。"""
    state, me, opp, repo, ev, ch = _setup()
    me.hand = [repo.get(ch.card_id)]  # イベント無し
    state.human_player_idx = None  # AI 経路 (auto)
    deck0 = len(me.deck)
    ros = InPlay.of(repo.get("OP10-072"), sickness=True)
    me.characters.append(ros)
    trigger_on_play(state, me, opp, ros, T._overlay())
    assert len(me.deck) == deck0, "イベント無しなのにドローした (= コスト踏み倒し)"


def test_event_discarded_then_draw_auto():
    """AI 経路: イベントを捨てて 2 ドロー (= コスト強制 + 効果)。"""
    state, me, opp, repo, ev, ch = _setup()
    me.hand = [repo.get(ev.card_id), repo.get(ch.card_id)]
    state.human_player_idx = None
    deck0, trash0 = len(me.deck), len(me.trash)
    ros = InPlay.of(repo.get("OP10-072"), sickness=True)
    me.characters.append(ros)
    trigger_on_play(state, me, opp, ros, T._overlay())
    assert deck0 - len(me.deck) == 2, "2 ドローしていない"
    assert len(me.trash) - trash0 == 1, "イベントを捨てていない"
    assert me.trash[-1].category.name == "EVENT", "捨てたのがイベントでない"


def test_human_picks_event_then_draw():
    """人間 経路: modal で 捨てるイベントを選び → 1 捨て + 2 ドロー (二重コストなし)。"""
    state, me, opp, repo, ev, ch = _setup()
    me.hand = [repo.get(ev.card_id), repo.get(ch.card_id)]
    state.human_player_idx = 0
    deck0, trash0, hand0 = len(me.deck), len(me.trash), len(me.hand)
    ros = InPlay.of(repo.get("OP10-072"), sickness=True)
    me.characters.append(ros)
    trigger_on_play(state, me, opp, ros, T._overlay())
    pc = state.pending_choice
    assert pc and pc.get("kind") == "counter_discard_pick", f"modal 未発火: {pc}"
    # 候補は イベントのみ (= filter 適用)
    assert all(c["card_id"] == ev.card_id for c in pc["candidates"])
    resolve_pending_choice(state, [0])
    assert deck0 - len(me.deck) == 2, "2 ドローしていない"
    assert len(me.trash) - trash0 == 1, "捨て枚数が 1 でない (二重コスト?)"
    assert len(me.hand) == hand0 - 1 + 2, "手札枚数が想定外"
