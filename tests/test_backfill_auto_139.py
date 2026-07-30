# -*- coding: utf-8 -*-
"""OP15 弾 効果 回帰テスト バックフィル (自動生成 wave 139):
OP15-005 / OP15-006 / OP15-007 / OP15-009 / OP15-010 / OP15-011 /
OP15-013 / OP15-014 / OP15-015 / OP15-017 の 10 枚。

目的 (= test_backfill_auto_001〜138.py と同一方針):
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
    try_replace_ko,
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
        for e in matches:
            if any(needle in prim for prim in e["do"]):
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
def test_all_op15_wave139_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP15-005", "OP15-006", "OP15-007", "OP15-009", "OP15-010",
           "OP15-011", "OP15-013", "OP15-014", "OP15-015", "OP15-017"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP15-005 カバジ (CHARACTER 赤 cost2 power3000):
#    【アタック時】相手の付与されているドン‼がある場合、
#             このキャラは、 このターン中、 パワー+2000。
# --------------------------------------------------------------------------- #
def test_op15_005_on_attack_pump_when_opp_has_attached_don():
    """相手に付与ドンがある場合、 アタック時 このキャラ +2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    oc = InPlay.of(repo.get("OP01-016"), sickness=False)
    oc.attached_dons = 1  # 相手キャラに付与ドン → 条件成立
    opp.characters = [oc]
    kabaji = InPlay.of(repo.get("OP15-005"), sickness=False)
    me.characters = [kabaji]

    do, eff = _do(overlay, "OP15-005", "on_attack")
    assert eval_condition(eff.get("if", {}), st, me, kabaji) is True, \
        "相手に付与ドンがあるのに opp_attached_don_ge 条件が成立していない"
    power_before = kabaji.power
    for prim in do:
        execute_effect(prim, st, me, opp, kabaji)
    assert kabaji.power == power_before + 2000, \
        f"アタック時 自己 +2000 が反映されていない: {kabaji.power} (before {power_before})"


def test_op15_005_condition_false_no_opp_attached_don():
    """相手に付与ドンが無ければ 条件不成立 (= +2000 は乗らない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.characters = [InPlay.of(repo.get("OP01-016"), sickness=False)]  # 付与ドン 0
    kabaji = InPlay.of(repo.get("OP15-005"), sickness=False)
    _, eff = _do(overlay, "OP15-005", "on_attack")
    assert eval_condition(eff.get("if", {}), st, me, kabaji) is False, \
        "相手に付与ドンが無いのに条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP15-006 キャベンディッシュ (CHARACTER 赤 cost4 power4000):
#    自分のトラッシュにイベントが4枚以上ある場合、 このキャラのパワー+2000。 (常在)
# --------------------------------------------------------------------------- #
def test_op15_006_static_pump_with_4_events_in_trash():
    """トラッシュにイベント4枚以上で 常在 +2000 (evaluate_static_effects)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    cav_def = repo.get("OP15-006")  # power4000
    cav = InPlay.of(cav_def, sickness=False)
    me.characters = [cav]
    me.trash = [repo.get("OP10-097")] * 4  # EVENT 4 枚 (= 条件成立)

    evaluate_static_effects(st, overlay)
    assert cav.power == cav_def.power + 2000, \
        f"トラッシュ EVENT 4枚で +2000 が反映されていない: {cav.power} (base {cav_def.power})"


def test_op15_006_static_no_pump_with_3_events():
    """トラッシュのイベントが3枚では 条件不成立 (= +0)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    cav_def = repo.get("OP15-006")
    cav = InPlay.of(cav_def, sickness=False)
    me.characters = [cav]
    me.trash = [repo.get("OP10-097")] * 3  # EVENT 3 枚 (= 4枚未満)

    evaluate_static_effects(st, overlay)
    assert cav.power == cav_def.power, \
        f"トラッシュ EVENT 3枚で pump が乗ってはいけない: {cav.power} (base {cav_def.power})"


# --------------------------------------------------------------------------- #
#  OP15-007 ギン (CHARACTER 赤 cost6 power7000):
#    【登場時】自分のリーダーが特徴《東の海》を持つ場合、
#             自分の手札からコスト5以下のキャラカード1枚までを、 登場させる。
# --------------------------------------------------------------------------- #
def test_op15_007_on_play_east_blue_leader_plays_from_hand_ai():
    """《東の海》リーダーで 手札のコスト5以下キャラを登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP15-001", overlay)  # クリーク (東の海)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-016")]  # CHARACTER cost1 ≤ 5

    do, eff = _do(overlay, "OP15-007", "on_play")
    assert eval_condition(eff.get("if", {}), st, me) is True, \
        "《東の海》リーダーで登場時条件が成立していない"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-007"), sickness=True))
    _drain(st, [0])
    assert any(c.card.card_id == "OP01-016" for c in me.characters), \
        "登場時に 手札のコスト5以下キャラが登場していない"


