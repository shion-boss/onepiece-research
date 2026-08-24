# -*- coding: utf-8 -*-
"""ST29 / ST30 弾 効果 回帰テスト バックフィル (自動生成 wave 187):
ST29-008 / ST29-009 / ST29-012 / ST29-014 / ST29-016 / ST29-017 /
ST30-001 / ST30-002 / ST30-003 / ST30-004 の 10 枚。

  ST29-008 ナミ (CHARACTER 黄) = 自《エッグヘッド》キャラが相手効果でKOされる場合、
     代わりに自ライフ上1枚を表向きにできる (replace_ko → flip_life_face_up_effect) /
     【トリガー】リーダーが「モンキー・Ｄ・ルフィ」なら 自身を登場
  ST29-009 ニコ・ロビン (CHARACTER 黄) = 【ブロッカー】(intrinsic) /
     【トリガー】リーダーが「モンキー・Ｄ・ルフィ」なら 自身を登場 (play_self)
  ST29-012 モンキー・Ｄ・ルフィ (CHARACTER 黄) = 【起動メイン】【ターン1回】自分の
     「モンキー・D・ルフィ」1枚にレストのドン1枚までを付与 (activate_main attach_rested_don) /
     【トリガー】自身を登場 (play_self)
  ST29-014 ロロノア・ゾロ (CHARACTER 黄) = 【速攻：キャラ】(on_attached_don n0 give_keyword) /
     【起動メイン】【ターン1回】手札の【トリガー】1枚を捨てる：1ドロー + 自リーダー/キャラに
     レストドン1まで付与 (activate_main optional_cost_then discard_hand_with_filter trigger → draw + attach)
  ST29-016 黄猿‼おれ達は… (EVENT 黄) = 【メイン】自「モンキー・Ｄ・ルフィ」1枚まで【ブロック不可】/
     【カウンター】自リーダー このバトル中 +3000 (main give_keyword; counter power_pump self_leader)
  ST29-017 死・獅子歌歌 (EVENT 黄) = 【カウンター】自リーダー/キャラ1枚まで +4000。その後
     自ライフ2以下なら 相手コスト3以下1枚までKO /【トリガー】2ドロー + 手札1枚捨てる
     (counter power_pump self_inplay + conditional self_life_le2 ko; trigger draw2 + trash1)
  ST30-001 ルフィ＆エース (LEADER 赤/緑) = 自元パワー7000以上のキャラがいれば 自リーダー-2000 /
     【相手のターン中】自「ポートガス・Ｄ・エース」「モンキー・Ｄ・ルフィ」すべて+3000 (静的)
  ST30-002 イナズマ (CHARACTER 赤) = 【登場時】デッキ上5枚を見て パワー6000のキャラ1枚まで
     公開し手札に、残りをデッキ下 (on_play search_top_n depth5 power_eq6000 CHARACTER)
  ST30-003 エドワード・ニューゲート (CHARACTER 赤) = 【自分のターン中】自元パワー6000の
     キャラすべて+1000 (静的 all_self_chara_filtered power_eq6000 if self_turn)
  ST30-004 エンポリオ・イワンコフ (CHARACTER 赤) = 【登場時】手札のパワー6000キャラ2枚を
     公開できる：3ドロー + 手札2枚捨てる (on_play optional_cost_then reveal_hand_with_filter → draw3 trash2)

目的 (= test_backfill_auto_001〜186.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 任意コスト を 持つカードは 人間 actor で pending_choice が
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
    eval_condition,
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
    try_replace_ko,
)

ROOT = Path(__file__).resolve().parent.parent

_LEADER_LUFFY = "ST29-001"   # モンキー・Ｄ・ルフィ (LEADER 黄)
_LEADER_LUACE = "ST30-001"   # ルフィ＆エース (LEADER 赤/緑, base power6000)
_LEADER_PLAIN = "OP01-001"   # ロロノア・ゾロ (LEADER 赤, base power5000) — 汎用
_FILLER = "OP01-013"         # サンジ cost2 power3000 麦わらの一味
_NAMI = "OP01-016"           # ナミ cost1 power2000 麦わらの一味
_BIG = "PRB02-013"           # ゲッコー・モリア cost6 power7000 (= 元パワー7000)
_P6000 = "PRB02-008"         # マルコ cost4 power6000 CHARACTER
_TRIG = "PRB02-012"          # ナミ cost2 CHARACTER (【トリガー】持ち)
_LUFFY_C = "PRB02-005"       # モンキー・D・ルフィ cost4 power5000 CHARACTER (named)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id=_LEADER_PLAIN,
           turn_player=0):
    """P0 = テスト対象デッキ、 P1 = ダミー。 MAIN / turn_number=3。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(_FILLER)] * 30
    p1.deck = [repo.get(_FILLER)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn_player
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _eff(overlay, cid, when):
    """指定 card_id の overlay から when 一致の効果 (dict) を返す (先頭)。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    return matches[0]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [0])
        n += 1


def _resolve_search(st):
    """search_top_n modal → 候補 index 0 を選択 → 残る reorder modal を空順で drain。"""
    resolve_pending_choice(st, [0])
    guard = 0
    while st.pending_choice is not None and guard < 6:
        resolve_pending_choice(st, [])
        guard += 1


def _acts(st, me, overlay, cid):
    return [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == cid]


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave187_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["ST29-008", "ST29-009", "ST29-012", "ST29-014", "ST29-016",
           "ST29-017", "ST30-001", "ST30-002", "ST30-003", "ST30-004"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  ST29-008 ナミ: replace_ko → 自ライフ上1枚を表向き (エッグヘッド self chara が
#            相手効果でKOされる場合) /【トリガー】ルフィ leader で 自身を登場
# --------------------------------------------------------------------------- #
def test_st29_008_replace_ko_flips_life_face_up():
    """自《エッグヘッド》キャラが相手効果でKOされる場合、代わりに自ライフ上1枚を表向きに
    (= replace_ko 成立 → face_up_life_count が1増え、 KO が置換されキャラは場に残る)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_LUFFY, overlay)
    me, opp = st.players[0], st.players[1]
    nami = InPlay.of(repo.get("ST29-008"), sickness=False)  # エッグヘッド/麦わらの一味
    me.characters = [nami]
    me.life = [repo.get(_FILLER)] * 2
    # 2026-08-11: 表向きライフは per-card フラグ (life_face_up) で持つ
    me.life_face_up = [i < (0) for i in range(len(me.life))]

    replaced = try_replace_ko(
        st, me, opp, nami, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, \
        "エッグヘッド self chara が相手効果KOされる時 replace_ko が成立していない"
    assert nami in me.characters, "置換成立時 ナミは場に残るべき"
    assert me.face_up_life_count == 1, \
        f"代わりに自ライフ上1枚が表向きになっていない: face_up={me.face_up_life_count}"


def test_st29_008_replace_ko_not_by_opp_effect():
    """相手効果由来でない (= by_opp_effect=False) 離脱では置換しない (条件を省略しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_LUFFY, overlay)
    me, opp = st.players[0], st.players[1]
    nami = InPlay.of(repo.get("ST29-008"), sickness=False)
    me.characters = [nami]
    me.life = [repo.get(_FILLER)] * 2
    # 2026-08-11: 表向きライフは per-card フラグ (life_face_up) で持つ
    me.life_face_up = [i < (0) for i in range(len(me.life))]

    replaced = try_replace_ko(
        st, me, opp, nami, overlay, by_opp_effect=False, leave_kind="ko",
    )
    assert replaced is False, \
        "by_opp_effect=False (= バトルKO等) では置換が成立してはいけない"
    assert me.face_up_life_count == 0, "非該当なのにライフが表向きになってはいけない"


def test_st29_008_trigger_play_self_when_luffy_leader_ai():
    """トリガー: リーダーが「モンキー・Ｄ・ルフィ」→ 自身を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_LUFFY, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("ST29-008")]
    st.current_source_card_id = "ST29-008"

    eff = _eff(overlay, "ST29-008", "trigger")
    assert eff.get("if", {}).get("leader_name") == "モンキー・Ｄ・ルフィ", \
        "overlay の リーダー名 条件が無い"
    assert eval_condition(eff.get("if", {}), st, me, opp) is True, \
        "ルフィ leader で条件が成立していない"

    chars_before = len(me.characters)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    assert any(c.card.card_id == "ST29-008" for c in me.characters), \
        "トリガー play_self で ナミ が登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"


