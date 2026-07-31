# -*- coding: utf-8 -*-
"""プロモ (P-*) 効果 回帰テスト バックフィル (自動生成 wave 155):
P-003 / P-004 / P-005 / P-006 / P-007 /
P-008 / P-009 / P-010 / P-013 / P-014 の 10 枚。

目的 (= test_backfill_auto_001〜154.py と同一方針):
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
)

ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------- #
#  効果の薄い (= 素材用) カード。
# --------------------------------------------------------------------------- #
NAMI = "OP01-016"           # ナミ (麦わらの一味, cost1 power2000) フィラー / cost1 相手キャラ
COST2 = "OP01-013"          # ウソップ (麦わらの一味, cost2 power3000) フィラー / cost2 相手キャラ
NEUTRAL_LEADER = "OP01-001"  # ロロノア・ゾロ (LEADER)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, turn=0,
           opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 MAIN / turn_number=3。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(COST2)] * 30
    p1.deck = [repo.get(COST2)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when):
    """指定 card_id の overlay から when 一致の効果の (do 配列, eff) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    assert matches, f"{cid} に when={when} の効果がない"
    return matches[0]["do"], matches[0]


def _activate(st, me, opp, overlay, cid):
    """cid の起動メインを legal から取り出して発火する。"""
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == cid]
    assert len(opts) == 1, f"{cid} の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])


def _drain(st, pick, guard=6):
    """残った pending_choice を安全に drain。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick))
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave155_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["P-003", "P-004", "P-005", "P-006", "P-007",
           "P-008", "P-009", "P-010", "P-013", "P-014"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  P-003 ユースタス・キッド: 【ドン!!×2】このキャラは【ダブルアタック】を得る。
# --------------------------------------------------------------------------- #
def test_p_003_double_attack_static_on_two_don():
    """ドン2枚付与で【ダブルアタック】が static_granted_keywords に立つ (常在)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me = st.players[0]
    kid = InPlay.of(repo.get("P-003"), sickness=False)
    me.characters = [kid]

    kid.attached_dons = 2
    evaluate_static_effects(st, overlay)
    assert "ダブルアタック" in kid.static_granted_keywords, \
        f"ドン2で【ダブルアタック】が付与されていない: {kid.static_granted_keywords}"


def test_p_003_double_attack_off_when_one_don():
    """ドン1枚 (=×2 ゲート未達) では【ダブルアタック】が付かない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me = st.players[0]
    kid = InPlay.of(repo.get("P-003"), sickness=False)
    me.characters = [kid]

    kid.attached_dons = 1
    evaluate_static_effects(st, overlay)
    assert "ダブルアタック" not in kid.static_granted_keywords, \
        "ドン1枚で【ダブルアタック】が付いてはいけない (【ドン!!×2】)"


# --------------------------------------------------------------------------- #
#  P-004 クロコダイル: 【ドン!!×1】このキャラは【ブロッカー】を得る。
# --------------------------------------------------------------------------- #
def test_p_004_blocker_static_on_one_don():
    """ドン1枚付与で【ブロッカー】が static_granted_keywords に立つ (常在)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me = st.players[0]
    croc = InPlay.of(repo.get("P-004"), sickness=False)
    me.characters = [croc]

    croc.attached_dons = 1
    evaluate_static_effects(st, overlay)
    assert "ブロッカー" in croc.static_granted_keywords, \
        f"ドン1で【ブロッカー】が付与されていない: {croc.static_granted_keywords}"


def test_p_004_blocker_off_when_no_don():
    """ドン0枚では【ブロッカー】が付かない (【ドン!!×1】ゲート)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me = st.players[0]
    croc = InPlay.of(repo.get("P-004"), sickness=False)
    me.characters = [croc]

    croc.attached_dons = 0
    evaluate_static_effects(st, overlay)
    assert "ブロッカー" not in croc.static_granted_keywords, \
        "ドン0枚で【ブロッカー】が付いてはいけない"


# --------------------------------------------------------------------------- #
#  P-005 カイドウ: 【起動メイン】ドン!!-2：このキャラは、このターン中、【バニッシュ】を得る。
# --------------------------------------------------------------------------- #
def test_p_005_activate_main_grants_banish_ai():
    """起動メイン (ドン!!-2 コスト) で【バニッシュ】を得る。 AI 自動発動。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    kaido = InPlay.of(repo.get("P-005"), sickness=False)
    me.characters = [kaido]
    me.don_active = 3  # ドン!!-2 コスト用

    don_before = me.don_active
    _activate(st, me, opp, overlay, "P-005")
    assert "バニッシュ" in kaido.granted_keywords, \
        f"起動メインで【バニッシュ】が付与されていない: {kaido.granted_keywords}"
    assert me.don_active == don_before - 2, \
        f"ドン!!-2 コストが2枚支払われていない: {me.don_active} (before {don_before})"