def test_op15_007_condition_false_non_east_blue_leader():
    """非《東の海》リーダーでは 登場時条件が不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ (超新星/麦わら = 東の海でない)
    me = st.players[0]
    _, eff = _do(overlay, "OP15-007", "on_play")
    assert eval_condition(eff.get("if", {}), st, me) is False, \
        "非《東の海》リーダーで登場時条件が成立してはいけない"


def test_op15_007_on_play_human_play_pick():
    """人間 + 手札にコスト5以下キャラ 複数 → play_from_hand modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP15-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-016"), repo.get("OP01-013")]  # cost1 / cost2 いずれも ≤5

    do, _ = _do(overlay, "OP15-007", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP15-007"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert any(c.card.card_id in ("OP01-016", "OP01-013") for c in me.characters), \
        "人間が選んだキャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP15-009 コビー (CHARACTER 赤 cost1 power2000):
#    自分の元々のパワー7000以下のキャラが相手の効果で場を離れる場合、
#    代わりに自分のリーダーを、 このターン中、 パワー-2000できる。 (replace_leave)
# --------------------------------------------------------------------------- #
def test_op15_009_replace_leave_pumps_leader_minus_2000_ai():
    """自元P7000以下キャラが相手効果で離脱する時、 代わりに自リーダー -2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    kobby = InPlay.of(repo.get("OP15-009"), sickness=False)
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # power2000 ≤ 7000
    me.characters = [kobby, victim]

    power_before = me.leader.power
    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, \
        "自元P7000以下キャラの相手効果離脱で replace_leave が成立していない"
    assert me.leader.power == power_before - 2000, \
        f"代替効果で自リーダー -2000 が反映されていない: {me.leader.power} (before {power_before})"


def test_op15_009_replace_leave_not_by_opp_effect():
    """相手の効果由来でない離脱 (by_opp_effect=False) では 代替は発火しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    kobby = InPlay.of(repo.get("OP15-009"), sickness=False)
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)
    me.characters = [kobby, victim]

    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=False, leave_kind="ko",
    )
    assert replaced is False, \
        "相手効果由来でない離脱で replace_leave が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP15-010 ネズミ (CHARACTER 赤 cost2 power2000):
#    【起動メイン】【ターン1回】リーダーかキャラ1枚に持ち主のレストのドン‼1枚までを、 付与する。
# --------------------------------------------------------------------------- #
def test_op15_010_activate_main_attach_rested_don_ai():
    """起動メイン: 自リーダー (既定) にレストドン1枚を付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    nezumi = InPlay.of(repo.get("OP15-010"), sickness=False)
    me.characters = [nezumi]
    me.don_rested = 2

    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP15-010"]
    assert len(opts) == 1, \
        f"OP15-010 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert me.leader.attached_dons == don_before + 1, \
        "起動メインで自リーダーにレストドンが付与されていない"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"


def test_op15_010_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    nezumi = InPlay.of(repo.get("OP15-010"), sickness=False)
    me.characters = [nezumi]
    me.don_rested = 3

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP15-010"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])
    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP15-010"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP15-011 パール (CHARACTER 赤 cost4 power4000):
#    【相手のターン中】自分のリーダーが特徴《東の海》を持つ場合、
#             このキャラは【ブロッカー】を得て、 パワー+2000。 (常在)
#    【KO時】自分のリーダーが特徴《東の海》を持つ場合、
#             相手の元々のパワー6000以下のキャラ1枚までを、 KOする。
# --------------------------------------------------------------------------- #
def test_op15_011_static_blocker_and_pump_opp_turn_east_blue():
    """相手ターン + 《東の海》リーダーで【ブロッカー】獲得 + パワー+2000 (常在)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP15-001", overlay, turn_player=1)  # 相手 (P1) ターン
    me = st.players[0]
    pearl_def = repo.get("OP15-011")  # power4000
    pearl = InPlay.of(pearl_def, sickness=False)
    me.characters = [pearl]

    evaluate_static_effects(st, overlay)
    assert pearl.is_blocker_now is True, \
        "相手ターン + 《東の海》で【ブロッカー】を得ていない"
    assert pearl.power == pearl_def.power + 2000, \
        f"相手ターン + 《東の海》で +2000 が反映されていない: {pearl.power}"


