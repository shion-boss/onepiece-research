# -*- coding: utf-8 -*-
"""「登場できない」 ペナルティは **ライフからの登場にも効く**。

`reveal_top_play` (デッキ上 1 枚を公開して登場) は元から `_char_summon_blocked` を見て
いたのに、 `reveal_life_top_play` (ライフ上 1 枚を公開して登場) だけが抜けていた
(2026-08-24、 Rust engine との突合で発覚)。

一次情報 (cardqa_op_13 / OP13-023 ウタ、 同型 OP14-020 ミホーク): 「キャラカードを
登場できない」 は **通常プレイも効果による登場も一律禁止**。 ライフから場に出す手続きも
「登場」 なので同じく禁止される。
"""
from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import execute_effect, load_effect_overlay

ROOT = Path(__file__).resolve().parent.parent
FILLER = "OP01-013"
SABO = "OP04-083"  # コスト5 「サボ」 (= ST13-007 の reveal_life_top_play が拾う対象)


def _setup():
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-002"), sickness=False))
    for p in (p0, p1):
        p.deck = [repo.get(FILLER)] * 10
        p.life = [repo.get(SABO)] + [repo.get(FILLER)] * 2
        p.life_face_up = [False] * 3
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(7),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    return repo, st, p0, p1


SPEC = {"reveal_life_top_play": {"filter": {"cost_eq": 5, "name": "サボ"}}}


def test_reveal_life_top_play_summons_when_not_blocked():
    """ベースライン: ペナルティが無ければライフ上の 「サボ」 は登場する。"""
    _repo, st, p0, p1 = _setup()
    execute_effect(SPEC, st, p0, p1, None)
    assert [c.card.card_id for c in p0.characters] == [SABO]
    assert len(p0.life) == 2, "登場したライフ 1 枚が場へ移る"
    assert len(p0.life_face_up) == len(p0.life), "表向きフラグはライフと同じ長さを保つ"


def test_reveal_life_top_play_blocked_by_chara_play_ban():
    """「このターン中、 キャラカードを登場できない」 (OP14-020 型) はライフ登場も止める。"""
    _repo, st, p0, p1 = _setup()
    p0.block_chara_play_until_turn_end = True

    execute_effect(SPEC, st, p0, p1, None)

    assert p0.characters == [], "登場できないので場に出ない"
    assert len(p0.life) == 3, "公開しただけ = ライフ枚数は不変 (公式)"
    assert len(p0.life_face_up) == 3


def test_reveal_life_top_play_blocked_by_cost_threshold():
    """「元々のコスト N 以上のキャラカードを登場できない」 (OP13-023 型) も同じ。"""
    _repo, st, p0, p1 = _setup()
    p0.block_chara_play_cost_ge_threshold = 5  # コスト5 の サボ が対象

    execute_effect(SPEC, st, p0, p1, None)

    assert p0.characters == []
    assert len(p0.life) == 3
