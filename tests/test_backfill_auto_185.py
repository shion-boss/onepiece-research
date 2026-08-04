# -*- coding: utf-8 -*-
"""ST26 / ST27 / ST28 弾 効果 回帰テスト バックフィル (自動生成 wave 185):
ST26-001 / ST26-002 / ST26-003 / ST26-004 / ST27-001 / ST27-002 /
ST27-003 / ST27-004 / ST27-005 / ST28-001 の 10 枚。

  ST26-001 おそばマスク (CHARACTER 紫) = 手札のこのカードは 元々パワー7000以上の
     「サン五郎」か「サンジ」がいれば コスト-5 / 【登場時】自分の「サン五郎」と「サンジ」
     すべてを 持ち主の手札に戻す
     (in_hand in_hand_cost_minus if self_chara_filtered_count_ge, on_play return_to_hand_multi)
  ST26-002 トニートニー・チョッパー (CHARACTER 紫) = 【ブロッカー】【登場時】ドン-2：
     相手のコスト1以下のキャラかドン1枚までを レストにする
     (on_play rest one_opp_chara_or_don cost_le 1, cost pay_don 2)
  ST26-003 ニコ・ロビン (CHARACTER 紫) = 【登場時】ドン-2：ドンデッキからドン1枚までを
     アクティブで追加 (on_play add_don 1, cost pay_don 2)
  ST26-004 フランキー将軍 (CHARACTER 紫) = 【登場時】ドン-2：相手のキャラ2枚までを
     このターン中 パワー-2000 (on_play power_pump all_opponent_chara_filtered limit 2, cost pay_don 2)
  ST27-001 アバロ・ピサロ (CHARACTER 黒) = 【起動メイン】【ターン1回】自「ハチノス」1枚を
     レストにできる：黒ひげ海賊団 leader なら このターン中 パワー+4000 /【KO時】1枚引く
     (activate_main power_pump self if leader_feature, cost once_per_turn+rest_self_target_name; on_ko draw)
  ST27-002 カタリーナ・デボン (CHARACTER 黒) = 【起動メイン】このキャラをトラッシュ：
     黒ひげ海賊団 leader なら 相手キャラ1枚まで このターン中 コスト-1 /【KO時】1枚引く
     (activate_main cost_minus one_opponent_character_any if leader_feature, cost trash_self; on_ko draw)
  ST27-003 クザン (CHARACTER 黒) = 【ブロッカー】【KO時】自トラッシュからコスト5以下の
     黒ひげ海賊団キャラ1枚までを レストで登場
     (on_ko play_from_trash filter cost_le 5 feature 黒ひげ海賊団 rested)
  ST27-004 サンファン・ウルフ (CHARACTER 黒) = 黒ひげ海賊団 leader なら【ブロッカー】獲得 +
     自トラッシュ4枚につきコスト+1 /【登場時】自手札1枚を捨てる
     (static on_attached_don give_keyword+set_base_cost delta_per if leader_feature, on_play trash_self_hand_random)
  ST27-005 マーシャル・Ｄ・ティーチ (CHARACTER 黒) = 【起動メイン】このキャラをレスト：
     コスト3以下のキャラ1枚までを KO /【KO時】自トラッシュから黒のカード1枚までを手札に加える
     (activate_main ko cost_le_3 cost rest_self; on_ko trash_to_hand filter color 黒)
  ST28-001 アシュラ童子 (CHARACTER 黄) = 【登場時】ワノ国 leader かつ相手ライフ3枚以上なら
     相手の元々コスト5以下のキャラ1枚までを KO
     (on_play ko cost_le_5 if leader_feature ワノ国 & opp_life_ge 3)

目的 (= test_backfill_auto_001〜184.py と同一方針):
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
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)
from engine.game import _compute_in_hand_cost_minus

ROOT = Path(__file__).resolve().parent.parent

_LEADER_BB = "OP09-081"      # マーシャル・Ｄ・ティーチ (四皇/黒ひげ海賊団) — 黒ひげ海賊団 leader
_LEADER_WANO = "EB01-001"    # 光月おでん (ワノ国/光月家) — ワノ国 leader
_LEADER_PLAIN = "OP01-001"   # ロロノア・ゾロ — 汎用 (黒ひげ/ワノ国 でない相手役)
_FILLER = "OP01-013"         # サンジ cost2 power3000 麦わらの一味
_NAMI = "OP01-016"           # ナミ cost1 power2000 麦わらの一味
_BIG_C = "PRB02-013"         # ゲッコー・モリア cost6 power7000
_SANGORO = "OP05-065"        # サン五郎 power8000 (= 元々パワー7000以上)
_HACHINOSU = "OP09-099"      # ハチノス (STAGE 黒ひげ海賊団)
_BB_CHEAP = "OP16-107"       # ジーザス・バージェス cost3 黒ひげ海賊団 (トラッシュ登場駒)


def _cond_of(eff: dict) -> dict:
    """効果の発動条件を取り出す (top-level `if` / `conditional` の両対応)。

    ⚠ 2026-08-05: 公式は 「〜できる：<条件>の場合、<効果>」 のコロン後の条件を **効果のみ** の
    gate とする (cardqa_op_02 / cardqa_st_04)。 top-level `if` に置くと **任意コストの支払いごと
    消える** ので、 overlay ではこの形の条件を `conditional` の中に移した。
    条件そのものは変わっていないので、 テストはどちらの位置でも読めればよい。
    """
    if isinstance(eff.get("if"), dict):
        return eff["if"]
    for _prim in eff.get("do") or []:
        if isinstance(_prim, dict) and "conditional" in _prim:
            return (_prim.get("conditional") or {}).get("if") or {}
    return {}


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


def _acts(st, me, overlay, cid):
    return [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == cid]


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave185_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["ST26-001", "ST26-002", "ST26-003", "ST26-004", "ST27-001",
           "ST27-002", "ST27-003", "ST27-004", "ST27-005", "ST28-001"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  ST26-001 おそばマスク: 手札コスト-5 (元々P7000以上のサン五郎/サンジがいる場合) /
#            【登場時】サン五郎・サンジ すべてを手札に戻す
# --------------------------------------------------------------------------- #
def test_st26_001_in_hand_cost_minus_when_big_sangoro():
    """元々パワー7000以上の「サン五郎」が場にいる → 手札のこのカードは コスト-5。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me = st.players[0]
    me.characters = [InPlay.of(repo.get(_SANGORO), sickness=False)]  # サン五郎 8000

    reduction = _compute_in_hand_cost_minus(st, me, repo.get("ST26-001"))
    assert reduction == 5, \
        f"元々P7000以上のサン五郎がいる時 in_hand コスト-5 が効いていない: {reduction}"


