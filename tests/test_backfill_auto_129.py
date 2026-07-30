# -*- coding: utf-8 -*-
"""OP13 (紫 ロジャー海賊団 / ビッグ・マム海賊団 ホーミーズ 系) 効果 回帰テスト
バックフィル (自動生成 wave 129):
OP13-062 / OP13-063 / OP13-066 / OP13-067 / OP13-068 /
OP13-071 / OP13-072 / OP13-074 / OP13-075 / OP13-077 の 10 枚。

目的 (= test_backfill_auto_001〜128.py と同一方針):
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
    trigger_counter_event,
    trigger_main_event,
    trigger_on_attack,
    trigger_on_play,
)

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("OP01-013")] * 30
    p1.deck = [repo.get("OP01-013")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when):
    """指定 card_id の overlay から when 一致の効果の (do, effect) を返す。"""
    for e in overlay.get(cid).effects:
        if e.get("when") == when:
            return e["do"], e
    raise AssertionError(f"{cid} に when={when} の効果がない")


def _drain(st, guard=14):
    """pending_choice を種別ごとに適切に選び続けて解決しきる。"""
    g = 0
    while st.pending_choice is not None and g < guard:
        kind = st.pending_choice.get("kind", "")
        if kind in ("optional_cost_confirm", "reveal_top_play_confirm",
                    "replace_ko_optional"):
            resolve_pending_choice(st, [1])
        else:
            cands = (st.pending_choice.get("candidates")
                     or st.pending_choice.get("cards")
                     or st.pending_choice.get("options") or [])
            resolve_pending_choice(st, [0] if len(cands) > 0 else [])
        g += 1


# 定番 leader / helper カード
_NEUTRAL = "OP01-001"        # ロロノア・ゾロ (leader、 超新星/麦わらの一味)
_ROGER_LEADER = "OP13-003"   # ゴール・Ｄ・ロジャー (leader、 紫、 海賊王/ロジャー海賊団)
_FILLER = "OP01-013"         # サンジ (麦わらの一味 cost2 pow3000 CHARACTER)
_VICTIM = "OP01-016"         # ナミ (麦わらの一味 cost1 pow2000 CHARACTER)
_HOMIE_C1 = "OP11-077"       # ランドルフ (CHARACTER 紫 cost1 pow2000、 ホーミーズ)


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave129_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP13-062", "OP13-063", "OP13-066", "OP13-067", "OP13-068",
           "OP13-071", "OP13-072", "OP13-074", "OP13-075", "OP13-077"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP13-062 クロッカス (CHARACTER 紫 cost5 pow6000):
#    【登場時】自分の付与されているドン‼がある場合、ドン‼デッキからドン‼1枚までを、
#      アクティブで追加する。
#    【アタック時】相手の元々のパワー3000以下のキャラ1枚までを、持ち主の手札に戻す。
# --------------------------------------------------------------------------- #
def test_op13_062_on_play_add_active_don_when_attached_ai():
    """【登場時】 自付与ドンあり → ドンデッキから1枚アクティブ追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _ROGER_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 1  # 付与ドンあり → 条件成立
    crocus = InPlay.of(repo.get("OP13-062"), sickness=True)
    me.characters = [crocus]

    active_before = me.don_active
    remain_before = me.don_remaining_in_deck
    trigger_on_play(st, me, opp, crocus, overlay)
    _drain(st)

    assert me.don_active == active_before + 1, "アクティブドンが1枚増えていない"
    assert me.don_remaining_in_deck == remain_before - 1, "ドンデッキが1枚減っていない"


