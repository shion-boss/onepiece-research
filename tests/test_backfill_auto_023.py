# -*- coding: utf-8 -*-
"""OP01 弾 効果 回帰テスト バックフィル (自動生成 wave 023):
OP01-067 / OP01-068 / OP01-069 / OP01-071 / OP01-072 / OP01-073 /
OP01-074 / OP01-077 / OP01-078 / OP01-079 の 10 枚 (青)。

目的 (= test_backfill_auto_001〜022.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 任意コスト を 持つカードは 人間 actor で pending_choice が
      正しい kind + 候補で立ち、 resolve_pending_choice で解決できる (= 人間が選べる)
  (3) 同じ効果を AI 文脈 (human_player_idx=None) で回しても crash せず自動解決する
      (= AI が選べる)

注記: OP01-072 スマイリー (power_pump amount_per source="self_hand_count") は
      2026-07-21 に engine/effects.py へ実装済 (= 手札1枚につき +1000)。
      test_op01_072_smiley_static_pump_per_hand で検証する (= 旧 skip は解消)。
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    eval_all_conditions,
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
    デッキ filler は OP01-020 (ワノ国、 麦わらの一味 でない) = search/draw フィルタ誤爆防止。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("OP01-020")] * 30
    p1.deck = [repo.get("OP01-020")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果の (do, effect) を返す。"""
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
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave23_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP01-067", "OP01-068", "OP01-069", "OP01-071", "OP01-072",
           "OP01-073", "OP01-074", "OP01-077", "OP01-078", "OP01-079"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP01-067 クロコダイル (CHARACTER 青 cost7 power7000):
#    【バニッシュ】【ドン‼×1】自分の手札の青のイベントを、コスト-1。
#    → static (on_attached_don n=1) で play_cost_reductions_filtered に登録。
# --------------------------------------------------------------------------- #
def test_op01_067_crocodile_static_cost_reduction_with_don():
    """ドン1 付与時: 自分の {色:青, EVENT} の登場コスト -1 が static に登録される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-062", overlay)
    me, opp = st.players[0], st.players[1]
    croc = InPlay.of(repo.get("OP01-067"), sickness=False)
    croc.attached_dons = 1  # ドン1 ゲート成立
    me.characters = [croc]

    evaluate_static_effects(st, overlay)
    reductions = me.play_cost_reductions_filtered
    assert len(reductions) == 1, \
        f"青イベントのコスト減が登録されていない: {reductions}"
    entry = reductions[0]
    assert entry["filter"].get("color") == "青", "フィルタ色が青でない"
    assert entry["filter"].get("category") == "EVENT", "フィルタが EVENT でない"
    assert entry["amount"] == 1, f"減少量が 1 でない: {entry['amount']}"


def test_op01_067_crocodile_no_reduction_without_don():
    """ドン未付与では静的コスト減が乗らない (ドンゲート)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-062", overlay)
    me, opp = st.players[0], st.players[1]
    croc = InPlay.of(repo.get("OP01-067"), sickness=False)
    croc.attached_dons = 0
    me.characters = [croc]

    evaluate_static_effects(st, overlay)
    assert me.play_cost_reductions_filtered == [], \
        f"ドン0 でコスト減が乗ってはいけない: {me.play_cost_reductions_filtered}"