def test_op15_011_static_no_effect_on_own_turn():
    """自分のターン中は【相手のターン中】条件が不成立 (= ブロッカーも +2000 も無し)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP15-001", overlay, turn_player=0)  # 自分 (P0) ターン
    me = st.players[0]
    pearl_def = repo.get("OP15-011")
    pearl = InPlay.of(pearl_def, sickness=False)
    me.characters = [pearl]

    evaluate_static_effects(st, overlay)
    assert pearl.is_blocker_now is False, \
        "自分ターンで【ブロッカー】を得てはいけない"
    assert pearl.power == pearl_def.power, \
        f"自分ターンで +2000 が乗ってはいけない: {pearl.power}"


def test_op15_011_on_ko_ko_opp_p6000_ai():
    """【KO時】《東の海》リーダーで 相手の元々P6000以下キャラをKO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP15-001", overlay, turn_player=1)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # power2000 ≤ 6000
    opp.characters = [victim]

    do, eff = _do(overlay, "OP15-011", "on_ko")
    assert eval_condition(eff.get("if", {}), st, me) is True, \
        "《東の海》リーダーで KO時条件が成立していない"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-011"), sickness=False))
    _drain(st, [0])
    assert victim not in opp.characters, "KO時に 相手P6000以下キャラがKOされていない"


def test_op15_011_on_ko_ko_human_pick():
    """人間 + 相手P6000以下キャラ 複数 → target_pick modal が立ち resolve で1枚KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP15-001", overlay, human_idx=0, turn_player=1)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # power2000
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # power3000
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP15-011", "on_ko")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP15-011"), sickness=False))
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
#  OP15-013 ハサミ (CHARACTER 赤 cost4 power2000):
#    手札のこのカードは、 自分のリーダーがパワー0以下の場合、 コスト-2。
#    【ブロッカー】(intrinsic)
# --------------------------------------------------------------------------- #
def test_op15_013_is_blocker():
    """ハサミは【ブロッカー】を持つ (intrinsic)。"""
    repo = _repo()
    hasami = InPlay.of(repo.get("OP15-013"), sickness=False)
    assert hasami.is_blocker_now is True, \
        "ハサミが【ブロッカー】と判定されていない"


def test_op15_013_in_hand_cost_minus_when_leader_power_le_0():
    """自リーダーがパワー0以下の場合、 手札の このカードはコスト-2。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    me.leader.turn_buff = -5000  # リーダー power 5000 → 0
    assert me.leader.power == 0, "テスト前提: リーダー power を 0 にできていない"
    assert _compute_in_hand_cost_minus(st, me, repo.get("OP15-013")) == 2, \
        "リーダー power 0 で 手札コスト -2 が計算されていない"


