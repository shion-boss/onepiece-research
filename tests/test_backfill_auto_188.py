# -*- coding: utf-8 -*-
"""ST30 弾 効果 回帰テスト バックフィル (自動生成 wave 188):
ST30-006 / ST30-007 / ST30-008 / ST30-009 / ST30-010 / ST30-011 /
ST30-012 / ST30-014 / ST30-015 / ST30-016 の 10 枚。

  ST30-006 ジンベエ (CHARACTER 赤) = 【登場時】手札のパワー6000キャラ1枚を捨てられる：
     カード2枚を引く (on_play optional_cost_then discard_hand_with_filter power_eq6000 → draw2)
  ST30-007 ポートガス・Ｄ・エース (CHARACTER 赤) = 【登場時】自ドン1枚レストで【速攻】/
     【アタック時】相手キャラ1枚まで このターン中 -1000
     (on_play optional_cost_then rest_self_don → give_keyword 速攻; on_attack power_pump -1000)
  ST30-008 マルコ (CHARACTER 赤) = 【ブロッカー】(intrinsic) /【KO時】手札のパワー6000キャラ
     1枚を捨てられる：このキャラをトラッシュからレストで登場
     (on_ko optional_cost_then discard_hand_with_filter power_eq6000 → play_self from trash rested)
  ST30-009 リトルオーズJr. (CHARACTER 赤) = 自元パワー6000のキャラが相手効果で場を離れる場合、
     代わりにこのキャラをトラッシュ + 1ドロー
     (replace_leave other_self_chara truly_original_power_eq6000 by_opp cost trash_self → draw1)
  ST30-010 クロコダイル (CHARACTER 緑) = 【ブロッカー】(intrinsic) /【登場時】相手のレストの
     キャラ1枚までは 次の相手リフレッシュでアクティブにならない
     (on_play stay_rested_next_refresh one_opponent_character_filtered rested)
  ST30-011 バギー (CHARACTER 緑) = 自元パワー6000のキャラが相手効果で場を離れる場合、
     代わりにこのキャラをレストにできる /【ブロッカー】(intrinsic)
     (replace_leave any_self_chara power6000 by_opp → rest self)
  ST30-012 モンキー・D・ルフィ (CHARACTER 緑) = 【登場時】自ドン1枚レストで【速攻】/
     【アタック時】相手の【ブロッカー】キャラ1枚までをレスト
     (on_play optional_cost_then rest_self_don → give_keyword 速攻; on_attack rest one_opp_chara_blocker)
  ST30-014 Mr.3(ギャルディーノ) (CHARACTER 緑) = 【起動メイン】このキャラをレストにできる：
     自元パワー6000キャラ2枚までにレストドン2枚ずつまで付与
     (activate_main cost rest_self → attach_rested_don all_self_chara_filtered power6000 limit2 count2 per_target)
  ST30-015 この時代の名が!!!"白ひげ"だァ!!! (EVENT 赤) = 【カウンター】自元パワー6000キャラ2枚以上
     なら 自リーダー/キャラ1枚まで +4000 /【トリガー】相手パワー6000以下1枚までKO
     (counter if self_chara_filtered_count_ge power6000 count2 → power_pump +4000; trigger ko power_le_6000)
  ST30-016 戦えるかルフィ!!!勿論だ!!! (EVENT 赤) = 【カウンター】自リーダー/キャラ1枚まで +3000。
     その後 自元パワー6000の「エース」と「ルフィ」がいれば 1ドロー
     (counter power_pump +3000; counter if self_field_named_all_with_power エース+ルフィ power6000 → draw1)

目的 (= test_backfill_auto_001〜187.py と同一方針):
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
    eval_condition,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
    try_replace_ko,
)

ROOT = Path(__file__).resolve().parent.parent

_LEADER_PLAIN = "OP01-001"   # ロロノア・ゾロ (LEADER 赤, base power5000) — 汎用
_FILLER = "OP01-013"         # サンジ cost2 power3000 麦わらの一味
_P6000 = "PRB02-008"         # マルコ cost4 power6000 CHARACTER (= 元パワー6000)


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


def _eff(overlay, cid, when, idx=0):
    """指定 card_id の overlay から when 一致の効果 (dict) を返す (idx 番目)。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    return matches[idx]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [0])
        n += 1


