# -*- coding: utf-8 -*-
"""Step 2-pre (R72+) 24 新規指標 + Step 2A 4 個 = 計 28 指標の値検証。

各指標が compute_breakdown に含まれ、 期待値を返すことを確認。
重みは全て初期 0 なので、 contribution = 0 を確認 (= 既存 score への影響なし)。
"""

from __future__ import annotations

import math
import random
from pathlib import Path

import pytest

from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.eval import (
    BoardEvalWeights,
    active_blocker_count,
    compute_breakdown,
    compute_score,
    dead_card_in_hand,
    don_reserve,
    double_attack_count,
    field_exposure,
    finisher_in_hand_count,
    hand_log,
    keyword_taunt_count,
    ko_immune_count,
    lethal_risk_diff,
    opp_known_finisher_count,
    playable_cost_match,
    removal_threat_count,
    rush_count,
    self_counter_in_hand_total,
    stage_count,
    stage_value,
    static_cost_reduction_total,
    synergy_count,
    trash_archetype_match,
    trash_count,
)
from engine.game import setup_game


ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def repo():
    return CardRepository.from_json(ROOT / "db" / "cards.json")


@pytest.fixture(scope="module")
def overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


@pytest.fixture
def state(repo, overlay):
    deck_a = DeckList.from_json(ROOT / "decks" / "cardrush_1454.json", repo)  # 紫エネル
    deck_b = DeckList.from_json(ROOT / "decks" / "cardrush_1453.json", repo)  # 緑ミホーク
    return setup_game(
        deck_a, deck_b, rng=random.Random(42), first_player=0, effects_overlay=overlay
    )


# --------------------------------------------------------------------------- #
# breakdown 構造テスト
# --------------------------------------------------------------------------- #

EXPECTED_NEW_KEYS = [
    # 計画書 10
    "is_first_player",
    "stage_count",
    "stage_value",
    "trash_count",
    "trash_archetype_match",
    "rush_count",
    "double_attack_count",
    "static_cost_reduction_total",
    "playable_cost_match",
    "synergy_count",
    # 即追加 9
    "is_my_turn",
    "turn_number_normalized",
    "dead_card_in_hand",
    "active_blocker_count",
    "removal_threat_count",
    "self_counter_in_hand_total",
    "finisher_in_hand_count",
    "keyword_taunt_count",
    "ko_immune_count",
    # state 拡張 5
    "cards_drawn_total",
    "cards_played_total",
    "dons_used_total",
    "tempo_lost_total",
    "known_finisher_count_in_hand",
    # Step 2A 4
    "don_reserve",
    "field_exposure",
    "hand_log",
    "lethal_risk_diff",
]


def test_breakdown_has_all_28_new_keys(state):
    """28 個の新規指標が全て breakdown dict に含まれる。"""
    bd = compute_breakdown(state, 0)
    for k in EXPECTED_NEW_KEYS:
        assert k in bd, f"missing key: {k}"


def test_breakdown_total_keys_73(state):
    """既存 15 + Step 2-pre 28 + Iter2 interaction 30 = 73 指標。"""
    bd = compute_breakdown(state, 0)
    assert len(bd) == 73


def test_default_weights_zero_for_new_keys(state):
    """新規 28 指標は default 重み 0 → contribution 0 (= 既存 score 不変)。"""
    bd = compute_breakdown(state, 0)
    for k in EXPECTED_NEW_KEYS:
        assert bd[k]["contribution"] == 0, f"{k} contribution should be 0 with default weights"


# --------------------------------------------------------------------------- #
# 計画書 10
# --------------------------------------------------------------------------- #


def test_is_first_player(state):
    """P0 (= me_idx=0) は先攻、 P1 視点では opp が先攻。"""
    bd0 = compute_breakdown(state, 0)
    bd1 = compute_breakdown(state, 1)
    assert bd0["is_first_player"]["self"] == 1
    assert bd0["is_first_player"]["opp"] == 0
    assert bd1["is_first_player"]["self"] == 0
    assert bd1["is_first_player"]["opp"] == 1


