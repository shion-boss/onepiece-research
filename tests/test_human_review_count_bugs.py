# -*- coding: utf-8 -*-
"""人間レビュー行き バグ 修正の回帰テスト (= backfill routine が @pytest.mark.skip で
退避した / 同型スキャンで発掘した『one_ target + count>1』silent バグ)。

背景: set_cannot_attack / set_cannot_rest は count 上限を 解決済み target の slice で
適用するため、 target が one_* (= 1 体しか解決しない) だと count>1 の 2 枚目以降が
黙って無視される。 公式テキスト「N 枚まで」を満たすには any_* target が必要
(engine の count 適用は any_* = 「filter 一致 全員」を前提)。

対象:
  - EB04-028 アイスタイム   set_cannot_attack (別ファイル test_backfill_auto_017 で解除)
  - EB04-047 ヘルメッポ      trash_self cost   (別ファイル test_backfill_auto_018 で解除)
  - OP14-033 ペローナ         set_cannot_rest  ← このファイル
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import execute_effect, load_effect_overlay

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, overlay, leader_id="OP14-041", human_idx=None):
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p0.deck = [repo.get("ST01-004")] * 30
    p1.deck = [repo.get("ST01-004")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3
    st.human_player_idx = human_idx
    return st


def _do(overlay, cid, when):
    for e in overlay.get(cid).effects:
        if e.get("when") == when:
            return e["do"]
    raise AssertionError(f"{cid} に when={when} の効果がない")


def test_op14_033_perona_set_cannot_rest_two_targets_ai():
    """OP14-033 登場時: 相手コスト5以下キャラ『2枚まで』レスト不能 (AI)。

    修正前は target=one_* で 1 体しかレスト不能にならなかった (count:2 が silent 無視)。
    修正後は any_* + count:2 で 2 体が cannot_be_rested_buff になる。
    """
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    c1 = InPlay.of(repo.get("ST01-013"), sickness=False)  # cost3
    c2 = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost低
    c3 = InPlay.of(repo.get("ST01-013"), sickness=False)  # cost3
    opp.characters = [c1, c2, c3]

    for prim in _do(overlay, "OP14-033", "on_play"):
        execute_effect(prim, st, me, opp, None)

    blocked = [c for c in opp.characters if getattr(c, "cannot_be_rested_buff", False)]
    assert len(blocked) == 2, \
        f"『2枚まで』レスト不能が 2 体に適用されていない (実際 {len(blocked)} 体) = count silent 無視バグ"


def test_op14_033_perona_set_cannot_rest_human_pick():
    """人間 actor: 候補 3 体 > count 2 なら pending_choice が立ち、選んだ 2 体に適用 (人間が選べる)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    c1 = InPlay.of(repo.get("ST01-013"), sickness=False)
    c2 = InPlay.of(repo.get("OP01-016"), sickness=False)
    c3 = InPlay.of(repo.get("ST01-013"), sickness=False)
    opp.characters = [c1, c2, c3]

    halted = False
    for prim in _do(overlay, "OP14-033", "on_play"):
        res = execute_effect(prim, st, me, opp, None)
        if res is False and st.pending_choice is not None:
            halted = True
            break

    # 候補 3 > count 2 → 人間には選択 modal が立つ (= 人間が対象を選べる)
    assert halted and st.pending_choice is not None, \
        "候補が count を超えるのに 人間 target 選択 modal が立たない"
