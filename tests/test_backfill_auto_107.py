# -*- coding: utf-8 -*-
"""OP10 弾 黒 (黒ひげ海賊団・ドレスローザ・スリラーバーク海賊団) 効果 回帰テスト
バックフィル (自動生成 wave 107):
OP10-085 / OP10-086 / OP10-087 / OP10-088 / OP10-090 /
OP10-091 / OP10-092 / OP10-093 / OP10-094 / OP10-095 の 10 枚。

  OP10-085 ジーザス・バージェス = ドン1 & 自トラッシュ8枚以上なら 自身に【速攻】(静的 give_keyword)
  OP10-086 シリュウ = 相手ターン中 自身+2000 (静的) / 起動メイン 黒ひげleader&登場ターンで
     相手コスト3以下1枚KO
  OP10-087 チョッパー = 起動メイン 自身+ドレスローザleader/stageレスト：相手手札5枚以上なら
     相手が手札1枚捨てる その後 上2枚トラッシュ
  OP10-088 ナミ = 起動メイン 自身+ドレスローザleader/stageレスト：1ドロー その後 上2枚トラッシュ
  OP10-090 フランキー = ブロッカー / KO時 トラッシュからコスト3以下ドレスローザキャラ1枚を
     レストで登場 (play_from_trash)
  OP10-091 ブルック = 起動メイン 自身+ドレスローザleader/stageレスト：相手コスト1以下1枚KO
     その後 上2枚トラッシュ
  OP10-092 ペローナ = 起動メイン(ターン1回) トラッシュのスリラーバーク海賊団2枚をデッキ下：
     ペローナ以外の自キャラ1枚を このターン中 +2000
  OP10-093 ホーミング聖 = 起動メイン 自身をトラッシュ：自分の黒のキャラ1枚を
     次の相手ターン終了時まで コスト+3 (set_base_cost_timed)
  OP10-094 リューマ = ドン1で 自身に【ダブルアタック】(静的 give_keyword)
  OP10-095 ロロノア・ゾロ = 登場時 ドレスローザleader/stageレスト：相手コスト4以下1枚KO
     その後 上2枚トラッシュ

目的 (= test_backfill_auto_001〜106.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 任意コスト を 持つカードは 人間 actor で pending_choice が
      正しい kind + 候補で立ち、 resolve_pending_choice で解決できる (= 人間が選べる)
  (3) 同じ効果を AI 文脈 (human_player_idx=None) で回しても crash せず自動解決する
      (= AI が選べる)

注記: OP10-085/094 は カードテキストに【速攻】/【ダブルアタック】が印字されるため
  CardDef.has_keyword は 常に True を返す (= 条件を判定できない)。 本テストは 静的付与
  経路 (InPlay.static_granted_keywords) を直接 assert し、 ドン数/トラッシュ数 の条件で
  付与が ON/OFF することを担保する。
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

_LEADER_GREEN = "OP01-001"       # ロロノア・ゾロ (leader、 汎用 = 特徴なし)
_LEADER_DRESSROSA = "EB01-040"   # キュロス (leader、 ドレスローザ)
_LEADER_KUROHIGE = "OP09-081"    # マーシャル・D・ティーチ (leader、 黒ひげ海賊団)
_FILLER = "ST01-004"             # サンジ cost2 power4000 (バニラ、 埋め用/相手キャラ)
_DRESS_COST1 = "OP15-040"        # ヴィオラ cost1 ドレスローザ (play_from_trash 対象)
_SB_CARD1 = "PRB02-013"          # ゲッコー・モリア (スリラーバーク海賊団、 コスト用)
_SB_CARD2 = "EB03-045"           # ペローナ (スリラーバーク海賊団、 コスト用)
_BLACK_CHARA = "OP10-085"        # ジーザス cost5 黒 (set_base_cost_timed 対象)
_COST1_CHARA = "EB04-002"        # ジュエリー・ボニー cost1 (コスト≤1 KO 対象)


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
def test_all_wave107_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP10-085", "OP10-086", "OP10-087", "OP10-088", "OP10-090",
           "OP10-091", "OP10-092", "OP10-093", "OP10-094", "OP10-095"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP10-085 ジーザス・バージェス (CHARACTER 黒): 【ドン‼×1】自分のトラッシュが8枚以上ある
#          場合、このキャラは【速攻】を得る。 (静的 give_keyword、 条件付き)
# --------------------------------------------------------------------------- #
def _burgess_static(repo, overlay, dons, trash):
    st = _state(repo, _LEADER_GREEN, overlay)
    me, _ = st.players
    c = InPlay.of(repo.get("OP10-085"), sickness=False)
    c.attached_dons = dons
    me.characters = [c]
    me.trash = [repo.get(_FILLER)] * trash
    evaluate_static_effects(st, overlay)
    return c


def test_op10_085_grants_rush_when_don1_and_trash8():
    """ドン1付与 & 自トラッシュ8枚以上 → 静的付与経路で【速攻】が付く。"""
    repo = _repo()
    overlay = _overlay()
    c = _burgess_static(repo, overlay, dons=1, trash=8)
    assert "速攻" in c.static_granted_keywords, \
        "ドン1 & トラッシュ8枚で【速攻】が静的付与されていない"


def test_op10_085_no_rush_when_trash_below_8():
    """自トラッシュ7枚以下では 条件不成立 → 静的付与されない。"""
    repo = _repo()
    overlay = _overlay()
    c = _burgess_static(repo, overlay, dons=1, trash=3)
    assert "速攻" not in c.static_granted_keywords, \
        "トラッシュ8枚未満で【速攻】が付与されてはいけない"


def test_op10_085_no_rush_when_no_don():
    """ドンが付いていなければ (attached_dons=0) 条件不成立 → 静的付与されない。"""
    repo = _repo()
    overlay = _overlay()
    c = _burgess_static(repo, overlay, dons=0, trash=8)
    assert "速攻" not in c.static_granted_keywords, \
        "ドン0で【速攻】が付与されてはいけない"


# --------------------------------------------------------------------------- #
#  OP10-086 シリュウ (CHARACTER 黒): 【相手のターン中】このキャラのパワー+2000。
#          【起動メイン】【ターン1回】自リーダーが特徴《黒ひげ海賊団》を持ち、このキャラが
#          登場したターンの場合、相手の元々のコスト3以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op10_086_static_pump_2000_on_opp_turn():
    """相手ターン中は 自身+2000 (静的)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_KUROHIGE, overlay)
    me, _ = st.players
    shiryu = InPlay.of(repo.get("OP10-086"), sickness=False)  # power 5000
    me.characters = [shiryu]
    st.turn_player_idx = 1  # 相手ターン → 条件成立
    evaluate_static_effects(st, overlay)
    assert shiryu.power == shiryu.card.power + 2000, \
        f"相手ターン中に +2000 されるべき: {shiryu.power} (base {shiryu.card.power})"