def test_st26_001_in_hand_no_reduction_without_big_sanji():
    """元々パワー7000以上の サン五郎/サンジ がいなければ コスト軽減は 0 (= 条件省略なし)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me = st.players[0]
    # サンジ(OP01-013 power3000) は「元々パワー7000以上」条件を満たさない
    me.characters = [InPlay.of(repo.get(_FILLER), sickness=False)]

    reduction = _compute_in_hand_cost_minus(st, me, repo.get("ST26-001"))
    assert reduction == 0, \
        f"条件 (元々P7000以上) 未成立で コスト軽減が乗ってはいけない: {reduction}"


def test_st26_001_on_play_return_self_sanji_sangoro():
    """【登場時】自分の「サン五郎」と「サンジ」すべてを 持ち主の手札に戻す。

    return_to_hand_multi に self-owned (me.characters) の bounce 分岐が入り、
    対象の自キャラが実際に手札へ戻る (非対象キャラは残る)。
    """
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    sangoro = InPlay.of(repo.get(_SANGORO), sickness=False)  # サン五郎
    sanji = InPlay.of(repo.get(_FILLER), sickness=False)     # サンジ
    nami = InPlay.of(repo.get(_NAMI), sickness=False)        # ナミ (非対象)
    me.characters = [sangoro, sanji, nami]
    me.hand = []
    hand_before = len(me.hand)

    src = InPlay.of(repo.get("ST26-001"), sickness=True)
    for prim in _eff(overlay, "ST26-001", "on_play")["do"]:
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    # サン五郎・サンジ は場から消え、 持ち主 (me) の手札へ戻る
    remaining = [c.card.card_id for c in me.characters]
    assert _SANGORO not in remaining, "サン五郎 が場から手札に戻っていない"
    assert _FILLER not in remaining, "サンジ が場から手札に戻っていない"
    assert _NAMI in remaining, "非対象の ナミ まで戻してはいけない"
    hand_ids = [c.card_id for c in me.hand]
    assert _SANGORO in hand_ids and _FILLER in hand_ids, \
        f"戻したキャラが 持ち主の手札に入っていない: {hand_ids}"
    assert len(me.hand) == hand_before + 2, \
        f"手札が2枚増えていない: {len(me.hand)}"


# --------------------------------------------------------------------------- #
#  ST26-002 トニートニー・チョッパー: 【登場時】ドン-2：相手のコスト1以下のキャラか
#            ドン1枚までを レストにする
# --------------------------------------------------------------------------- #
def test_st26_002_on_play_rest_opp_cost1_ai():
    """相手のコスト1以下キャラ (アクティブ) を レストにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_NAMI), sickness=False)  # cost1 <= 1
    opp.characters = [victim]

    for prim in _eff(overlay, "ST26-002", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST26-002"), sickness=True))
    _drain(st)

    assert victim.rested is True, "相手のコスト1以下キャラがレストにされていない"


def test_st26_002_on_play_rest_human_pick():
    """人間 + 相手コスト1キャラ複数 → target_pick modal で 1 体をレストにできる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_NAMI), sickness=False)
    b = InPlay.of(repo.get(_NAMI), sickness=False)
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "ST26-002", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST26-002"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で レスト選択 modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b.rested is True, "人間が選んだ相手キャラがレストにされていない"
    assert a.rested is False, "選ばなかったキャラはレストされないべき"


# --------------------------------------------------------------------------- #
#  ST26-003 ニコ・ロビン: 【登場時】ドン-2：ドンデッキからドン1枚までをアクティブで追加
# --------------------------------------------------------------------------- #
def test_st26_003_on_play_add_don_ai():
    """ドンデッキからドン1枚をアクティブで追加 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 0
    active_before = me.don_active
    rem_before = me.don_remaining_in_deck

    for prim in _eff(overlay, "ST26-003", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST26-003"), sickness=True))
    _drain(st)

    assert me.don_active == active_before + 1, \
        f"ドン1枚がアクティブで追加されていない: {me.don_active}"
    assert me.don_remaining_in_deck == rem_before - 1, \
        "ドンデッキ残数が1枚減るべき"


# --------------------------------------------------------------------------- #
#  ST26-004 フランキー将軍: 【登場時】ドン-2：相手のキャラ2枚までを このターン中 -2000
# --------------------------------------------------------------------------- #
def test_st26_004_on_play_debuff_two_ai():
    """相手キャラ2枚を このターン中 パワー-2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)  # power3000
    b = InPlay.of(repo.get(_NAMI), sickness=False)    # power2000
    opp.characters = [a, b]
    a_before, b_before = a.power, b.power

    for prim in _eff(overlay, "ST26-004", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST26-004"), sickness=True))
    _drain(st)

    assert a.power == a_before - 2000, f"a に -2000 が乗っていない: {a.power}"
    assert b.power == b_before - 2000, f"b に -2000 が乗っていない: {b.power}"


def test_st26_004_on_play_debuff_human_pick():
    """人間 + 相手キャラ3体 (limit2) → target_pick modal が立ち 2 体を選んで -2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_NAMI), sickness=False)
    c = InPlay.of(repo.get(_BIG_C), sickness=False)
    opp.characters = [a, b, c]

    execute_effect(_eff(overlay, "ST26-004", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST26-004"), sickness=True))
    assert st.pending_choice is not None, "人間 + 3体で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 3, f"候補が3体でない: {len(cands)}"
    a_idx = next(i for i, x in enumerate(cands) if x["iid"] == a.instance_id)
    b_idx = next(i for i, x in enumerate(cands) if x["iid"] == b.instance_id)
    a_before, b_before, c_before = a.power, b.power, c.power
    resolve_pending_choice(st, [a_idx, b_idx])
    _drain(st)
    assert a.power == a_before - 2000, "人間が選んだ a に -2000 が乗っていない"
    assert b.power == b_before - 2000, "人間が選んだ b に -2000 が乗っていない"
    assert c.power == c_before, "選ばなかった c に -2000 が乗ってはいけない"


# --------------------------------------------------------------------------- #
#  ST27-001 アバロ・ピサロ: 【起動メイン】【ターン1回】自ハチノス1枚レスト：
#            黒ひげ海賊団 leader なら +4000 /【KO時】1枚引く
# --------------------------------------------------------------------------- #
def test_st27_001_activate_main_self_pump_ai():
    """起動メイン: ハチノスをレスト (コスト) → 黒ひげ leader なら 自身 +4000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_BB, overlay)
    me, opp = st.players[0], st.players[1]
    pisaro = InPlay.of(repo.get("ST27-001"), sickness=False)
    hachi = InPlay.of(repo.get(_HACHINOSU), sickness=False)
    me.characters = [pisaro]
    me.stages = [hachi]

    power_before = pisaro.power
    eff = _eff(overlay, "ST27-001", "activate_main")
    assert _cond_of(eff).get("leader_feature") == "黒ひげ海賊団", \
        "overlay の 黒ひげ海賊団 leader 条件が無い"
    opts = _acts(st, me, overlay, "ST27-001")
    assert len(opts) == 1, f"ST27-001 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    assert pisaro.power == power_before + 4000, \
        f"起動メインの 自己 +4000 が反映されていない: {pisaro.power}"
    assert hachi.rested is True, "起動メインコストで ハチノス がレストされるべき"


def test_st27_001_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_BB, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("ST27-001"), sickness=False)]
    me.stages = [InPlay.of(repo.get(_HACHINOSU), sickness=False)]

    opts1 = _acts(st, me, overlay, "ST27-001")
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st)
    opts2 = _acts(st, me, overlay, "ST27-001")
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


def test_st27_001_activate_main_requires_hachinos():
    """コストの「自ハチノス1枚をレスト」が払えない (ハチノス不在) → 起動メインが legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_BB, overlay)
    me, _opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("ST27-001"), sickness=False)]
    # me.stages 空 = ハチノス無し

    opts = _acts(st, me, overlay, "ST27-001")
    assert len(opts) == 0, "ハチノスが無いのに起動メインが legal に出てはいけない"


