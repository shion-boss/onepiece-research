# -*- coding: utf-8 -*-
"""`reveal_life_top_play` の 「登場させて**もよい**」 を本人が選べる。

公式 (OP10-022 ロー / ST13-007 サボ / ST13-010 エース / ST13-014): 「自分のライフの上から1枚を
公開し、 そのカードが <条件> の場合、 登場させて**もよい**」。 = 任意 (総合 1-3-5-1)。

⚠ 2026-08-24 まで **人間にも AI にも選択肢が無く、 マッチしたら必ず登場** していた
  (`effects.py` に 「TODO: 人間 acting 時は modal で…」 と書かれたまま)。 デッキ版
  `reveal_top_play` には modal があるのに **ライフ版だけ抜けていた**。
"""
from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import execute_effect, load_effect_overlay, resolve_pending_choice
from engine.game import _recompute_static

ROOT = Path(__file__).resolve().parent.parent
CHARA = "OP01-013"   # CHARACTER (ライフの一番上に置く)
SPEC = {"reveal_life_top_play": {"filter": {}}}


def _setup(enum=False, human=None):
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-002"), sickness=False))
    for p in (p0, p1):
        p.deck = [repo.get(CHARA)] * 10
        p.life = [repo.get(CHARA)] * 3
        p.life_face_up = [False] * 3
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(4),
                   effects_overlay=ov)
    st.turn_player_idx = 0
    st.choice_enumeration = enum
    if human is not None:
        st.human_player_idx = human
    _recompute_static(st)
    return st, p0, p1


def test_ai_mode_keeps_legacy_always_play():
    """選択を列挙しないモードは従来どおり 「マッチなら登場」 (= self-play / parity 不変)。"""
    st, me, opp = _setup()
    execute_effect(SPEC, st, me, opp, me.leader)
    assert st.pending_choice is None
    assert len(me.characters) == 1, "AI 既定 (= 登場) が変わっている"
    assert len(me.life) == 2, "ライフから 1 枚出ていない"


def test_human_can_decline():
    """⭐ 「登場させない」 を選べる (ライフは減らない)。 従来は強制登場だった。"""
    st, me, opp = _setup(human=0)
    execute_effect(SPEC, st, me, opp, me.leader)
    assert st.pending_choice is not None, "2 択が立たない (= 強制登場のまま)"
    assert st.pending_choice.get("kind") == "reveal_life_top_play_confirm"
    resolve_pending_choice(st, [0])          # 登場させない
    assert st.pending_choice is None
    assert len(me.characters) == 0, "見送ったのに登場している"
    assert len(me.life) == 3, "見送ったのにライフが減っている"
    assert len(me.life_face_up) == 3, "ライフと表向きフラグの長さが食い違う"


def test_human_can_accept():
    """「登場させる」 を選ぶと登場し、 ライフが 1 枚減る。"""
    st, me, opp = _setup(human=0)
    execute_effect(SPEC, st, me, opp, me.leader)
    assert st.pending_choice is not None
    resolve_pending_choice(st, [1])          # 登場させる
    assert st.pending_choice is None
    assert len(me.characters) == 1, "登場を選んだのに出ていない"
    assert len(me.life) == 2
    assert len(me.life_face_up) == 2, "ライフと表向きフラグの長さが食い違う"


def test_choice_enumeration_offers_both():
    """選択列挙 ON では AI にも 2 択が出る (= 探索が分岐できる)。"""
    from engine.game import legal_actions

    st, me, opp = _setup(enum=True)
    execute_effect(SPEC, st, me, opp, me.leader)
    assert st.pending_choice is not None, "列挙 ON でも 2 択が立たない"
    acts = legal_actions(st)
    picks = sorted(tuple(getattr(a, "picks", ())) for a in acts)
    assert picks == [(0,), (1,)], f"2 択 (登場する/しない) になっていない: {picks}"