def test_op13_062_on_play_no_add_when_no_attached_don():
    """負例: 付与ドンが無ければ 条件不成立 → ドン追加は起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _ROGER_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 0  # 付与ドン無し → 条件不成立
    crocus = InPlay.of(repo.get("OP13-062"), sickness=True)
    me.characters = [crocus]

    active_before = me.don_active
    trigger_on_play(st, me, opp, crocus, overlay)
    _drain(st)

    assert me.don_active == active_before, "付与ドン無しでドンが増えてはいけない"


def test_op13_062_on_attack_bounce_opp_power_le3000_ai():
    """【アタック時】 相手のパワー3000以下キャラ1枚を持ち主の手札に戻す (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _ROGER_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    crocus = InPlay.of(repo.get("OP13-062"), sickness=False)
    me.characters = [crocus]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # pow3000 (≤3000)
    opp.characters = [victim]
    opp_hand_before = len(opp.hand)

    trigger_on_attack(st, me, opp, crocus, overlay)
    _drain(st)

    assert victim not in opp.characters, "相手のパワー3000以下キャラが手札に戻っていない"
    assert len(opp.hand) == opp_hand_before + 1, "戻したキャラが相手の手札に加わっていない"


def test_op13_062_on_attack_bounce_human_pick():
    """人間 + 相手キャラ複数 (共に pow≤3000) → 戻す対象を選ぶ target_pick modal。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _ROGER_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    crocus = InPlay.of(repo.get("OP13-062"), sickness=False)
    me.characters = [crocus]
    a = InPlay.of(repo.get(_FILLER), sickness=False)   # pow3000
    b = InPlay.of(repo.get(_VICTIM), sickness=False)   # pow2000
    opp.characters = [a, b]

    trigger_on_attack(st, me, opp, crocus, overlay)

    assert st.pending_choice is not None, "人間 + 複数候補で対象選択 modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b not in opp.characters, "人間が選んだキャラが手札に戻っていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP13-063 光月おでん (CHARACTER 紫 cost5 pow6000):
#    【ブロッカー】【登場時】自分の付与されているドン‼がある場合、
#      ドン‼デッキからドン‼1枚までを、レストで追加する。
# --------------------------------------------------------------------------- #
def test_op13_063_on_play_add_rested_don_when_attached_ai():
    """【登場時】 自付与ドンあり → ドンデッキから1枚レスト追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _ROGER_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 1  # 付与ドンあり
    oden = InPlay.of(repo.get("OP13-063"), sickness=True)
    me.characters = [oden]

    rested_before = me.don_rested
    remain_before = me.don_remaining_in_deck
    trigger_on_play(st, me, opp, oden, overlay)
    _drain(st)

    assert me.don_rested == rested_before + 1, "レストドンが1枚増えていない"
    assert me.don_remaining_in_deck == remain_before - 1, "ドンデッキが1枚減っていない"


def test_op13_063_on_play_no_add_when_no_attached_don():
    """負例: 付与ドンが無ければ 条件不成立 → レストドン追加は起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _ROGER_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 0
    oden = InPlay.of(repo.get("OP13-063"), sickness=True)
    me.characters = [oden]

    rested_before = me.don_rested
    trigger_on_play(st, me, opp, oden, overlay)
    _drain(st)

    assert me.don_rested == rested_before, "付与ドン無しでレストドンが増えてはいけない"


# --------------------------------------------------------------------------- #
#  OP13-066 シルバーズ・レイリー (CHARACTER 紫 cost8 pow9000):
#    【速攻】【登場時】自分の付与されているドン‼がある場合、相手のコスト5以下のキャラ
#      1枚までを、レストにする。その後、このターン終了時、ドン‼デッキからドン‼1枚まで
#      を、アクティブで追加する。
# --------------------------------------------------------------------------- #
def test_op13_066_on_play_rest_opp_and_add_don_when_attached_ai():
    """【登場時】 自付与ドンあり → 相手 cost5以下1枚レスト + ドン1アクティブ追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _ROGER_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    rayleigh = InPlay.of(repo.get("OP13-066"), sickness=False)
    rayleigh.attached_dons = 1  # 自付与ドンあり (このキャラに付与) → 条件成立
    me.characters = [rayleigh]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (≤5)
    victim.rested = False
    opp.characters = [victim]

    active_before = me.don_active
    trigger_on_play(st, me, opp, rayleigh, overlay)
    _drain(st)

    assert victim.rested is True, "相手の cost5以下キャラがレストされていない"
    assert me.don_active == active_before + 1, "アクティブドンが1枚追加されていない"


def test_op13_066_on_play_no_effect_when_no_attached_don():
    """負例: 付与ドンが無ければ 条件不成立 → レスト/ドン追加は起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _ROGER_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    rayleigh = InPlay.of(repo.get("OP13-066"), sickness=False)
    rayleigh.attached_dons = 0
    me.characters = [rayleigh]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    victim.rested = False
    opp.characters = [victim]

    active_before = me.don_active
    trigger_on_play(st, me, opp, rayleigh, overlay)
    _drain(st)

    assert victim.rested is False, "条件不成立で相手キャラがレストされてはいけない"
    assert me.don_active == active_before, "条件不成立でドンが追加されてはいけない"


# --------------------------------------------------------------------------- #
#  OP13-067 スコッパー・ギャバン (CHARACTER 紫 cost6 pow7000):
#    【登場時】自分のリーダーが『ロジャー海賊団』を含む特徴を持つ場合、カード2枚を引き、
#      自分の手札1枚を捨てる。その後、ドン‼デッキからドン‼1枚までを、レストで追加する。
# --------------------------------------------------------------------------- #
def test_op13_067_on_play_draw2_discard1_add_rested_when_roger_ai():
    """【登場時】 リーダー ロジャー → 2ドロー1捨て + ドン1レスト追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _ROGER_LEADER, overlay)  # ロジャー海賊団 leader → 条件成立
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 10
    gaban = InPlay.of(repo.get("OP13-067"), sickness=True)
    me.characters = [gaban]

    deck_before = len(me.deck)
    rested_before = me.don_rested
    trigger_on_play(st, me, opp, gaban, overlay)
    _drain(st)

    # 2 ドロー → 1 捨て = 手札 net +1
    assert len(me.hand) == 1, f"2ドロー1捨てで手札が1枚にならない: hand={len(me.hand)}"
    assert len(me.deck) == deck_before - 2, "デッキが2枚減っていない"
    assert me.don_rested == rested_before + 1, "レストドンが1枚追加されていない"


