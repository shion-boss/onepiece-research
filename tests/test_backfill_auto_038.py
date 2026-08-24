# -*- coding: utf-8 -*-
"""OP03 弾 (緑 東の海 イベント / 青 東の海 ミルキャラ) 効果 回帰テスト
バックフィル (自動生成 wave 038):
OP03-038 / OP03-039 / OP03-041 / OP03-042 / OP03-043 / OP03-045 /
OP03-047 / OP03-048 / OP03-049 / OP03-050 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_001.py と同一方針):
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
    load_effect_overlay,
    resolve_pending_choice,
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


def _get_eff(overlay, cid, when, needle=None):
    for e in overlay.get(cid).effects:
        if e["when"] == when and (needle is None or needle in str(e["do"])):
            return e
    raise KeyError(cid, when, needle)


def _drain(st, sel=None, guard=8):
    """pending_choice を sel (既定 [0]) で解決し続ける (人間チェーン用)。"""
    if sel is None:
        sel = [0]
    g = 0
    while st.pending_choice is not None and g < guard:
        resolve_pending_choice(st, sel)
        g += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op03_wave38_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP03-038", "OP03-039", "OP03-041", "OP03-042", "OP03-043",
           "OP03-045", "OP03-047", "OP03-048", "OP03-049", "OP03-050"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP03-038 猛毒ガス弾『M・H・５』 (EVENT 緑):
#    【メイン】相手のコスト2以下のキャラ2枚までを、レストにする。
#    【トリガー】相手のコスト5以下のキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_op03_038_main_rest_two_cost_le2_ai():
    """【メイン】相手のコスト2以下キャラ 2 枚までをレスト (AI 自動、 コストゲート検証)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-021", overlay)
    me, opp = st.players[0], st.players[1]
    lo1 = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost1 (<=2)
    lo2 = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2 (<=2)
    hi = InPlay.of(repo.get("OP01-005"), sickness=False)    # ウタ cost4 (対象外)
    opp.characters = [lo1, lo2, hi]

    main_eff = _get_eff(overlay, "OP03-038", "main")
    for prim in main_eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-038"), sickness=False))

    assert lo1.rested is True and lo2.rested is True, \
        "コスト2以下の相手キャラ 2 枚がレストされていない"
    assert hi.rested is False, "コスト3以上の相手キャラはレストされない"


