# -*- coding: utf-8 -*-
"""OP01 弾 効果 回帰テスト バックフィル (自動生成 wave 025):
OP01-094 / OP01-096 / OP01-098 / OP01-101 / OP01-102 / OP01-104 /
OP01-105 / OP01-106 / OP01-108 / OP01-109 の 10 枚。

目的 (= test_backfill_auto_001〜024.py と同一方針):
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
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。
    デッキは効果の薄いバニラ気味カード (ST01-004) で埋める (= サーチ/ドローの混入回避)。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("ST01-004")] * 30
    p1.deck = [repo.get("ST01-004")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果の do 配列を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e["do"], e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]["do"], matches[0]


def _drain_choices(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op01_wave25_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP01-094", "OP01-096", "OP01-098", "OP01-101", "OP01-102",
           "OP01-104", "OP01-105", "OP01-106", "OP01-108", "OP01-109"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP01-094 カイドウ: 【登場時】ドン!!-6 + 自リーダー《百獣海賊団》なら
#    このキャラ以外のキャラすべてを KO する。
# --------------------------------------------------------------------------- #
def test_op01_094_kaido_ko_all_others_ai():
    """登場時 (百獣海賊団 leader): 自身以外の自他キャラすべてを KO する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay)  # 百獣海賊団 leader
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP01-094"), sickness=True)
    other_own = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [src, other_own]
    opp.characters = [InPlay.of(repo.get("OP01-013"), sickness=False),
                      InPlay.of(repo.get("OP01-016"), sickness=False)]

    _, eff = _do(overlay, "OP01-094", "on_play")
    assert eff.get("if", {}).get("leader_feature") == "百獣海賊団", \
        "overlay の リーダー条件 leader_feature=百獣海賊団 が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, src)

    assert me.characters == [src], \
        f"自身以外の自キャラが KO されていない: {[c.card.card_id for c in me.characters]}"
    assert opp.characters == [], \
        f"相手キャラがすべて KO されていない: {[c.card.card_id for c in opp.characters]}"


# --------------------------------------------------------------------------- #
#  OP01-096 キング: 【登場時】ドン!!-2 相手コスト3以下1枚まで + コスト2以下1枚までを KO。
# --------------------------------------------------------------------------- #
def test_op01_096_king_on_play_ko_multi_ai():
    """登場時: 相手のコスト3以下キャラと コスト2以下キャラをそれぞれ 1 枚 KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    c3 = InPlay.of(repo.get("OP01-025"), sickness=False)  # ゾロ cost3 (<=3)
    c2 = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 (<=2)
    assert c3.card.cost <= 3 and c2.card.cost <= 2
    opp.characters = [c3, c2]

    do, _ = _do(overlay, "OP01-096", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-096"), sickness=True))
    assert opp.characters == [], \
        f"コスト3以下 + コスト2以下 のキャラが KO されていない: {[c.card.card_id for c in opp.characters]}"


def test_op01_096_king_on_play_human_target_pick():
    """人間 + 相手コスト3以下キャラ 複数 → target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP01-096", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP01-096"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    _drain_choices(st, pick=[0])
    assert a not in opp.characters, "人間が選んだキャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP01-098 黒炭オロチ: 【登場時】デッキから「人造悪魔の実SMILE」1枚までを公開手札 →