def test_op15_013_in_hand_no_reduction_when_leader_power_positive():
    """自リーダーのパワーが正 (> 0) なら コスト軽減は無い。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    assert me.leader.power > 0, "テスト前提: 通常リーダーは power > 0"
    assert _compute_in_hand_cost_minus(st, me, repo.get("OP15-013")) == 0, \
        "リーダー power が正なのにコスト軽減が発生している"


# --------------------------------------------------------------------------- #
#  OP15-014 バルトロメオ (CHARACTER 赤 cost4 power6000):
#    このキャラがKOされる場合、 代わりに自分の手札からイベント1枚を捨てることができる。
#    【登場時】自分の手札から元々のコスト3以下の特徴《ドレスローザ》を持つ
#             イベント1枚までを、 発動する。
# --------------------------------------------------------------------------- #
def test_op15_014_replace_ko_discard_event_ai():
    """KO時、 手札のイベント1枚を捨てて KO を置換する (AI: EVENT があれば置換成立)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    bart = InPlay.of(repo.get("OP15-014"), sickness=False)
    me.characters = [bart]
    me.hand = [repo.get("EB04-008")]  # EVENT (= 捨てるコスト用)

    hand_before = len(me.hand)
    replaced = try_replace_ko(
        st, me, opp, bart, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "EVENT を捨てられるのに KO が置換されていない"
    assert bart in me.characters, "置換成立時 バルトロメオは場に残るべき"
    assert len(me.hand) == hand_before - 1, "置換コストで手札 EVENT が1枚捨てられるべき"


def test_op15_014_replace_ko_no_event_in_hand():
    """手札に EVENT が無ければ cost 不能 → 置換できない (False)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    bart = InPlay.of(repo.get("OP15-014"), sickness=False)
    me.characters = [bart]
    me.hand = [repo.get("OP01-016")]  # CHARACTER のみ = 捨てられない

    replaced = try_replace_ko(
        st, me, opp, bart, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is False, "EVENT が無いのに置換が成立してはいけない"


def test_op15_014_on_play_play_event_from_hand_ai():
    """【登場時】手札の《ドレスローザ》cost3以下イベントを発動 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP10-097")]  # ドレスローザ EVENT cost1

    do, _ = _do(overlay, "OP15-014", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-014"), sickness=True))
    _drain(st, [0])
    assert not any(c.card_id == "OP10-097" for c in me.hand), \
        "発動した《ドレスローザ》イベントが手札に残っている"
    assert any(c.card_id == "OP10-097" for c in me.trash), \
        "発動した《ドレスローザ》イベントがトラッシュに置かれていない"


# --------------------------------------------------------------------------- #
#  OP15-015 ヒグマ (CHARACTER 赤 cost1 power1000):
#    【登場時】相手のキャラ1枚に相手のレストのドン‼1枚までを、 付与する。
#             その後、 相手のドン‼が付与されているキャラ1枚までを、
#             このターン中、 パワー-1000。
# --------------------------------------------------------------------------- #
def test_op15_015_on_play_attach_opp_don_then_debuff_ai():
    """【登場時】相手キャラに相手レストドン1付与 → 付与ドン持ちキャラ -1000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    oc = InPlay.of(repo.get("OP01-013"), sickness=False)  # power3000
    opp.characters = [oc]
    opp.don_rested = 2  # 相手のレストドン供給源

    do, _ = _do(overlay, "OP15-015", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-015"), sickness=True))
    _drain(st, [0])
    assert oc.attached_dons == 1, \
        f"相手キャラに相手のレストドンが付与されていない: {oc.attached_dons}"
    assert oc.turn_buff == -1000, \
        f"付与ドン持ち相手キャラに -1000 (turn) が反映されていない: turn_buff={oc.turn_buff}"


# --------------------------------------------------------------------------- #
#  OP15-017 モーガン (CHARACTER 赤 cost5 power6000):
#    【ブロッカー】(intrinsic)
#    【起動メイン】【ターン1回】相手のキャラ1枚に相手のレストのドン‼1枚を付与できる：
#             リーダーかキャラ1枚に持ち主のレストのドン‼1枚までを、 付与する。
# --------------------------------------------------------------------------- #
def test_op15_017_is_blocker():
    """モーガンは【ブロッカー】を持つ (intrinsic)。"""
    repo = _repo()
    morgan = InPlay.of(repo.get("OP15-017"), sickness=False)
    assert morgan.is_blocker_now is True, \
        "モーガンが【ブロッカー】と判定されていない"


def test_op15_017_activate_main_optional_cost_then_ai():
    """起動メイン: 相手キャラに相手レストドン1付与 (コスト) → 自リーダーにレストドン1付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    morgan = InPlay.of(repo.get("OP15-017"), sickness=False)
    me.characters = [morgan]
    me.don_rested = 2  # 効果側 (自付与) の供給源
    oc = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [oc]
    opp.don_rested = 2  # コスト側 (相手キャラへ相手ドン付与) の供給源

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP15-017"]
    assert len(opts) == 1, \
        f"OP15-017 の起動メインが legal に出ない: {len(opts)}"
    leader_don_before = me.leader.attached_dons
    opp_don_before = oc.attached_dons
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert oc.attached_dons == opp_don_before + 1, \
        f"コストで相手キャラに相手のレストドンが付与されていない: {oc.attached_dons}"
    assert me.leader.attached_dons == leader_don_before + 1, \
        f"効果で自リーダーにレストドンが付与されていない: {me.leader.attached_dons}"
