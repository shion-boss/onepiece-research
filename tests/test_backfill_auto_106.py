# -*- coding: utf-8 -*-
"""OP10 弾 紫 (ドンキホーテ海賊団) / 黒 (ドレスローザ・黒ひげ海賊団) 効果 回帰テスト
バックフィル (自動生成 wave 106):
OP10-071 / OP10-074 / OP10-076 / OP10-077 / OP10-078 /
OP10-079 / OP10-080 / OP10-081 / OP10-082 / OP10-083 の 10 枚。

  OP10-071 ドフラミンゴ = 登場時 ドン-1：手札のコスト5以下ドンキホーテ海賊団キャラ1枚を登場
     (play_from_hand) / 相手アタック時 ドン1レスト：ドンデッキからドン1アクティブ (add_don)
  OP10-074 ピーカ = ターン1回 相手効果KOされる場合 代わりにアクティブドン2レスト (replace_ko)
  OP10-076 ベビー5 = 登場時 手札1枚捨てる：リーダーがドンキホーテ海賊団ならドン+1 (optional_cost_then)
  OP10-077 ベラミー = ブロック時 ドン2レスト：ドンデッキからドン1アクティブ (add_don)
  OP10-078 家族を笑う者は… = メイン/カウンター 上3枚から自身以外のドンキホーテ海賊団1枚を手札 (search_top_n)
  OP10-079 神誅殺 = メイン 相手コスト5以下1枚KO + ドン+1 / トリガー ドン+1
  OP10-080 小熊玩具 = カウンター 自リーダーかキャラ+4000 その後 ドン7以上&手札5以下なら1ドロー
  OP10-081 ウソップ = 登場時 ドレスローザleader/stageレスト：相手コスト2以下1枚KO + 上2枚トラッシュ
  OP10-082 クザン = 起動メイン 自身トラッシュ：1ドロー その後 トラッシュから黒ひげ海賊団cost5以下を登場
  OP10-083 モモの助 = 起動メイン 自身+ドレスローザleader/stageレスト：相手キャラ1枚をコスト-2

目的 (= test_backfill_auto_001〜105.py と同一方針):
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
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
    try_replace_ko,
)

ROOT = Path(__file__).resolve().parent.parent

_LEADER_GREEN = "OP01-001"       # ロロノア・ゾロ (leader、 汎用 = 特徴なし)
_LEADER_DRESSROSA = "EB01-040"   # キュロス (leader、 ドレスローザ)
_LEADER_DONQ = "OP14-060"        # ドフラミンゴ (leader、 ドンキホーテ海賊団)
_FILLER = "ST01-004"             # サンジ cost2 power4000 (バニラ、 埋め用/相手キャラ)
_DONQ_CHARA = "OP03-079"         # ヴェルゴ cost5 ドンキホーテ海賊団 (play_from_hand 対象)
_DONQ_CHARA2 = "OP05-036"        # モネ cost3 ドンキホーテ海賊団 (play_from_hand 第2候補)
_KUROHIGE_CHARA = "OP09-086"     # ジーザス・バージェス cost4 黒ひげ海賊団 (play_from_trash 対象)
_COST1_CHARA = "EB04-002"        # ジュエリー・ボニー cost1 (コスト≤2 KO 対象)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(_FILLER)] * 30
    p1.deck = [repo.get(_FILLER)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _eff(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果 (dict) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave106_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP10-071", "OP10-074", "OP10-076", "OP10-077", "OP10-078",
           "OP10-079", "OP10-080", "OP10-081", "OP10-082", "OP10-083"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP10-071 ドンキホーテ・ドフラミンゴ (CHARACTER 紫): 【登場時】ドン‼-1：自分の手札から
#          コスト5以下の特徴《ドンキホーテ海賊団》キャラ1枚までを登場させる。
#          【相手のアタック時】【ターン1回】自分のドン1枚をレスト：ドンデッキからドン1アクティブ追加。
# --------------------------------------------------------------------------- #
def test_op10_071_on_play_summon_donq_chara_from_hand_ai():
    """【登場時】手札のコスト5以下ドンキホーテ海賊団キャラを登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DONQ, overlay)
    me, opp = st.players[0], st.players[1]
    dofla = InPlay.of(repo.get("OP10-071"), sickness=True)
    me.characters = [dofla]
    me.hand = [repo.get(_DONQ_CHARA)]  # ヴェルゴ cost5 ドンキホーテ海賊団

    for prim in _eff(overlay, "OP10-071", "on_play")["do"]:
        execute_effect(prim, st, me, opp, dofla)
        _drain(st, [0])

    assert any(c.card.card_id == _DONQ_CHARA for c in me.characters), \
        "手札のコスト5以下ドンキホーテ海賊団キャラが登場していない"
    assert not any(c.card_id == _DONQ_CHARA for c in me.hand), \
        "登場したキャラは手札から取り除かれるべき"