# --------------------------------------------------------------------------- #
#  OP01-068 ゲッコー・モリア (CHARACTER 青 cost4 power5000):
#    【自分のターン中】自分の手札が5枚以上の場合、このキャラは【ダブルアタック】を得る。
# --------------------------------------------------------------------------- #
def test_op01_068_moria_gains_double_attack_with_five_hand():
    """自分のターン + 手札5枚以上: static_granted_keywords に ダブルアタック。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-062", overlay)
    me, opp = st.players[0], st.players[1]
    moria = InPlay.of(repo.get("OP01-068"), sickness=False)
    me.characters = [moria]
    me.hand = [repo.get("OP01-020")] * 5  # 手札5枚 (= 条件成立)

    evaluate_static_effects(st, overlay)
    assert "ダブルアタック" in moria.static_granted_keywords, \
        f"手札5枚で ダブルアタック が付与されていない: {moria.static_granted_keywords}"


def test_op01_068_moria_no_double_attack_with_four_hand():
    """手札4枚では条件不成立 → ダブルアタックを得ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-062", overlay)
    me, opp = st.players[0], st.players[1]
    moria = InPlay.of(repo.get("OP01-068"), sickness=False)
    me.characters = [moria]
    me.hand = [repo.get("OP01-020")] * 4

    evaluate_static_effects(st, overlay)
    assert "ダブルアタック" not in moria.static_granted_keywords, \
        "手札4枚で ダブルアタック が付与されてはいけない"


def test_op01_068_moria_no_double_attack_on_opp_turn():
    """相手のターン中は【自分のターン中】条件が不成立 → 得ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-062", overlay)
    st.turn_player_idx = 1  # 相手のターン
    me, opp = st.players[0], st.players[1]
    moria = InPlay.of(repo.get("OP01-068"), sickness=False)
    me.characters = [moria]
    me.hand = [repo.get("OP01-020")] * 5

    evaluate_static_effects(st, overlay)
    assert "ダブルアタック" not in moria.static_granted_keywords, \
        "相手ターンで ダブルアタック が付与されてはいけない"


# --------------------------------------------------------------------------- #
#  OP01-069 シーザー・クラウン (CHARACTER 青 cost4 power5000):
#    【KO時】自分のデッキから「スマイリー」1枚までを、登場させ、デッキをシャッフルする。
# --------------------------------------------------------------------------- #
def test_op01_069_caesar_on_ko_summon_smiley_ai():
    """KO時: デッキ内「スマイリー」(OP01-072) をデッキから登場させる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-062", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP01-072")] + [repo.get("OP01-020")] * 29  # 先頭にスマイリー
    deck_before = len(me.deck)

    do, _ = _do(overlay, "OP01-069", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-069"), sickness=False))

    assert any(c.card.card_id == "OP01-072" for c in me.characters), \
        "デッキのスマイリーが登場していない"
    assert len(me.deck) == deck_before - 1, \
        f"登場でデッキが1枚減っていない: {len(me.deck)} (before {deck_before})"


# --------------------------------------------------------------------------- #
#  OP01-071 ジンベエ (CHARACTER 青 cost4 power2000):
#    【登場時】コスト3以下のキャラ1枚までを、持ち主のデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op01_071_jinbe_on_play_return_cost3_ai():
    """登場時: 相手のコスト3以下キャラ1体をデッキ下へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-062", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost1
    opp.characters = [victim]
    deck_before = len(opp.deck)

    do, _ = _do(overlay, "OP01-071", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-071"), sickness=True))

    assert len(opp.characters) == 0, "相手のコスト3以下キャラがデッキ下へ戻っていない"
    assert len(opp.deck) == deck_before + 1, \
        f"持ち主のデッキが1枚増えていない: {len(opp.deck)} (before {deck_before})"


def test_op01_071_jinbe_on_play_human_target_pick():
    """人間 + 相手コスト3以下キャラ 複数 → target_pick modal が立ち resolve で1体をデッキ下へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-062", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP01-071", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP01-071"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    assert len(st.pending_choice.get("candidates", [])) == 2, \
        "候補が2体でない"
    resolve_pending_choice(st, [0])
    _drain(st, pick=[0])
    assert len(opp.characters) == 1, "人間解決後に相手キャラが1体戻っていない"


# --------------------------------------------------------------------------- #
#  OP01-072 スマイリー: 【ドン‼×1】【自分のターン中】自分の手札1枚につきパワー+1000。
#    (power_pump amount_per source="self_hand_count" を engine に実装済 = 2026-07-21)。
# --------------------------------------------------------------------------- #
def test_op01_072_smiley_static_pump_per_hand():
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-062", overlay)
    me, opp = st.players[0], st.players[1]
    smiley = InPlay.of(repo.get("OP01-072"), sickness=False)
    smiley.attached_dons = 1
    me.characters = [smiley]
    me.hand = [repo.get("OP01-020")] * 4
    evaluate_static_effects(st, overlay)
    assert smiley.static_buff == 4000


# --------------------------------------------------------------------------- #
#  OP01-073 ドンキホーテ・ドフラミンゴ (CHARACTER 青 cost3 power4000):
#    【ブロッカー】【登場時】自分のデッキの上から5枚を見て、好きな順番に並び変え、
#    デッキの上か下に置く。
# --------------------------------------------------------------------------- #
def test_op01_073_doflamingo_on_play_look_reorder_ai():
    """登場時: デッキトップ5枚を見て並べ替え。 デッキ枚数は不変で crash しない (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-062", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP01-016"), repo.get("OP01-013"), repo.get("OP01-025"),
               repo.get("OP01-024"), repo.get("OP01-020")] + [repo.get("OP01-020")] * 25
    deck_before = len(me.deck)

    do, _ = _do(overlay, "OP01-073", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-073"), sickness=True))
    _drain(st)

    assert len(me.deck) == deck_before, \
        f"reorder でデッキ枚数が変わってはいけない: {len(me.deck)} (before {deck_before})"
    assert st.pending_choice is None, "reorder 後に modal が残っている"


def test_op01_073_doflamingo_look_reorder_human_no_crash():
    """人間文脈でも reorder が crash せず解決する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-062", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    deck_before = len(me.deck)

    do, _ = _do(overlay, "OP01-073", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-073"), sickness=True))
    _drain(st)
    assert len(me.deck) == deck_before, "reorder でデッキ枚数が変わってはいけない"


# --------------------------------------------------------------------------- #
#  OP01-074 バーソロミュー・くま (CHARACTER 青 cost4 power5000):
#    【ブロッカー】【KO時】自分の手札からコスト4以下の「パシフィスタ」1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op01_074_kuma_on_ko_play_pacifista_ai():
    """KO時: 手札のコスト4以下パシフィスタ (OP01-075) を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-062", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-075")]  # パシフィスタ cost4
    chars_before = len(me.characters)

    do, _ = _do(overlay, "OP01-074", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-074"), sickness=False))

    assert any(c.card.card_id == "OP01-075" for c in me.characters), \
        "手札のパシフィスタが登場していない"
    assert len(me.characters) == chars_before + 1, "キャラが1体増えていない"
    assert not any(c.card_id == "OP01-075" for c in me.hand), \
        "登場後も手札にパシフィスタが残っている"


def test_op01_074_kuma_on_ko_play_pacifista_human_pick():
    """人間 + 手札にパシフィスタ複数 → play_from_hand modal が立ち resolve で登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-062", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-075"), repo.get("OP01-075")]

    do, _ = _do(overlay, "OP01-074", "on_ko")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP01-074"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, pick=[0])
    assert any(c.card.card_id == "OP01-075" for c in me.characters), \
        "人間が選んだパシフィスタが登場していない"


