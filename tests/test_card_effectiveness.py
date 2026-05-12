# -*- coding: utf-8 -*-
"""engine/card_role.py の effectiveness API のユニットテスト。"""

from __future__ import annotations

from engine.card_role import (
    ARCHETYPES,
    best_cards_against,
    compute_effectiveness,
    load_effectiveness_db,
)


# ============================================================================ #
# DB 形式
# ============================================================================ #

def test_effectiveness_db_loads():
    db = load_effectiveness_db()
    assert "by_role" in db
    assert "by_tag_modifier" in db


def test_archetypes_constant():
    assert ARCHETYPES == ("アグロ", "ミッドレンジ", "コントロール", "ランプ")


def test_all_role_archetype_cells_present():
    """全 role × 全 archetype セルが存在する。"""
    db = load_effectiveness_db()
    by_role = db["by_role"]
    expected_roles = {
        "removal", "negation", "disruption", "search", "draw",
        "ramp", "blocker", "recovery", "finisher", "synergy",
    }
    for role in expected_roles:
        assert role in by_role, f"missing role {role}"
        for arche in ARCHETYPES:
            v = by_role[role].get(arche)
            assert isinstance(v, (int, float)), f"missing/invalid {role} vs {arche}"


def test_all_cells_in_sanity_range():
    """全 セル score ∈ [10, 90]。"""
    db = load_effectiveness_db()
    by_role = db["by_role"]
    for role, entry in by_role.items():
        for arche in ARCHETYPES:
            v = entry.get(arche)
            if not isinstance(v, (int, float)):
                continue
            assert 10 <= v <= 90, f"{role} vs {arche} = {v} (out of [10,90])"


# ============================================================================ #
# sanity 不等式
# ============================================================================ #

def test_removal_better_vs_aggro_than_ramp():
    assert compute_effectiveness("removal", [], "アグロ") > compute_effectiveness(
        "removal", [], "ランプ"
    )


def test_blocker_strong_vs_aggro_weak_vs_control():
    assert compute_effectiveness("blocker", [], "アグロ") > compute_effectiveness(
        "blocker", [], "コントロール"
    )


def test_finisher_strong_vs_control():
    assert compute_effectiveness("finisher", [], "コントロール") > compute_effectiveness(
        "finisher", [], "アグロ"
    )


def test_disruption_strong_vs_ramp():
    assert compute_effectiveness("disruption", [], "ランプ") > compute_effectiveness(
        "disruption", [], "アグロ"
    )


def test_recovery_strong_vs_aggro():
    assert compute_effectiveness("recovery", [], "アグロ") > compute_effectiveness(
        "recovery", [], "コントロール"
    )


# ============================================================================ #
# 計算ロジック
# ============================================================================ #

def test_score_in_zero_hundred_range():
    """全組み合わせで score ∈ [0, 100]。"""
    for role in ["removal", "blocker", "draw", "synergy"]:
        for arche in ARCHETYPES:
            s = compute_effectiveness(role, [], arche)
            assert 0 <= s <= 100


def test_tag_modifier_adds_to_base():
    base = compute_effectiveness("removal", [], "アグロ")
    with_redirect = compute_effectiveness("removal", ["redirect"], "アグロ")
    assert with_redirect == base + 15  # redirect modifier vs アグロ = +15


def test_multiple_tag_modifiers_stack():
    base = compute_effectiveness("removal", [], "アグロ")
    with_two = compute_effectiveness("removal", ["redirect", "protection"], "アグロ")
    # base 75 + redirect 15 + protection 10 = 100 (clamped)
    assert with_two == min(100, base + 15 + 10)


def test_score_clamped_to_100():
    s = compute_effectiveness("blocker", ["redirect", "protection"], "アグロ")
    # base 85 + redirect 15 + protection 10 = 110 → clamped to 100
    assert s == 100


def test_unknown_role_returns_neutral():
    assert compute_effectiveness("nonexistent_role", [], "アグロ") == 50


def test_unknown_archetype_returns_neutral():
    assert compute_effectiveness("removal", [], "ナゾ") == 50


def test_unknown_tag_ignored():
    """未知のタグは無視 (= base のみ)。"""
    base = compute_effectiveness("draw", [], "コントロール")
    with_unknown = compute_effectiveness("draw", ["unknown_tag"], "コントロール")
    assert base == with_unknown


def test_cost_reduction_negative_vs_aggro():
    """cost_reduction modifier は アグロ 対戦で負値 (= 遅すぎる)。"""
    base = compute_effectiveness("ramp", [], "アグロ")
    with_cr = compute_effectiveness("ramp", ["cost_reduction"], "アグロ")
    assert with_cr < base


# ============================================================================ #
# best_cards_against
# ============================================================================ #

def test_best_cards_against_returns_sorted():
    """effectiveness 降順で並ぶ。"""
    results = best_cards_against("アグロ", target_role="blocker", top_k=10)
    assert len(results) > 0
    for i in range(len(results) - 1):
        assert results[i].effectiveness >= results[i + 1].effectiveness


def test_best_cards_against_target_role_filter():
    """target_role 指定で primary_role がそれに一致するカードのみ返る。"""
    results = best_cards_against("コントロール", target_role="finisher", top_k=20)
    assert all(r.primary_role == "finisher" for r in results)


def test_best_cards_against_cost_range():
    results = best_cards_against("ランプ", target_role="removal", cost_range=(3, 5), top_k=20)
    assert all(3 <= r.cost <= 5 for r in results)


def test_best_cards_against_color_filter():
    results = best_cards_against("アグロ", target_role="blocker", color_filter=["赤"], top_k=20)
    assert all("赤" in r.color for r in results)


def test_best_cards_against_top_k_limit():
    results = best_cards_against("ミッドレンジ", target_role="draw", top_k=5)
    assert len(results) <= 5


def test_best_cards_against_no_role_filter_returns_diverse():
    """target_role 未指定で十分大きい top_k なら複数 role のカードが返る。

    note: top_k 小さすぎると最高スコア役割 (= finisher 等) が枠を独占するので、
    1000 件で diverse 性を確認。
    """
    results = best_cards_against("コントロール", top_k=1000)
    roles = {r.primary_role for r in results}
    assert len(roles) >= 3  # finisher / negation / disruption / draw 等