def test_op10_086_no_static_pump_on_self_turn():
    """自ターン中は【相手のターン中】条件が不成立 → +0。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_KUROHIGE, overlay)
    me, _ = st.players
    shiryu = InPlay.of(repo.get("OP10-086"), sickness=False)
    me.characters = [shiryu]
    st.turn_player_idx = 0  # 自ターン → 条件不成立
    evaluate_static_effects(st, overlay)
    assert shiryu.power == shiryu.card.power, \
        f"自ターン中は +2000 が乗ってはいけない: {shiryu.power} (base {shiryu.card.power})"


def test_op10_086_activate_main_ko_opp_cost_le3_ai():
    """【起動メイン】相手のコスト3以下キャラ1枚をKO (AI、 黒ひげ leader & 登場ターン)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_KUROHIGE, overlay)
    me, opp = st.players
    shiryu = InPlay.of(repo.get("OP10-086"), sickness=True)  # 登場ターン
    me.characters = [shiryu]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (<=3)
    opp.characters = [victim]

    for prim in _eff(overlay, "OP10-086", "activate_main")["do"]:
        execute_effect(prim, st, me, opp, shiryu)
        _drain(st, [0])

    assert victim not in opp.characters, "相手のコスト3以下キャラがKOされていない"
    assert any(c.card_id == _FILLER for c in opp.trash), \
        "KOされたキャラは持ち主のトラッシュに置かれるべき"