# --------------------------------------------------------------------------- #
#  ST29-009 ニコ・ロビン: 【トリガー】ルフィ leader で 自身を登場 (blocker は intrinsic)
# --------------------------------------------------------------------------- #
def test_st29_009_trigger_play_self_when_luffy_leader_ai():
    """トリガー: リーダーが「モンキー・Ｄ・ルフィ」→ 自身を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_LUFFY, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("ST29-009")]
    st.current_source_card_id = "ST29-009"

    eff = _eff(overlay, "ST29-009", "trigger")
    assert eval_condition(eff.get("if", {}), st, me, opp) is True

    chars_before = len(me.characters)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    assert any(c.card.card_id == "ST29-009" for c in me.characters), \
        "トリガー play_self で ニコ・ロビン が登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"


def test_st29_009_condition_off_when_plain_leader():
    """リーダーが「モンキー・Ｄ・ルフィ」でなければ 条件不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    eff = _eff(overlay, "ST29-009", "trigger")
    assert eval_condition(eff.get("if", {}), st, me, opp) is False, \
        "ルフィ でない leader では条件が不成立であるべき"


# --------------------------------------------------------------------------- #
#  ST29-012 モンキー・Ｄ・ルフィ: 【起動メイン】【ターン1回】自「ルフィ」に
#            レストドン1まで付与 /【トリガー】自身を登場
# --------------------------------------------------------------------------- #
def test_st29_012_activate_main_attach_rested_don_ai():
    """起動メイン: 自「モンキー・D・ルフィ」(= リーダー) にレストドン1枚を付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_LUFFY, overlay)  # リーダー = モンキー・Ｄ・ルフィ
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("ST29-012"), sickness=False)
    me.characters = [luffy]
    me.don_rested = 2  # レストドン供給源

    attached_before = me.leader.attached_dons + sum(
        c.attached_dons for c in me.characters)
    rested_before = me.don_rested
    opts = _acts(st, me, overlay, "ST29-012")
    assert len(opts) == 1, f"ST29-012 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    attached_after = me.leader.attached_dons + sum(
        c.attached_dons for c in me.characters)
    assert attached_after == attached_before + 1, \
        "起動メインで「モンキー・D・ルフィ」へレストドンが付与されていない"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"


def test_st29_012_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_LUFFY, overlay)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("ST29-012"), sickness=False)
    me.characters = [luffy]
    me.don_rested = 3

    opts1 = _acts(st, me, overlay, "ST29-012")
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st)
    opts2 = _acts(st, me, overlay, "ST29-012")
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


def test_st29_012_trigger_play_self_ai():
    """トリガー: 自身を登場 (条件なし、 AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("ST29-012")]
    st.current_source_card_id = "ST29-012"

    chars_before = len(me.characters)
    for prim in _eff(overlay, "ST29-012", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    assert any(c.card.card_id == "ST29-012" for c in me.characters), \
        "トリガー play_self で モンキー・Ｄ・ルフィ が登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"


# --------------------------------------------------------------------------- #
#  ST29-014 ロロノア・ゾロ: 【速攻：キャラ】/【起動メイン】手札の【トリガー】1枚を
#            捨てる：1ドロー + 自リーダー/キャラにレストドン1まで付与
# --------------------------------------------------------------------------- #
def test_st29_014_grants_rush_chara():
    """【速攻：キャラ】が自身に付与される (on_attached_don n=0)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    zoro = InPlay.of(repo.get("ST29-014"), sickness=True)
    me.characters = [zoro]
    eff = _eff(overlay, "ST29-014", "on_attached_don")
    assert eff.get("n") == 0, "on_attached_don n=0 (常時付与) でない"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, zoro)
    assert "速攻：キャラ" in zoro.granted_keywords, \
        "【速攻：キャラ】が付与されていない"


def test_st29_014_activate_main_discard_trigger_draw_attach_ai():
    """起動メイン: 手札の【トリガー】1枚を捨てる (コスト) → 1ドロー + レストドン1付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    zoro = InPlay.of(repo.get("ST29-014"), sickness=False)
    me.characters = [zoro]
    me.hand = [repo.get(_TRIG)]  # 【トリガー】持ち = 捨てコスト源
    me.deck = [repo.get(_FILLER)] * 10
    me.don_rested = 2

    deck_before = len(me.deck)
    trash_before = len(me.trash)
    attached_before = me.leader.attached_dons + sum(
        c.attached_dons for c in me.characters)
    rested_before = me.don_rested

    opts = _acts(st, me, overlay, "ST29-014")
    assert len(opts) == 1, f"ST29-014 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    assert len(me.deck) == deck_before - 1, "1ドローでデッキが1枚減っていない"
    assert any(c.card_id == _TRIG for c in me.trash), \
        "コストで【トリガー】カードが捨てられていない"
    assert len(me.trash) == trash_before + 1, "捨てコストでトラッシュが1枚増えていない"
    attached_after = me.leader.attached_dons + sum(
        c.attached_dons for c in me.characters)
    assert attached_after == attached_before + 1, \
        "効果でレストドンが1枚付与されていない"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"


# --------------------------------------------------------------------------- #
#  ST29-016 黄猿‼ (EVENT): 【メイン】自「ルフィ」に【ブロック不可】/
#            【カウンター】自リーダー +3000
# --------------------------------------------------------------------------- #
def test_st29_016_main_grants_unblockable_to_luffy():
    """【メイン】自「モンキー・Ｄ・ルフィ」(= リーダー) に【ブロック不可】を付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_LUFFY, overlay)
    me, opp = st.players[0], st.players[1]
    for prim in _eff(overlay, "ST29-016", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert "ブロック不可" in me.leader.granted_keywords, \
        "自「モンキー・Ｄ・ルフィ」に【ブロック不可】が付与されていない"


def test_st29_016_counter_leader_pump():
    """【カウンター】自リーダーを このバトル中 パワー+3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_LUFFY, overlay)
    me, opp = st.players[0], st.players[1]
    leader_base = me.leader.power
    for prim in _eff(overlay, "ST29-016", "counter")["do"]:
        execute_effect(prim, st, me, opp, me.leader)
    _drain(st)
    assert me.leader.power == leader_base + 3000, \
        f"カウンターで 自リーダー+3000 が反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  ST29-017 死・獅子歌歌 (EVENT): 【カウンター】自リーダー/キャラ+4000。その後