def test_op13_067_on_play_no_effect_when_leader_not_roger():
    """負例: リーダーが ロジャー海賊団 でなければ 条件不成立 → ドロー/ドン追加は起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)  # ゾロ leader → 条件不成立
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 10
    gaban = InPlay.of(repo.get("OP13-067"), sickness=True)
    me.characters = [gaban]

    deck_before = len(me.deck)
    rested_before = me.don_rested
    trigger_on_play(st, me, opp, gaban, overlay)
    _drain(st)

    assert len(me.hand) == 0, "条件不成立でドローが起きてはいけない"
    assert len(me.deck) == deck_before, "条件不成立でデッキは減ってはいけない"
    assert me.don_rested == rested_before, "条件不成立でレストドンが増えてはいけない"


# --------------------------------------------------------------------------- #
#  OP13-068 ダグラス・バレット (CHARACTER 紫 cost3 pow4000):
#    自分の場のドン‼が8枚以上ある場合、このキャラのパワー+2000。 (= 静的)
#    【登場時】自分のリーダーが『ロジャー海賊団』を含む特徴を持つ場合、
#      ドン‼デッキからドン‼1枚までを、レストで追加する。
# --------------------------------------------------------------------------- #
def test_op13_068_static_pump_when_don_ge8():
    """静的: 自場のドン8枚以上 → このキャラ +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    barrett_def = repo.get("OP13-068")
    barrett = InPlay.of(barrett_def, sickness=False)
    me.characters = [barrett]
    me.don_active = 8  # 自場ドン 8 (≥8) → 条件成立

    evaluate_static_effects(st, overlay)
    assert barrett.power == barrett_def.power + 2000, \
        f"ドン8枚で +2000 されていない: {barrett.power} (base {barrett_def.power})"