def test_op10_086_activate_main_human_target_pick():
    """人間 + 相手コスト3以下 複数 → target_pick modal が立ち、 選んだキャラをKO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_KUROHIGE, overlay, human_idx=0)
    me, opp = st.players
    shiryu = InPlay.of(repo.get("OP10-086"), sickness=True)
    me.characters = [shiryu]
    a = InPlay.of(repo.get(_FILLER), sickness=False)       # cost2
    b = InPlay.of(repo.get(_COST1_CHARA), sickness=False)  # cost1
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP10-086", "activate_main")["do"][0], st, me, opp, shiryu)
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


# --------------------------------------------------------------------------- #
#  OP10-087 トニートニー・チョッパー (CHARACTER 黒): 【起動メイン】このキャラと自分の特徴
#          《ドレスローザ》を持つ、リーダーかステージ1枚を、レストにできる：相手の手札が
#          5枚以上ある場合、相手は自身の手札1枚を捨てる。その後、自分のデッキの上から
#          2枚をトラッシュに置く。
# --------------------------------------------------------------------------- #
def test_op10_087_activate_main_opp_discard_and_mill_ai():
    """【起動メイン】自身+ドレスローザleaderレスト → 相手手札1枚捨て + 上2枚トラッシュ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DRESSROSA, overlay)
    me, opp = st.players
    chopper = InPlay.of(repo.get("OP10-087"), sickness=False)
    me.characters = [chopper]
    me.deck = [repo.get(_FILLER)] * 10
    opp.hand = [repo.get(_FILLER)] * 5  # 5枚以上 = 条件成立
    trash_before = len(me.trash)
    opp_hand_before = len(opp.hand)

    for prim in _eff(overlay, "OP10-087", "activate_main")["do"]:
        execute_effect(prim, st, me, opp, chopper)
        _drain(st, [0])

    assert chopper.rested is True, "コストで このキャラ (チョッパー) がレストされるべき"
    assert me.leader.rested is True, "コストで ドレスローザ leader がレストされるべき"
    assert len(opp.hand) == opp_hand_before - 1, "相手が手札1枚を捨てるべき"
    assert len(me.trash) == trash_before + 2, "その後 上2枚がトラッシュに置かれるべき"


def test_op10_087_activate_main_no_discard_when_opp_hand_lt5_ai():
    """相手手札4枚以下では 条件「相手の手札が5枚以上ある場合」が不成立 → 相手手札は減らず、
    **その後のミル(上2枚トラッシュ)も起きない**。

    公式 cardqa_op_10 (670c9ed2c408): 「相手の手札が4枚以下の場合、この【起動メイン】効果で
    自分のデッキの上から2枚をトラッシュに置くことはできますか？」→「いいえ、できません」。
    カードテキスト「相手の手札が5枚以上ある場合、相手は…捨てる。その後、上2枚をトラッシュ」の
    条件節は **その後のミルまで** gate する。
    ⚠ 2026-08-09 是正前は mill_self_top が conditional の外にあり、 本テストも旧バグ
      (「条件に関わらず 上2枚トラッシュ」) を正解として固定していた → 公式に合わせ書き換え。
    """
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DRESSROSA, overlay)
    me, opp = st.players
    chopper = InPlay.of(repo.get("OP10-087"), sickness=False)
    me.characters = [chopper]
    me.deck = [repo.get(_FILLER)] * 10
    opp.hand = [repo.get(_FILLER)] * 4  # 5枚未満 = 条件不成立
    trash_before = len(me.trash)
    opp_hand_before = len(opp.hand)

    for prim in _eff(overlay, "OP10-087", "activate_main")["do"]:
        execute_effect(prim, st, me, opp, chopper)
        _drain(st, [0])

    assert len(opp.hand) == opp_hand_before, "相手手札5枚未満では 相手は手札を捨てないべき"
    assert len(me.trash) == trash_before, \
        "相手手札5枚未満では 条件不成立で その後のミル(上2枚トラッシュ)も起きないべき (cardqa_op_10)"