#            自ライフ2以下なら 相手コスト3以下1枚までKO /【トリガー】2ドロー + 手札1枚捨てる
# --------------------------------------------------------------------------- #
def test_st29_017_counter_pump_and_ko_when_low_life_ai():
    """カウンター: 自リーダー+4000。 自ライフ2以下 → 相手コスト3以下キャラをKO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2  # 自ライフ 2 (= 条件成立)
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 ≤ 3
    opp.characters = [victim]
    leader_base = me.leader.power

    for prim in _eff(overlay, "ST29-017", "counter")["do"]:
        execute_effect(prim, st, me, opp, me.leader)
    _drain(st)

    assert me.leader.power == leader_base + 4000, \
        f"カウンターで 自リーダー+4000 が反映されていない: {me.leader.power}"
    assert victim not in opp.characters, \
        "自ライフ2以下で 相手コスト3以下キャラが KO されていない"


def test_st29_017_counter_no_ko_when_high_life():
    """自ライフ3枚 (> 2) なら 後段のKOは発動しない (= 条件を省略しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3  # 自ライフ 3 (= 条件不成立)
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]

    for prim in _eff(overlay, "ST29-017", "counter")["do"]:
        execute_effect(prim, st, me, opp, me.leader)
    _drain(st)
    assert victim in opp.characters, \
        "自ライフ3枚では 相手キャラが KO されてはいけない (条件不成立)"