def test_op03_038_trigger_rest_one_cost_le5_ai():
    """【トリガー】相手のコスト5以下キャラ 1 枚をレスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-021", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-005"), sickness=False)  # cost4 (<=5)
    opp.characters = [victim]

    trig_eff = _get_eff(overlay, "OP03-038", "trigger")
    for prim in trig_eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-038"), sickness=False))
    assert victim.rested is True, "トリガーで相手コスト5以下キャラがレストされていない"


def test_op03_038_trigger_rest_human_pick():
    """人間 + 相手キャラ複数 → rest の target_pick modal が立ち resolve で 1 体をレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-021", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2
    b = InPlay.of(repo.get("OP01-005"), sickness=False)   # ウタ cost4
    opp.characters = [a, b]

    trig_eff = _get_eff(overlay, "OP03-038", "trigger")
    execute_effect(trig_eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP03-038"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で rest modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b.rested is True, "人間が選んだ相手キャラがレストされていない"
    assert a.rested is False, "選ばなかった相手キャラはレストされない"


# --------------------------------------------------------------------------- #
#  OP03-039 ワン・ツー・ジャンゴ (EVENT 緑):
#    【メイン】相手のコスト1以下のキャラ1枚までをレストにする。
#             その後、自分のキャラ1枚までを、このターン中、パワー+1000。
#    【トリガー】相手のコスト4以下のキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_op03_039_main_rest_and_pump_ai():
    """【メイン】相手コスト1以下をレスト + 自キャラ +1000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-021", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost1 (<=1)
    opp.characters = [victim]
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ power3000
    me.characters = [friend]
    power_before = friend.power

    main_eff = _get_eff(overlay, "OP03-039", "main")
    for prim in main_eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-039"), sickness=False))

    assert victim.rested is True, "相手コスト1以下キャラがレストされていない"
    assert friend.power == power_before + 1000, \
        f"自キャラの +1000 が反映されていない: {friend.power} (before {power_before})"


def test_op03_039_main_rest_human_pick():
    """人間 + 相手コスト1以下キャラ複数 → rest modal が立ち resolve で 1 体をレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-021", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost1
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost1
    opp.characters = [a, b]

    main_eff = _get_eff(overlay, "OP03-039", "main")
    execute_effect(main_eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP03-039"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で rest modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    _drain(st, [a_idx])
    assert a.rested is True, "人間が選んだ相手キャラがレストされていない"


def test_op03_039_trigger_rest_cost_le4_ai():
    """【トリガー】相手コスト4以下キャラ 1 枚をレスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-021", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-005"), sickness=False)  # cost4 (<=4)
    opp.characters = [victim]

    trig_eff = _get_eff(overlay, "OP03-039", "trigger")
    for prim in trig_eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-039"), sickness=False))
    assert victim.rested is True, "トリガーで相手コスト4以下キャラがレストされていない"


# --------------------------------------------------------------------------- #
#  OP03-041 ウソップ (CHARACTER 青 cost4):
#    【ドン!!×1】アタックでライフにダメージを与えた時、デッキ上7枚をトラッシュ (任意)。
# --------------------------------------------------------------------------- #
def test_op03_041_usopp_life_taken_mill7_ai():
    """【ドン!!×1】相手ライフダメージ時、自デッキ上7枚をトラッシュ (AI、 ドン1ゲート)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP03-041"), sickness=False)
    src.attached_dons = 1  # ドン!!×1 ゲート成立
    me.characters = [src]
    deck_before = len(me.deck)
    trash_before = len(me.trash)

    eff = _get_eff(overlay, "OP03-041", "on_opp_life_taken")
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドン!!×1 ゲート self_attached_don_ge=1 が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, src)

    assert len(me.deck) == deck_before - 7, \
        f"デッキ上7枚がトラッシュされていない: {len(me.deck)} (before {deck_before})"
    assert len(me.trash) == trash_before + 7, "トラッシュが7枚増えていない"


# --------------------------------------------------------------------------- #
#  OP03-042 ウソップ海賊団 (CHARACTER 青 cost1):
#    【登場時】自分のトラッシュの青の「ウソップ」1枚までを、手札に加える。
# --------------------------------------------------------------------------- #
def test_op03_042_on_play_recover_blue_usopp_ai():
    """【登場時】トラッシュの青「ウソップ」1枚を手札に加える (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    blue_usopp = repo.get("OP16-043")  # 青 ウソップ
    me.trash = [blue_usopp]
    hand_before = len(me.hand)

    on_play = _get_eff(overlay, "OP03-042", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-042"), sickness=True))

    assert any(c.card_id == "OP16-043" for c in me.hand), \
        "青の「ウソップ」がトラッシュから手札に加わっていない"
    assert len(me.hand) == hand_before + 1, "手札が1枚増えるべき"
    assert blue_usopp not in me.trash, "手札に加えたカードがトラッシュに残っている"


# --------------------------------------------------------------------------- #
#  OP03-043 ガイモン (CHARACTER 青 cost2):
#    相手ライフダメージ時、自デッキ上3枚をトラッシュ (任意)。
#    そうした場合、このキャラをトラッシュに置く。
# --------------------------------------------------------------------------- #
def test_op03_043_gaimon_life_taken_mill3_ai():
    """【相手ライフダメージ時】自デッキ上3枚をトラッシュ + そうした場合 自身もトラッシュ。

    ⚠ 2026-08-13 是正: 公式は 「…トラッシュに置いて**もよい**。**そうした場合**、この
      キャラをトラッシュに置く」。 旧 overlay は自身のトラッシュを entry の cost に
      置いており、 do だけを直接実行するこのテストでは **自身が落ちなかった**。
      現在は optional_cost_then(cost=[], effect=[mill 3, return_self_to_trash])。
    """
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP03-043"), sickness=False)
    me.characters = [src]
    deck_before = len(me.deck)
    trash_before = len(me.trash)

    eff = _get_eff(overlay, "OP03-043", "on_opp_life_taken")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, src)

    assert len(me.deck) == deck_before - 3, \
        f"デッキ上3枚がトラッシュされていない: {len(me.deck)} (before {deck_before})"
    assert len(me.trash) == trash_before + 4, \
        "トラッシュが (デッキ3枚 + このキャラ自身 =) 4 枚増えていない"


# --------------------------------------------------------------------------- #
#  OP03-045 カルネ (CHARACTER 青 cost3 power3000):
#    【ブロッカー】【相手のターン中】自分のデッキが20枚以下の場合、このキャラはパワー+3000。
# --------------------------------------------------------------------------- #
def test_op03_045_karne_static_pump_opp_turn_deck_le20():
    """静的: 相手ターン中 + 自デッキ20枚以下 → 自身 static_buff +3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1  # 相手ターン (= me_idx=0 視点で opp_turn)
    me.deck = [repo.get("OP01-013")] * 20  # デッキ 20 枚 (<=20)
    karne = InPlay.of(repo.get("OP03-045"), sickness=False)
    me.characters = [karne]

    assert eval_condition({"opp_turn": True, "self_deck_count_le": 20}, st, me) is True, \
        "テスト前提: 相手ターン + デッキ20枚以下 が成立していない"
    evaluate_static_effects(st, overlay)
    assert karne.static_buff == 3000, \
        f"条件成立時 static_buff +3000 が乗っていない: {karne.static_buff}"


def test_op03_045_karne_no_pump_self_turn():
    """自分のターン中は【相手のターン中】条件が不成立 → static_buff +0。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 0  # 自分のターン → opp_turn False
    me.deck = [repo.get("OP01-013")] * 20
    karne = InPlay.of(repo.get("OP03-045"), sickness=False)
    me.characters = [karne]

    evaluate_static_effects(st, overlay)
    assert karne.static_buff == 0, \
        f"自分のターンで +3000 が乗ってはいけない: {karne.static_buff}"


def test_op03_045_karne_no_pump_deck_over20():
    """デッキが21枚以上 (=20枚超) では条件不成立 → static_buff +0。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1  # 相手ターン
    me.deck = [repo.get("OP01-013")] * 30  # 30 枚 (>20)
    karne = InPlay.of(repo.get("OP03-045"), sickness=False)
    me.characters = [karne]

    evaluate_static_effects(st, overlay)
    assert karne.static_buff == 0, \
        f"デッキ20枚超では +3000 が乗ってはいけない: {karne.static_buff}"


# --------------------------------------------------------------------------- #
#  OP03-047 ゼフ (CHARACTER 青 cost5):
#    【登場時】コスト3以下のキャラ1枚までを持ち主の手札に戻し、自デッキ上2枚をトラッシュ (任意)。
#    【ドン!!×1】アタックでライフダメージ時、自デッキ上7枚をトラッシュ (任意)。
# --------------------------------------------------------------------------- #
def test_op03_047_zeff_on_play_bounce_and_mill_ai():
    """【登場時】相手コスト3以下キャラを手札に戻し + 自デッキ上2枚トラッシュ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2 (<=3)
    opp.characters = [victim]
    opp_hand_before = len(opp.hand)
    deck_before = len(me.deck)

    on_play = _get_eff(overlay, "OP03-047", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-047"), sickness=True))

    assert victim not in opp.characters, "相手コスト3以下キャラが手札に戻っていない"
    assert len(opp.hand) == opp_hand_before + 1, "戻したキャラが持ち主の手札に加わっていない"
    assert len(me.deck) == deck_before - 2, \
        f"自デッキ上2枚がトラッシュされていない: {len(me.deck)} (before {deck_before})"


def test_op03_047_zeff_on_play_bounce_human_pick():
    """人間 + コスト3以下キャラ複数 → return_to_hand modal が立ち resolve で 1 体を手札へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost1
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2
    opp.characters = [a, b]

    on_play = _get_eff(overlay, "OP03-047", "on_play")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP03-047"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で return_to_hand modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b not in opp.characters, "人間が選んだキャラが手札に戻っていない"


def test_op03_047_zeff_life_taken_mill7_ai():
    """【ドン!!×1】相手ライフダメージ時、自デッキ上7枚トラッシュ (AI、 ドン1ゲート)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP03-047"), sickness=False)
    src.attached_dons = 1
    me.characters = [src]
    deck_before = len(me.deck)

    eff = _get_eff(overlay, "OP03-047", "on_opp_life_taken")
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドン!!×1 ゲートが無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, src)
    assert len(me.deck) == deck_before - 7, "デッキ上7枚がトラッシュされていない"


# --------------------------------------------------------------------------- #
#  OP03-048 ノジコ (CHARACTER 青 cost2):
#    【登場時】自リーダーが「ナミ」の場合、相手のコスト5以下のキャラ1枚を持ち主の手札に戻す。
# --------------------------------------------------------------------------- #
def test_op03_048_nojiko_on_play_bounce_when_nami_ai():
    """【登場時】(リーダー ナミ) 相手コスト5以下キャラを手札に戻す (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-040", overlay)  # ナミ リーダー
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-005"), sickness=False)  # cost4 (<=5)
    opp.characters = [victim]
    opp_hand_before = len(opp.hand)

    on_play = _get_eff(overlay, "OP03-048", "on_play")
    assert on_play.get("if", {}).get("leader_name") == "ナミ", \
        "overlay の リーダー名 ナミ 条件が無い"
    assert eval_condition(on_play["if"], st, me) is True, \
        "テスト前提: リーダーが ナミ で条件成立していない"
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-048"), sickness=True))

    assert victim not in opp.characters, "相手コスト5以下キャラが手札に戻っていない"
    assert len(opp.hand) == opp_hand_before + 1, "戻したキャラが持ち主の手札に加わっていない"


def test_op03_048_nojiko_condition_false_when_not_nami():
    """リーダーが「ナミ」でない場合、【登場時】条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ リーダー (ナミでない)
    me, opp = st.players[0], st.players[1]
    on_play = _get_eff(overlay, "OP03-048", "on_play")
    assert eval_condition(on_play["if"], st, me) is False, \
        "リーダーが ナミ でないのに条件が成立している"


def test_op03_048_nojiko_on_play_bounce_human_pick():
    """人間 + 相手キャラ複数 → return_to_hand modal が立ち resolve で 1 体を手札へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-040", overlay, human_idx=0)  # ナミ リーダー
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2
    b = InPlay.of(repo.get("OP01-005"), sickness=False)   # ウタ cost4
    opp.characters = [a, b]

    on_play = _get_eff(overlay, "OP03-048", "on_play")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP03-048"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で return_to_hand modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b not in opp.characters, "人間が選んだ相手キャラが手札に戻っていない"


# --------------------------------------------------------------------------- #
#  OP03-049 パティ (CHARACTER 青 cost3 power5000):
#    【登場時】自分のデッキが20枚以下の場合、コスト3以下のキャラ1枚までを持ち主の手札に戻す。
# --------------------------------------------------------------------------- #
def test_op03_049_patty_on_play_bounce_when_deck_le20_ai():
    """【登場時】(自デッキ20枚以下) コスト3以下キャラを手札に戻す (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP01-013")] * 20  # デッキ 20 枚 (<=20)
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2 (<=3)
    opp.characters = [victim]
    opp_hand_before = len(opp.hand)

    on_play = _get_eff(overlay, "OP03-049", "on_play")
    assert on_play.get("if", {}).get("self_deck_count_le") == 20, \
        "overlay の 自デッキ20枚以下 条件が無い"
    assert eval_condition(on_play["if"], st, me) is True, \
        "テスト前提: 自デッキ20枚以下 が成立していない"
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-049"), sickness=True))

    assert victim not in opp.characters, "相手コスト3以下キャラが手札に戻っていない"
    assert len(opp.hand) == opp_hand_before + 1, "戻したキャラが持ち主の手札に加わっていない"


def test_op03_049_patty_condition_false_deck_over20():
    """自デッキが21枚以上 (=20枚超) では【登場時】条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP01-013")] * 30  # 30 枚 (>20)
    on_play = _get_eff(overlay, "OP03-049", "on_play")
    assert eval_condition(on_play["if"], st, me) is False, \
        "自デッキ20枚超なのに条件が成立している"


# --------------------------------------------------------------------------- #
#  OP03-050 ブードル (CHARACTER 青 cost2):
#    【ブロッカー】【KO時】自分のデッキの上から1枚をトラッシュに置いてもよい。
# --------------------------------------------------------------------------- #
def test_op03_050_boodle_on_ko_mill1_ai():
    """【KO時】自デッキ上1枚をトラッシュ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP03-050"), sickness=False)
    deck_before = len(me.deck)
    trash_before = len(me.trash)

    eff = _get_eff(overlay, "OP03-050", "on_ko")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, src)

    assert len(me.deck) == deck_before - 1, \
        f"KO時に自デッキ上1枚がトラッシュされていない: {len(me.deck)} (before {deck_before})"
    assert len(me.trash) == trash_before + 1, "トラッシュが1枚増えていない"