def test_st27_001_on_ko_draw_ai():
    """【KO時】カード1枚を引く (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_BB, overlay)
    me, opp = st.players[0], st.players[1]
    deck_before = len(me.deck)

    for prim in _eff(overlay, "ST27-001", "on_ko")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST27-001"), sickness=False))
    _drain(st)

    assert len(me.deck) == deck_before - 1, "KO時の 1ドローでデッキが1枚減っていない"


# --------------------------------------------------------------------------- #
#  ST27-002 カタリーナ・デボン: 【起動メイン】このキャラをトラッシュ：
#            黒ひげ海賊団 leader なら 相手キャラ1枚まで コスト-1 /【KO時】1枚引く
# --------------------------------------------------------------------------- #
def test_st27_002_activate_main_opp_cost_minus_ai():
    """起動メイン: 自身をトラッシュ (コスト) → 相手キャラ1枚を このターン中 コスト-1 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_BB, overlay)
    me, opp = st.players[0], st.players[1]
    debon = InPlay.of(repo.get("ST27-002"), sickness=False)
    me.characters = [debon]
    victim_def = repo.get(_FILLER)  # cost2
    victim = InPlay.of(victim_def, sickness=False)
    opp.characters = [victim]

    eff = _eff(overlay, "ST27-002", "activate_main")
    assert _cond_of(eff).get("leader_feature") == "黒ひげ海賊団", \
        "overlay の 黒ひげ海賊団 leader 条件が無い"
    opts = _acts(st, me, overlay, "ST27-002")
    assert len(opts) == 1, f"ST27-002 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    assert debon not in me.characters, "起動コストで自身がトラッシュに置かれていない"
    assert victim.base_cost == victim_def.cost - 1, \
        f"相手キャラの コスト-1 が反映されていない: {victim.base_cost} (print {victim_def.cost})"