def test_p_005_activate_main_blocked_without_don():
    """アクティブドンが2枚未満なら ドン!!-2 コスト不能 → 起動メインが legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me = st.players[0]
    kaido = InPlay.of(repo.get("P-005"), sickness=False)
    me.characters = [kaido]
    me.don_active = 1  # 2枚未満 = 支払い不能

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "P-005"]
    assert len(opts) == 0, \
        "ドン2枚を払えないのに起動メインが legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  P-006 モンキー・D・ルフィ: 【ドン!!×2】【自分のターン中】このキャラはパワー+2000。
# --------------------------------------------------------------------------- #
def test_p_006_self_turn_pump_static():
    """ドン2 + 自分のターン中 → base 3000 + DON2000 + 効果2000 = 7000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, turn=0)  # 自分のターン
    me = st.players[0]
    luffy = InPlay.of(repo.get("P-006"), sickness=False)
    me.characters = [luffy]

    luffy.attached_dons = 2
    evaluate_static_effects(st, overlay)
    assert luffy.power == 7000, \
        f"自ターン + ドン2 で 7000 にならない: {luffy.power}"


def test_p_006_no_pump_on_opponent_turn():
    """相手ターン中は【自分のターン中】不成立 → 効果 +2000 が乗らない (5000)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, turn=1)  # 相手ターン
    me = st.players[0]
    luffy = InPlay.of(repo.get("P-006"), sickness=False)
    me.characters = [luffy]

    luffy.attached_dons = 2
    evaluate_static_effects(st, overlay)
    assert luffy.power == 5000, \
        f"相手ターンで効果 +2000 が乗ってはいけない: {luffy.power}"


# --------------------------------------------------------------------------- #
#  P-007 モンキー・D・ルフィ: 【ドン!!×1】属性(打)を持つ相手とのバトルでKOされない。
# --------------------------------------------------------------------------- #
def test_p_007_immune_to_strike_attribute_on_one_don():
    """ドン1付与で 属性(打) 免疫が ko_immune_battle_attributes_in に立つ (常在)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me = st.players[0]
    luffy = InPlay.of(repo.get("P-007"), sickness=False)
    me.characters = [luffy]

    luffy.attached_dons = 1
    evaluate_static_effects(st, overlay)
    assert "打" in luffy.ko_immune_battle_attributes_in, \
        f"ドン1で属性(打)KO免疫が付与されていない: {luffy.ko_immune_battle_attributes_in}"


def test_p_007_immune_off_when_no_don():
    """ドン0枚では 属性(打) 免疫が付かない (【ドン!!×1】ゲート)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me = st.players[0]
    luffy = InPlay.of(repo.get("P-007"), sickness=False)
    me.characters = [luffy]

    luffy.attached_dons = 0
    evaluate_static_effects(st, overlay)
    assert "打" not in luffy.ko_immune_battle_attributes_in, \
        "ドン0枚で属性(打)免疫が付いてはいけない"


# --------------------------------------------------------------------------- #
#  P-008 ヤマト: 【起動メイン】このキャラをレストにできる：
#                相手のコスト2以下のキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_p_008_activate_main_rest_opp_cost2_ai():
    """起動メイン (自レストがコスト) → 相手コスト2以下キャラ1枚をレスト。 AI 自動。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    yamato = InPlay.of(repo.get("P-008"), sickness=False)
    me.characters = [yamato]
    victim = InPlay.of(repo.get(NAMI), sickness=False)  # cost1
    opp.characters = [victim]

    _activate(st, me, opp, overlay, "P-008")
    assert victim.rested is True, "相手コスト2以下キャラがレストされていない"
    assert yamato.rested is True, "起動メインコストで自身がレストされるべき"