def test_op10_087_activate_main_human_optional_cost_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、 承諾で発動する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DRESSROSA, overlay, human_idx=0)
    me, opp = st.players
    chopper = InPlay.of(repo.get("OP10-087"), sickness=False)
    me.characters = [chopper]
    me.deck = [repo.get(_FILLER)] * 10
    opp.hand = [repo.get(_FILLER)] * 5

    execute_effect(_eff(overlay, "OP10-087", "activate_main")["do"][0], st, me, opp, chopper)
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert chopper.rested is True and me.leader.rested is True, \
        "承諾後 チョッパー と ドレスローザ leader がレストされるべき"


# --------------------------------------------------------------------------- #
#  OP10-088 ナミ (CHARACTER 黒): 【起動メイン】このキャラと自分の特徴《ドレスローザ》を持つ、
#          リーダーかステージ1枚を、レストにできる：カード1枚を引く。その後、自分のデッキの
#          上から2枚をトラッシュに置く。
# --------------------------------------------------------------------------- #
def test_op10_088_activate_main_draw_and_mill_ai():
    """【起動メイン】自身+ドレスローザleaderレスト → 1ドロー + 上2枚トラッシュ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DRESSROSA, overlay)
    me, opp = st.players
    nami = InPlay.of(repo.get("OP10-088"), sickness=False)
    me.characters = [nami]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 10
    trash_before = len(me.trash)
    deck_before = len(me.deck)

    for prim in _eff(overlay, "OP10-088", "activate_main")["do"]:
        execute_effect(prim, st, me, opp, nami)
        _drain(st, [0])

    assert len(me.hand) == 1, "起動メインで 1ドローされるべき"
    assert len(me.trash) == trash_before + 2, "その後 上2枚がトラッシュに置かれるべき"
    # デッキ: -1 (ドロー) -2 (トラッシュ) = -3
    assert len(me.deck) == deck_before - 3, "デッキが ドロー1 + トラッシュ2 = 3枚減るべき"
    assert nami.rested is True and me.leader.rested is True, \
        "コストで ナミ と ドレスローザ leader がレストされるべき"


def test_op10_088_activate_main_human_optional_cost_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、 承諾で 1ドロー。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DRESSROSA, overlay, human_idx=0)
    me, opp = st.players
    nami = InPlay.of(repo.get("OP10-088"), sickness=False)
    me.characters = [nami]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 10

    execute_effect(_eff(overlay, "OP10-088", "activate_main")["do"][0], st, me, opp, nami)
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert len(me.hand) == 1, "承諾後 1ドローされるべき"
    assert nami.rested is True and me.leader.rested is True, \
        "承諾後 ナミ と ドレスローザ leader がレストされるべき"


# --------------------------------------------------------------------------- #
#  OP10-090 フランキー (CHARACTER 黒): 【ブロッカー】【KO時】自分のトラッシュからコスト3以下の
#          特徴《ドレスローザ》を持つキャラカード1枚までを、レストで登場させる。
# --------------------------------------------------------------------------- #
def test_op10_090_on_ko_play_dress_from_trash_rested_ai():
    """【KO時】トラッシュからコスト3以下ドレスローザキャラを レストで登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DRESSROSA, overlay)
    me, opp = st.players
    franky = InPlay.of(repo.get("OP10-090"), sickness=False)
    me.characters = [franky]
    me.trash = [repo.get(_DRESS_COST1)]  # ヴィオラ cost1 ドレスローザ

    for prim in _eff(overlay, "OP10-090", "on_ko")["do"]:
        execute_effect(prim, st, me, opp, franky)
        _drain(st, [0])

    played = [c for c in me.characters if c.card.card_id == _DRESS_COST1]
    assert played, "トラッシュからコスト3以下ドレスローザキャラが登場していない"
    assert played[0].rested is True, "登場したキャラはレスト状態であるべき"
    assert not any(c.card_id == _DRESS_COST1 for c in me.trash), \
        "登場したキャラはトラッシュから取り除かれるべき"