#    シャッフル。
# --------------------------------------------------------------------------- #
def test_op01_098_orochi_on_play_search_smile_ai():
    """登場時: デッキの「人造悪魔の実SMILE」(OP01-116) 1 枚を手札に加える (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("OP01-116")] + [repo.get("ST01-004")] * 20  # SMILE を仕込む

    hand_before = len(me.hand)
    deck_before = len(me.deck)
    do, _ = _do(overlay, "OP01-098", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-098"), sickness=True))
    assert any(c.card_id == "OP01-116" for c in me.hand), \
        "デッキの「人造悪魔の実SMILE」が手札に加わっていない"
    assert len(me.hand) == hand_before + 1, "サーチで手札が1枚増えていない"
    assert len(me.deck) == deck_before - 1, "サーチでデッキが1枚減っていない"


def test_op01_098_orochi_on_play_no_smile_in_deck():
    """デッキに「人造悪魔の実SMILE」が無ければ 手札は増えない (該当カードのみ対象)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("ST01-004")] * 20  # SMILE 無し

    do, _ = _do(overlay, "OP01-098", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-098"), sickness=True))
    assert me.hand == [], \
        f"該当カードが無いのに手札が増えている: {[c.card_id for c in me.hand]}"


# --------------------------------------------------------------------------- #
#  OP01-101 ササキ: 【ドン!!×1】【アタック時】自分の手札1枚を捨てられる：
#    ドン!!デッキからドン!!1枚までをレストで追加する。
# --------------------------------------------------------------------------- #
def test_op01_101_sasaki_attack_optional_cost_then_ai():
    """アタック時 (任意コスト): 手札1捨て → レストドン1枚を追加 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("ST01-004"), repo.get("ST01-004")]
    attacker = InPlay.of(repo.get("OP01-101"), sickness=False)
    attacker.attached_dons = 1  # 【ドン!!×1】ゲート成立
    me.characters = [attacker]

    hand_before = len(me.hand)
    rested_before = me.don_rested
    do, eff = _do(overlay, "OP01-101", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    for prim in do:
        execute_effect(prim, st, me, opp, attacker)
    assert len(me.hand) == hand_before - 1, "任意コスト (手札1捨て) が支払われていない"
    assert me.don_rested == rested_before + 1, "レストドンが1枚追加されていない"


def test_op01_101_sasaki_attack_human_optional_confirm():
    """人間: 任意コスト → optional_cost_confirm modal が立ち、 承諾で 効果まで解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("ST01-004"), repo.get("ST01-004")]
    attacker = InPlay.of(repo.get("OP01-101"), sickness=False)
    attacker.attached_dons = 1
    me.characters = [attacker]

    hand_before = len(me.hand)
    rested_before = me.don_rested
    do, _ = _do(overlay, "OP01-101", "on_attack")
    execute_effect(do[0], st, me, opp, attacker)
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾 (= コストを払う)
    _drain_choices(st)
    assert len(me.hand) == hand_before - 1, "承諾後 手札1枚が捨てられていない"
    assert me.don_rested == rested_before + 1, "承諾後 レストドンが追加されていない"