def test_st27_002_activate_main_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal が立ち 1 体を選んで コスト-1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_BB, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("ST27-002"), sickness=False)]
    a_def, b_def = repo.get(_FILLER), repo.get(_NAMI)
    a = InPlay.of(a_def, sickness=False)
    b = InPlay.of(b_def, sickness=False)
    opp.characters = [a, b]

    opts = _acts(st, me, overlay, "ST27-002")
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b.base_cost == b_def.cost - 1, "人間が選んだ相手キャラに コスト-1 が反映されていない"


def test_st27_002_on_ko_draw_ai():
    """【KO時】カード1枚を引く (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_BB, overlay)
    me, opp = st.players[0], st.players[1]
    deck_before = len(me.deck)

    for prim in _eff(overlay, "ST27-002", "on_ko")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST27-002"), sickness=False))
    _drain(st)

    assert len(me.deck) == deck_before - 1, "KO時の 1ドローでデッキが1枚減っていない"


# --------------------------------------------------------------------------- #
#  ST27-003 クザン: 【KO時】自トラッシュからコスト5以下の黒ひげ海賊団キャラ1枚まで
#            を レストで登場
# --------------------------------------------------------------------------- #
def test_st27_003_on_ko_play_from_trash_ai():
    """KO時: 自トラッシュのコスト5以下の黒ひげ海賊団キャラを レストで登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_BB, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(_BB_CHEAP)]  # ジーザス・バージェス cost3 黒ひげ海賊団

    for prim in _eff(overlay, "ST27-003", "on_ko")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST27-003"), sickness=False))
    _drain(st)

    played = [c for c in me.characters if c.card.card_id == _BB_CHEAP]
    assert len(played) == 1, "トラッシュの黒ひげ海賊団キャラが登場していない"
    assert played[0].rested is True, "登場したキャラは レスト状態であるべき"