# --------------------------------------------------------------------------- #
#  OP10-091 ブルック (CHARACTER 黒): 【起動メイン】このキャラと自分の特徴《ドレスローザ》を
#          持つ、リーダーかステージ1枚を、レストにできる：相手のコスト1以下のキャラ1枚までを、
#          KOする。その後、自分のデッキの上から2枚をトラッシュに置く。
# --------------------------------------------------------------------------- #
def test_op10_091_activate_main_ko_opp_cost_le1_and_mill_ai():
    """【起動メイン】自身+ドレスローザleaderレスト → 相手コスト1以下1枚KO + 上2枚トラッシュ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DRESSROSA, overlay)
    me, opp = st.players
    brook = InPlay.of(repo.get("OP10-091"), sickness=False)
    me.characters = [brook]
    me.deck = [repo.get(_FILLER)] * 10
    victim = InPlay.of(repo.get(_COST1_CHARA), sickness=False)  # cost1 (<=1)
    opp.characters = [victim]
    trash_before = len(me.trash)

    for prim in _eff(overlay, "OP10-091", "activate_main")["do"]:
        execute_effect(prim, st, me, opp, brook)
        _drain(st, [0])

    assert brook.rested is True and me.leader.rested is True, \
        "コストで ブルック と ドレスローザ leader がレストされるべき"
    assert victim not in opp.characters, "相手のコスト1以下キャラがKOされていない"
    assert len(me.trash) == trash_before + 2, "その後 上2枚がトラッシュに置かれるべき"


def test_op10_091_activate_main_human_optional_cost_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、 承諾で発動する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DRESSROSA, overlay, human_idx=0)
    me, opp = st.players
    brook = InPlay.of(repo.get("OP10-091"), sickness=False)
    me.characters = [brook]
    me.deck = [repo.get(_FILLER)] * 10
    victim = InPlay.of(repo.get(_COST1_CHARA), sickness=False)  # 単一候補
    opp.characters = [victim]

    execute_effect(_eff(overlay, "OP10-091", "activate_main")["do"][0], st, me, opp, brook)
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert brook.rested is True and me.leader.rested is True, \
        "承諾後 ブルック と ドレスローザ leader がレストされるべき"
    assert victim not in opp.characters, "承諾後 相手のコスト1以下キャラがKOされるべき"


# --------------------------------------------------------------------------- #
#  OP10-092 ペローナ (CHARACTER 黒): 【起動メイン】【ターン1回】自分のトラッシュから特徴
#          《スリラーバーク海賊団》を持つカード2枚を好きな順番でデッキの下に置くことができる：
#          自分の「ペローナ」以外のキャラ1枚までを、このターン中、パワー+2000。
# --------------------------------------------------------------------------- #
def test_op10_092_activate_main_pump_other_chara_ai():
    """【起動メイン】トラッシュのスリラーバーク海賊団2枚をデッキ下 → ペローナ以外の
    自キャラ1枚を +2000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players
    perona = InPlay.of(repo.get("OP10-092"), sickness=False)
    friend = InPlay.of(repo.get(_FILLER), sickness=False)  # power 4000 (ペローナ以外)
    me.characters = [perona, friend]
    me.trash = [repo.get(_SB_CARD1), repo.get(_SB_CARD2)]  # スリラーバーク海賊団 2枚
    power_before = friend.power
    deck_before = len(me.deck)

    for prim in _eff(overlay, "OP10-092", "activate_main")["do"]:
        execute_effect(prim, st, me, opp, perona)
        _drain(st, [0])

    assert friend.power == power_before + 2000, \
        f"ペローナ以外の自キャラが このターン中 +2000 されるべき: {friend.power} (before {power_before})"
    assert not any(c.card_id in (_SB_CARD1, _SB_CARD2) for c in me.trash), \
        "スリラーバーク海賊団2枚は トラッシュから取り除かれるべき"
    assert len(me.deck) == deck_before + 2, "コストの2枚が デッキの下に置かれるべき"