def test_op10_071_on_play_human_play_from_hand_pick():
    """人間 + 複数候補 → play_from_hand_pick modal が立ち、 選んだキャラを登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DONQ, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    dofla = InPlay.of(repo.get("OP10-071"), sickness=True)
    me.characters = [dofla]
    me.hand = [repo.get(_DONQ_CHARA), repo.get(_DONQ_CHARA2)]  # 候補 2 枚

    execute_effect(_eff(overlay, "OP10-071", "on_play")["do"][0], st, me, opp, dofla)
    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand_pick modal が立たない"
    assert st.pending_choice.get("kind") == "play_from_hand_pick", \
        f"kind が play_from_hand_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2枚でない: {len(cands)}"
    ci = next(i for i, c in enumerate(cands) if c["card_id"] == _DONQ_CHARA2)
    resolve_pending_choice(st, [ci])
    _drain(st, [0])
    assert any(c.card.card_id == _DONQ_CHARA2 for c in me.characters), \
        "人間が選んだキャラが登場していない"
    assert any(c.card_id == _DONQ_CHARA for c in me.hand), \
        "選ばなかったキャラは手札に残るべき"


def test_op10_071_opp_attack_add_don_ai():
    """【相手のアタック時】ドンデッキからドン1アクティブ追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DONQ, overlay)
    me, opp = st.players[0], st.players[1]
    dofla = InPlay.of(repo.get("OP10-071"), sickness=False)
    me.characters = [dofla]
    me.don_active = 0
    me.don_remaining_in_deck = 5
    before = me.don_active

    for prim in _eff(overlay, "OP10-071", "opp_attack")["do"]:
        execute_effect(prim, st, me, opp, dofla)
        _drain(st, [0])

    assert me.don_active == before + 1, "ドンデッキからアクティブドンが1枚追加されていない"
    assert me.don_remaining_in_deck == 4, "ドンデッキが1枚減るべき"


# --------------------------------------------------------------------------- #
#  OP10-074 ピーカ (CHARACTER 紫): 【ターン1回】このキャラが相手の効果でKOされる場合、
#          代わりに自分のアクティブのドン2枚をレストにできる。 (replace_ko)
# --------------------------------------------------------------------------- #
def test_op10_074_replace_ko_rest_2_don_instead_ai():
    """相手効果KO の代わりに アクティブドン2枚をレスト → 場に残る (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    piika = InPlay.of(repo.get("OP10-074"), sickness=False)
    me.characters = [piika]
    me.don_active = 3
    me.don_rested = 0

    fired = try_replace_ko(st, me, opp, piika, overlay, by_opp_effect=True)

    assert fired is True, "replace_ko が発動していない"
    assert piika in me.characters, "KO 代替で ピーカ は場に残るべき"
    assert me.don_active == 1 and me.don_rested == 2, \
        f"アクティブドン2枚がレストされるべき: active={me.don_active} rested={me.don_rested}"


def test_op10_074_replace_ko_not_by_opp_effect_no_fire():
    """相手効果でない離脱 (by_opp_effect=False) では replace_ko は発動しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    piika = InPlay.of(repo.get("OP10-074"), sickness=False)
    me.characters = [piika]
    me.don_active = 3

    fired = try_replace_ko(st, me, opp, piika, overlay, by_opp_effect=False)
    assert fired is False, "自効果/戦闘KO では replace_ko は発動しないべき"
    assert me.don_active == 3, "発動しない場合ドンはレストされない"