def test_st27_003_on_ko_ignores_non_blackbeard_trash():
    """トラッシュに 黒ひげ海賊団 でないキャラしか無ければ 登場しない (= 特徴条件を省略しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_BB, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(_FILLER)]  # サンジ (麦わらの一味、 黒ひげ海賊団 でない)

    for prim in _eff(overlay, "ST27-003", "on_ko")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST27-003"), sickness=False))
    _drain(st)

    assert all(c.card.card_id != _FILLER for c in me.characters), \
        "黒ひげ海賊団 でないキャラを登場させてはいけない"


# --------------------------------------------------------------------------- #
#  ST27-004 サンファン・ウルフ: 黒ひげ海賊団 leader なら【ブロッカー】+ トラッシュ4枚
#            につきコスト+1 /【登場時】自手札1枚を捨てる
# --------------------------------------------------------------------------- #
def test_st27_004_on_play_discard_ai():
    """登場時: 自手札1枚をランダムに捨てる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_BB, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER), repo.get(_NAMI)]
    hand_before = len(me.hand)
    trash_before = len(me.trash)

    for prim in _eff(overlay, "ST27-004", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST27-004"), sickness=True))
    _drain(st)

    assert len(me.hand) == hand_before - 1, "登場時に手札が1枚捨てられていない"
    assert len(me.trash) == trash_before + 1, "捨てた1枚がトラッシュに置かれていない"


def test_st27_004_static_blocker_and_cost_per_trash():
    """黒ひげ leader → ブロッカー付与 + 自トラッシュ4枚につき コスト+1 (静的)。
    トラッシュ8枚 → +2 (= base_cost 4 → 6)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_BB, overlay)
    me, _opp = st.players[0], st.players[1]
    wolf_def = repo.get("ST27-004")  # cost4
    wolf = InPlay.of(wolf_def, sickness=False)
    me.characters = [wolf]
    me.trash = [repo.get(_FILLER)] * 8  # 8 / 4 = +2

    evaluate_static_effects(st, overlay)
    assert wolf.is_blocker_now is True, \
        "黒ひげ leader で ブロッカー が付与されていない"
    assert wolf.base_cost == wolf_def.cost + 2, \
        f"トラッシュ8枚で コスト+2 が反映されていない: {wolf.base_cost} (print {wolf_def.cost})"


def test_st27_004_static_no_blocker_off_blackbeard():
    """黒ひげ以外の leader では ブロッカー付与 / コスト増加 は起きない (= leader 条件を省略しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, _opp = st.players[0], st.players[1]
    wolf_def = repo.get("ST27-004")
    wolf = InPlay.of(wolf_def, sickness=False)
    me.characters = [wolf]
    me.trash = [repo.get(_FILLER)] * 8

    evaluate_static_effects(st, overlay)
    assert wolf.is_blocker_now is False, "黒ひげ以外の leader で ブロッカー が付いてはいけない"
    assert wolf.base_cost == wolf_def.cost, \
        f"黒ひげ以外の leader で コスト増加してはいけない: {wolf.base_cost}"


# --------------------------------------------------------------------------- #
#  ST27-005 マーシャル・Ｄ・ティーチ: 【起動メイン】このキャラをレスト：
#            コスト3以下のキャラ1枚まで KO /【KO時】自トラッシュから黒のカード1枚まで手札
# --------------------------------------------------------------------------- #
def test_st27_005_activate_main_ko_cost3_ai():
    """起動メイン: 自身をレスト (コスト) → コスト3以下の相手キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_BB, overlay)
    me, opp = st.players[0], st.players[1]
    teach = InPlay.of(repo.get("ST27-005"), sickness=False)
    me.characters = [teach]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 <= 3
    opp.characters = [victim]

    opts = _acts(st, me, overlay, "ST27-005")
    assert len(opts) == 1, f"ST27-005 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    assert victim not in opp.characters, "コスト3以下の相手キャラが KO されていない"
    assert teach.rested is True, "起動メインコストで ティーチ がレストされるべき"


def test_st27_005_activate_main_ko_human_pick():
    """人間 + コスト3以下の相手キャラ複数 → target_pick modal が立ち 1 体を KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_BB, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("ST27-005"), sickness=False)]
    a = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    b = InPlay.of(repo.get(_NAMI), sickness=False)    # cost1
    opp.characters = [a, b]

    opts = _acts(st, me, overlay, "ST27-005")
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])
    assert st.pending_choice is not None, "人間 + 複数候補で KO 選択 modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