def test_op10_092_activate_main_human_optional_cost_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、 承諾で発動する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay, human_idx=0)
    me, opp = st.players
    perona = InPlay.of(repo.get("OP10-092"), sickness=False)
    friend = InPlay.of(repo.get(_FILLER), sickness=False)  # 単一の pump 候補
    me.characters = [perona, friend]
    me.trash = [repo.get(_SB_CARD1), repo.get(_SB_CARD2)]

    execute_effect(_eff(overlay, "OP10-092", "activate_main")["do"][0], st, me, opp, perona)
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    power_before = friend.power
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert friend.power == power_before + 2000, "承諾後 自キャラが +2000 されるべき"


# --------------------------------------------------------------------------- #
#  OP10-093 ホーミング聖 (CHARACTER 黒): 【起動メイン】このキャラをトラッシュに置くことが
#          できる：自分の黒のキャラ1枚までを、次の相手のターン終了時まで、コスト+3。
# --------------------------------------------------------------------------- #
def test_op10_093_activate_main_self_trash_and_cost_plus_ai():
    """【起動メイン】自身をトラッシュ (コスト) → 自分の黒キャラ1枚を コスト+3 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players
    homing = InPlay.of(repo.get("OP10-093"), sickness=False)
    friend = InPlay.of(repo.get(_BLACK_CHARA), sickness=False)  # 黒キャラ (cost5)
    me.characters = [homing, friend]
    base_cost = friend.card.cost

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP10-093"]
    assert len(opts) == 1, f"OP10-093 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert homing not in me.characters, "コストで ホーミング聖 がトラッシュに置かれるべき"
    assert any(c.card_id == "OP10-093" for c in me.trash), \
        "トラッシュに置かれた ホーミング聖 が トラッシュに存在するべき"
    assert friend.next_opp_turn_end_base_cost_override == base_cost + 3, \
        f"黒キャラが 次の相手ターン終了時まで コスト+3 されるべき: " \
        f"{friend.next_opp_turn_end_base_cost_override} (base {base_cost})"


def test_op10_093_activate_main_human_target_pick():
    """人間 + 自分の黒キャラ 複数 → コスト+3 の対象選択 target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay, human_idx=0)
    me, opp = st.players
    homing = InPlay.of(repo.get("OP10-093"), sickness=False)
    a = InPlay.of(repo.get(_BLACK_CHARA), sickness=False)     # 黒キャラ cost5
    b = InPlay.of(repo.get("OP10-090"), sickness=False)       # 黒キャラ (フランキー cost4)
    me.characters = [homing, a, b]

    # do (= set_base_cost_timed) を直接発火 → 対象選択 modal (コストは cost 節で別途)。
    # ⚠ do 単体発火では 自身トラッシュ コストを踏まないため、 ホーミング聖自身 (黒) も
    #    「自分の黒のキャラ」候補に含まれる (= a / b / homing の 3 件)。
    execute_effect(_eff(overlay, "OP10-093", "activate_main")["do"][0], st, me, opp, homing)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 3, f"候補 (黒キャラ3体) が 3 件でない: {len(cands)}"
    assert any(c["iid"] == b.instance_id for c in cands), "選択対象の黒キャラが候補にない"

    bi = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    base_cost = b.card.cost
    resolve_pending_choice(st, [bi])
    _drain(st, [0])
    assert b.next_opp_turn_end_base_cost_override == base_cost + 3, \
        "人間が選んだ黒キャラに コスト+3 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP10-094 リューマ (CHARACTER 黒): 【ドン‼×1】このキャラは【ダブルアタック】を得る。
