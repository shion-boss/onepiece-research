# -*- coding: utf-8 -*-
"""カード効果 回帰テスト バックフィル (自動生成 wave 174):
ST10-008 / ST10-009 / ST10-010 / ST10-011 / ST10-012 /
ST10-013 / ST10-014 / ST10-015 / ST10-016 / ST10-017 の 10 枚
(= ST10 紫「ハートの海賊団 / キッド海賊団」+ 赤 麦わらの一味 イベント の効果カード群)。

目的 (= test_backfill_auto_001〜173.py と同一方針):
  (1) 各カードの効果が overlay / 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
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
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
    trigger_on_self_don_returned_to_deck,
)

ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------- #
#  効果の薄い (= 素材用) カード。
# --------------------------------------------------------------------------- #
NAMI = "OP01-016"       # ナミ (cost1 power2000 麦わらの一味) フィラー / 相手キャラ
SANJI = "OP01-013"      # サンジ (cost2 power3000 麦わらの一味) フィラー
LEADER = "OP01-001"     # ロロノア・ゾロ (LEADER)


def _cond_of(eff: dict) -> dict:
    """効果の発動条件を取り出す (top-level `if` / `conditional` / optional_cost_then 内 の三形対応)。

    ⚠ 2026-08-05: 公式は 「「：」以前が発動コスト」 (cardqa_st_06)。 コロン後の条件は **効果のみ**
    を gate するので、 overlay ではその条件を `conditional` の中へ移した。
    `optional_cost_then` を持つ効果では **cost を条件の外に出す** 必要があるため、
    conditional は `effect` 配列の中に入る。 条件自体は変わっていないので、
    テストはどの位置でも読めればよい。
    """
    if isinstance(eff.get("if"), dict):
        return eff["if"]
    def _dig(arr):
        for _p in arr or []:
            if not isinstance(_p, dict):
                continue
            if "conditional" in _p:
                return (_p.get("conditional") or {}).get("if") or {}
            if "optional_cost_then" in _p:
                got = _dig((_p["optional_cost_then"] or {}).get("effect") or [])
                if got:
                    return got
        return {}
    return _dig(eff.get("do") or [])


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, turn=0,
           opp_leader_id=LEADER):
    """P0 = テスト対象デッキ、 P1 = ダミー。 MAIN / turn_number=3。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(SANJI)] * 30
    p1.deck = [repo.get(SANJI)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _eff(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果を返す。
    needle 指定時は do[0] に needle キーを含む効果を返す (複数 when 同名時の分離)。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    assert matches, f"{cid} に when={when} の効果がない"
    if needle is not None:
        matches = [e for e in matches if needle in e["do"][0]]
        assert matches, f"{cid} の when={when} に do[0]={needle} の効果がない"
    return matches[0]


def _drain(st, picks=None):
    """resolve 後続の連鎖 modal を流す (guard 付き)。"""
    if picks is None:
        picks = [0]
    guard = 0
    while st.pending_choice is not None and guard < 6:
        resolve_pending_choice(st, picks)
        guard += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave174_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["ST10-008", "ST10-009", "ST10-010", "ST10-011", "ST10-012",
           "ST10-013", "ST10-014", "ST10-015", "ST10-016", "ST10-017"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  ST10-008 シャチ＆ペンギン (CHARACTER 紫 cost4 power5000):
#    【登場時】自分の場のドン!!が3枚以下の場合、ドン!!デッキからドン!!2枚までを、
#    レストで追加する。
# --------------------------------------------------------------------------- #
def test_st10_008_on_play_add_rested_don_ai():
    """【登場時】自ドン3以下 → ドンデッキからレストドン2枚を追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 2  # 場のドン 2 (= 3 以下 → 条件成立)
    me.don_rested = 0
    me.don_remaining_in_deck = 8

    eff = _eff(overlay, "ST10-008", "on_play")
    assert _cond_of(eff).get("self_don_le") == 3, \
        "overlay の 条件 self_don_le=3 が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST10-008"), sickness=True))

    assert me.don_rested == 2, f"レストドンが2枚追加されていない: {me.don_rested}"
    assert me.don_remaining_in_deck == 6, "ドンデッキから2枚供給されていない"


# --------------------------------------------------------------------------- #
#  ST10-009 ジャンバール (CHARACTER 紫 cost4 power5000):
#    【登場時】➀(コストエリアのドンをレストにできる)：ドンデッキからドン1枚までを、
#    アクティブで追加する。
# --------------------------------------------------------------------------- #
def test_st10_009_on_play_optional_cost_add_don_ai():
    """【登場時】任意コスト (ドン1レスト) → ドン1枚アクティブ追加。 AI は自動処理し crash しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    me.don_rested = 0
    me.don_remaining_in_deck = 7

    eff = _eff(overlay, "ST10-009", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST10-009"), sickness=True))
    _drain(st, [1])  # 万一 confirm が立っても pay して解決

    assert st.pending_choice is None, "AI 文脈で pending_choice が残ってはいけない"
    # AI auto-pay: ドン1レスト (active-1 rested+1) → add_don でアクティブ+1。
    # net active = 3 -1 +1 = 3、 rested = 1、 deck = 7 -1 = 6。
    assert me.don_rested == 1, f"コストで1ドンがレストされていない: {me.don_rested}"
    assert me.don_remaining_in_deck == 6, "ドンデッキから1枚供給されていない"


def test_st10_009_on_play_optional_cost_human_confirm():
    """人間 actor: 任意コストは optional_cost_confirm modal が立ち、 pay で解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    me.don_rested = 0
    me.don_remaining_in_deck = 7

    eff = _eff(overlay, "ST10-009", "on_play")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST10-009"), sickness=True))

    assert st.pending_choice is not None, "人間で任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # pay
    _drain(st, [1])
    assert me.don_remaining_in_deck == 6, "承諾後 ドンデッキから1枚供給されていない"


# --------------------------------------------------------------------------- #
#  ST10-010 トラファルガー・ロー (CHARACTER 紫 cost4 power5000):
#    【ブロッカー】【登場時】ドン!!-1：相手の手札が7枚以上ある場合、相手の手札2枚を捨てる。
# --------------------------------------------------------------------------- #
def test_st10_010_on_play_trash_opp_hand_ai():
    """【登場時】(ドン-1 コスト / 相手手札7以上) 相手の手札2枚を捨てる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.hand = [repo.get(SANJI) for _ in range(7)]  # 7 枚 (= 条件成立)

    eff = _eff(overlay, "ST10-010", "on_play")
    assert _cond_of(eff).get("opp_hand_count_ge") == 7, \
        "overlay の 条件 opp_hand_count_ge=7 が無い"
    assert eff.get("cost", {}).get("pay_don") == 1, \
        "overlay の コスト pay_don=1 が無い"

    hand_before = len(opp.hand)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST10-010"), sickness=True))

    assert len(opp.hand) == hand_before - 2, \
        f"相手の手札が2枚捨てられていない: {len(opp.hand)} (before {hand_before})"
    assert len(opp.trash) == 2, "捨てた手札がトラッシュにない"


# --------------------------------------------------------------------------- #
#  ST10-011 ヒート (CHARACTER 紫 cost3 power4000):
#    【自分のターン中】【ターン1回】自分の場のドンがドンデッキに戻された時、
#    このキャラは、次の自分のターン開始時まで、パワー+2000。
# --------------------------------------------------------------------------- #
def test_st10_011_don_returned_self_pump_ai():
    """自ターン中のドン返却トリガー → このキャラ +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay, turn=0)  # 自分のターン
    me, opp = st.players[0], st.players[1]
    heat = InPlay.of(repo.get("ST10-011"), sickness=False)  # power 4000
    me.characters = [heat]

    power_before = heat.power
    trigger_on_self_don_returned_to_deck(st, me, opp, overlay, count=1)
    _drain(st)

    assert heat.power == power_before + 2000, \
        f"ドン返却トリガーで +2000 が反映されていない: {heat.power} (before {power_before})"


def test_st10_011_no_pump_on_opp_turn():
    """相手ターン中は【自分のターン中】条件が不成立 → +0。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay, turn=1)  # 相手のターン
    me, opp = st.players[0], st.players[1]
    heat = InPlay.of(repo.get("ST10-011"), sickness=False)
    me.characters = [heat]

    power_before = heat.power
    trigger_on_self_don_returned_to_deck(st, me, opp, overlay, count=1)
    _drain(st)

    assert heat.power == power_before, \
        f"相手ターンで pump が乗ってはいけない: {heat.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  ST10-012 ベポ (CHARACTER 紫 cost4 power5000):
#    【登場時】/【アタック時】相手の場のドンの枚数が自分の場のドンの枚数より多い場合、
#    ドンデッキからドン1枚までを、レストで追加する。
# --------------------------------------------------------------------------- #
def test_st10_012_on_play_add_rested_don_ai():
    """【登場時】相手ドン > 自ドン → レストドン1枚を追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 0
    me.don_rested = 0
    me.don_remaining_in_deck = 8
    opp.don_active = 3  # 相手ドン 3 > 自ドン 0 (= 条件成立)

    eff = _eff(overlay, "ST10-012", "on_play")
    conds = eff.get("conditions", [])
    assert any("don_diff_le" in c for c in conds), \
        "overlay の 条件 don_diff_le が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST10-012"), sickness=True))

    assert me.don_rested == 1, f"レストドンが1枚追加されていない: {me.don_rested}"
    assert me.don_remaining_in_deck == 7, "ドンデッキから1枚供給されていない"


def test_st10_012_on_attack_add_rested_don_ai():
    """【アタック時】も同条件でレストドン1枚追加 (on_attack の do を直接発火)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 1
    me.don_rested = 0
    me.don_remaining_in_deck = 8
    opp.don_active = 4  # 相手 4 > 自 1

    eff = _eff(overlay, "ST10-012", "on_attack")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST10-012"), sickness=False))

    assert me.don_rested == 1, f"アタック時にレストドンが追加されていない: {me.don_rested}"


# --------------------------------------------------------------------------- #
#  ST10-013 ユースタス・キッド (CHARACTER 紫 cost7 power8000):
#    【登場時】/【アタック時】ドン!!-1：自分のリーダー1枚までを、
#    次の自分のターン開始時まで、パワー+1000。
# --------------------------------------------------------------------------- #
def test_st10_013_on_play_leader_pump_ai():
    """【登場時】(ドン-1) 自リーダーに +1000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    eff = _eff(overlay, "ST10-013", "on_play")
    assert eff.get("cost", {}).get("pay_don") == 1, "overlay の コスト pay_don=1 が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST10-013"), sickness=True))

    assert me.leader.power == power_before + 1000, \
        f"自リーダーに +1000 が反映されていない: {me.leader.power} (before {power_before})"


def test_st10_013_on_attack_leader_pump_ai():
    """【アタック時】も同じく自リーダーに +1000 (on_attack の do を直接発火)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    eff = _eff(overlay, "ST10-013", "on_attack")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST10-013"), sickness=False))

    assert me.leader.power == power_before + 1000, \
        f"アタック時に自リーダー +1000 が反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  ST10-014 ワイヤー (CHARACTER 紫 cost3 power3000):
#    【ブロッカー】【ターン1回】自分の場のドンがドンデッキに戻された時、
#    カード1枚を引き、手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_st10_014_don_returned_draw_discard_ai():
    """ドン返却トリガー → 1ドロー + 手札1捨て (AI: net 手札不変だが deck-1 / trash+1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    wire = InPlay.of(repo.get("ST10-014"), sickness=False)
    me.characters = [wire]
    me.hand = [repo.get(NAMI)]  # 捨てる元の手札
    me.deck = [repo.get(SANJI)] * 10
    me.trash = []

    hand_before = len(me.hand)
    deck_before = len(me.deck)
    trigger_on_self_don_returned_to_deck(st, me, opp, overlay, count=1)
    _drain(st)

    assert len(me.deck) == deck_before - 1, "1ドローで山札が1枚減っていない"
    assert len(me.trash) == 1, "手札1枚が捨てられていない (トラッシュに無い)"
    # net: draw +1、 discard -1 → 手札枚数は不変
    assert len(me.hand) == hand_before, \
        f"draw1 + discard1 で手札枚数が不変であるべき: {len(me.hand)}"


def test_st10_014_once_per_turn_guard():
    """【ターン1回】: 同一ターンで2度目のドン返却では発火しない (deck が減らない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    wire = InPlay.of(repo.get("ST10-014"), sickness=False)
    me.characters = [wire]
    me.hand = [repo.get(NAMI), repo.get(NAMI)]
    me.deck = [repo.get(SANJI)] * 10

    trigger_on_self_don_returned_to_deck(st, me, opp, overlay, count=1)
    _drain(st)
    deck_after_first = len(me.deck)
    assert deck_after_first == 9, "1回目で1ドローされていない"

    trigger_on_self_don_returned_to_deck(st, me, opp, overlay, count=1)
    _drain(st)
    assert len(me.deck) == deck_after_first, \
        "【ターン1回】なのに2回目も発火している (deck が更に減った)"


# --------------------------------------------------------------------------- #
#  ST10-015 ゴムゴムの巨人つっぱり (EVENT 赤 cost1):
#    【カウンター】自分のリーダーかキャラ1枚までを、このバトル中、パワー+2000し、
#    相手のパワー2000以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_st10_015_counter_ko_low_power_ai():
    """【カウンター】相手のパワー2000以下キャラ1枚を KO する (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(NAMI), sickness=False)  # power 2000 (= 対象)
    opp.characters = [victim]

    eff = _eff(overlay, "ST10-015", "counter")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert victim not in opp.characters, "パワー2000以下の相手キャラが KO されていない"
    assert any(c.card_id == NAMI for c in opp.trash), "KO されたキャラがトラッシュにない"


def test_st10_015_counter_ko_human_pick():
    """人間 + 相手のパワー2000以下キャラ 複数 → KO の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(NAMI), sickness=False)  # power 2000
    b = InPlay.of(repo.get(NAMI), sickness=False)  # power 2000
    opp.characters = [a, b]

    # do[1] = ko (do[0] = 自陣 power_pump)。 KO の対象選択 modal を検証。
    eff = _eff(overlay, "ST10-015", "counter")
    ko_prim = next(p for p in eff["do"] if "ko" in p)
    execute_effect(ko_prim, st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b not in opp.characters, "人間が選んだ相手キャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  ST10-016 ゴムゴムの猿王銃乱打 (EVENT 赤 cost5):
#    【メイン】相手のパワー7000以下のキャラ1枚までを、KOする。
#    【トリガー】自分のリーダー1枚までを、次の自分のターン終了時まで、パワー+1000。
# --------------------------------------------------------------------------- #
def test_st10_016_main_ko_le7000_ai():
    """【メイン】相手のパワー7000以下キャラ1枚を KO する (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(SANJI), sickness=False)  # power 3000 (<= 7000)
    opp.characters = [victim]

    eff = _eff(overlay, "ST10-016", "main")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert victim not in opp.characters, "パワー7000以下の相手キャラが KO されていない"
    assert any(c.card_id == SANJI for c in opp.trash), "KO されたキャラがトラッシュにない"


def test_st10_016_trigger_leader_pump_ai():
    """【トリガー】自リーダーに +1000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    eff = _eff(overlay, "ST10-016", "trigger")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 1000, \
        f"トリガーで自リーダー +1000 が反映されていない: {me.leader.power}"


def test_st10_016_main_ko_human_pick():
    """人間 + 相手のパワー7000以下キャラ 複数 → KO の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(SANJI), sickness=False)  # power 3000
    b = InPlay.of(repo.get(NAMI), sickness=False)   # power 2000
    opp.characters = [a, b]

    eff = _eff(overlay, "ST10-016", "main")
    execute_effect(eff["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    _drain(st, [a_idx])
    assert a not in opp.characters, "人間が選んだ相手キャラが KO されていない"
    assert b in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  ST10-017 磁気万力 (EVENT 紫 cost3):
#    【メイン】相手のコスト2以下のキャラ1枚までを、レストにし、
#    ドンデッキからドン1枚までを、レストで追加する。
#    【トリガー】ドンデッキからドン1枚までを、アクティブで追加する。
# --------------------------------------------------------------------------- #
def test_st10_017_main_rest_and_add_don_ai():
    """【メイン】相手コスト2以下キャラ1枚をレスト + レストドン1枚追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 0
    me.don_remaining_in_deck = 8
    victim = InPlay.of(repo.get(NAMI), sickness=False)  # cost1 (<= 2)
    victim.rested = False
    opp.characters = [victim]

    eff = _eff(overlay, "ST10-017", "main")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert victim.rested is True, "相手コスト2以下キャラがレストされていない"
    assert me.don_rested == 1, f"レストドンが1枚追加されていない: {me.don_rested}"
    assert me.don_remaining_in_deck == 7, "ドンデッキから1枚供給されていない"


def test_st10_017_trigger_add_active_don_ai():
    """【トリガー】ドンデッキからドン1枚をアクティブで追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 0
    me.don_remaining_in_deck = 8

    eff = _eff(overlay, "ST10-017", "trigger")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)

    assert me.don_active == 1, f"トリガーでアクティブドンが追加されていない: {me.don_active}"
    assert me.don_remaining_in_deck == 7, "ドンデッキから1枚供給されていない"


def test_st10_017_main_rest_human_pick():
    """人間 + 相手コスト2以下キャラ 複数 → rest の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_remaining_in_deck = 8
    a = InPlay.of(repo.get(NAMI), sickness=False)   # cost1
    b = InPlay.of(repo.get(SANJI), sickness=False)  # cost2
    a.rested = False
    b.rested = False
    opp.characters = [a, b]

    eff = _eff(overlay, "ST10-017", "main")
    rest_prim = next(p for p in eff["do"] if "rest" in p)
    execute_effect(rest_prim, st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で rest modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b.rested is True, "人間が選んだ相手キャラがレストされていない"
    assert a.rested is False, "選ばなかったキャラはレストされないべき"