def test_op13_068_static_no_pump_when_don_lt8():
    """負例: 自場のドンが7枚以下なら 静的 +2000 は乗らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    barrett_def = repo.get("OP13-068")
    barrett = InPlay.of(barrett_def, sickness=False)
    me.characters = [barrett]
    me.don_active = 7  # 7 枚 (<8) → 不成立

    evaluate_static_effects(st, overlay)
    assert barrett.power == barrett_def.power, \
        f"ドン7枚で power が上がってはいけない: {barrett.power}"


def test_op13_068_on_play_add_rested_don_when_roger_ai():
    """【登場時】 リーダー ロジャー → ドン1レスト追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _ROGER_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    barrett = InPlay.of(repo.get("OP13-068"), sickness=True)
    me.characters = [barrett]

    rested_before = me.don_rested
    remain_before = me.don_remaining_in_deck
    trigger_on_play(st, me, opp, barrett, overlay)
    _drain(st)

    assert me.don_rested == rested_before + 1, "レストドンが1枚追加されていない"
    assert me.don_remaining_in_deck == remain_before - 1, "ドンデッキが1枚減っていない"


# --------------------------------------------------------------------------- #
#  OP13-071 ネコマムシ (CHARACTER 紫 cost3 pow3000):
#    【登場時】自分の場のドン‼が8枚以上ある場合、相手の元々のパワー3000以下のキャラ
#      1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op13_071_on_play_ko_opp_power_le3000_when_don_ge8_ai():
    """【登場時】 自場ドン8以上 → 相手のパワー3000以下キャラ1枚を KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 8  # ドン 8 (≥8) → 条件成立
    nekomamushi = InPlay.of(repo.get("OP13-071"), sickness=True)
    me.characters = [nekomamushi]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # pow3000 (≤3000)
    opp.characters = [victim]

    trigger_on_play(st, me, opp, nekomamushi, overlay)
    _drain(st)

    assert victim not in opp.characters, "相手のパワー3000以下キャラが KO されていない"


def test_op13_071_on_play_no_ko_when_don_lt8():
    """負例: 自場のドンが7枚以下なら 条件不成立 → KO は起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 7  # 7 枚 (<8)
    nekomamushi = InPlay.of(repo.get("OP13-071"), sickness=True)
    me.characters = [nekomamushi]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]

    trigger_on_play(st, me, opp, nekomamushi, overlay)
    _drain(st)

    assert victim in opp.characters, "条件不成立で相手キャラが KO されてはいけない"


def test_op13_071_on_play_ko_human_pick():
    """人間 + 相手キャラ複数 (共に pow≤3000) → KO 対象を選ぶ target_pick modal。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_active = 8
    nekomamushi = InPlay.of(repo.get("OP13-071"), sickness=True)
    me.characters = [nekomamushi]
    a = InPlay.of(repo.get(_FILLER), sickness=False)   # pow3000
    b = InPlay.of(repo.get(_VICTIM), sickness=False)   # pow2000
    opp.characters = [a, b]

    trigger_on_play(st, me, opp, nekomamushi, overlay)

    assert st.pending_choice is not None, "人間 + 複数候補で KO 対象選択 modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP13-072 バギー (CHARACTER 紫 cost2 pow2000):
#    【登場時】自分のリーダーが『ロジャー海賊団』を含む特徴を持ち、自分の付与されている
#      ドン‼がある場合、ドン‼デッキからドン‼1枚までを、レストで追加する。
# --------------------------------------------------------------------------- #
def test_op13_072_on_play_add_rested_don_when_roger_and_attached_ai():
    """【登場時】 リーダー ロジャー かつ 自付与ドンあり → ドン1レスト追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _ROGER_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 1  # 付与ドンあり
    buggy = InPlay.of(repo.get("OP13-072"), sickness=True)
    me.characters = [buggy]

    rested_before = me.don_rested
    remain_before = me.don_remaining_in_deck
    trigger_on_play(st, me, opp, buggy, overlay)
    _drain(st)

    assert me.don_rested == rested_before + 1, "レストドンが1枚追加されていない"
    assert me.don_remaining_in_deck == remain_before - 1, "ドンデッキが1枚減っていない"


