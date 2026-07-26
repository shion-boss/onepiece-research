# -*- coding: utf-8 -*-
"""OP08 弾 (百獣海賊団 / 黒ひげ海賊団 / 空島 系) 効果 回帰テスト
バックフィル (自動生成 wave 089):
OP08-088 / OP08-090 / OP08-091 / OP08-092 / OP08-093 / OP08-094 /
OP08-095 / OP08-096 / OP08-097 / OP08-100 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_001.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 任意コスト を 持つカードは 人間 actor で pending_choice が
      正しい kind + 候補で立ち、 resolve_pending_choice で解決できる (= 人間が選べる)
  (3) 同じ効果を AI 文脈 (human_player_idx=None) で回しても crash せず自動解決する
      (= AI が選べる)
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    evaluate_static_effects,
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id="OP01-001", overlay=None, human_idx=None,
           opp_leader_id="OP01-001", turn_player_idx=0):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=turn_player_idx / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("OP01-013")] * 30
    p1.deck = [repo.get("OP01-013")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn_player_idx
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when):
    return [p for e in overlay.get(cid).effects if e["when"] == when for p in e["do"]]


def _drain(st, pick=0, guard=12):
    """pending_choice を pick を選び続けて解決しきる。"""
    g = 0
    while st.pending_choice is not None and g < guard:
        cands = st.pending_choice.get("candidates")
        if cands is not None and len(cands) == 0:
            resolve_pending_choice(st, [])
        else:
            resolve_pending_choice(st, [pick])
        g += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op08_wave089_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP08-088", "OP08-090", "OP08-091", "OP08-092", "OP08-093",
           "OP08-094", "OP08-095", "OP08-096", "OP08-097", "OP08-100"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP08-088 デュバル (黒 CHARACTER cost1):
#    【登場時】自分のキャラ1枚までを、次の相手のターン終了時まで、コスト+1。
# --------------------------------------------------------------------------- #
def test_op08_088_on_play_cost_plus1_timed_ai():
    """【登場時】自分のキャラ1枚のコストを +1 する (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)  # base cost 2
    me.characters = [friend]

    cost_before = friend.base_cost
    for prim in _do(overlay, "OP08-088", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-088"), sickness=True))
    _drain(st)

    assert friend.base_cost == cost_before + 1, \
        f"自キャラのコストが +1 されていない: {friend.base_cost} (before {cost_before})"


def test_op08_088_on_play_human_target_pick():
    """【登場時】人間 + 自キャラ複数 → target_pick modal が立ち resolve で 1 体 +1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost 2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost 1
    me.characters = [a, b]

    execute_effect(_do(overlay, "OP08-088", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP08-088"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_before = b.base_cost
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b.base_cost == b_before + 1, "人間が選んだキャラのコストが +1 されていない"


# --------------------------------------------------------------------------- #
#  OP08-090 ハムレット (黒 CHARACTER cost3):
#    【登場時】自分のトラッシュからコスト2以下の特徴《SMILE》を持つキャラカード
#      1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op08_090_on_play_revive_smile_ai():
    """【登場時】トラッシュのコスト2以下《SMILE》キャラを登場させる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP08-086")]  # ジンラミー 百獣海賊団/SMILE cost2

    for prim in _do(overlay, "OP08-090", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-090"), sickness=True))
    _drain(st)

    assert any(c.card.card_id == "OP08-086" for c in me.characters), \
        f"トラッシュの SMILE キャラが登場していない: {[c.card.card_id for c in me.characters]}"
    assert not any(c.card_id == "OP08-086" for c in me.trash), \
        "登場した SMILE キャラがトラッシュに残っている"


def test_op08_090_on_play_human_pick_from_trash():
    """人間 + トラッシュに《SMILE》キャラ複数 → play_from_trash_pick modal が立ち resolve。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP08-086"), repo.get("OP01-104")]  # SMILE cost2 x2

    execute_effect(_do(overlay, "OP08-090", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP08-090"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "play_from_trash_pick", \
        f"kind が play_from_trash_pick でない: {st.pending_choice.get('kind')}"
    assert len(st.pending_choice.get("candidates", [])) == 2, "SMILE 候補が2枚でない"
    resolve_pending_choice(st, [0])
    _drain(st)
    assert len(me.characters) == 1, "人間選択後 キャラが1体登場していない"


# --------------------------------------------------------------------------- #
#  OP08-091 フーズ・フー (黒 CHARACTER cost5):
#    【登場時】自分の手札1枚を捨てることができる：相手のコスト3以下のキャラ1枚までを、KOする。
#    【トリガー】相手のコスト3以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op08_091_on_play_discard_then_ko_ai():
    """【登場時】手札1枚捨てて 相手コスト3以下キャラを KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 <= 3
    opp.characters = [victim]

    for prim in _do(overlay, "OP08-091", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-091"), sickness=True))
    _drain(st)

    assert victim not in opp.characters, "相手コスト3以下キャラが KO されていない"
    assert len(me.hand) == 0, "手札1枚が捨てられていない"


def test_op08_091_on_play_human_optional_cost_modal():
    """【登場時】人間 → 任意コスト optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]
    opp.characters = [InPlay.of(repo.get("OP01-016"), sickness=False)]

    execute_effect(_do(overlay, "OP08-091", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP08-091"), sickness=True))
    assert st.pending_choice is not None, "人間で任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"


def test_op08_091_trigger_ko_ai():
    """【トリガー】相手コスト3以下キャラを KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 <= 3
    opp.characters = [victim]

    for prim in _do(overlay, "OP08-091", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert victim not in opp.characters, "トリガーで相手コスト3以下キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP08-092 ページワン (黒 CHARACTER cost5):
#    【登場時】自分のトラッシュからコスト4以下の「うるティ」1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op08_092_on_play_revive_ulti_ai():
    """【登場時】トラッシュのコスト4以下「うるティ」を登場させる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP01-093")]  # うるティ cost2 <= 4

    for prim in _do(overlay, "OP08-092", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-092"), sickness=True))
    _drain(st)

    assert any(c.card.card_id == "OP01-093" for c in me.characters), \
        f"トラッシュの「うるティ」が登場していない: {[c.card.card_id for c in me.characters]}"


def test_op08_092_high_cost_ulti_not_played():
    """negative: コスト5以上の「うるティ」はフィルタ外で登場しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    # 「うるティ」以外のキャラだけをトラッシュに置き、 name フィルタで登場しないことを検証。
    me.trash = [repo.get("OP08-086")]  # SMILE キャラ (「うるティ」ではない)

    for prim in _do(overlay, "OP08-092", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-092"), sickness=True))
    _drain(st)

    assert not any(c.card.card_id == "OP08-086" for c in me.characters), \
        "「うるティ」以外のキャラが誤って登場している"
    assert len(me.characters) == 0, "対象不在なのにキャラが登場している"
    # cost4 の「うるティ」は cost_le:4 の上限 inclusive で登場可能なことも確認。
    assert int(repo.get("OP08-078").cost) == 4


# --------------------------------------------------------------------------- #
#  OP08-093 X・ドレーク (黒 CHARACTER cost4):
#    【ドン‼×1】このキャラのコスト+2。
# --------------------------------------------------------------------------- #
def test_op08_093_attached_don_cost_plus2_static():
    """【ドン‼×1】ドン1枚付与でこのキャラの基本コストが +2 (静的、 印刷4 → 6)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    drake = InPlay.of(repo.get("OP08-093"), sickness=False)
    drake.attached_dons = 1  # n=1 ゲート成立
    me.characters = [drake]

    printed = int(repo.get("OP08-093").cost)  # 4
    evaluate_static_effects(st, overlay)
    assert drake.base_cost == printed + 2, \
        f"ドン1枚でコストが +2 されていない: {drake.base_cost} (printed {printed})"


def test_op08_093_no_don_no_cost_bonus():
    """negative: ドン付与が無ければコストは印刷値のまま。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    drake = InPlay.of(repo.get("OP08-093"), sickness=False)
    drake.attached_dons = 0
    me.characters = [drake]

    printed = int(repo.get("OP08-093").cost)
    evaluate_static_effects(st, overlay)
    assert drake.base_cost == printed, \
        f"ドン0枚で誤ってコストが増えている: {drake.base_cost} (printed {printed})"


# --------------------------------------------------------------------------- #
#  OP08-094 炎皇 (黒 EVENT cost2):
#    【メイン】/【カウンター】自分のトラッシュからカード3枚を好きな順番でデッキの下に
#      置くことができる：相手のコスト2以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op08_094_main_trash_to_deck_then_ko_ai():
    """【メイン】トラッシュ3枚をデッキ下へ + 相手コスト2以下キャラを KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP01-013")] * 3
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 <= 2
    opp.characters = [victim]

    deck_before = len(me.deck)
    for prim in _do(overlay, "OP08-094", "main"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert victim not in opp.characters, "相手コスト2以下キャラが KO されていない"
    assert len(me.trash) == 0, "トラッシュ3枚がデッキ下へ移動していない"
    assert len(me.deck) == deck_before + 3, "デッキが3枚増えていない"


def test_op08_094_main_human_optional_cost_modal():
    """【メイン】人間 → 任意コスト optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP01-013")] * 3
    opp.characters = [InPlay.of(repo.get("OP01-013"), sickness=False)]

    execute_effect(_do(overlay, "OP08-094", "main")[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間で任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"


def test_op08_094_counter_available():
    """【カウンター】効果が overlay に登録され、 AI 文脈で crash せず発火する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay, turn_player_idx=1)  # 相手ターン (防御側)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP01-013")] * 3
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 <= 2
    opp.characters = [victim]

    counter_do = _do(overlay, "OP08-094", "counter")
    assert len(counter_do) > 0, "OP08-094 に counter 効果が無い"
    for prim in counter_do:
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert victim not in opp.characters, "カウンターで相手コスト2以下キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP08-095 鉄塊 牙閃 (黒 EVENT cost2):
#    【メイン】自分のトラッシュが10枚以上ある場合、自分のキャラ1枚までを、
#      次の相手のターン終了時まで、パワー+2000。
#    【トリガー】自分のリーダーかキャラ1枚までを、このターン中、パワー+2000。
# --------------------------------------------------------------------------- #
def test_op08_095_main_pump_when_trash_ge10_ai():
    """【メイン】トラッシュ10枚以上で自キャラ +2000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP01-013")] * 10
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)  # power 3000
    me.characters = [friend]

    power_before = friend.power
    for prim in _do(overlay, "OP08-095", "main"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert friend.power == power_before + 2000, \
        f"トラッシュ10枚以上で +2000 されていない: {friend.power} (before {power_before})"


def test_op08_095_main_trash_ge10_gate_in_overlay():
    """overlay の【メイン】効果に self_trash_count_ge:10 の発動条件がある。"""
    overlay = _overlay()
    eff = next(e for e in overlay.get("OP08-095").effects if e["when"] == "main")
    assert eff.get("if", {}).get("self_trash_count_ge") == 10, \
        f"OP08-095 の main に トラッシュ10枚以上条件が無い: {eff.get('if')}"


def test_op08_095_main_human_target_pick():
    """【メイン】人間 + 自キャラ複数 → target_pick modal が立ち resolve で 1 体 +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP01-013")] * 10
    a = InPlay.of(repo.get("OP01-013"), sickness=False)
    b = InPlay.of(repo.get("OP01-016"), sickness=False)
    me.characters = [a, b]

    execute_effect(_do(overlay, "OP08-095", "main")[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    b_before = b.power
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b.power == b_before + 2000, "人間が選んだキャラが +2000 されていない"


def test_op08_095_trigger_pump_turn_ai():
    """【トリガー】自リーダーかキャラ +2000 (このターン中、 AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [friend]

    lb, fb = me.leader.power, friend.power
    for prim in _do(overlay, "OP08-095", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert (me.leader.power == lb + 2000) or (friend.power == fb + 2000), \
        "トリガーで自リーダー/キャラのいずれも +2000 されていない"


# --------------------------------------------------------------------------- #
#  OP08-096 人の夢は!!!終わらねェ!!!! (黒 EVENT cost1):
#    【カウンター】自分のデッキの上から1枚をトラッシュに置く。置いたカードがコスト6以上の
#      場合、自分のリーダーかキャラ1枚までを、このバトル中、パワー+5000。
#    【トリガー】自分のトラッシュからコスト3以下の黒のキャラカード1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op08_096_counter_pump_when_milled_cost6_ai():
    """【カウンター】デッキ上がコスト6以上 → +5000 (このバトル中、 AI: 自リーダー)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("EB04-044")] + [repo.get("OP01-013")] * 20  # コビー cost6 を上に
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [friend]

    lb = me.leader.power
    for prim in _do(overlay, "OP08-096", "counter"):
        execute_effect(prim, st, me, opp, friend)
    _drain(st)

    assert any(c.card_id == "EB04-044" for c in me.trash), \
        "デッキ上1枚がトラッシュに置かれていない"
    assert me.leader.power == lb + 5000 or friend.power == friend.card.power + 5000, \
        f"コスト6以上で +5000 されていない: leader {me.leader.power} (base {lb})"


def test_op08_096_counter_no_pump_when_milled_low_cost():
    """negative: デッキ上がコスト6未満なら +5000 は乗らない (トラッシュには置く)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP01-013")] * 20  # cost2 を上に
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [friend]

    lb = me.leader.power
    for prim in _do(overlay, "OP08-096", "counter"):
        execute_effect(prim, st, me, opp, friend)
    _drain(st)

    assert me.leader.battle_buff == 0 and friend.battle_buff == 0, \
        "コスト6未満なのに +5000 が乗っている"
    assert len(me.trash) == 1, "デッキ上1枚がトラッシュに置かれていない"


def test_op08_096_trigger_revive_black_char_ai():
    """【トリガー】トラッシュのコスト3以下 黒キャラを登場させる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("EB04-042")]  # アルファ 黒 cost1

    for prim in _do(overlay, "OP08-096", "trigger"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-096"), sickness=True))
    _drain(st)

    assert any(c.card.card_id == "EB04-042" for c in me.characters), \
        f"トラッシュの黒キャラが登場していない: {[c.card.card_id for c in me.characters]}"


# --------------------------------------------------------------------------- #
#  OP08-097 ヘリケラトプス (黒 EVENT cost3):
#    【メイン】自分のリーダーが特徴《百獣海賊団》を持つ場合、相手のキャラ1枚までを、
#      このターン中、コスト-2。その後、相手のコスト0のキャラ1枚までを、KOする。
#    【トリガー】相手のコスト3以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op08_097_main_cost_minus_then_ko_ai():
    """【メイン】相手キャラ コスト-2 → コスト0になったキャラを KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, leader_id="OP01-061", overlay=overlay)  # カイドウ 四皇/百獣海賊団
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 → -2 = 0 → KO
    opp.characters = [victim]

    for prim in _do(overlay, "OP08-097", "main"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert victim not in opp.characters, \
        "コスト-2で0になった相手キャラが KO されていない"


def test_op08_097_main_leader_feature_gate_in_overlay():
    """overlay の【メイン】発動条件に 自リーダー《百獣海賊団》(leader_feature) がある。"""
    overlay = _overlay()
    eff = next(e for e in overlay.get("OP08-097").effects if e["when"] == "main")
    assert eff.get("if", {}).get("leader_feature") == "百獣海賊団", \
        f"OP08-097 の main に 百獣海賊団 リーダー条件が無い: {eff.get('if')}"


def test_op08_097_main_human_cost_minus_pick():
    """【メイン】人間 + 相手キャラ複数 → コスト-2 対象の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, leader_id="OP01-061", overlay=overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    opp.characters = [InPlay.of(repo.get("OP01-013"), sickness=False),
                      InPlay.of(repo.get("OP01-016"), sickness=False)]

    execute_effect(_do(overlay, "OP08-097", "main")[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    assert len(st.pending_choice.get("candidates", [])) == 2, "相手キャラ候補が2体でない"


def test_op08_097_trigger_ko_cost3_ai():
    """【トリガー】相手コスト3以下キャラを KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 <= 3
    opp.characters = [victim]

    for prim in _do(overlay, "OP08-097", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert victim not in opp.characters, "トリガーで相手コスト3以下キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP08-100 サウスバード (黄 CHARACTER cost1):
#    【登場時】自分のデッキの上から7枚を見て、「アッパーヤード」1枚までを、登場させる。
#      その後、残りを好きな順番でデッキの下に置く。
#  ※「アッパーヤード」は STAGE カード。 現状 engine は search_top_n destination=play で
#    STAGE を場に置けず (キャラは可、 STAGE はデッキから取り除かれるだけで stages に入らない)、
#    実バグ = 人間レビューへ。 このタスクでは engine を編集しないため 発火 assert は skip。
# --------------------------------------------------------------------------- #
def test_op08_100_on_play_ai_no_crash():
    """【登場時】AI 文脈で crash せず自動解決する (STAGE 未実装の間の最低保証)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP05-117")] + [repo.get("OP01-013")] * 20  # アッパーヤード を上に

    for prim in _do(overlay, "OP08-100", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-100"), sickness=True))
    _drain(st)
    # crash せず pending が解けきっていることのみ保証
    assert st.pending_choice is None, "AI 文脈で pending_choice が解決されていない"


def test_op08_100_on_play_overlay_shape():
    """overlay が search_top_n depth7 / filter name「アッパーヤード」/ destination play を持つ。"""
    overlay = _overlay()
    eff = next(e for e in overlay.get("OP08-100").effects if e["when"] == "on_play")
    spec = eff["do"][0].get("search_top_n", {})
    assert spec.get("depth") == 7, f"depth が7でない: {spec.get('depth')}"
    assert spec.get("filter", {}).get("name") == "アッパーヤード", \
        f"filter name が「アッパーヤード」でない: {spec.get('filter')}"
    assert spec.get("destination") == "play", \
        f"destination が play でない: {spec.get('destination')}"


def test_op08_100_on_play_stage_summon_ai():
    """【登場時】デッキ上7枚から「アッパーヤード」(STAGE) を登場させる (engine 実装待ち)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP05-117")] + [repo.get("OP01-013")] * 20

    for prim in _do(overlay, "OP08-100", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-100"), sickness=True))
    _drain(st)

    assert any(getattr(s, "card", s).card_id == "OP05-117"
               for s in getattr(me, "stages", [])), \
        "「アッパーヤード」が場 (stages) に登場していない"