def test_st27_005_on_ko_trash_to_hand_black_ai():
    """KO時: 自トラッシュから 黒のカード1枚を手札に加える (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_BB, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("ST27-001")]  # 黒
    me.hand = []

    for prim in _eff(overlay, "ST27-005", "on_ko")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST27-005"), sickness=False))
    _drain(st)

    assert any(c.card_id == "ST27-001" for c in me.hand), \
        "トラッシュの黒カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  ST28-001 アシュラ童子: 【登場時】ワノ国 leader かつ相手ライフ3枚以上なら
#            相手の元々コスト5以下のキャラ1枚までを KO
# --------------------------------------------------------------------------- #
def test_st28_001_on_play_ko_when_wano_and_life3_ai():
    """ワノ国 leader + 相手ライフ3枚以上 → 元々コスト5以下の相手キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WANO, overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_FILLER)] * 3  # ライフ 3 (= 条件成立)
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 <= 5
    opp.characters = [victim]

    eff = _eff(overlay, "ST28-001", "on_play")
    assert _cond_of(eff).get("leader_feature") == "ワノ国", \
        "overlay の ワノ国 leader 条件が無い"
    assert _cond_of(eff).get("opp_life_ge") == 3, \
        "overlay の 相手ライフ3枚以上条件が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST28-001"), sickness=True))
    _drain(st)

    assert victim not in opp.characters, "元々コスト5以下の相手キャラが KO されていない"


def test_st28_001_condition_off_when_life_low():
    """相手ライフが2枚 (< 3) なら 条件不成立 (= KO 発動しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WANO, overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_FILLER)] * 2
    eff = _eff(overlay, "ST28-001", "on_play")
    assert eval_condition(_cond_of(eff), st, me, opp) is False, \
        "相手ライフ2枚では条件が不成立であるべき"


def test_st28_001_condition_off_when_plain_leader():
    """ワノ国 でない leader なら 条件不成立 (= KO 発動しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_FILLER)] * 3
    eff = _eff(overlay, "ST28-001", "on_play")
    assert eval_condition(_cond_of(eff), st, me, opp) is False, \
        "ワノ国 でない leader では条件が不成立であるべき"


def test_st28_001_on_play_ko_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal が立ち 1 体を KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WANO, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_FILLER)] * 3
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_NAMI), sickness=False)
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "ST28-001", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST28-001"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で KO 選択 modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"