def test_op13_072_on_play_no_add_when_no_attached_don():
    """負例: リーダー ロジャー でも 付与ドンが無ければ 条件不成立 → ドン追加は起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _ROGER_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 0  # 付与ドン無し → 条件不成立
    buggy = InPlay.of(repo.get("OP13-072"), sickness=True)
    me.characters = [buggy]

    rested_before = me.don_rested
    trigger_on_play(st, me, opp, buggy, overlay)
    _drain(st)

    assert me.don_rested == rested_before, "付与ドン無しでレストドンが増えてはいけない"


def test_op13_072_on_play_no_add_when_leader_not_roger():
    """負例: 付与ドンがあっても リーダーが ロジャー でなければ 条件不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)  # ゾロ leader
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 1
    buggy = InPlay.of(repo.get("OP13-072"), sickness=True)
    me.characters = [buggy]

    rested_before = me.don_rested
    trigger_on_play(st, me, opp, buggy, overlay)
    _drain(st)

    assert me.don_rested == rested_before, \
        "リーダー非ロジャーでレストドンが増えてはいけない"


# --------------------------------------------------------------------------- #
#  OP13-074 ヘラ (CHARACTER 紫 cost4 pow5000):
#    【登場時】自分の手札からパワー3000以下の特徴《ホーミーズ》を持つキャラカード1枚
#      までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op13_074_on_play_deploy_homie_from_hand_ai():
    """【登場時】 手札の pow3000以下 ホーミーズ キャラを登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    hera = InPlay.of(repo.get("OP13-074"), sickness=True)
    me.characters = [hera]
    me.hand = [repo.get(_HOMIE_C1)]  # ランドルフ ホーミーズ pow2000 (≤3000)

    trigger_on_play(st, me, opp, hera, overlay)
    _drain(st)

    assert any(c.card.card_id == _HOMIE_C1 for c in me.characters), \
        "手札の pow3000以下 ホーミーズ が登場していない"
    assert len(me.hand) == 0, "登場した ホーミーズ が手札から抜けていない"


def test_op13_074_on_play_no_deploy_when_no_valid_homie():
    """負例: 手札に pow3000以下 ホーミーズ が無ければ 登場は起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    hera = InPlay.of(repo.get("OP13-074"), sickness=True)
    me.characters = [hera]
    me.hand = [repo.get(_FILLER)]  # サンジ (ホーミーズでない)

    trigger_on_play(st, me, opp, hera, overlay)
    _drain(st)

    assert not any(c.card.card_id == _FILLER for c in me.characters), \
        "ホーミーズでないキャラが登場してはいけない"
    assert len(me.hand) == 1, "非対象カードは手札に残るべき"