# --------------------------------------------------------------------------- #
#  OP01-077 ペローナ (CHARACTER 青 cost1 power2000):
#    【登場時】自分のデッキの上から5枚を見て、好きな順番に並び変え、デッキの上か下に置く。
# --------------------------------------------------------------------------- #
def test_op01_077_perona_on_play_look_reorder_ai():
    """登場時: デッキトップ5枚を見て並べ替え。 デッキ枚数は不変で crash しない (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-062", overlay)
    me, opp = st.players[0], st.players[1]
    deck_before = len(me.deck)

    do, _ = _do(overlay, "OP01-077", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-077"), sickness=True))
    _drain(st)

    assert len(me.deck) == deck_before, \
        f"reorder でデッキ枚数が変わってはいけない: {len(me.deck)} (before {deck_before})"
    assert st.pending_choice is None, "reorder 後に modal が残っている"


# --------------------------------------------------------------------------- #
#  OP01-078 ボア・ハンコック (CHARACTER 青 cost4 power5000):
#    【ブロッカー】【ドン‼×1】【アタック時】/【ブロック時】
#    自分の手札が5枚以下の場合、カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op01_078_hancock_on_attack_draw_ai():
    """アタック時 (ドン1 + 手札5以下): カード1枚を引く (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-062", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-020")] * 3
    me.deck = [repo.get("OP01-020")] * 30
    hancock = InPlay.of(repo.get("OP01-078"), sickness=False)
    hancock.attached_dons = 1
    me.characters = [hancock]

    do, eff = _do(overlay, "OP01-078", "on_attack")
    assert eval_all_conditions(eff, st, me, hancock) is True, \
        "テスト前提: ドン1 + 手札3枚で条件が成立していない"
    for prim in do:
        execute_effect(prim, st, me, opp, hancock)

    assert len(me.hand) == 4, f"アタック時ドローが起きていない: {len(me.hand)}"


