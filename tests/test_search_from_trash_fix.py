# -*- coding: utf-8 -*-
"""トラッシュ回収効果の回帰テスト。

overlay で `search` プリミティブに `source: "trash"` を渡していた 5 枚
(OP05-089 / OP14-093 / OP11-085 / OP10-067 / OP10-067_p1) は、 engine の
`search` プリミティブが常に `me.deck` のみを探索し `source` 指定を無視するため、
トラッシュからの回収が発火しない実バグを抱えていた。 公式テキスト通りの
「自分のトラッシュから (filter) のカードを手札に加える」 は専用の
`search_from_trash` プリミティブが担うので、 全 5 枚をそちらへ修正した
(OP05-089 は test_backfill_auto_061.py 側で担保)。 本ファイルは残り 4 枚が
トラッシュから正しく手札へ回収されることを assert する。
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import execute_effect, load_effect_overlay

ROOT = Path(__file__).resolve().parent.parent

_LEADER = "OP01-001"
_FILLER = "ST01-004"  # 汎用フィラー (デッキ埋め)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, overlay):
    p0 = Player(name="P0", leader=InPlay.of(repo.get(_LEADER), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(_LEADER), sickness=False))
    p0.deck = [repo.get(_FILLER)] * 20
    p1.deck = [repo.get(_FILLER)] * 20
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3
    return st


def _do(overlay, cid, when):
    for e in overlay.get(cid).effects:
        if e.get("when") == when:
            return e["do"]
    raise AssertionError(f"{cid} に when={when} の効果がない")


def _fire(cid, when, target_id):
    """cid の when 効果を、 トラッシュに target_id だけ置いた状態で発火し、
    target_id が手札に回収され トラッシュから消えることを assert する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(target_id)]
    self_ip = InPlay.of(repo.get(cid), sickness=False)
    hand_before = len(me.hand)

    for prim in _do(overlay, cid, when):
        execute_effect(prim, st, me, opp, self_ip)

    assert any(c.card_id == target_id for c in me.hand), \
        f"{cid}: トラッシュの {target_id} が手札に回収されていない"
    assert not any(c.card_id == target_id for c in me.trash), \
        f"{cid}: 回収された {target_id} がトラッシュに残っている"
    assert len(me.hand) == hand_before + 1, \
        f"{cid}: 手札が1枚 (回収) 増えていない"


def test_op14_093_on_ko_recur_bw_char_from_trash():
    """OP14-093 KO時: トラッシュのコスト8以下『B・W』特徴キャラを手札へ。"""
    _fire("OP14-093", "on_ko", "EB03-046")  # ミス・ダブルフィンガー (B・W, cost4)


def test_op11_085_on_play_recur_smile_from_trash():
    """OP11-085 登場時: トラッシュのコスト5以下《SMILE》カードを手札へ。"""
    _fire("OP11-085", "on_play", "EB04-035")  # 人斬り鎌ぞう (SMILE, cost3)


def test_op10_067_on_play_recur_purple_event_from_trash():
    """OP10-067 登場時: トラッシュのコスト5以下 紫イベントを手札へ。"""
    _fire("OP10-067", "on_play", "EB04-040")  # 火龍大炬 (紫 EVENT, cost1)


def test_op10_067_p1_on_play_recur_purple_event_from_trash():
    """OP10-067_p1 (パラレル) 登場時: 同上。"""
    _fire("OP10-067_p1", "on_play", "EB04-040")
