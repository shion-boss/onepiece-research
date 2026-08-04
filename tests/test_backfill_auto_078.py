# -*- coding: utf-8 -*-
"""OP07 弾 効果 回帰テスト バックフィル (自動生成 wave 078):
OP07-063 / OP07-065 / OP07-066 / OP07-068 / OP07-069 / OP07-070 /
OP07-072 / OP07-073 / OP07-074 / OP07-075 の 10 枚
(フォクシー海賊団 紫 「自ドン<=相手ドン」 ギミック中心 + 麦わらルフィ)。

目的 (= 永続的 pytest による担保、 test_backfill_auto_077.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 択一 を 持つカードは 人間 actor で pending_choice が
      正しい kind + 候補で立ち、 resolve_pending_choice で解決できる (= 人間が選べる)
  (3) 同じ効果を AI 文脈 (human_player_idx=None) で回しても crash せず自動解決する
      (= AI が選べる)
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    eval_all_conditions,
    eval_condition,
    execute_effect,
    evaluate_static_effects,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

_LEADER = "OP01-001"         # ロロノア・ゾロ (赤、 直接 execute_effect なので色は無関係)
_FOXY_LEADER = "OP07-059"    # フォクシー (特徴《フォクシー海賊団》を持つ leader)
_FILLER = "OP01-013"         # サンジ cost2 power3000 (汎用フィラー、 麦わら)
_FOXY_C1 = "OP07-065"        # ジーナ cost1 (フォクシー海賊団)
_FOXY_C2 = "OP07-066"        # トニートニー・チョッパー cost2 (動物/フォクシー海賊団)
_FOXY_C3 = "OP07-060"        # イトミミズ cost3 (フォクシー海賊団)
_PURPLE_4000 = "OP07-063"    # カポーティ cost3 power4000 紫 (フォクシー)
_OPP_C = "OP01-013"          # サンジ cost2 power3000 (相手キャラ、 cost<=6)
_OPP_C2 = "OP06-025"         # ケイミー cost1 (相手キャラ 2 体目)


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


def _eff(overlay, cid, when):
    """when 一致の効果 dict (do + if を含む) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    return matches[0]


def _do(overlay, cid, when):
    """指定 card_id の overlay から when 一致の効果の do (list) を返す。"""
    return _eff(overlay, cid, when)["do"]


def _drain(st, pick=0, guard=15):
    """pending_choice を pick で自動解決し切る (= 後続効果を流す)。"""
    g = 0
    while st.pending_choice is not None and g < guard:
        resolve_pending_choice(st, [pick])
        g += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave78_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP07-063", "OP07-065", "OP07-066", "OP07-068", "OP07-069",
           "OP07-070", "OP07-072", "OP07-073", "OP07-074", "OP07-075"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP07-063 カポーティ (CHARACTER 紫 cost3):
#    【登場時】ドン!!-1：自分のリーダーが特徴《フォクシー海賊団》を持つ場合、相手のコスト
#      6以下のキャラ1枚までは、次の相手のターン終了時までアタックできない。
# --------------------------------------------------------------------------- #
def test_op07_063_on_play_cannot_attack_ai():
    """登場時: 相手のコスト6以下キャラ1枚を 次の相手ターン終了時までアタック不能 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _FOXY_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_OPP_C), sickness=False)  # cost2 <= 6
    opp.characters = [victim]

    for prim in _do(overlay, "OP07-063", "on_play"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert victim.cannot_attack_through_opp_turn is True, \
        "相手のコスト6以下キャラにアタック不能 (next_opp_turn_end) が付いていない"


def test_op07_063_leader_feature_condition():
    """条件: リーダーが《フォクシー海賊団》で成立、 そうでなければ不成立。"""
    repo = _repo()
    overlay = _overlay()
    cond = _eff(overlay, "OP07-063", "on_play").get("if")
    assert cond is not None, "OP07-063 に leader_feature 条件がない"
    st_ok = _state(repo, _FOXY_LEADER, overlay)
    assert eval_condition(cond, st_ok, st_ok.players[0]) is True, \
        "フォクシー海賊団 leader で条件が成立するべき"
    st_ng = _state(repo, _LEADER, overlay)
    assert eval_condition(cond, st_ng, st_ng.players[0]) is False, \
        "フォクシー海賊団でない leader で条件が成立してはいけない"


def test_op07_063_on_play_human_pick():
    """登場時 (人間): 相手のコスト6以下が2体 → target_pick modal → 1体をアタック不能に。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _FOXY_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_OPP_C), sickness=False)   # cost2
    b = InPlay.of(repo.get(_OPP_C2), sickness=False)  # cost1
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP07-063", "on_play")[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b.cannot_attack_through_opp_turn is True, \
        "人間が選んだキャラにアタック不能が付いていない"
    assert a.cannot_attack_through_opp_turn is False, \
        "選ばなかったキャラはアタック可能のままであるべき"