#          (静的 give_keyword、 ドン条件付き)
# --------------------------------------------------------------------------- #
def _ryuma_static(repo, overlay, dons):
    st = _state(repo, _LEADER_GREEN, overlay)
    me, _ = st.players
    c = InPlay.of(repo.get("OP10-094"), sickness=False)
    c.attached_dons = dons
    me.characters = [c]
    evaluate_static_effects(st, overlay)
    return c


def test_op10_094_grants_double_attack_when_don1():
    """ドン1付与 → 静的付与経路で【ダブルアタック】が付く。"""
    repo = _repo()
    overlay = _overlay()
    c = _ryuma_static(repo, overlay, dons=1)
    assert "ダブルアタック" in c.static_granted_keywords, \
        "ドン1で【ダブルアタック】が静的付与されていない"


def test_op10_094_no_double_attack_when_no_don():
    """ドンが付いていなければ (attached_dons=0) 静的付与されない。"""
    repo = _repo()
    overlay = _overlay()
    c = _ryuma_static(repo, overlay, dons=0)
    assert "ダブルアタック" not in c.static_granted_keywords, \
        "ドン0で【ダブルアタック】が付与されてはいけない"


# --------------------------------------------------------------------------- #
#  OP10-095 ロロノア・ゾロ (CHARACTER 黒): 【登場時】自分の特徴《ドレスローザ》を持つ、
#          リーダーかステージ1枚を、レストにできる：相手のコスト4以下のキャラ1枚までを、
#          KOする。その後、自分のデッキの上から2枚をトラッシュに置く。
# --------------------------------------------------------------------------- #
def test_op10_095_on_play_ko_opp_cost_le4_and_mill_ai():
    """【登場時】ドレスローザleaderレスト → 相手コスト4以下1枚KO + 上2枚トラッシュ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DRESSROSA, overlay)
    me, opp = st.players
    zoro = InPlay.of(repo.get("OP10-095"), sickness=True)
    me.characters = [zoro]
    me.deck = [repo.get(_FILLER)] * 10
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (<=4)
    opp.characters = [victim]
    trash_before = len(me.trash)

    assert me.leader.rested is False
    for prim in _eff(overlay, "OP10-095", "on_play")["do"]:
        execute_effect(prim, st, me, opp, zoro)
        _drain(st, [0])

    assert me.leader.rested is True, "コストで ドレスローザ leader がレストされるべき"
    assert victim not in opp.characters, "相手のコスト4以下キャラがKOされていない"
    assert len(me.trash) == trash_before + 2, "その後 上2枚がトラッシュに置かれるべき"


def test_op10_095_on_play_human_optional_cost_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、 承諾で発動する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DRESSROSA, overlay, human_idx=0)
    me, opp = st.players
    zoro = InPlay.of(repo.get("OP10-095"), sickness=True)
    me.characters = [zoro]
    me.deck = [repo.get(_FILLER)] * 10
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # 単一候補
    opp.characters = [victim]

    execute_effect(_eff(overlay, "OP10-095", "on_play")["do"][0], st, me, opp, zoro)
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert me.leader.rested is True, "承諾後 ドレスローザ leader がレストされるべき"
    assert victim not in opp.characters, "承諾後 相手のコスト4以下キャラがKOされるべき"