def _acts(st, me, overlay, cid):
    return [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == cid]


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave188_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["ST30-006", "ST30-007", "ST30-008", "ST30-009", "ST30-010",
           "ST30-011", "ST30-012", "ST30-014", "ST30-015", "ST30-016"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  ST30-006 ジンベエ: 【登場時】手札のパワー6000キャラ1枚を捨てられる：2ドロー
# --------------------------------------------------------------------------- #
def test_st30_006_on_play_discard_p6000_draw2_ai():
    """登場時: 手札の パワー6000キャラ1枚を捨てる (コスト) → 2ドロー (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_P6000)]  # 捨てコスト源 (power6000 CHARACTER)
    me.deck = [repo.get(_FILLER)] * 10

    deck_before = len(me.deck)
    trash_before = len(me.trash)
    execute_effect(_eff(overlay, "ST30-006", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST30-006"), sickness=True))
    _drain(st)

    assert len(me.deck) == deck_before - 2, "2ドローでデッキが2枚減っていない"
    assert len(me.trash) == trash_before + 1, "捨てコストでトラッシュが1枚増えていない"
    assert any(c.card_id == _P6000 for c in me.trash), \
        "捨てコストで パワー6000キャラがトラッシュに置かれていない"


def test_st30_006_on_play_no_draw_without_p6000():
    """手札に パワー6000キャラが無ければ 捨てコスト不能 → ドローは発動しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]  # power3000 のみ = 捨てられない
    me.deck = [repo.get(_FILLER)] * 10

    deck_before = len(me.deck)
    execute_effect(_eff(overlay, "ST30-006", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST30-006"), sickness=True))
    _drain(st)
    assert len(me.deck) == deck_before, \
        "パワー6000キャラが無いのにドローが発動してはいけない (捨てコスト不能)"


def test_st30_006_on_play_human_optional_confirm():
    """人間: 登場時の任意コストで optional_cost_confirm modal が立ち pay で解決 → 2ドロー。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_P6000)]
    me.deck = [repo.get(_FILLER)] * 10

    deck_before = len(me.deck)
    execute_effect(_eff(overlay, "ST30-006", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST30-006"), sickness=True))
    assert st.pending_choice is not None, "人間で任意コスト確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # pay
    _drain(st)
    assert len(me.deck) == deck_before - 2, \
        "人間が支払った後に 2ドローが起きていない"


# --------------------------------------------------------------------------- #
#  ST30-007 ポートガス・Ｄ・エース: 【登場時】自ドン1レストで【速攻】/
#            【アタック時】相手キャラ1枚 -1000
# --------------------------------------------------------------------------- #
def test_st30_007_on_play_rest_don_grants_rush_ai():
    """登場時: 自アクティブドン1枚をレスト (コスト) → 自身に【速攻】付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    ace = InPlay.of(repo.get("ST30-007"), sickness=True)
    me.characters = [ace]
    me.don_active = 2

    active_before = me.don_active
    rested_before = me.don_rested
    execute_effect(_eff(overlay, "ST30-007", "on_play")["do"][0], st, me, opp, ace)
    _drain(st)

    assert "速攻" in ace.granted_keywords, "登場時に【速攻】が付与されていない"
    assert me.don_active == active_before - 1, "アクティブドンが1枚レストされていない"
    assert me.don_rested == rested_before + 1, "レストドンが1枚増えていない"


def test_st30_007_on_attack_debuff_opp_ai():
    """アタック時: 相手キャラ1枚を このターン中 パワー-1000 (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_P6000), sickness=False)  # power6000
    opp.characters = [victim]

    power_before = victim.power
    execute_effect(_eff(overlay, "ST30-007", "on_attack")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST30-007"), sickness=False))
    _drain(st)
    assert victim.power == power_before - 1000, \
        f"アタック時 相手キャラ -1000 が反映されていない: {victim.power}"


def test_st30_007_on_attack_debuff_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal が立ち resolve で -1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)  # power3000
    b = InPlay.of(repo.get(_P6000), sickness=False)   # power6000
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "ST30-007", "on_attack")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST30-007"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b.power == b_before - 1000, "人間が選んだ相手キャラに -1000 が反映されていない"


# --------------------------------------------------------------------------- #
#  ST30-008 マルコ: 【KO時】手札のパワー6000キャラ1枚を捨てられる：
#            トラッシュからレストで登場
# --------------------------------------------------------------------------- #
def test_st30_008_on_ko_discard_revive_rested_ai():
    """KO時: 手札の パワー6000キャラ1枚を捨てる (コスト) → 自身をトラッシュから
    レストで登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    # マルコは既に KO 済 = トラッシュにある。 手札に捨てコスト用 power6000 キャラ。
    me.trash = [repo.get("ST30-008")]
    me.hand = [repo.get(_P6000)]
    st.current_source_card_id = "ST30-008"  # play_self が trash から探す src

    execute_effect(_eff(overlay, "ST30-008", "on_ko")["do"][0], st, me, opp, None)
    _drain(st)

    marco_in_play = [c for c in me.characters if c.card.card_id == "ST30-008"]
    assert len(marco_in_play) == 1, "KO時効果で マルコ がトラッシュから登場していない"
    assert marco_in_play[0].rested is True, "マルコ はレストで登場するべき"
    assert not any(c.card_id == "ST30-008" for c in me.trash), \
        "登場した マルコ がトラッシュに残ってはいけない"
    assert any(c.card_id == _P6000 for c in me.trash), \
        "捨てコストの パワー6000キャラがトラッシュに置かれていない"


def test_st30_008_on_ko_no_revive_without_p6000():
    """手札に パワー6000キャラが無ければ 捨てコスト不能 → 登場しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("ST30-008")]
    me.hand = [repo.get(_FILLER)]  # power3000 のみ = 捨てられない
    st.current_source_card_id = "ST30-008"

    execute_effect(_eff(overlay, "ST30-008", "on_ko")["do"][0], st, me, opp, None)
    _drain(st)
    assert not any(c.card.card_id == "ST30-008" for c in me.characters), \
        "捨てコスト不能なのに マルコ が登場してはいけない"


# --------------------------------------------------------------------------- #
#  ST30-009 リトルオーズJr.: 自元パワー6000キャラが相手効果で離脱する場合、
#            代わりに自身をトラッシュ + 1ドロー (replace_leave)
# --------------------------------------------------------------------------- #
def test_st30_009_replace_leave_trash_self_draw_ai():
    """自元パワー6000キャラが相手効果KO時、 代わりにリトルオーズをトラッシュ + 1ドロー。
    → 置換成立、 victim (power6000) は場に残り、 リトルオーズが消え、 手札が1枚増える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    oars = InPlay.of(repo.get("ST30-009"), sickness=False)
    victim = InPlay.of(repo.get(_P6000), sickness=False)  # 元パワー6000
    me.characters = [oars, victim]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 10

    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, \
        "元パワー6000キャラが相手効果KO時 replace_leave が成立していない"
    assert victim in me.characters, "置換成立時 victim (power6000) は場に残るべき"
    assert oars not in me.characters, "置換コストで リトルオーズがトラッシュに置かれるべき"
    assert len(me.hand) == 1, "置換 do で 1ドローが起きていない"


def test_st30_009_replace_leave_not_when_battle_ko():
    """相手効果由来でない (= by_opp_effect=False = バトルKO等) では 置換しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    oars = InPlay.of(repo.get("ST30-009"), sickness=False)
    victim = InPlay.of(repo.get(_P6000), sickness=False)
    me.characters = [oars, victim]
    me.hand = []

    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=False, leave_kind="ko",
    )
    assert replaced is False, \
        "by_opp_effect=False では replace_leave が成立してはいけない"
    assert oars in me.characters, "非該当なのに リトルオーズが消えてはいけない"


def test_st30_009_replace_leave_not_when_non_6000_victim():
    """離脱するキャラが元パワー6000でなければ 置換対象外 (= 条件を省略しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    oars = InPlay.of(repo.get("ST30-009"), sickness=False)
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # power3000 ≠ 6000
    me.characters = [oars, victim]
    me.hand = []

    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is False, \
        "元パワー6000でないキャラの離脱では置換が成立してはいけない"


# --------------------------------------------------------------------------- #
#  ST30-010 クロコダイル: 【登場時】相手のレストキャラ1枚まで 次リフレッシュ非アクティブ
# --------------------------------------------------------------------------- #
def test_st30_010_on_play_stay_rested_ai():
    """登場時: 相手のレストのキャラ1枚を 次の相手リフレッシュで非アクティブにする (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    victim.rested = True  # レスト状態 = 対象
    opp.characters = [victim]

    assert victim.stay_rested_next_refresh is False, "前提: 初期は非アクティブフラグ off"
    execute_effect(_eff(overlay, "ST30-010", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST30-010"), sickness=True))
    _drain(st)
    assert victim.stay_rested_next_refresh is True, \
        "相手のレストキャラに 次リフレッシュ非アクティブ フラグが立っていない"


def test_st30_010_on_play_no_target_when_active():
    """相手キャラが アクティブ (非レスト) なら 対象外 → フラグは立たない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    victim.rested = False  # アクティブ = 対象外
    opp.characters = [victim]

    execute_effect(_eff(overlay, "ST30-010", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST30-010"), sickness=True))
    _drain(st)
    assert victim.stay_rested_next_refresh is False, \
        "アクティブなキャラに 非アクティブ フラグが立ってはいけない (対象外)"


# --------------------------------------------------------------------------- #
#  ST30-011 バギー: 自元パワー6000キャラが相手効果で離脱する場合、
#            代わりに自身をレストにできる (replace_leave)
# --------------------------------------------------------------------------- #
def test_st30_011_replace_leave_rest_self_ai():
    """自元パワー6000キャラが相手効果KO時、 代わりにバギーをレストにできる。
    → 置換成立、 victim は場に残り、 バギーがレストになる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    baggy = InPlay.of(repo.get("ST30-011"), sickness=False)
    baggy.rested = False
    victim = InPlay.of(repo.get(_P6000), sickness=False)  # 元パワー6000
    me.characters = [baggy, victim]

    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, \
        "元パワー6000キャラが相手効果KO時 replace_leave が成立していない"
    assert victim in me.characters, "置換成立時 victim (power6000) は場に残るべき"
    assert baggy in me.characters, "バギー自身は場に残る (レストするだけ)"
    assert baggy.rested is True, "置換 do で バギーがレストになっていない"


def test_st30_011_replace_leave_not_when_non_6000():
    """離脱するキャラが元パワー6000でなければ 置換対象外。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    baggy = InPlay.of(repo.get("ST30-011"), sickness=False)
    baggy.rested = False
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # power3000 ≠ 6000
    me.characters = [baggy, victim]

    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is False, \
        "元パワー6000でないキャラの離脱では置換が成立してはいけない"
    assert baggy.rested is False, "非該当なのに バギーがレストになってはいけない"


# --------------------------------------------------------------------------- #
#  ST30-012 モンキー・D・ルフィ: 【登場時】自ドン1レストで【速攻】/
#            【アタック時】相手の【ブロッカー】キャラ1枚までをレスト
# --------------------------------------------------------------------------- #
def test_st30_012_on_play_rest_don_grants_rush_ai():
    """登場時: 自アクティブドン1枚をレスト (コスト) → 自身に【速攻】付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("ST30-012"), sickness=True)
    me.characters = [luffy]
    me.don_active = 2

    active_before = me.don_active
    execute_effect(_eff(overlay, "ST30-012", "on_play")["do"][0], st, me, opp, luffy)
    _drain(st)
    assert "速攻" in luffy.granted_keywords, "登場時に【速攻】が付与されていない"
    assert me.don_active == active_before - 1, "アクティブドンが1枚レストされていない"


def test_st30_012_on_attack_rest_opp_blocker_ai():
    """アタック時: 相手の【ブロッカー】キャラ1枚をレストにする (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    # ST30-010 クロコダイル = 【ブロッカー】(intrinsic) を持つ相手キャラ
    blocker = InPlay.of(repo.get("ST30-010"), sickness=False)
    blocker.rested = False
    assert blocker.is_blocker_now, "前提: ST30-010 は【ブロッカー】を持つ"
    opp.characters = [blocker]

    execute_effect(_eff(overlay, "ST30-012", "on_attack")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST30-012"), sickness=False))
    _drain(st)
    assert blocker.rested is True, \
        "アタック時 相手の【ブロッカー】キャラがレストされていない"


def test_st30_012_on_attack_no_blocker_no_rest():
    """相手に【ブロッカー】キャラがいなければ 対象外 → レストは起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    plain = InPlay.of(repo.get(_FILLER), sickness=False)  # ブロッカー無し
    plain.rested = False
    opp.characters = [plain]

    execute_effect(_eff(overlay, "ST30-012", "on_attack")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST30-012"), sickness=False))
    _drain(st)
    assert plain.rested is False, \
        "【ブロッカー】でないキャラがレストされてはいけない (対象外)"


# --------------------------------------------------------------------------- #
#  ST30-014 Mr.3: 【起動メイン】自レスト → 自元パワー6000キャラ2枚までにレストドン2枚ずつ
# --------------------------------------------------------------------------- #
def test_st30_014_activate_main_attach_rested_don_per_target_ai():
    """起動メイン: このキャラをレスト (コスト) → 自元パワー6000キャラ2枚に レストドン2枚ずつ付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    mr3 = InPlay.of(repo.get("ST30-014"), sickness=False)  # power3000 (対象外)
    a = InPlay.of(repo.get(_P6000), sickness=False)  # power6000
    b = InPlay.of(repo.get(_P6000), sickness=False)  # power6000
    me.characters = [mr3, a, b]
    me.don_rested = 4  # 2 targets × 2 枚 = 4 供給

    rested_before = me.don_rested
    opts = _acts(st, me, overlay, "ST30-014")
    assert len(opts) == 1, f"ST30-014 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    assert mr3.rested is True, "起動メインコストで Mr.3 がレストされていない"
    assert a.attached_dons == 2, f"元パワー6000キャラ a に レストドン2枚が付与されていない: {a.attached_dons}"
    assert b.attached_dons == 2, f"元パワー6000キャラ b に レストドン2枚が付与されていない: {b.attached_dons}"
    assert me.don_rested == rested_before - 4, "レストドンが4枚消費されるべき"


def test_st30_014_activate_main_only_targets_power6000():
    """元パワー6000でないキャラ (Mr.3 自身 power3000) には付与されない (= filter を省略しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    mr3 = InPlay.of(repo.get("ST30-014"), sickness=False)
    other = InPlay.of(repo.get(_FILLER), sickness=False)  # power3000 ≠ 6000
    me.characters = [mr3, other]
    me.don_rested = 4

    opts = _acts(st, me, overlay, "ST30-014")
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)
    assert other.attached_dons == 0, \
        "元パワー6000でないキャラに レストドンが付与されてはいけない"


# --------------------------------------------------------------------------- #
#  ST30-015 (EVENT): 【カウンター】自元パワー6000キャラ2枚以上で 自リーダー/キャラ+4000 /
#            【トリガー】相手パワー6000以下1枚KO
# --------------------------------------------------------------------------- #
def test_st30_015_counter_pump_when_two_p6000_ai():
    """カウンター: 自元パワー6000キャラが2枚以上 → 自リーダー/キャラ1枚 +4000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_P6000), sickness=False)  # power6000
    b = InPlay.of(repo.get(_P6000), sickness=False)  # power6000
    me.characters = [a, b]

    counter_eff = _eff(overlay, "ST30-015", "counter")
    assert eval_condition(counter_eff.get("if", {}), st, me, opp) is True, \
        "元パワー6000キャラ2枚で カウンター条件が成立していない"
    for prim in counter_eff["do"]:
        execute_effect(prim, st, me, opp, me.leader)
    _drain(st)
    # AI は 最高 power の 自陣 inplay (= power6000 キャラ) を選び +4000 → 10000
    assert any(c.power == 6000 + 4000 for c in me.characters), \
        "カウンターの +4000 が 自陣キャラに反映されていない"


def test_st30_015_counter_condition_off_with_one_p6000():
    """自元パワー6000キャラが1枚だけなら カウンター条件は不成立 (= 2枚以上を省略しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(_P6000), sickness=False)]  # 1 枚のみ

    counter_eff = _eff(overlay, "ST30-015", "counter")
    assert eval_condition(counter_eff.get("if", {}), st, me, opp) is False, \
        "元パワー6000キャラ1枚では カウンター条件が不成立であるべき"


def test_st30_015_trigger_ko_opp_p6000_ai():
    """トリガー: 相手のパワー6000以下のキャラ1枚をKOする (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_P6000), sickness=False)  # power6000 ≤ 6000
    opp.characters = [victim]

    for prim in _eff(overlay, "ST30-015", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert victim not in opp.characters, \
        "トリガーで 相手パワー6000以下キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  ST30-016 (EVENT): 【カウンター】自リーダー/キャラ+3000。その後 自元パワー6000の
#            「エース」と「ルフィ」がいれば 1ドロー
# --------------------------------------------------------------------------- #
def test_st30_016_counter_pump_leader_ai():
    """カウンター (1): 自リーダーを このバトル中 パワー+3000 (自陣キャラ無し → リーダー)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    leader_base = me.leader.power
    # 1 つ目の counter 効果 (= power_pump、 if 無し) を取得
    pump_eff = _eff(overlay, "ST30-016", "counter", idx=0)
    for prim in pump_eff["do"]:
        execute_effect(prim, st, me, opp, me.leader)
    _drain(st)
    assert me.leader.power == leader_base + 3000, \
        f"カウンターで 自リーダー+3000 が反映されていない: {me.leader.power}"


def test_st30_016_counter_draw_when_ace_and_luffy_ai():
    """カウンター (2): 自元パワー6000の「エース」「ルフィ」が両方いれば 1ドロー (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    ace = InPlay.of(repo.get("ST30-007"), sickness=False)   # ポートガス・D・エース power6000
    luffy = InPlay.of(repo.get("ST30-012"), sickness=False)  # モンキー・D・ルフィ power6000
    me.characters = [ace, luffy]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 10

    # 2 つ目の counter 効果 (= draw、 if self_field_named_all_with_power) を取得
    draw_eff = _eff(overlay, "ST30-016", "counter", idx=1)
    assert eval_condition(draw_eff.get("if", {}), st, me, opp) is True, \
        "「エース」「ルフィ」両方 (元パワー6000) で 条件が成立していない"
    deck_before = len(me.deck)
    for prim in draw_eff["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert len(me.deck) == deck_before - 1, "条件成立時に 1ドローが起きていない"


def test_st30_016_counter_no_draw_when_missing_one():
    """「エース」だけで「ルフィ」がいなければ 後段の1ドローは発動しない (= 条件を省略しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    ace = InPlay.of(repo.get("ST30-007"), sickness=False)  # エースのみ
    me.characters = [ace]

    draw_eff = _eff(overlay, "ST30-016", "counter", idx=1)
    assert eval_condition(draw_eff.get("if", {}), st, me, opp) is False, \
        "「ルフィ」が不在なら 1ドロー条件は不成立であるべき"