def test_op01_078_hancock_no_draw_with_six_hand():
    """手札6枚 (5枚超) では条件不成立 → 引かない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-062", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-020")] * 6
    hancock = InPlay.of(repo.get("OP01-078"), sickness=False)
    hancock.attached_dons = 1
    me.characters = [hancock]

    _, eff = _do(overlay, "OP01-078", "on_attack")
    assert eval_all_conditions(eff, st, me, hancock) is False, \
        "手札6枚で条件が成立してはいけない"


def test_op01_078_hancock_on_block_draw_ai():
    """ブロック時 (ドン1 + 手札5以下): カード1枚を引く (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-062", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-020")] * 2
    me.deck = [repo.get("OP01-020")] * 30
    hancock = InPlay.of(repo.get("OP01-078"), sickness=False)
    hancock.attached_dons = 1
    me.characters = [hancock]

    do, eff = _do(overlay, "OP01-078", "on_block")
    assert eval_all_conditions(eff, st, me, hancock) is True, \
        "テスト前提: ブロック時条件が成立していない"
    for prim in do:
        execute_effect(prim, st, me, opp, hancock)

    assert len(me.hand) == 3, f"ブロック時ドローが起きていない: {len(me.hand)}"


# --------------------------------------------------------------------------- #
#  OP01-079 ミス・オールサンデー (CHARACTER 青 cost3 power1000):
#    【ブロッカー】【KO時】自分のリーダーが特徴《B・W》を持つ場合、
#    自分のトラッシュのイベント1枚までを、手札に加える。
# --------------------------------------------------------------------------- #
def test_op01_079_all_sunday_on_ko_recover_event_bw_leader():
    """KO時 + B・W リーダー (OP01-062 クロコダイル): トラッシュのイベントを手札へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-062", overlay)  # クロコダイル (B・W)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("EB04-028")]  # 青イベント アイスタイム
    hand_before = len(me.hand)

    do, eff = _do(overlay, "OP01-079", "on_ko")
    assert eff.get("if", {}).get("leader_feature") == "B・W", \
        "overlay の リーダー特徴 B・W 条件が無い"
    assert eval_all_conditions(eff, st, me,
                               InPlay.of(repo.get("OP01-079"), sickness=False)) is True, \
        "B・W リーダーで条件が成立していない"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-079"), sickness=False))

    assert any(c.card_id == "EB04-028" for c in me.hand), \
        "トラッシュのイベントが手札に加わっていない"
    assert len(me.hand) == hand_before + 1, "手札が1枚増えていない"


def test_op01_079_all_sunday_no_recover_without_bw_leader():
    """リーダーが B・W でなければ (OP01-001 麦わらの一味) 条件不成立 → 回収しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # 麦わらの一味 (B・W でない)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("EB04-028")]

    _, eff = _do(overlay, "OP01-079", "on_ko")
    assert eval_all_conditions(eff, st, me,
                               InPlay.of(repo.get("OP01-079"), sickness=False)) is False, \
        "非 B・W リーダーで条件が成立してはいけない"