# --------------------------------------------------------------------------- #
#  OP10-076 ベビー5 (CHARACTER 紫): 【登場時】自分の手札1枚を捨てることができる：自分の
#          リーダーが特徴《ドンキホーテ海賊団》を持つ場合、ドンデッキからドン1アクティブ追加。
# --------------------------------------------------------------------------- #
def test_op10_076_on_play_discard_for_add_don_ai():
    """【登場時】手札1枚捨てて ドン+1 (AI 自動、 ドンキホーテ海賊団 leader 前提)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DONQ, overlay)
    me, opp = st.players[0], st.players[1]
    baby = InPlay.of(repo.get("OP10-076"), sickness=True)
    me.characters = [baby]
    me.hand = [repo.get(_FILLER)]  # 捨てる元手
    me.don_active = 0
    me.don_remaining_in_deck = 5

    for prim in _eff(overlay, "OP10-076", "on_play")["do"]:
        execute_effect(prim, st, me, opp, baby)
        _drain(st, [1])

    assert me.don_active == 1, "手札を捨ててアクティブドンが1枚追加されるべき"
    assert len(me.hand) == 0, "任意コストで手札1枚が捨てられるべき"


def test_op10_076_on_play_human_optional_cost_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、 承諾で発動する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DONQ, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    baby = InPlay.of(repo.get("OP10-076"), sickness=True)
    me.characters = [baby]
    me.hand = [repo.get(_FILLER)]
    me.don_active = 0
    me.don_remaining_in_deck = 5

    execute_effect(_eff(overlay, "OP10-076", "on_play")["do"][0], st, me, opp, baby)
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [1])
    assert me.don_active == 1, "承諾後 ドン+1 されるべき"
    assert len(me.hand) == 0, "承諾後 手札1枚が捨てられるべき"


# --------------------------------------------------------------------------- #
#  OP10-077 ベラミー (CHARACTER 紫): 【ブロッカー】【ブロック時】自分のドン2枚をレストできる：
#          ドンデッキからドン1アクティブ追加。 (add_don)
# --------------------------------------------------------------------------- #
def test_op10_077_on_block_add_don_ai():
    """【ブロック時】ドンデッキからドン1アクティブ追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    bella = InPlay.of(repo.get("OP10-077"), sickness=False)
    me.characters = [bella]
    me.don_active = 2
    me.don_remaining_in_deck = 5

    for prim in _eff(overlay, "OP10-077", "on_block")["do"]:
        execute_effect(prim, st, me, opp, bella)
        _drain(st, [0])

    assert me.don_active == 3, "ブロック時にアクティブドンが1枚追加されるべき"
    assert me.don_remaining_in_deck == 4, "ドンデッキが1枚減るべき"


# --------------------------------------------------------------------------- #
#  OP10-078 家族を笑う者はおれが許さん…!!! (EVENT 紫): 【メイン】/【カウンター】自分の
#          デッキの上から3枚を見て、「家族を笑う者は…」以外の特徴《ドンキホーテ海賊団》
#          カード1枚までを公開し手札に加える。その後、残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op10_078_main_search_donq_to_hand_ai():
    """【メイン】上3枚から自身以外のドンキホーテ海賊団カード1枚を手札へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_DONQ_CHARA)] + [repo.get(_FILLER)] * 14

    for prim in _eff(overlay, "OP10-078", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])

    assert any(c.card_id == _DONQ_CHARA for c in me.hand), \
        f"上3枚からドンキホーテ海賊団カードが手札に加わっていない: {[c.card_id for c in me.hand]}"


def test_op10_078_counter_search_donq_human_modal():
    """人間 + 該当候補 → search_top_n modal が立ち、 resolve で手札へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_DONQ_CHARA)] + [repo.get(_FILLER)] * 14

    execute_effect(_eff(overlay, "OP10-078", "counter")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 該当候補で search_top_n modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    # seen の idx=0 (= ドンキホーテ海賊団) を選ぶ
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert any(c.card_id == _DONQ_CHARA for c in me.hand), \
        "人間が選んだドンキホーテ海賊団カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP10-079 神誅殺 (EVENT 紫): 【メイン】相手のコスト5以下のキャラ1枚までをKOする。
#          その後、ドンデッキからドン1アクティブ追加。 【トリガー】ドン1アクティブ追加。
# --------------------------------------------------------------------------- #
def test_op10_079_main_ko_opp_cost_le5_then_add_don_ai():
    """【メイン】相手コスト5以下1枚KO + ドン+1 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_DONQ_CHARA), sickness=False)  # cost5 (<=5)
    opp.characters = [victim]
    me.don_active = 0
    me.don_remaining_in_deck = 5

    for prim in _eff(overlay, "OP10-079", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])

    assert victim not in opp.characters, "相手のコスト5以下キャラがKOされていない"
    assert any(c.card_id == _DONQ_CHARA for c in opp.trash), \
        "KOされたキャラは持ち主のトラッシュに置かれるべき"
    assert me.don_active == 1, "KO後 ドン+1 されるべき"


def test_op10_079_main_human_target_pick():
    """人間 + 複数候補 → target_pick modal が立ち、 選んだキャラをKO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)      # cost2 (<=5)
    b = InPlay.of(repo.get(_DONQ_CHARA), sickness=False)  # cost5 (<=5)
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP10-079", "main")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    bi = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [bi])
    _drain(st, [bi])
    assert b not in opp.characters, "人間が選んだキャラがKOされていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


