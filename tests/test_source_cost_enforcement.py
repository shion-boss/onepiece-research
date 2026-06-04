# -*- coding: utf-8 -*-
"""source 系/特殊コストの強制 (= cost を払わず効果だけ無償発動するバグ class の回帰)。

2026-06-04: ohtsuki 実プレイで OP10-072 (discard_hand_with_filter) のコスト踏み倒しが
発覚 → 予防監査で _can_pay/_pay_counter_cost が未処理だった cost キーを一掃:
  rest_self / trash_self / self_ko / return_self_don_to_deck / trash_to_deck /
  life_to_hand / life_top_or_bottom_to_hand / reveal_hand_with_filter。
これらは on_play 等の「コスト：効果」で コストを払わず効果だけ発動していた (公式 4-10 違反)。
"""
from __future__ import annotations

from engine.core import InPlay
from engine.effects import trigger_on_play

import tests.test_effects as T


def _fresh():
    repo, overlay = T._repo(), T._overlay()
    s = T._make_state(repo, "OP01-001", overlay=overlay)
    s.turn_player_idx = 0
    s.human_player_idx = None
    return s, s.players[0], s.players[1], repo, overlay


def _low_cost_chara(repo):
    return next(c for cid, c in repo._by_id.items()
               if c.category.name == "CHARACTER")


def test_rest_self_paid(repo=None):
    """OP10-112: rest_self を払って (= 自レスト) 効果発動。"""
    s, me, opp, repo, overlay = _fresh()
    opp.life = [_low_cost_chara(repo) for _ in range(5)]
    src = InPlay.of(repo.get("OP10-112"), sickness=True, rested=False)
    me.characters.append(src)
    l0 = len(opp.life)
    trigger_on_play(s, me, opp, src, overlay)
    assert src.rested, "rest_self コストが払われていない (= 自レストせず効果のみ)"
    assert len(opp.life) == l0 - 1, "効果 (相手ライフトラッシュ) が出ていない"


def test_return_don_cost_feasibility():
    """OP06-074: return_self_don_to_deck=1。 ドン0 なら払えず効果不発。"""
    s, me, opp, repo, overlay = _fresh()
    me.don_active = 0
    me.don_rested = 0
    victim = InPlay.of(repo.get("OP04-077"), sickness=False)
    opp.characters = [victim]
    src = InPlay.of(repo.get("OP06-074"), sickness=True)
    me.characters.append(src)
    trigger_on_play(s, me, opp, src, overlay)
    assert victim in opp.characters, "ドン0でコスト払えないのに効果 (KO/無効) が発動した"


def test_return_don_cost_paid():
    """OP06-074: ドンがあれば 1 枚戻して効果発動。"""
    s, me, opp, repo, overlay = _fresh()
    me.don_active = 5
    opp.characters = [InPlay.of(repo.get("OP04-077"), sickness=False)]
    src = InPlay.of(repo.get("OP06-074"), sickness=True)
    me.characters.append(src)
    trigger_on_play(s, me, opp, src, overlay)
    assert me.don_active == 4, "return_self_don_to_deck コストが払われていない"


def test_life_cost_feasibility():
    """OP11-106: life_top_or_bottom_to_hand=1。 ライフ0 なら払えず効果不発。"""
    s, me, opp, repo, overlay = _fresh()
    me.life = []
    me.hand = []
    victim = InPlay.of(repo.get("OP04-077"), sickness=False)
    opp.characters = [victim]
    src = InPlay.of(repo.get("OP11-106"), sickness=True)
    me.characters.append(src)
    trigger_on_play(s, me, opp, src, overlay)
    assert victim in opp.characters, "ライフ0でコスト払えないのに効果 (KO) が発動した"


def test_life_cost_paid():
    """OP11-106: ライフがあれば 1 枚手札に加えて効果発動。"""
    s, me, opp, repo, overlay = _fresh()
    me.life = [_low_cost_chara(repo) for _ in range(4)]
    me.hand = []
    opp.characters = [InPlay.of(repo.get("OP04-077"), sickness=False)]
    src = InPlay.of(repo.get("OP11-106"), sickness=True)
    me.characters.append(src)
    lf0 = len(me.life)
    trigger_on_play(s, me, opp, src, overlay)
    assert len(me.life) == lf0 - 1, "life コストが払われていない"
    assert len(me.hand) == 1, "ライフが手札に加わっていない"


def test_trash_self_paid():
    """OP15-100: trash_self を払って (= 自身トラッシュ) 効果発動。"""
    s, me, opp, repo, overlay = _fresh()
    opp.characters = [InPlay.of(repo.get("OP04-077"), sickness=False)]
    src = InPlay.of(repo.get("OP15-100"), sickness=True)
    me.characters.append(src)
    trigger_on_play(s, me, opp, src, overlay)
    assert src not in me.characters, "trash_self コストが払われていない (= 自身が場に残存)"
    assert "OP15-100" in [c.card_id for c in me.trash], "自身がトラッシュに置かれていない"


def test_reveal_hand_cost_feasibility():
    """OP08-040: reveal_hand_with_filter (白ひげ2枚)。 該当0 なら払えず効果不発。"""
    s, me, opp, repo, overlay = _fresh()
    me.hand = []  # 白ひげ海賊団 なし
    victim = InPlay.of(repo.get("OP04-077"), sickness=False, rested=False)
    opp.characters = [victim]
    src = InPlay.of(repo.get("OP08-040"), sickness=True)
    me.characters.append(src)
    trigger_on_play(s, me, opp, src, overlay)
    assert not victim.rested, "公開コスト払えないのに効果 (相手レスト) が発動した"