def test_p_008_activate_main_rest_human_pick():
    """人間 + 相手コスト2以下キャラ複数 → target_pick modal が立ち resolve でレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    yamato = InPlay.of(repo.get("P-008"), sickness=False)
    me.characters = [yamato]
    a = InPlay.of(repo.get(NAMI), sickness=False)   # cost1
    b = InPlay.of(repo.get(COST2), sickness=False)  # cost2
    opp.characters = [a, b]

    _activate(st, me, opp, overlay, "P-008")
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b.rested is True, "人間が選んだキャラがレストされていない"
    assert a.rested is False, "選ばなかったキャラはレストされてはいけない"


# --------------------------------------------------------------------------- #
#  P-009 トラファルガー・ロー: 【登場時】相手の手札が6枚以上ある場合、
#                             相手は自身のライフ1枚を手札に加える。
# --------------------------------------------------------------------------- #
def test_p_009_on_play_condition_gate():
    """条件 opp_hand_count_ge=6: 手札6で成立、 手札3で不成立。"""
    repo = _repo()
    overlay = _overlay()
    _, eff = _do(overlay, "P-009", "on_play")
    cond = eff.get("if")
    assert cond and cond.get("opp_hand_count_ge") == 6, \
        f"overlay の条件 opp_hand_count_ge=6 が無い: {cond}"

    st = _state(repo, NEUTRAL_LEADER, overlay)
    me = st.players[0]
    st.players[1].hand = [repo.get(COST2)] * 6
    assert eval_condition(cond, st, me,
                          InPlay.of(repo.get("P-009"), sickness=True)) is True, \
        "相手手札6枚で条件が成立していない"

    st2 = _state(repo, NEUTRAL_LEADER, overlay)
    me2 = st2.players[0]
    st2.players[1].hand = [repo.get(COST2)] * 3
    assert eval_condition(cond, st2, me2,
                          InPlay.of(repo.get("P-009"), sickness=True)) is False, \
        "相手手札3枚で条件が成立してはいけない"


def test_p_009_on_play_mill_opp_life_to_hand_ai():
    """条件成立時: 相手ライフ上1枚が相手の手札へ移る。 AI 自動。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.hand = [repo.get(COST2)] * 6
    opp.life = [repo.get(COST2)] * 3

    life_before = len(opp.life)
    hand_before = len(opp.hand)
    do, _ = _do(overlay, "P-009", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-009"), sickness=True))
    assert len(opp.life) == life_before - 1, \
        f"相手ライフが1枚減っていない: {len(opp.life)} (before {life_before})"
    assert len(opp.hand) == hand_before + 1, \
        f"取ったライフが相手の手札に入っていない: {len(opp.hand)}"


# --------------------------------------------------------------------------- #
#  P-010 カイドウ: 【自分のターン終了時】ドン!!デッキからドン!!1枚までをアクティブで追加する。
# --------------------------------------------------------------------------- #
def test_p_010_end_of_turn_add_active_don_ai():
    """ターン終了時: ドンデッキからアクティブドン1枚を追加。 AI 自動。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]

    active_before = me.don_active
    remain_before = me.don_remaining_in_deck
    do, _ = _do(overlay, "P-010", "end_of_turn")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-010"), sickness=False))
    assert me.don_active == active_before + 1, \
        f"アクティブドンが1枚追加されていない: {me.don_active} (before {active_before})"
    assert me.don_remaining_in_deck == remain_before - 1, \
        "ドンデッキ残数が1枚減るべき"


# --------------------------------------------------------------------------- #
#  P-013 ゴードン: 【起動メイン】…：相手のキャラ1枚までを、このターン中、パワー-3000。
# --------------------------------------------------------------------------- #
def test_p_013_activate_main_debuff_ai():
    """起動メイン → 相手キャラ1枚を このターン中 パワー-3000。 AI 自動選択。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    gordon = InPlay.of(repo.get("P-013"), sickness=False)
    me.characters = [gordon]
    victim = InPlay.of(repo.get(COST2), sickness=False)  # power 3000
    opp.characters = [victim]

    power_before = victim.power
    _activate(st, me, opp, overlay, "P-013")
    assert victim.power == power_before - 3000, \
        f"相手キャラ -3000 が反映されていない: {victim.power} (before {power_before})"


def test_p_013_activate_main_debuff_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal が立ち resolve で 1 体に -3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    gordon = InPlay.of(repo.get("P-013"), sickness=False)
    me.characters = [gordon]
    a = InPlay.of(repo.get(NAMI), sickness=False)   # power 2000
    b = InPlay.of(repo.get(COST2), sickness=False)  # power 3000
    opp.characters = [a, b]

    _activate(st, me, opp, overlay, "P-013")
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b.power == b_before - 3000, "人間が選んだ相手キャラに -3000 が反映されていない"
    assert a.power == 2000, "選ばなかったキャラの power は変化してはいけない"


# --------------------------------------------------------------------------- #
#  P-014 コビー: 【ブロッカー】…(overlay = 【トリガー】自身登場 play_self)
# --------------------------------------------------------------------------- #
def test_p_014_trigger_play_self_ai():
    """【トリガー】このカード (トラッシュ) を登場させる。 AI: 場に出る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("P-014")]  # play_self の登場元
    me.characters = []

    do, _ = _do(overlay, "P-014", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-014"), sickness=True))
    assert any(c.card.card_id == "P-014" for c in me.characters), \
        "【トリガー】でコビーが場に登場していない"
    assert all(c.card_id != "P-014" for c in me.trash), \
        "登場後 トラッシュに P-014 が残ってはいけない"