# --------------------------------------------------------------------------- #
#  OP07-065 ジーナ (CHARACTER 紫 cost1):
#    【登場時】自分のリーダーが特徴《フォクシー海賊団》を持ち、自分の場のドン!!が相手の
#      場のドン!!の枚数以下の場合、ドン!!デッキからドン!!1枚までを、アクティブで追加する。
# --------------------------------------------------------------------------- #
def test_op07_065_on_play_add_active_don_ai():
    """登場時: ドンデッキからアクティブドン1枚を追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _FOXY_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 0
    me.don_remaining_in_deck = 5
    active_before = me.don_active
    deck_before = me.don_remaining_in_deck

    for prim in _do(overlay, "OP07-065", "on_play"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert me.don_active == active_before + 1, "アクティブドンが1枚追加されていない"
    assert me.don_remaining_in_deck == deck_before - 1, "ドンデッキから1枚減るべき"


def test_op07_065_conditions_leader_and_don_diff():
    """条件 (conditions 配列): フォクシー leader + 自ドン<=相手ドン の AND。"""
    repo = _repo()
    overlay = _overlay()
    eff = _eff(overlay, "OP07-065", "on_play")
    # (a) フォクシー leader + 自0<=相手0 → 成立
    st_ok = _state(repo, _FOXY_LEADER, overlay)
    assert eval_all_conditions(eff, st_ok, st_ok.players[0]) is True, \
        "フォクシー leader + 自ドン<=相手ドンで条件が成立するべき"
    # (b) フォクシーでない leader → 不成立
    st_ng = _state(repo, _LEADER, overlay)
    assert eval_all_conditions(eff, st_ng, st_ng.players[0]) is False, \
        "フォクシーでない leader で条件が成立してはいけない"
    # (c) フォクシー leader だが 自ドンが相手より多い → 不成立
    st_don = _state(repo, _FOXY_LEADER, overlay)
    st_don.players[0].don_active = 3
    assert eval_all_conditions(eff, st_don, st_don.players[0]) is False, \
        "自ドンが相手より多いと条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP07-066 トニートニー・チョッパー (CHARACTER 紫 cost2):
#    【ブロッカー】【登場時】自分の場のドン!!が相手の場のドン!!の枚数以下の場合、ドン!!
#      デッキからドン!!1枚までを、レストで追加する。
# --------------------------------------------------------------------------- #
def test_op07_066_on_play_add_rested_don_ai():
    """登場時: ドンデッキからレストドン1枚を追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 0
    me.don_remaining_in_deck = 5
    rested_before = me.don_rested
    deck_before = me.don_remaining_in_deck

    for prim in _do(overlay, "OP07-066", "on_play"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert me.don_rested == rested_before + 1, "レストドンが1枚追加されていない"
    assert me.don_remaining_in_deck == deck_before - 1, "ドンデッキから1枚減るべき"


def test_op07_066_don_diff_condition():
    """条件: 自ドン<=相手ドン で成立 (don_diff_le 0)、 自ドンが多いと不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me = st.players[0]
    cond = _eff(overlay, "OP07-066", "on_play").get("if")
    assert cond is not None, "OP07-066 に don_diff 条件がない"
    assert eval_condition(cond, st, me) is True, "自0<=相手0で条件が成立するべき"
    me.don_active = 2
    assert eval_condition(cond, st, me) is False, \
        "自ドンが相手より多いと条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP07-068 ハンバーグ (CHARACTER 紫 cost5):
#    【ドン‼×1】【アタック時】自分の場のドン!!が相手の場のドン!!の枚数以下の場合、
#      ドン!!デッキからドン!!1枚までを、レストで追加する。
# --------------------------------------------------------------------------- #
def test_op07_068_on_attack_add_rested_don_ai():
    """アタック時: ドンデッキからレストドン1枚を追加 (AI、 do 部分)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 0
    me.don_remaining_in_deck = 5
    rested_before = me.don_rested
    deck_before = me.don_remaining_in_deck

    for prim in _do(overlay, "OP07-068", "on_attack"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert me.don_rested == rested_before + 1, "レストドンが1枚追加されていない"
    assert me.don_remaining_in_deck == deck_before - 1, "ドンデッキから1枚減るべき"


def test_op07_068_don_gate_conditions():
    """条件: 自ドン<=相手ドン かつ ドン‼×1 (自身に付与ドン1枚以上) の AND。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    eff = _eff(overlay, "OP07-068", "on_attack")
    attacker = InPlay.of(repo.get("OP07-068"), sickness=False)
    me.characters = [attacker]
    # 付与ドン は don_diff にも算入されるため、 相手にも同数のドンを持たせて
    # don_diff_le 0 (自ドン<=相手ドン) を成立させた上で【ドン‼×1】gate を検証する。
    opp.don_active = 1
    # (a) 付与ドン0 → ドン‼×1 gate 不成立
    attacker.attached_dons = 0
    assert eval_all_conditions(eff, st, me, attacker) is False, \
        "付与ドン0で【ドン‼×1】gate が成立してはいけない"
    # (b) 付与ドン1 + 自ドン(1)<=相手ドン(1) → 成立
    attacker.attached_dons = 1
    assert eval_all_conditions(eff, st, me, attacker) is True, \
        "付与ドン1 + 自ドン<=相手ドンで条件が成立するべき"


# --------------------------------------------------------------------------- #
#  OP07-069 ピクルス (CHARACTER 紫 cost3):
#    自分の場のドン!!が相手の場のドン!!の枚数以下の場合、自分の、「ピクルス」以外の
#    特徴《フォクシー海賊団》を持つキャラは相手の効果でKOされない。 (静的)
# --------------------------------------------------------------------------- #
def test_op07_069_static_ko_immune_grants_foxy_except_self():
    """静的: 「ピクルス」以外のフォクシーキャラに static_ko_immune を付与 (自身は除外)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me = st.players[0]
    pickles = InPlay.of(repo.get("OP07-069"), sickness=False)   # ピクルス自身
    foxy = InPlay.of(repo.get(_FOXY_C3), sickness=False)        # イトミミズ (フォクシー)
    me.characters = [pickles, foxy]
    me.don_active = 0  # 自ドン<=相手ドン 成立

    evaluate_static_effects(st, overlay)
    assert foxy.static_ko_immune is True, \
        "フォクシーキャラに相手効果KO耐性が付いていない"
    assert pickles.static_ko_immune is False, \
        "「ピクルス」自身は除外されるべき (KO耐性を付けてはいけない)"


def test_op07_069_static_ko_immune_off_when_don_behind_fails():
    """条件: 自ドンが相手より多い場合は KO 耐性が付かない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me = st.players[0]
    pickles = InPlay.of(repo.get("OP07-069"), sickness=False)
    foxy = InPlay.of(repo.get(_FOXY_C3), sickness=False)
    me.characters = [pickles, foxy]
    me.don_active = 3  # 自ドン > 相手ドン → 条件不成立

    evaluate_static_effects(st, overlay)
    assert foxy.static_ko_immune is False, \
        "自ドンが相手より多い場合は KO 耐性が付いてはいけない"


# --------------------------------------------------------------------------- #
#  OP07-070 ビッグパン (CHARACTER 紫 cost6):
#    【登場時】自分の場のドン!!が相手の場のドン!!の枚数以下の場合、自分の手札から
#      コスト4以下の特徴《フォクシー海賊団》を持つカード1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op07_070_on_play_play_foxy_from_hand_ai():
    """登場時: 手札のコスト4以下フォクシーカード1枚を登場させる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FOXY_C2)]  # チョッパー cost2 フォクシー
    me.characters = []

    for prim in _do(overlay, "OP07-070", "on_play"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert any(c.card.card_id == _FOXY_C2 for c in me.characters), \
        "手札のフォクシーキャラが場に登場していない"
    assert not any(getattr(c, "card_id", None) == _FOXY_C2 for c in me.hand), \
        "登場させたカードが手札に残っている"


def test_op07_070_don_diff_condition():
    """条件: 自ドン<=相手ドン で成立、 自ドンが多いと不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me = st.players[0]
    cond = _eff(overlay, "OP07-070", "on_play").get("if")
    assert cond is not None, "OP07-070 に don_diff 条件がない"
    assert eval_condition(cond, st, me) is True, "自0<=相手0で条件が成立するべき"
    me.don_active = 2
    assert eval_condition(cond, st, me) is False, \
        "自ドンが相手より多いと条件が成立してはいけない"


def test_op07_070_on_play_human_pick():
    """登場時 (人間): フォクシーcost≤4 候補が2枚 → play 選択 modal → 1枚を登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FOXY_C1), repo.get(_FOXY_C2)]  # ジーナ / チョッパー (共にフォクシー)
    me.characters = []

    execute_effect(_do(overlay, "OP07-070", "on_play")[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で登場 選択 modal が立たない"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) >= 2, f"登場候補が2枚以上でない: {len(cands)}"
    resolve_pending_choice(st, [0])
    _drain(st)
    assert len(me.characters) == 1, "人間が選んだ1枚が登場していない"
    assert me.characters[0].card.card_id in (_FOXY_C1, _FOXY_C2), \
        "登場したのがフォクシー候補でない"


# --------------------------------------------------------------------------- #
#  OP07-072 ポルチェ (CHARACTER 紫 cost3):
#    【登場時】ドン‼-1：自分のデッキの上から5枚を見て、特徴《フォクシー海賊団》を持つ
#      カード1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置き、
#      自分の手札からパワー4000以下の紫のキャラカード1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op07_072_on_play_search_then_play_ai():
    """登場時: 上5枚からフォクシーを手札に + 手札の紫パワー4000以下を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    # デッキ上にフォクシーカードを確実に配置
    me.deck = [repo.get(_FOXY_C2)] + [repo.get(_FILLER)] * 10
    # 手札に紫 power4000 以下キャラ
    me.hand = [repo.get(_PURPLE_4000)]  # カポーティ power4000 紫
    me.characters = []

    do = _do(overlay, "OP07-072", "on_play")
    # do[0] = search_top_n (フォクシーを手札へ)
    execute_effect(do[0], st, me, opp, None)
    _drain(st)
    assert any(getattr(c, "card_id", None) == _FOXY_C2 for c in me.hand), \
        "上5枚からフォクシーカードが手札に加わっていない"
    # do[1] = play_from_hand (紫 power4000以下 を登場)
    execute_effect(do[1], st, me, opp, None)
    _drain(st)
    assert any(c.card.card_id == _PURPLE_4000 for c in me.characters), \
        "手札の紫 power4000以下キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP07-073 モンキー・D・ルフィ (CHARACTER 紫 cost6):
#    【起動メイン】【ターン1回】ドン‼-3：相手のキャラが3枚以上いる場合、このキャラを
#      アクティブにする。
# --------------------------------------------------------------------------- #
def test_op07_073_activate_untap_self_ai():
    """起動メイン: ドン-3 支払いで このキャラ(レスト)をアクティブにする (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("OP07-073"), sickness=False)
    luffy.rested = True
    me.characters = [luffy]
    me.don_active = 6  # ドン-3 支払い可能
    opp.characters = [InPlay.of(repo.get(_FILLER), sickness=False) for _ in range(3)]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP07-073"]
    assert len(opts) == 1, f"OP07-073 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)
    assert luffy.rested is False, "起動メインでルフィがアクティブになっていない"


def test_op07_073_activate_requires_3_opp_chara():
    """negative: 相手のキャラが3枚未満なら起動メインが legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("OP07-073"), sickness=False)
    luffy.rested = True
    me.characters = [luffy]
    me.don_active = 6
    opp.characters = [InPlay.of(repo.get(_FILLER), sickness=False) for _ in range(2)]  # 2体

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP07-073"]
    assert len(opts) == 0, "相手キャラ2体で起動メインが legal に出てはいけない"


def test_op07_073_activate_once_per_turn():
    """【ターン1回】: ドンが残っていても一度発動すると再び legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("OP07-073"), sickness=False)
    luffy.rested = True
    me.characters = [luffy]
    me.don_active = 9  # 2 回分払える量 (= once_per_turn 単独検証)
    opp.characters = [InPlay.of(repo.get(_FILLER), sickness=False) for _ in range(3)]

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP07-073"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st)

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP07-073"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP07-074 モンダ (CHARACTER 紫 cost2):
#    【起動メイン】このキャラをトラッシュに置くことができる：自分のリーダーが特徴
#      《フォクシー海賊団》を持つ場合、ドン!!デッキからドン!!1枚までを、レストで追加する。
# --------------------------------------------------------------------------- #
def test_op07_074_activate_trash_self_add_rested_don_ai():
    """起動メイン: 自身をトラッシュ + レストドン1枚追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _FOXY_LEADER, overlay)  # フォクシー leader → 条件成立
    me, opp = st.players[0], st.players[1]
    monda = InPlay.of(repo.get("OP07-074"), sickness=False)
    me.characters = [monda]
    me.don_rested = 0
    me.don_remaining_in_deck = 5
    rested_before = me.don_rested

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP07-074"]
    assert len(opts) == 1, f"OP07-074 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)
    assert monda not in me.characters, "起動メインコストで自身がトラッシュに置かれていない"
    assert any(c.card_id == "OP07-074" for c in me.trash), \
        "トラッシュに置いた自身がトラッシュにない"
    assert me.don_rested == rested_before + 1, "レストドンが1枚追加されていない"


def test_op07_074_activate_requires_foxy_leader():
    """negative: リーダーが《フォクシー海賊団》でなければ起動メインが legal に出ない。"""
    # ⚠ 2026-08-05 是正: 公式は 「〜できる：<条件>の場合、<効果>」 のコロン後の条件を
    #   **効果のみ** の gate とする。 任意コストは条件不成立でも支払える。
    #   一次情報 (cardqa_op_02): 「自分のリーダーが「エンポリオ・イワンコフ」ではない場合、
    #   この【起動メイン】効果を発動できますか？」 → 「はい、できます。 その場合、このカードを
    #   レストにしますが、 **その後の効果では何も起きません**」。
    #   → 「条件不成立なら legal に出ない」 は **行動の合法性ごと消す旧バグ** を固定していた。
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)  # フォクシーでない leader
    me = st.players[0]
    me.characters = [InPlay.of(repo.get("OP07-074"), sickness=False)]
    me.don_remaining_in_deck = 5

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP07-074"]
    assert len(opts) == 1, (
        "任意コストは条件不成立でも払えるので legal に残るべき (公式: cardqa_op_02)"
    )


# --------------------------------------------------------------------------- #
#  OP07-075 ノロノロビ～～～～ム (EVENT 紫 cost1):
#    【カウンター】ドン‼-1：相手のリーダーとキャラ1枚までを、このターン中、パワー-2000。
# --------------------------------------------------------------------------- #
def test_op07_075_counter_debuff_leader_and_chara_ai():
    """カウンター: 相手リーダー -2000 + 相手キャラ1枚 -2000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_OPP_C), sickness=False)  # power3000
    opp.characters = [victim]
    leader_before = opp.leader.power
    victim_before = victim.power

    for prim in _do(overlay, "OP07-075", "counter"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert opp.leader.power == leader_before - 2000, \
        f"相手リーダーに -2000 が反映されていない: {opp.leader.power}"
    assert victim.power == victim_before - 2000, \
        f"相手キャラに -2000 が反映されていない: {victim.power}"


def test_op07_075_counter_chara_human_pick():
    """カウンター (人間): 相手キャラが2体 → target_pick modal → 選んだ方に -2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_OPP_C), sickness=False)   # power3000
    b = InPlay.of(repo.get(_FILLER), sickness=False)  # power3000
    opp.characters = [a, b]

    do = _do(overlay, "OP07-075", "counter")
    # do[0] = リーダー -2000 (対象一意、 modal なし)
    execute_effect(do[0], st, me, opp, None)
    _drain(st)
    # do[1] = 相手キャラ1枚 -2000 (2体 → 人間 modal)
    execute_effect(do[1], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    a_before = a.power
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b.power == b_before - 2000, "人間が選んだキャラに -2000 が反映されていない"
    assert a.power == a_before, "選ばなかったキャラは変化しないべき"
