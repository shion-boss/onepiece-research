# -*- coding: utf-8 -*-
"""
matrix_schema Phase 7F-4 テスト (= 2026-05-14)
===============================================

per-cell timestamp + hash + ai_version の v2 schema 機能検証。
"""

from __future__ import annotations

from pathlib import Path

from engine.matrix_schema import (
    MATRIX_SCHEMA_VERSION,
    collect_deck_hashes,
    compute_recipe_hash,
    find_stale_cells,
    is_cell_stale,
    make_cell_v2,
    now_utc_iso,
)

ROOT = Path(__file__).resolve().parent.parent


# ─────────────────────────────────────────────────────
# compute_recipe_hash
# ─────────────────────────────────────────────────────


def test_hash_deterministic_for_same_recipe():
    """同じ recipe は同じ hash。"""
    recipe = {
        "leader": "OP15-058",
        "main": [
            {"card_id": "OP15-066", "count": 4},
            {"card_id": "OP15-076", "count": 4},
        ],
    }
    h1 = compute_recipe_hash(recipe)
    h2 = compute_recipe_hash(recipe)
    assert h1 == h2
    assert len(h1) == 16


def test_hash_invariant_to_main_order():
    """main の順序が違っても同じ hash (= canonical 化済)。"""
    r1 = {
        "leader": "OP15-058",
        "main": [
            {"card_id": "OP15-066", "count": 4},
            {"card_id": "OP15-076", "count": 4},
        ],
    }
    r2 = {
        "leader": "OP15-058",
        "main": [
            {"card_id": "OP15-076", "count": 4},
            {"card_id": "OP15-066", "count": 4},
        ],
    }
    assert compute_recipe_hash(r1) == compute_recipe_hash(r2)


def test_hash_changes_with_card_count():
    """count が変わると hash も変わる。"""
    r1 = {"leader": "OP15-058", "main": [{"card_id": "OP15-066", "count": 4}]}
    r2 = {"leader": "OP15-058", "main": [{"card_id": "OP15-066", "count": 3}]}
    assert compute_recipe_hash(r1) != compute_recipe_hash(r2)


def test_hash_changes_with_leader():
    """leader が変わると hash も変わる。"""
    r1 = {"leader": "OP15-058", "main": [{"card_id": "OP15-066", "count": 4}]}
    r2 = {"leader": "OP15-002", "main": [{"card_id": "OP15-066", "count": 4}]}
    assert compute_recipe_hash(r1) != compute_recipe_hash(r2)


def test_hash_ignores_metadata():
    """metadata (score / date / source) は hash に影響しない。"""
    r1 = {
        "leader": "OP15-058",
        "main": [{"card_id": "OP15-066", "count": 4}],
        "score": "優勝",
        "tournament_date": "2026-05-11",
        "source": "https://cardrush.media/...",
    }
    r2 = {
        "leader": "OP15-058",
        "main": [{"card_id": "OP15-066", "count": 4}],
        "score": "準優勝",  # 異なる
        "tournament_date": "2026-04-01",  # 異なる
    }
    assert compute_recipe_hash(r1) == compute_recipe_hash(r2)


# ─────────────────────────────────────────────────────
# make_cell_v2 / is_cell_stale
# ─────────────────────────────────────────────────────


def test_make_cell_v2_includes_all_fields():
    """v2 cell に必要 field が全部入る。"""
    cell = make_cell_v2(
        deck_b_slug="cardrush_1234",
        winrate=0.65, wins=13, losses=7, draws=0, avg_turns=8.5,
        deck_a_hash="abc123", deck_b_hash="def456",
        ai_version="PlanningAI_R71",
    )
    for key in [
        "deck_b", "winrate", "wins", "losses", "draws", "avg_turns",
        "deck_a_recipe_hash", "deck_b_recipe_hash",
        "ai_version", "computed_at", "stale",
    ]:
        assert key in cell, f"missing field: {key}"


def test_is_cell_stale_for_matching_hashes():
    """全 field 一致なら stale=False。"""
    cell = make_cell_v2(
        "x", 0.5, 10, 10, 0, 5.0,
        deck_a_hash="A", deck_b_hash="B", ai_version="v1",
    )
    assert not is_cell_stale(cell, "A", "B", "v1")


def test_is_cell_stale_when_hash_mismatch():
    """deck hash 不一致なら stale=True。"""
    cell = make_cell_v2(
        "x", 0.5, 10, 10, 0, 5.0,
        deck_a_hash="A", deck_b_hash="B", ai_version="v1",
    )
    assert is_cell_stale(cell, "A_NEW", "B", "v1")
    assert is_cell_stale(cell, "A", "B_NEW", "v1")


def test_is_cell_stale_when_ai_version_mismatch():
    """ai_version 不一致なら stale=True。"""
    cell = make_cell_v2(
        "x", 0.5, 10, 10, 0, 5.0,
        deck_a_hash="A", deck_b_hash="B", ai_version="v1",
    )
    assert is_cell_stale(cell, "A", "B", "v2")


def test_is_cell_stale_when_stale_flag_set():
    """stale flag が True なら stale=True (= 手動マーキング)。"""
    cell = make_cell_v2(
        "x", 0.5, 10, 10, 0, 5.0,
        deck_a_hash="A", deck_b_hash="B", ai_version="v1",
        stale=True,
    )
    assert is_cell_stale(cell, "A", "B", "v1")


def test_is_cell_stale_for_v1_schema():
    """v1 schema (= hash field なし) は stale 扱い (= 再計算)。"""
    v1_cell = {
        "deck_b": "x", "winrate": 0.5,
        "wins": 10, "losses": 10, "draws": 0, "avg_turns": 5.0,
    }
    assert is_cell_stale(v1_cell, "A", "B", "v1")


# ─────────────────────────────────────────────────────
# find_stale_cells / collect_deck_hashes
# ─────────────────────────────────────────────────────


def test_find_stale_cells_skips_self_pair():
    """self-pair (deck_a == deck_b) は stale 判定の対象外。"""
    matrix_doc = {
        "matrix": [
            {
                "deck_a": "A",
                "row": [
                    {"deck_b": "A", "winrate": None},  # self-pair
                    make_cell_v2("B", 0.5, 10, 10, 0, 5, deck_a_hash="HA", deck_b_hash="HB", ai_version="v1"),
                ],
            },
        ],
    }
    stale = find_stale_cells(matrix_doc, {"A": "HA", "B": "HB"}, "v1")
    assert stale == []


def test_find_stale_cells_detects_hash_change():
    """deck recipe hash 変更を検出。"""
    matrix_doc = {
        "matrix": [
            {
                "deck_a": "A",
                "row": [
                    make_cell_v2("B", 0.5, 10, 10, 0, 5, deck_a_hash="HA_OLD", deck_b_hash="HB", ai_version="v1"),
                ],
            },
        ],
    }
    stale = find_stale_cells(matrix_doc, {"A": "HA_NEW", "B": "HB"}, "v1")
    assert stale == [(0, 0)]


def test_collect_deck_hashes_for_real_decks():
    """実 deck files に対して hash を集める (= 全 hash が 16 文字 hex)。"""
    decks_dir = ROOT / "decks"
    hashes = collect_deck_hashes(decks_dir)
    assert len(hashes) > 0
    for slug, h in hashes.items():
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)