def test_st29_017_trigger_draw2_discard1_ai():
    """トリガー: カード2枚を引き、 自手札1枚を捨てる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 10

    deck_before = len(me.deck)
    trash_before = len(me.trash)
    for prim in _eff(overlay, "ST29-017", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert len(me.deck) == deck_before - 2, "2ドローでデッキが2枚減っていない"
    assert len(me.trash) == trash_before + 1, "手札1枚がトラッシュに捨てられていない"
    assert len(me.hand) == 1, "2ドロー -1捨て で手札が1枚であるべき"


# --------------------------------------------------------------------------- #
#  ST30-001 ルフィ＆エース (LEADER): 静的 自元パワー7000+のキャラで 自リーダー-2000 /
#            相手ターン中 自「エース」「ルフィ」すべて+3000
# --------------------------------------------------------------------------- #
def test_st30_001_static_leader_minus_when_big_chara():
    """静的: 自陣に元パワー7000以上のキャラがいる → 自リーダー パワー-2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_LUACE, overlay, turn_player=0)  # 自ターン
    me, _opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(_BIG), sickness=False)]  # モリア 元パワー7000
    leader_base = me.leader.power  # base 6000

    evaluate_static_effects(st, overlay)
    assert me.leader.power == leader_base - 2000, \
        f"元パワー7000+のキャラで 自リーダー-2000 が反映されていない: {me.leader.power}"


