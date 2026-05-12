# -*- coding: utf-8 -*-
"""engine/explorer.py のユニットテスト。"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.explorer import (
    CounterCandidate,
    determine_counter_role_priority,
    generate_counter_candidates,
)

ROOT = Path(__file__).resolve().parent.parent


# ============================================================================ #
# fixtures
# ============================================================================ #

@pytest.fixture(scope="module")
def repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


@pytest.fixture(scope="module")
def overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


@pytest.fixture(scope="module")
def target_deck(repo) -> DeckList:
    """紫エネル (アグロ系)。"""
    return DeckList.from_json(ROOT / "decks" / "cardrush_1424.json", repo)


# ============================================================================ #
# determine_counter_role_priority
# ============================================================================ #

def test_role_priority_for_aggro():
    p = determine_counter_role_priority("アグロ")
    assert "blocker" in p
    assert "recovery" in p
    assert p[0] == "blocker"


def test_role_priority_for_control():
    p = determine_counter_role_priority("コントロール")
    assert "finisher" in p
    assert "disruption" in p


def test_role_priority_for_ramp():
    p = determine_counter_role_priority("ランプ")
    assert "disruption" in p
    assert p[0] == "disruption"


def test_role_priority_unknown_archetype_falls_back():
    p = determine_counter_role_priority("ナゾアーキ")
    assert len(p) >= 4
    assert "removal" in p


def test_role_priority_finisher_heavy_target_boosts_removal():
    """対象が finisher 多 (= 高コスト大型主体) なら removal を boost。"""
    target_kc = [{"role": "finisher"}] * 4 + [{"role": "synergy"}]
    p = determine_counter_role_priority("ミッドレンジ", target_kc)
    # boost で removal が priority 0 に来る
    assert p[0] == "removal"


# ============================================================================ #
# generate_counter_candidates: 基本動作
# ============================================================================ #

def test_generates_n_candidates(target_deck, repo, overlay):
    cands = generate_counter_candidates(target_deck, repo, overlay, n_candidates=10)
    # 最大 10 件、 リーダー候補不足等で少なくなることはあるが空ではない
    assert 0 < len(cands) <= 10


def test_default_n_candidates_20(target_deck, repo, overlay):
    cands = generate_counter_candidates(target_deck, repo, overlay)
    assert 0 < len(cands) <= 20


def test_candidates_are_valid_decks(target_deck, repo, overlay):
    """全候補が DeckList.validate() に通る。"""
    cands = generate_counter_candidates(target_deck, repo, overlay, n_candidates=5)
    for cand in cands:
        cand.deck.validate()
        # 50 枚 + リーダー
        assert len(cand.deck.main) == 50
        assert cand.deck.leader.card_id == cand.leader_id


def test_candidates_have_estimated_score(target_deck, repo, overlay):
    cands = generate_counter_candidates(target_deck, repo, overlay, n_candidates=5)
    for cand in cands:
        assert isinstance(cand.estimated_score, int)
        assert 0 <= cand.estimated_score <= 100


def test_candidates_have_rationale(target_deck, repo, overlay):
    cands = generate_counter_candidates(target_deck, repo, overlay, n_candidates=5)
    for cand in cands:
        assert isinstance(cand.rationale, list)
        assert len(cand.rationale) > 0


def test_candidates_sorted_by_score_desc(target_deck, repo, overlay):
    """estimated_score 降順にソートされている。"""
    cands = generate_counter_candidates(target_deck, repo, overlay, n_candidates=10)
    for i in range(len(cands) - 1):
        assert cands[i].estimated_score >= cands[i + 1].estimated_score


# ============================================================================ #
# 多様性確保
# ============================================================================ #

def test_archetype_diversity(target_deck, repo, overlay):
    """diversity=archetype で複数 archetype が混在する。"""
    cands = generate_counter_candidates(
        target_deck, repo, overlay, n_candidates=20, diversity="archetype"
    )
    archetypes = {c.archetype for c in cands}
    # 少なくとも 2 種以上の archetype が混在
    assert len(archetypes) >= 2


# ============================================================================ #
# leader_filter
# ============================================================================ #

def test_leader_filter_restricts_leaders(target_deck, repo, overlay):
    """leader_filter 指定で対応 leader のみ返る。"""
    target_leader = "OP09-061"  # 紫黒ルフィ
    cands = generate_counter_candidates(
        target_deck, repo, overlay,
        n_candidates=5,
        leader_filter=[target_leader],
    )
    # 1 件 (= 1 leader しか指定してないので)
    assert len(cands) <= 1
    if cands:
        assert cands[0].leader_id == target_leader


# ============================================================================ #
# must_include
# ============================================================================ #

def test_must_include_in_all_candidates(target_deck, repo, overlay):
    """must_include 指定したカードが全候補に入る (= 色合致 leader のみ生成される)。"""
    must = ["OP07-064"]  # サンジ (黄/紫?)
    cands = generate_counter_candidates(
        target_deck, repo, overlay,
        n_candidates=5,
        must_include=must,
    )
    if not cands:
        pytest.skip("候補生成失敗 (= 色合致 leader 不在)")
    for cand in cands:
        card_ids = [c.card_id for c in cand.deck.main]
        assert "OP07-064" in card_ids, f"{cand.leader_id} に OP07-064 が無い"


# ============================================================================ #
# CounterCandidate dataclass
# ============================================================================ #

def test_counter_candidate_structure(target_deck, repo, overlay):
    cands = generate_counter_candidates(target_deck, repo, overlay, n_candidates=1)
    if not cands:
        pytest.skip("候補生成失敗")
    c = cands[0]
    assert isinstance(c, CounterCandidate)
    assert hasattr(c, "deck")
    assert hasattr(c, "leader_id")
    assert hasattr(c, "archetype")
    assert hasattr(c, "estimated_score")
    assert hasattr(c, "rationale")
    assert hasattr(c, "role_distribution")