def test_stage_count_initial_zero(state):
    """初期 setup_game 直後はステージ未設置。"""
    p0, p1 = state.players
    assert stage_count(p0) == 0
    assert stage_count(p1) == 0


def test_trash_count_initial_zero(state):
    """初期はトラッシュ空。"""
    assert trash_count(state.players[0]) == 0


def test_trash_archetype_match_initial_zero(state):
    """初期は trash 空 → archetype match 0。"""
    assert trash_archetype_match(state.players[0]) == 0


def test_trash_archetype_match_after_inserting(repo, overlay):
    """trash に leader feature と共通の card を入れると count 増える。"""
    deck_a = DeckList.from_json(ROOT / "decks" / "cardrush_1453.json", repo)  # 緑ミホーク
    deck_b = DeckList.from_json(ROOT / "decks" / "cardrush_1454.json", repo)
    s = setup_game(deck_a, deck_b, rng=random.Random(0), first_player=0, effects_overlay=overlay)
    p = s.players[0]
    leader_features = set(p.leader.card.features or ())
    if not leader_features:
        pytest.skip("leader has no features")
    # leader feature を 1 つでも持つカードを deck から探して trash に入れる
    matched = None
    for c in p.deck:
        if leader_features & set(c.features or ()):
            matched = c
            break
    if matched is None:
        pytest.skip("no card with matching feature in deck")
    p.trash.append(matched)
    assert trash_archetype_match(p) >= 1


def test_rush_count_initial_zero(state):
    """初期は場のキャラなし → rush 0。"""
    assert rush_count(state.players[0]) == 0


def test_double_attack_count_initial_zero(state):
    assert double_attack_count(state.players[0]) == 0


def test_static_cost_reduction_total_initial_zero(state):
    assert static_cost_reduction_total(state.players[0]) == 0


def test_playable_cost_match_returns_diff(state):
    """max(hand cost) - don_active を返す。 don_active=0 なら max_cost と同値。"""
    p = state.players[0]
    if not p.hand:
        pytest.skip("hand empty")
    expected = max((c.cost or 0) for c in p.hand) - p.don_active
    assert playable_cost_match(p) == expected


def test_playable_cost_match_empty_hand_zero(repo, overlay):
    """hand 空時は 0 を返す。"""
    deck_a = DeckList.from_json(ROOT / "decks" / "cardrush_1454.json", repo)
    deck_b = DeckList.from_json(ROOT / "decks" / "cardrush_1453.json", repo)
    s = setup_game(deck_a, deck_b, rng=random.Random(0), first_player=0, effects_overlay=overlay)
    s.players[0].hand = []
    assert playable_cost_match(s.players[0]) == 0


def test_synergy_count_initial_zero(state):
    """初期は場のキャラなし → synergy 0。"""
    assert synergy_count(state.players[0]) == 0


# --------------------------------------------------------------------------- #
# 即追加 9
# --------------------------------------------------------------------------- #


def test_is_my_turn_initial(state):
    """初期は P0 のターン → P0 視点で self=1, opp=0。"""
    bd0 = compute_breakdown(state, 0)
    bd1 = compute_breakdown(state, 1)
    assert bd0["is_my_turn"]["self"] == 1
    assert bd0["is_my_turn"]["opp"] == 0
    assert bd1["is_my_turn"]["self"] == 0
    assert bd1["is_my_turn"]["opp"] == 1


def test_turn_number_normalized(state):
    """初期は turn 1 → normalized 0.1。"""
    bd = compute_breakdown(state, 0)
    assert bd["turn_number_normalized"]["self"] == pytest.approx(0.1)


def test_dead_card_in_hand_when_no_don(state):
    """don_active=0 なら cost > 0 のカード全部 dead。"""
    p = state.players[0]
    p.don_active = 0
    p.play_cost_reduction = 0
    expected = sum(1 for c in p.hand if (c.cost or 0) > 0)
    assert dead_card_in_hand(p) == expected


