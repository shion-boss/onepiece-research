# -*- coding: utf-8 -*-
"""OP15 弾 効果 回帰テスト バックフィル (自動生成 wave 140):
OP15-018 / OP15-019 / OP15-020 / OP15-021 / OP15-022 /
OP15-023 / OP15-024 / OP15-027 / OP15-028 / OP15-029 の 10 枚。

目的 (= test_backfill_auto_001〜139.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 を 持つカードは 人間 actor で pending_choice が
      正しい kind + 候補で立ち、 resolve_pending_choice で解決できる (= 人間が選べる)
  (3) 同じ効果を AI 文脈 (human_player_idx=None) で回しても crash せず自動解決する
      (= AI が選べる)
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
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
from engine.deck import CardRepository

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001",
           turn_player=0):
    """P0 = テスト対象デッキ、 P1 = ダミー。 MAIN / turn_number=3。
    デッキは効果の薄いカード (OP01-016 ナミ) で埋める。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("OP01-016")] * 30
    p1.deck = [repo.get("OP01-016")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn_player
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果の (do 配列, eff) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        # ⚠ 2026-08-05: コロン後の条件を conditional / optional_cost_then の中へ移したため、
        #   目的の primitive が入れ子になっている。 平坦化して探す。
        def _flat(arr):
            out = []
            for _p in arr or []:
                if not isinstance(_p, dict):
                    continue
                if "conditional" in _p:
                    out += _flat((_p["conditional"] or {}).get("do"))
                elif "optional_cost_then" in _p:
                    out += _flat((_p["optional_cost_then"] or {}).get("effect"))
                else:
                    out.append(_p)
            return out
        for e in matches:
            if any(needle in prim for prim in _flat(e["do"])):
                return e["do"], e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]["do"], matches[0]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op15_wave140_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP15-018", "OP15-019", "OP15-020", "OP15-021", "OP15-022",
           "OP15-023", "OP15-024", "OP15-027", "OP15-028", "OP15-029"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP15-018 モージ (CHARACTER 赤 cost2 power3000):