def test_op13_074_on_play_deploy_human_pick():
    """人間 + 手札に対象 ホーミーズ 複数 → 登場先を選ぶ play_from_hand modal。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    hera = InPlay.of(repo.get("OP13-074"), sickness=True)
    me.characters = [hera]
    me.hand = [repo.get(_HOMIE_C1), repo.get("OP11-106")]  # ランドルフ / ゼウス (共に ホーミーズ pow2000)

    trigger_on_play(st, me, opp, hera, overlay)

    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st)
    assert any(c.card.card_id in (_HOMIE_C1, "OP11-106") for c in me.characters), \
        "人間が選んだ ホーミーズ が登場していない"


# --------------------------------------------------------------------------- #
#  OP13-075 いっちょやるか生きててこその“殺し合い”!!! (EVENT 紫 cost1):
#    【メイン】自分のドン‼1枚をレストにできる：自分のリーダーが「ゴール・Ｄ・ロジャー」で、
#      自分の付与されているドン‼がある場合、ドン‼デッキからドン‼1枚までを、レストで追加する。
#    【カウンター】自分のリーダーを、このバトル中、パワー+3000。
# --------------------------------------------------------------------------- #
def test_op13_075_main_add_rested_don_when_roger_and_attached_ai():
    """【メイン】 ドン1レスト (コスト) + リーダー ロジャー & 付与ドンあり → ドン1レスト追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _ROGER_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 2
    me.don_rested = 0
    me.leader.attached_dons = 1  # 付与ドンあり
    remain_before = me.don_remaining_in_deck

    trigger_main_event(st, me, opp, repo.get("OP13-075"), overlay)
    _drain(st)

    # コストで 1 枚レスト + add_rested_don で 1 枚追加 = don_rested 2
    assert me.don_rested == 2, f"コスト1レスト + ドン1追加で don_rested=2 にならない: {me.don_rested}"
    assert me.don_active == 1, "コストでアクティブドンが1枚レストされるべき"
    assert me.don_remaining_in_deck == remain_before - 1, "ドンデッキが1枚減っていない"


def test_op13_075_counter_pump_leader():
    """【カウンター】 自リーダーを このバトル中 パワー+3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _ROGER_LEADER, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    trigger_counter_event(st, me, opp, repo.get("OP13-075"), overlay)
    _drain(st)

    assert me.leader.power == power_before + 3000, \
        f"カウンターの +3000 が自リーダーに反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  OP13-077 頂点まで行って来い!!! (EVENT 紫 cost1):
#    【メイン】自分のドン‼3枚をレストにできる：自分の付与されているドン‼がある場合、
#      相手の元々の、パワー4000以下のキャラ1枚までとパワー3000以下のキャラ1枚までを、KOする。
#    【カウンター】自分のリーダーを、このバトル中、パワー+3000。
# --------------------------------------------------------------------------- #
def test_op13_077_main_ko_two_opp_when_attached_ai():
    """【メイン】 ドン3レスト (コスト) + 付与ドンあり → 相手キャラ2枚 (pow4000以下/3000以下) を KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _ROGER_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    me.don_rested = 0
    me.leader.attached_dons = 1  # 付与ドンあり → 条件成立
    a = InPlay.of(repo.get(_FILLER), sickness=False)   # pow3000 (≤4000)
    b = InPlay.of(repo.get(_VICTIM), sickness=False)   # pow2000 (≤3000)
    opp.characters = [a, b]

    trigger_main_event(st, me, opp, repo.get("OP13-077"), overlay)
    _drain(st)

    assert a not in opp.characters, "相手のパワー4000以下キャラが KO されていない"
    assert b not in opp.characters, "相手のパワー3000以下キャラが KO されていない"
    assert me.don_rested == 3, "コストでドンが3枚レストされるべき"


def test_op13_077_main_no_ko_when_no_attached_don():
    """負例: 付与ドンが無ければ 条件不成立 → KO は起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _ROGER_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    me.don_rested = 0
    me.leader.attached_dons = 0  # 付与ドン無し → 条件不成立
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_VICTIM), sickness=False)
    opp.characters = [a, b]

    trigger_main_event(st, me, opp, repo.get("OP13-077"), overlay)
    _drain(st)

    assert a in opp.characters and b in opp.characters, \
        "条件不成立で相手キャラが KO されてはいけない"


def test_op13_077_counter_pump_leader():
    """【カウンター】 自リーダーを このバトル中 パワー+3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _ROGER_LEADER, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    trigger_counter_event(st, me, opp, repo.get("OP13-077"), overlay)
    _drain(st)

    assert me.leader.power == power_before + 3000, \
        f"カウンターの +3000 が自リーダーに反映されていない: {me.leader.power}"