# --------------------------------------------------------------------------- #
#  OP01-102 ジャック: 【アタック時】ドン!!-1 相手は自身の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op01_102_jack_attack_opp_discard_ai():
    """アタック時 (ドン-1): 相手が自身の手札を1枚捨てる → 相手手札 -1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.hand = [repo.get("ST01-004"), repo.get("OP01-013")]

    opp_hand_before = len(opp.hand)
    do, _ = _do(overlay, "OP01-102", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-102"), sickness=False))
    assert len(opp.hand) == opp_hand_before - 1, \
        f"相手手札が1枚捨てられていない: {len(opp.hand)} (before {opp_hand_before})"


# --------------------------------------------------------------------------- #
#  OP01-104 スピード: 【トリガー】自身を登場させる (play_self)。
# --------------------------------------------------------------------------- #
def test_op01_104_speed_trigger_play_self_ai():
    """【トリガー】ライフからめくれた自身を場に登場させる (play_self)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP01-104")]
    st.current_source_card_id = "OP01-104"

    chars_before = len(me.characters)
    do, _ = _do(overlay, "OP01-104", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert any(c.card.card_id == "OP01-104" for c in me.characters), \
        "トリガー play_self で スピード が登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"


# --------------------------------------------------------------------------- #
#  OP01-105 バオファン: 【登場時】相手の手札2枚を選び、公開する。
# --------------------------------------------------------------------------- #
def test_op01_105_baofang_on_play_reveal_opp_hand_ai():
    """登場時: 相手手札2枚を公開 (= known_hand_card_ids に記録、 手札枚数は不変)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.hand = [repo.get("ST01-004"), repo.get("OP01-013"), repo.get("OP01-016")]
    opp.known_hand_card_ids = []

    hand_before = len(opp.hand)
    do, _ = _do(overlay, "OP01-105", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-105"), sickness=True))
    assert len(opp.hand) == hand_before, "公開のみ (= 手札枚数は変わらない) のはず"
    assert len(opp.known_hand_card_ids) == 2, \
        f"公開した2枚が known_hand_card_ids に記録されていない: {opp.known_hand_card_ids}"


# --------------------------------------------------------------------------- #
#  OP01-106 バジル・ホーキンス: 【登場時】ドン!!デッキからドン!!1枚までをレストで追加 /
#    【トリガー】このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op01_106_hawkins_on_play_add_rested_don_ai():
    """登場時: ドンデッキからレストドン1枚をコストエリアに追加 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]

    rested_before = me.don_rested
    remaining_before = me.don_remaining_in_deck
    assert remaining_before >= 1, "テスト前提: ドンデッキに残りがある"
    do, _ = _do(overlay, "OP01-106", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-106"), sickness=True))
    assert me.don_rested == rested_before + 1, "レストドンが1枚追加されていない"
    assert me.don_remaining_in_deck == remaining_before - 1, \
        "ドンデッキの残りが1枚減っていない"


def test_op01_106_hawkins_trigger_play_self_ai():
    """【トリガー】ライフからめくれた自身を場に登場させる (play_self)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP01-106")]
    st.current_source_card_id = "OP01-106"

    chars_before = len(me.characters)
    do, _ = _do(overlay, "OP01-106", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert any(c.card.card_id == "OP01-106" for c in me.characters), \
        "トリガー play_self で ホーキンス が登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"


# --------------------------------------------------------------------------- #
#  OP01-108 人斬り鎌ぞう: 【KO時】ドン!!-1 相手のコスト5以下キャラ1枚までを KO。
# --------------------------------------------------------------------------- #
def test_op01_108_kamazou_on_ko_ko_cost_le5_ai():
    """KO時 (ドン-1): 相手のコスト5以下キャラを KO する (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 (<=5)
    assert victim.card.cost <= 5
    opp.characters = [victim]

    do, _ = _do(overlay, "OP01-108", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-108"), sickness=False))
    assert victim not in opp.characters, "コスト5以下キャラが KO されていない"


def test_op01_108_kamazou_on_ko_human_target_pick():
    """人間 + 相手コスト5以下キャラ 複数 → target_pick modal が立ち resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP01-108", "on_ko")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP01-108"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain_choices(st)
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは場に残るべき"


# --------------------------------------------------------------------------- #
#  OP01-109 フーズ・フー: 【ドン!!×1】【自分のターン中】自場のドン!!が8枚以上なら
#    このキャラはパワー+1000 (静的)。
# --------------------------------------------------------------------------- #
def test_op01_109_whosewho_static_pump_when_don_ge8():
    """静的 (on_attached_don n=1、 自ターン中、 ドン8枚以上): +1000。
    印刷 3000 + DON1枚(+1000) + 効果(+1000) = 5000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    ww_def = repo.get("OP01-109")  # power 3000
    ww = InPlay.of(ww_def, sickness=False)
    ww.attached_dons = 1  # n=1 ゲート成立 + DON +1000
    me.characters = [ww]
    me.don_active = 7  # 自場ドン合計 = don_active 7 + attached 1 = 8 (>=8)

    evaluate_static_effects(st, overlay)
    assert ww.power == ww_def.power + 1000 + 1000, \
        f"ドン8枚以上で効果 +1000 が乗っていない: {ww.power} (base {ww_def.power})"


def test_op01_109_whosewho_static_no_pump_when_don_lt8():
    """自場のドン!!が8枚未満なら効果 pump は乗らない (DON分の +1000 のみ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    ww_def = repo.get("OP01-109")
    ww = InPlay.of(ww_def, sickness=False)
    ww.attached_dons = 1
    me.characters = [ww]
    me.don_active = 3  # 合計 = 3 + 1 = 4 (<8)

    evaluate_static_effects(st, overlay)
    assert ww.power == ww_def.power + 1000, \
        f"ドン8枚未満で効果 pump が乗ってはいけない: {ww.power} (base {ww_def.power})"
