# -*- coding: utf-8 -*-
"""OP14-104 ゲッコー・モリア【登場時】の行き先選択 (= ライフに加えるか登場させる) regression。

公式: 「自分のトラッシュからコスト4以下の特徴《スリラーバーク海賊団》を持つキャラカード
1枚までを、**ライフの上に表向きで加えるか登場させる**。」

bug (2026-06-09 cardrush_1439 青黄ナミ campaign g1 で発見、 修正前): overlay が
`play_from_trash` のみ (= 登場固定) で「ライフの上に表向きで加える」選択肢が欠落していた。
human acting でも候補が auto 登場し、 ライフ加算 (= +1 life) を選べなかった。
修正: play_from_trash に `or_to_life` flag + `play_from_trash_or_life_pick` modal
(human のみ。 AI は従来通り登場 = matrix/AI 不変)。
"""
from __future__ import annotations

from engine.effects import execute_effect, resolve_pending_choice
import tests.test_effects as T


MORIA_SPEC = {
    "filter": {"category": "CHARACTER", "cost_le": 4, "feature": "スリラーバーク海賊団"},
    "limit": 1,
    "or_to_life": True,
}


def _setup(human_idx=0):
    repo, overlay = T._repo(), T._overlay()
    state = T._make_state(repo, "OP11-041", overlay=overlay)  # leader ナミ (麦わらの一味)
    me, opp = state.players[0], state.players[1]
    state.turn_player_idx = 0
    state.human_player_idx = human_idx  # human_idx==0 → P0 acting = human
    state.turn_number = 9
    me.characters = []
    me.trash = [repo.get("OP14-102")]  # クマシー (c1 スリラーバーク海賊団)
    return state, me, opp, repo


def test_moria_human_offers_destination_modal():
    """human acting 時、 モリア on_play は「登場/ライフ」 の行き先 modal を立てる (auto しない)。"""
    state, me, opp, repo = _setup()
    execute_effect({"play_from_trash": dict(MORIA_SPEC)}, state, me, opp, None)
    pc = state.pending_choice
    assert pc is not None and pc["kind"] == "play_from_trash_or_life_pick", pc
    dests = {a["dest"] for a in pc["actions"]}
    assert dests == {"play", "life"}, pc["actions"]
    # まだ場にもライフにも出ていない (= 選択待ち)
    assert len(me.characters) == 0 and len(me.trash) == 1


def test_moria_choose_life_adds_face_up_life():
    """「ライフに加える」 を選ぶと トラッシュ→ライフ上 (face-up)、 場には出ない。"""
    state, me, opp, repo = _setup()
    life0 = len(me.life)
    fu0 = getattr(me, "face_up_life_count", 0)
    execute_effect({"play_from_trash": dict(MORIA_SPEC)}, state, me, opp, None)
    actions = state.pending_choice["actions"]
    life_idx = next(i for i, a in enumerate(actions) if a["dest"] == "life")
    resolve_pending_choice(state, [life_idx])
    assert len(me.life) == life0 + 1, "ライフが +1 されていない"
    assert me.life[0].card_id == "OP14-102", "クマシーがライフ上 (top) に乗っていない"
    assert me.face_up_life_count == fu0 + 1, "face_up_life_count が増えていない"
    assert len(me.characters) == 0, "ライフ選択なのに場に出ている"
    assert len(me.trash) == 0, "トラッシュから取り除かれていない"


def test_moria_choose_play_summons():
    """「登場させる」 を選ぶと場に出る (= 従来挙動)、 ライフは増えない。"""
    state, me, opp, repo = _setup()
    life0 = len(me.life)
    execute_effect({"play_from_trash": dict(MORIA_SPEC)}, state, me, opp, None)
    actions = state.pending_choice["actions"]
    play_idx = next(i for i, a in enumerate(actions) if a["dest"] == "play")
    resolve_pending_choice(state, [play_idx])
    assert any(ip.card.card_id == "OP14-102" for ip in me.characters), "クマシーが場に出ていない"
    assert len(me.life) == life0, "登場選択なのにライフが増えた"


def test_moria_skip_zero():
    """skip (picks 空) で何もしない (= 「~まで」 0 枚も合法)。"""
    state, me, opp, repo = _setup()
    execute_effect({"play_from_trash": dict(MORIA_SPEC)}, state, me, opp, None)
    resolve_pending_choice(state, [])
    assert len(me.characters) == 0 and len(me.life) == 0 and len(me.trash) == 1


def test_moria_ai_auto_plays_unchanged():
    """AI acting 時は modal を立てず従来通り登場 (= matrix/AI 不変)。"""
    state, me, opp, repo = _setup(human_idx=1)  # P0 が turn だが human は P1 → P0 視点 AI
    execute_effect({"play_from_trash": dict(MORIA_SPEC)}, state, me, opp, None)
    assert state.pending_choice is None, "AI なのに行き先 modal が立った"
    assert any(ip.card.card_id == "OP14-102" for ip in me.characters), "AI が登場させていない"
    assert len(me.life) == 0, "AI 登場なのにライフに加わった"