#    【アタック時】相手のドン‼が付与されているパワー3000以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op15_018_on_attack_ko_attached_don_p3000_ai():
    """アタック時: 付与ドン持ち かつ 現在パワー3000以下 の相手キャラをKO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    oc = InPlay.of(repo.get("OP01-016"), sickness=False)  # base power2000
    oc.attached_dons = 1  # 付与ドン → 対象化 (2000+1000=3000 ≤ 3000)
    opp.characters = [oc]

    do, _ = _do(overlay, "OP15-018", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-018"), sickness=False))
    _drain(st, [0])
    assert oc not in opp.characters, \
        "アタック時に 付与ドン持ちP3000以下の相手キャラがKOされていない"


def test_op15_018_on_attack_no_attached_don_survives():
    """付与ドンの無い相手キャラは 対象外 (= KO されない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    oc = InPlay.of(repo.get("OP01-016"), sickness=False)  # 付与ドン 0
    opp.characters = [oc]

    do, _ = _do(overlay, "OP15-018", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-018"), sickness=False))
    _drain(st, [0])
    assert oc in opp.characters, \
        "付与ドンの無い相手キャラをKOしてはいけない (対象外)"


def test_op15_018_on_attack_human_pick():
    """人間 + 対象複数 → target_pick modal が立ち resolve で選んだ1枚のみKO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False); a.attached_dons = 1
    b = InPlay.of(repo.get("OP01-016"), sickness=False); b.attached_dons = 1
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP15-018", "on_attack")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP15-018"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b not in opp.characters, "人間が選んだ相手キャラがKOされていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP15-019 バリア突進牛 (EVENT 赤 cost3):
#    【メイン】カード1枚を引き、自分のリーダーを、次の相手のエンドフェイズ終了時まで、パワー+1000。
#    【トリガー】相手のキャラ1枚までを、このターン中、パワー-4000。
# --------------------------------------------------------------------------- #
def test_op15_019_main_draw_and_leader_pump_ai():
    """メイン: カード1枚ドロー + 自リーダー +1000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-016")] * 2

    hand_before = len(me.hand)
    power_before = me.leader.power
    do, _ = _do(overlay, "OP15-019", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert len(me.hand) == hand_before + 1, "メインで1枚ドローされていない"
    assert me.leader.power == power_before + 1000, \
        f"自リーダー +1000 が反映されていない: {me.leader.power} (before {power_before})"


def test_op15_019_trigger_debuff_opp_minus_4000_ai():
    """トリガー: 相手キャラ1枚を このターン中 -4000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    oc = InPlay.of(repo.get("OP01-013"), sickness=False)  # power3000
    opp.characters = [oc]

    do, _ = _do(overlay, "OP15-019", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert oc.turn_buff == -4000, \
        f"トリガーで相手キャラ -4000 (turn) が反映されていない: turn_buff={oc.turn_buff}"


# --------------------------------------------------------------------------- #
#  OP15-020 火拳 (EVENT 赤 cost7):
#    【メイン】自分のリーダーを、このターン中、パワー+3000し、相手のキャラ1枚までを、
#      次の相手のエンドフェイズ終了時まで、パワー-8000。その後、自分の手札2枚を捨ててもよい。
#      そうした場合、相手のパワー0以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op15_020_main_pump_debuff_then_ko_ai():
    """メイン: 自リーダー+3000 / 相手キャラ-8000 → 手札2捨て → P0以下KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    oc = InPlay.of(repo.get("OP01-016"), sickness=False)  # power2000
    opp.characters = [oc]
    me.hand = [repo.get("OP01-016")] * 3  # 捨てるコスト用

    power_before = me.leader.power
    hand_before = len(me.hand)
    do, _ = _do(overlay, "OP15-020", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert me.leader.power == power_before + 3000, \
        f"自リーダー +3000 が反映されていない: {me.leader.power}"
    assert len(me.hand) == hand_before - 2, \
        f"任意コストで手札2枚が捨てられていない: {len(me.hand)}"
    assert oc not in opp.characters, \
        "-8000 でパワー0以下になった相手キャラが (手札2捨て後) KOされていない"


# --------------------------------------------------------------------------- #
#  OP15-021 見てろよ!エース!!! (EVENT 赤 cost4):
#    手札のこのカードは、自分のトラッシュにイベントが4枚以上ある場合、コスト-3。
#    【メイン】/【カウンター】相手のキャラ1枚までを、このターン中、パワー-3000。
# --------------------------------------------------------------------------- #
def test_op15_021_in_hand_cost_minus_with_4_events():
    """トラッシュにイベント4枚以上で 手札のこのカードはコスト-3。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    me.trash = [repo.get("OP10-097")] * 4  # EVENT 4枚 (= 条件成立)
    assert _compute_in_hand_cost_minus(st, me, repo.get("OP15-021")) == 3, \
        "トラッシュ EVENT 4枚で 手札コスト -3 が計算されていない"


def test_op15_021_in_hand_no_reduction_with_3_events():
    """トラッシュのイベントが3枚では コスト軽減は無い (= 4枚未満)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    me.trash = [repo.get("OP10-097")] * 3  # EVENT 3枚
    assert _compute_in_hand_cost_minus(st, me, repo.get("OP15-021")) == 0, \
        "トラッシュ EVENT 3枚でコスト軽減が発生してはいけない"


def test_op15_021_main_debuff_opp_minus_3000_ai():
    """メイン: 相手キャラ1枚を このターン中 -3000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    oc = InPlay.of(repo.get("OP01-013"), sickness=False)  # power3000
    opp.characters = [oc]

    do, _ = _do(overlay, "OP15-021", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert oc.turn_buff == -3000, \
        f"メインで相手キャラ -3000 (turn) が反映されていない: turn_buff={oc.turn_buff}"


def test_op15_021_counter_debuff_human_pick():
    """カウンター + 相手キャラ複数 → target_pick modal が立ち resolve で選んだ1枚に -3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)
    b = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP15-021", "counter")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b.turn_buff == -3000, "人間が選んだ相手キャラに -3000 が乗っていない"
    assert a.turn_buff == 0, "選ばなかったキャラに debuff が乗ってはいけない"


# --------------------------------------------------------------------------- #
#  OP15-022 ブルック (LEADER 緑/黒 power5000):
#    【起動メイン】【ターン1回】自分のデッキの上から4枚をトラッシュに置く。
#      その後、自分のデッキが0枚の場合、自分のキャラ1枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_op15_022_activate_mill4_then_untap_when_deck_empty_ai():
    """起動メイン: デッキ上4枚トラッシュ → デッキ0枚なら 自キャラ1枚アクティブ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP15-022", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP01-016")] * 4  # ちょうど4枚 → mill 後 デッキ0枚
    ch = InPlay.of(repo.get("OP01-016"), sickness=False)
    ch.rested = True
    me.characters = [ch]

    trash_before = len(me.trash)
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP15-022"]
    assert len(opts) == 1, \
        f"OP15-022 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert len(me.deck) == 0, f"デッキ上4枚がトラッシュされていない: deck={len(me.deck)}"
    assert len(me.trash) == trash_before + 4, "トラッシュに4枚積まれていない"
    assert ch.rested is False, "デッキ0枚のとき 自キャラがアクティブになっていない"


def test_op15_022_activate_no_untap_when_deck_not_empty():
    """デッキが0枚でない場合、 mill のみで キャラのアクティブ化は起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP15-022", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP01-016")] * 10  # mill 4 後もデッキ6枚残る
    ch = InPlay.of(repo.get("OP01-016"), sickness=False)
    ch.rested = True
    me.characters = [ch]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP15-022"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert len(me.deck) == 6, f"mill 4 後デッキが6枚でない: {len(me.deck)}"
    assert ch.rested is True, "デッキが残っているのに キャラがアクティブになってはいけない"


# --------------------------------------------------------------------------- #
#  OP15-023 アーロン (CHARACTER 緑 cost4 power5000):
#    【KO時】相手のレストのカード2枚までは、次の相手のリフレッシュフェイズでアクティブにならない。
#    【起動メイン】【ターン1回】相手のキャラ1枚に相手のレストのドン‼1枚を付与できる：
#      リーダーかキャラ1枚に持ち主のコストエリアのドン‼1枚までを、付与する。
# --------------------------------------------------------------------------- #
def test_op15_023_on_ko_keep_opp_rested_don_ai():
    """【KO時】相手のレストドン2枚を 次のリフレッシュでアクティブにさせない (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.don_rested = 3

    before = opp.next_refresh_kept_rested_don
    do, _ = _do(overlay, "OP15-023", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-023"), sickness=False))
    _drain(st, [0])
    assert opp.next_refresh_kept_rested_don == before + 2, \
        f"相手レストドン2枚が次リフレッシュ保持に設定されていない: {opp.next_refresh_kept_rested_don}"


def test_op15_023_activate_optional_cost_then_ai():
    """起動メイン: 相手キャラに相手レストドン1付与 (コスト) → 自軍にドン1付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    aaron = InPlay.of(repo.get("OP15-023"), sickness=False)
    me.characters = [aaron]
    me.don_rested = 2  # 効果側 (自付与 = コストエリア) の供給源
    oc = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [oc]
    opp.don_rested = 2  # コスト側 (相手キャラへ相手ドン付与) の供給源

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP15-023"]
    assert len(opts) == 1, \
        f"OP15-023 の起動メインが legal に出ない: {len(opts)}"
    oc_don_before = oc.attached_dons
    me_don_before = me.leader.attached_dons + sum(c.attached_dons for c in me.characters)
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert oc.attached_dons == oc_don_before + 1, \
        f"コストで相手キャラに相手のレストドンが付与されていない: {oc.attached_dons}"
    me_don_after = me.leader.attached_dons + sum(c.attached_dons for c in me.characters)
    assert me_don_after == me_don_before + 1, \
        f"効果で自軍にドンが1枚付与されていない: {me_don_after} (before {me_don_before})"


# --------------------------------------------------------------------------- #
#  OP15-024 ウソップ (CHARACTER 緑 cost4 power5000):
#    【相手のターン中】このキャラは相手のリーダーとキャラの効果でレストにされず、【ブロッカー】を得る。
#    【KO時】相手のリーダーかコスト7以下のキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_op15_024_static_blocker_on_opp_turn():
    """相手のターン中はこのキャラが【ブロッカー】を得る (常在)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, turn_player=1)  # 相手 (P1) ターン
    me = st.players[0]
    usopp = InPlay.of(repo.get("OP15-024"), sickness=False)
    me.characters = [usopp]

    evaluate_static_effects(st, overlay)
    assert usopp.is_blocker_now is True, \
        "相手ターン中に【ブロッカー】を得ていない"


def test_op15_024_static_no_blocker_on_own_turn():
    """自分のターン中は【相手のターン中】条件が不成立 (= ブロッカーは付かない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, turn_player=0)  # 自分 (P0) ターン
    me = st.players[0]
    usopp = InPlay.of(repo.get("OP15-024"), sickness=False)
    me.characters = [usopp]

    evaluate_static_effects(st, overlay)
    assert usopp.is_blocker_now is False, \
        "自分ターンで【ブロッカー】を得てはいけない"


def test_op15_024_on_ko_rest_opp_cost_le_7_ai():
    """【KO時】相手のコスト7以下キャラ1枚をレストにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    oc = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 ≤ 7
    opp.characters = [oc]

    do, _ = _do(overlay, "OP15-024", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-024"), sickness=False))
    _drain(st, [0])
    assert oc.rested is True, "KO時に相手コスト7以下キャラがレストにされていない"


# --------------------------------------------------------------------------- #
#  OP15-027 ジュラキュール・ミホーク (CHARACTER 緑 cost4 power5000):
#    【登場時】相手のドン‼が付与されているキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_op15_027_on_play_rest_attached_don_ai():
    """【登場時】付与ドン持ちの相手キャラをレストにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    oc = InPlay.of(repo.get("OP01-016"), sickness=False)
    oc.attached_dons = 1
    opp.characters = [oc]

    do, _ = _do(overlay, "OP15-027", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-027"), sickness=True))
    _drain(st, [0])
    assert oc.rested is True, "登場時に 付与ドン持ちの相手キャラがレストにされていない"


def test_op15_027_on_play_no_attached_don_not_rested():
    """付与ドンの無い相手キャラは 対象外 (= レストにされない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    oc = InPlay.of(repo.get("OP01-016"), sickness=False)  # 付与ドン 0
    opp.characters = [oc]

    do, _ = _do(overlay, "OP15-027", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-027"), sickness=True))
    _drain(st, [0])
    assert oc.rested is False, "付与ドンの無い相手キャラをレストにしてはいけない (対象外)"


def test_op15_027_on_play_human_pick():
    """人間 + 対象複数 → target_pick modal が立ち resolve で選んだ1枚のみレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False); a.attached_dons = 1
    b = InPlay.of(repo.get("OP01-016"), sickness=False); b.attached_dons = 1
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP15-027", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP15-027"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b.rested is True, "人間が選んだ相手キャラがレストにされていない"
    assert a.rested is False, "選ばなかったキャラはレストにされてはいけない"


# --------------------------------------------------------------------------- #
#  OP15-028 ニャーバン兄弟 (CHARACTER 緑 cost1 power2000):
#    【登場時】自分のリーダーが特徴《東の海》を持つ場合、
#      相手のキャラ1枚に相手のコストエリアのドン‼1枚までを、付与する。
# --------------------------------------------------------------------------- #
def test_op15_028_on_play_attach_opp_don_east_blue_ai():
    """《東の海》リーダーで 相手キャラに相手のドン1枚を付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP15-001", overlay)  # クリーク (東の海)
    me, opp = st.players[0], st.players[1]
    oc = InPlay.of(repo.get("OP01-016"), sickness=False)
    opp.characters = [oc]
    opp.don_rested = 2  # 相手のドン供給源

    do, eff = _do(overlay, "OP15-028", "on_play")
    assert eval_condition(eff.get("if", {}), st, me) is True, \
        "《東の海》リーダーで登場時条件が成立していない"
    opp_rested_before = opp.don_rested
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-028"), sickness=True))
    _drain(st, [0])
    assert oc.attached_dons == 1, \
        f"相手キャラに相手のドンが付与されていない: {oc.attached_dons}"
    assert opp.don_rested == opp_rested_before - 1, \
        "相手のドンが1枚拘束 (消費) されるべき"


def test_op15_028_condition_false_non_east_blue_leader():
    """非《東の海》リーダーでは 登場時条件が不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ (東の海でない)
    me = st.players[0]
    _, eff = _do(overlay, "OP15-028", "on_play")
    assert eval_condition(eff.get("if", {}), st, me) is False, \
        "非《東の海》リーダーで登場時条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP15-029 バーソロミュー・くま (CHARACTER 緑 cost4 power5000):
#    【登場時】相手のコスト5以下のキャラ1枚までは、
#      次の相手のエンドフェイズ終了時まで、レストにできない。
# --------------------------------------------------------------------------- #
def test_op15_029_on_play_set_cannot_rest_cost_le_5_ai():
    """【登場時】相手のコスト5以下キャラ1枚を レスト不能にする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    oc = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 ≤ 5
    opp.characters = [oc]

    do, _ = _do(overlay, "OP15-029", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-029"), sickness=True))
    _drain(st, [0])
    assert oc.cannot_be_rested_buff is True, \
        "登場時に 相手コスト5以下キャラがレスト不能になっていない"


def test_op15_029_on_play_human_pick():
    """人間 + 対象複数 → target_pick modal が立ち resolve で選んだ1枚のみレスト不能。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP15-029", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP15-029"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b.cannot_be_rested_buff is True, "人間が選んだ相手キャラがレスト不能になっていない"
    assert a.cannot_be_rested_buff is False, "選ばなかったキャラは対象外のままであるべき"