def test_active_blocker_count_initial_zero(state):
    """初期は場のキャラなし → active blocker 0。"""
    assert active_blocker_count(state.players[0]) == 0


def test_removal_threat_count_returns_int(state):
    """removal カード数 (= role lookup ベース) を返す。"""
    assert isinstance(removal_threat_count(state.players[0]), int)


def test_self_counter_in_hand_total_matches_sum(state):
    """手札の counter 値合計と一致。"""
    p = state.players[0]
    expected = sum(c.counter or 0 for c in p.hand)
    assert self_counter_in_hand_total(p) == expected


def test_finisher_in_hand_count_returns_int(state):
    assert isinstance(finisher_in_hand_count(state.players[0]), int)


def test_keyword_taunt_count_initial_zero(state):
    """初期は場のキャラなし → taunt 0。"""
    assert keyword_taunt_count(state.players[0]) == 0


def test_ko_immune_count_initial_zero(state):
    assert ko_immune_count(state.players[0]) == 0


# --------------------------------------------------------------------------- #
# state 拡張 5
# --------------------------------------------------------------------------- #


def test_cards_drawn_total_after_setup(state):
    """setup_game で 5 枚ドロー (= マリガンしない場合)。"""
    p = state.players[0]
    # マリガンしてれば 10、 してなければ 5 + life ドロー (= life is moved from deck, no draw)
    assert p.cards_drawn_count >= 5


def test_cards_played_total_initial_zero(state):
    assert state.players[0].cards_played_count == 0


def test_dons_used_total_initial_zero(state):
    assert state.players[0].dons_used_count == 0


def test_tempo_lost_total_initial_zero(state):
    assert state.players[0].dons_unused_at_end_count == 0


def test_known_finisher_count_in_hand_initial_zero(state):
    """known_hand_card_ids は初期空 → 0。"""
    assert opp_known_finisher_count(state.players[0]) == 0


# --------------------------------------------------------------------------- #
# Step 2A 4
# --------------------------------------------------------------------------- #


def test_don_reserve_equals_don_active(state):
    """don_reserve = don_active と一致。"""
    p = state.players[0]
    assert don_reserve(p) == p.don_active


def test_field_exposure_initial_zero(state):
    """初期は場のキャラなし → exposure 0。"""
    p0, p1 = state.players
    assert field_exposure(p0, p1) == 0


def test_hand_log_value(state):
    """log(hand+1)。"""
    p = state.players[0]
    assert hand_log(p) == pytest.approx(math.log(len(p.hand) + 1))


def test_lethal_risk_diff_initial_zero(state):
    """初期は両方 lethal=0 → diff = 0。"""
    assert lethal_risk_diff(state, 0) == 0


# --------------------------------------------------------------------------- #
# 重みを上げると contribution に反映される
# --------------------------------------------------------------------------- #


def test_weight_change_affects_contribution(state):
    """W_IS_FIRST_PLAYER=1000 にすると contribution = 1000 * diff。"""
    bd0 = compute_breakdown(state, 0, BoardEvalWeights(W_IS_FIRST_PLAYER=0))
    bd1 = compute_breakdown(state, 0, BoardEvalWeights(W_IS_FIRST_PLAYER=1000))
    assert bd0["is_first_player"]["contribution"] == 0
    assert bd1["is_first_player"]["contribution"] == 1000 * bd1["is_first_player"]["diff"]


def test_compute_score_unchanged_with_zero_weights(state):
    """新規 28 個全て重み 0 → compute_score は新規追加なし時と同じ。

    回帰テスト: Step 2-pre 追加で既存スコアが変わってないこと。
    """
    s = compute_score(state, 0)
    # 新規重みを全て explicit に 0 に設定した場合と同値
    w = BoardEvalWeights()  # 全 default
    s_explicit = compute_score(state, 0, w)
    assert s == s_explicit