def test_op10_079_trigger_add_don_ai():
    """【トリガー】ドンデッキからドン1アクティブ追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 0
    me.don_remaining_in_deck = 5

    for prim in _eff(overlay, "OP10-079", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])

    assert me.don_active == 1, "トリガーで ドン+1 されるべき"


# --------------------------------------------------------------------------- #
#  OP10-080 小熊玩具 (EVENT 紫): 【カウンター】自分のリーダーかキャラ1枚までを、このバトル中、
#          パワー+4000。その後、自分の場のドンが7枚以上でかつ手札が5枚以下の場合、1ドロー。
# --------------------------------------------------------------------------- #
def test_op10_080_counter_power_pump_4000_ai():
    """【カウンター】自リーダーかキャラ1枚に このバトル中 パワー+4000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = []  # 候補を leader のみに絞る
    before = me.leader.power

    execute_effect(_eff(overlay, "OP10-080", "counter")["do"][0], st, me, opp, None)
    _drain(st, [0])

    assert me.leader.power == before + 4000, \
        f"自リーダーが このバトル中 +4000 されるべき: {before} → {me.leader.power}"


def test_op10_080_counter_conditional_draw_when_don7_hand_le5_ai():
    """その後 ドン7以上 & 手札5以下 の条件付き1ドロー (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 7          # 場のドン7枚以上
    me.hand = [repo.get(_FILLER)] * 3  # 手札5枚以下
    deck_before = len(me.deck)
    hand_before = len(me.hand)

    for prim in _eff(overlay, "OP10-080", "counter")["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])

    assert len(me.hand) == hand_before + 1, "条件成立時に1ドローされるべき"
    assert len(me.deck) == deck_before - 1, "ドローでデッキが1枚減るべき"


def test_op10_080_counter_no_draw_when_don_insufficient_ai():
    """ドン7未満なら条件不成立 → ドローしない (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3          # 7 未満
    me.hand = [repo.get(_FILLER)] * 3
    hand_before = len(me.hand)

    for prim in _eff(overlay, "OP10-080", "counter")["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])

    assert len(me.hand) == hand_before, "ドン7未満では条件付きドローは起きないべき"


# --------------------------------------------------------------------------- #
#  OP10-081 ウソップ (CHARACTER 黒): 【登場時】自分の特徴《ドレスローザ》を持つ、リーダーか
#          ステージ1枚をレストにできる：相手のコスト2以下のキャラ1枚までをKOする。
#          その後、自分のデッキの上から2枚をトラッシュに置く。
# --------------------------------------------------------------------------- #
def test_op10_081_on_play_ko_opp_cost_le2_and_mill_ai():
    """【登場時】ドレスローザleaderレスト → 相手コスト2以下1枚KO + 上2枚トラッシュ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DRESSROSA, overlay)  # ドレスローザ leader
    me, opp = st.players[0], st.players[1]
    usopp = InPlay.of(repo.get("OP10-081"), sickness=True)
    me.characters = [usopp]
    me.deck = [repo.get(_FILLER)] * 10
    victim = InPlay.of(repo.get(_COST1_CHARA), sickness=False)  # cost1 (<=2)
    opp.characters = [victim]
    trash_before = len(me.trash)

    assert me.leader.rested is False
    for prim in _eff(overlay, "OP10-081", "on_play")["do"]:
        execute_effect(prim, st, me, opp, usopp)
        _drain(st, [0])

    assert me.leader.rested is True, "コストで ドレスローザ leader がレストされるべき"
    assert victim not in opp.characters, "相手のコスト2以下キャラがKOされていない"
    assert len(me.trash) == trash_before + 2, "上2枚がトラッシュに置かれるべき"


def test_op10_081_on_play_human_optional_cost_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、 承諾で発動する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DRESSROSA, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    usopp = InPlay.of(repo.get("OP10-081"), sickness=True)
    me.characters = [usopp]
    me.deck = [repo.get(_FILLER)] * 10
    victim = InPlay.of(repo.get(_COST1_CHARA), sickness=False)  # 単一候補 (= target 自動)
    opp.characters = [victim]

    execute_effect(_eff(overlay, "OP10-081", "on_play")["do"][0], st, me, opp, usopp)
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert me.leader.rested is True, "承諾後 ドレスローザ leader がレストされるべき"
    assert victim not in opp.characters, "承諾後 相手のコスト2以下キャラがKOされるべき"


# --------------------------------------------------------------------------- #
#  OP10-082 クザン (CHARACTER 黒): 【起動メイン】このキャラをトラッシュに置くことができる：
#          1ドロー。その後、自分のトラッシュから「クザン」以外のコスト5以下の
#          特徴《黒ひげ海賊団》キャラ1枚までを登場させる。
# --------------------------------------------------------------------------- #
def test_op10_082_activate_main_draw_and_play_from_trash_ai():
    """【起動メイン】1ドロー + トラッシュから黒ひげ海賊団cost5以下を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    kuzan = InPlay.of(repo.get("OP10-082"), sickness=False)
    me.characters = [kuzan]
    me.hand = []
    me.trash = [repo.get(_KUROHIGE_CHARA)]  # ジーザス cost4 黒ひげ海賊団
    deck_before = len(me.deck)

    for prim in _eff(overlay, "OP10-082", "activate_main")["do"]:
        execute_effect(prim, st, me, opp, kuzan)
        _drain(st, [0])

    assert len(me.hand) == 1 and len(me.deck) == deck_before - 1, "1ドローが起きていない"
    assert any(c.card.card_id == _KUROHIGE_CHARA for c in me.characters), \
        "トラッシュから黒ひげ海賊団キャラが登場していない"
    assert not any(c.card_id == _KUROHIGE_CHARA for c in me.trash), \
        "登場したキャラはトラッシュから取り除かれるべき"


# --------------------------------------------------------------------------- #
#  OP10-083 光月モモの助 (CHARACTER 黒): 【起動メイン】このキャラと自分の特徴《ドレスローザ》
#          を持つ、リーダーかステージ1枚をレストにできる：相手のキャラ1枚までを、
#          このターン中、コスト-2。
# --------------------------------------------------------------------------- #
def test_op10_083_activate_main_cost_minus_opp_ai():
    """【起動メイン】自身+ドレスローザleaderレスト → 相手キャラ1枚をコスト-2 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DRESSROSA, overlay)
    me, opp = st.players[0], st.players[1]
    momo = InPlay.of(repo.get("OP10-083"), sickness=False)
    me.characters = [momo]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]

    assert me.leader.rested is False and momo.rested is False
    for prim in _eff(overlay, "OP10-083", "activate_main")["do"]:
        execute_effect(prim, st, me, opp, momo)
        _drain(st, [0])

    assert momo.rested is True, "コストで このキャラ (モモの助) がレストされるべき"
    assert me.leader.rested is True, "コストで ドレスローザ leader がレストされるべき"
    assert victim.cost_minus_until_turn_end >= 2, \
        f"相手キャラが このターン中 コスト-2 されるべき: {victim.cost_minus_until_turn_end}"


def test_op10_083_activate_main_human_optional_cost_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、 承諾で発動する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DRESSROSA, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    momo = InPlay.of(repo.get("OP10-083"), sickness=False)
    me.characters = [momo]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # 単一候補
    opp.characters = [victim]

    execute_effect(_eff(overlay, "OP10-083", "activate_main")["do"][0], st, me, opp, momo)
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert momo.rested is True and me.leader.rested is True, \
        "承諾後 モモの助 と ドレスローザ leader がレストされるべき"
    assert victim.cost_minus_until_turn_end >= 2, "承諾後 相手キャラがコスト-2されるべき"