def test_st30_001_static_leader_no_minus_when_small_chara():
    """自陣に元パワー7000以上のキャラがいなければ -2000 は乗らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_LUACE, overlay, turn_player=0)
    me, _opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(_FILLER), sickness=False)]  # power3000
    leader_base = me.leader.power

    evaluate_static_effects(st, overlay)
    assert me.leader.power == leader_base, \
        f"元パワー7000未満のみなら -2000 が乗ってはいけない: {me.leader.power}"


def test_st30_001_static_ace_luffy_pump_on_opp_turn():
    """【相手のターン中】自「モンキー・Ｄ・ルフィ」すべて +3000 (静的)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_LUACE, overlay, turn_player=1)  # 相手ターン
    me, _opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get(_LUFFY_C), sickness=False)  # モンキー・D・ルフィ power5000
    me.characters = [luffy]

    evaluate_static_effects(st, overlay)
    assert luffy.power == 5000 + 3000, \
        f"相手ターン中 自「ルフィ」+3000 が反映されていない: {luffy.power}"


def test_st30_001_static_no_pump_on_self_turn():
    """自分のターン中は「ルフィ」への +3000 は乗らない (相手ターン限定)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_LUACE, overlay, turn_player=0)  # 自ターン
    me, _opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get(_LUFFY_C), sickness=False)
    me.characters = [luffy]

    evaluate_static_effects(st, overlay)
    assert luffy.power == 5000, \
        f"自ターン中は「ルフィ」+3000 が乗ってはいけない: {luffy.power}"


# --------------------------------------------------------------------------- #
#  ST30-002 イナズマ: 【登場時】デッキ上5枚 → パワー6000のキャラ1枚まで手札 (search)
# --------------------------------------------------------------------------- #
def test_st30_002_on_play_search_power6000_ai():
    """登場時: デッキ上5枚から パワー6000のキャラを手札に加える (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_P6000)] + [repo.get(_FILLER)] * 20  # 先頭に power6000 char
    me.hand = []

    execute_effect(_eff(overlay, "ST30-002", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST30-002"), sickness=True))
    _drain(st, [])
    assert any(c.card_id == _P6000 for c in me.hand), \
        "デッキ上5枚から パワー6000のキャラが手札に加わっていない"


def test_st30_002_on_play_search_human_pick():
    """人間: search_top_n modal が立ち、 選択で パワー6000キャラが手札に加わる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_P6000)] + [repo.get(_FILLER)] * 20
    me.hand = []

    execute_effect(_eff(overlay, "ST30-002", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST30-002"), sickness=True))
    assert st.pending_choice is not None, "人間で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    _resolve_search(st)
    assert any(c.card_id == _P6000 for c in me.hand), \
        "人間が選んだ パワー6000キャラが手札に加わっていない"


def test_st30_002_on_play_search_no_hit_when_absent():
    """デッキ上5枚に パワー6000キャラが無ければ 手札に加わらない (対象外は取れない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 20  # power3000 のみ
    me.hand = []

    execute_effect(_eff(overlay, "ST30-002", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST30-002"), sickness=True))
    _drain(st, [])
    assert not any(c.card_id == _P6000 for c in me.hand), \
        "パワー6000キャラが不在なのに手札に加わってはいけない"


# --------------------------------------------------------------------------- #
#  ST30-003 エドワード・ニューゲート: 静的 自ターン中 自元パワー6000キャラすべて+1000
# --------------------------------------------------------------------------- #
def test_st30_003_static_pump_power6000_on_self_turn():
    """静的: 自ターン中、 自元パワー6000のキャラすべて +1000 (自身も power6000 → +1000)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay, turn_player=0)  # 自ターン
    me, _opp = st.players[0], st.players[1]
    newgate = InPlay.of(repo.get("ST30-003"), sickness=False)  # power6000
    ally = InPlay.of(repo.get(_P6000), sickness=False)         # マルコ power6000
    me.characters = [newgate, ally]

    evaluate_static_effects(st, overlay)
    assert newgate.power == 6000 + 1000, \
        f"自ターン中 自身 (power6000) に +1000 が乗っていない: {newgate.power}"
    assert ally.power == 6000 + 1000, \
        f"自ターン中 味方 power6000 に +1000 が乗っていない: {ally.power}"


def test_st30_003_static_no_pump_on_opp_turn():
    """相手ターン中は +1000 が乗らない (自分のターン限定)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay, turn_player=1)  # 相手ターン
    me, _opp = st.players[0], st.players[1]
    ally = InPlay.of(repo.get(_P6000), sickness=False)  # power6000
    me.characters = [ally]

    evaluate_static_effects(st, overlay)
    assert ally.power == 6000, \
        f"相手ターン中は +1000 が乗ってはいけない: {ally.power}"


def test_st30_003_static_no_pump_non_6000():
    """元パワー6000でないキャラには +1000 が乗らない (= power_eq6000 条件を省略しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay, turn_player=0)
    me, _opp = st.players[0], st.players[1]
    other = InPlay.of(repo.get(_FILLER), sickness=False)  # power3000 ≠ 6000
    me.characters = [other]

    evaluate_static_effects(st, overlay)
    assert other.power == 3000, \
        f"元パワー6000でないキャラに +1000 が乗ってはいけない: {other.power}"


# --------------------------------------------------------------------------- #
#  ST30-004 エンポリオ・イワンコフ: 【登場時】手札のパワー6000キャラ2枚を公開できる：
#            3ドロー + 手札2枚捨てる
# --------------------------------------------------------------------------- #
def test_st30_004_on_play_reveal_draw3_discard2_ai():
    """登場時: 手札の パワー6000キャラ2枚を公開 (コスト) → 3ドロー + 手札2枚捨てる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    # 公開コスト用 power6000 キャラ 2 枚 + 捨て札にできる filler
    me.hand = [repo.get(_P6000), repo.get(_P6000), repo.get(_FILLER)]
    me.deck = [repo.get(_FILLER)] * 10

    deck_before = len(me.deck)
    trash_before = len(me.trash)
    execute_effect(_eff(overlay, "ST30-004", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST30-004"), sickness=True))
    _drain(st)

    assert len(me.deck) == deck_before - 3, "3ドローでデッキが3枚減っていない"
    assert len(me.trash) == trash_before + 2, "手札2枚がトラッシュに捨てられていない"


def test_st30_004_on_play_no_effect_when_no_power6000_pair():
    """手札に パワー6000キャラが2枚無ければ 公開コスト不能 → ドロー/捨ては発動しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_P6000), repo.get(_FILLER)]  # power6000 は1枚のみ
    me.deck = [repo.get(_FILLER)] * 10

    deck_before = len(me.deck)
    execute_effect(_eff(overlay, "ST30-004", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST30-004"), sickness=True))
    _drain(st)
    assert len(me.deck) == deck_before, \
        "power6000キャラが2枚無いのにドローが発動してはいけない (公開コスト不能)"


def test_st30_004_on_play_human_optional_confirm():
    """人間: 登場時の任意コストで optional_cost_confirm modal が立ち pay で解決 → 3ドロー。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_P6000), repo.get(_P6000), repo.get(_FILLER)]
    me.deck = [repo.get(_FILLER)] * 10

    deck_before = len(me.deck)
    execute_effect(_eff(overlay, "ST30-004", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST30-004"), sickness=True))
    assert st.pending_choice is not None, "人間で任意コスト確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # pay
    _drain(st)
    assert len(me.deck) == deck_before - 3, \
        "人間が支払った後に 3ドローが起きていない"
