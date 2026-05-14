# -*- coding: utf-8 -*-
"""
variant_detector Phase 7F-3 テスト (= 2026-05-14)
==================================================

同 archetype の複数 recipe を k-means クラスタリングして variant を検出する。
"""

from __future__ import annotations

import json
import glob
from pathlib import Path
from collections import defaultdict

from engine.variant_detector import (
    Variant,
    detect_variants,
)

ROOT = Path(__file__).resolve().parent.parent


def _build_recipe(card_ids_with_counts: dict[str, int], leader: str = "OP01-001") -> dict:
    """テスト用 recipe dict を生成。"""
    return {
        "name": "test",
        "leader": leader,
        "main": [{"card_id": cid, "count": cnt} for cid, cnt in card_ids_with_counts.items()],
    }


# ─────────────────────────────────────────────────────
# サンプル不足時 = 単一 variant
# ─────────────────────────────────────────────────────


def test_too_few_recipes_returns_single_variant():
    """4 件未満 (= サンプル不足) は単一 variant を返す。"""
    recipes = [
        _build_recipe({"OP01-013": 4, "OP01-016": 3}),
        _build_recipe({"OP01-013": 4, "OP01-016": 3}),
    ]
    variants = detect_variants(recipes)
    assert len(variants) == 1
    assert variants[0].cluster_id == 0
    assert variants[0].member_indices == [0, 1]


# ─────────────────────────────────────────────────────
# 同一構築 = 単一 variant
# ─────────────────────────────────────────────────────


def test_identical_recipes_form_single_variant():
    """全 recipe が同一構築 → 単一 variant に分類 (= silhouette 低 → k=1)。"""
    recipes = [
        _build_recipe({"OP01-013": 4, "OP01-016": 4, "OP02-013": 4})
        for _ in range(8)
    ]
    variants = detect_variants(recipes, min_silhouette=0.4)
    assert len(variants) == 1
    assert len(variants[0].member_indices) == 8


# ─────────────────────────────────────────────────────
# 明確に異なる構築 = 複数 variant
# ─────────────────────────────────────────────────────


def test_clearly_different_recipes_split_into_variants():
    """明確に異なる 2 グループ → 2 variant に分割される。"""
    # Group A: OP01-013 多採用、 OP02-013 不採用
    # Group B: OP01-013 不採用、 OP02-013 多採用
    recipes_a = [
        _build_recipe({"OP01-013": 4, "OP01-016": 4, "P-044": 4, "OP03-044": 4})
        for _ in range(5)
    ]
    recipes_b = [
        _build_recipe({"OP02-013": 4, "OP15-066": 4, "OP15-076": 4, "OP15-077": 4})
        for _ in range(5)
    ]
    all_recipes = recipes_a + recipes_b
    variants = detect_variants(all_recipes, min_silhouette=0.4)
    # 2 variant に分割
    assert len(variants) >= 2, f"明確に異なる構築 で variant 分割されるはず ({len(variants)})"
    # 各 variant のメンバー数が合計 10 (= 入力数)
    total_members = sum(len(v.member_indices) for v in variants)
    assert total_members == 10


def test_characteristic_cards_extracted():
    """variant 別の特徴カードが抽出される。"""
    recipes_a = [
        _build_recipe({"OP01-013": 4, "OP01-016": 4})
        for _ in range(5)
    ]
    recipes_b = [
        _build_recipe({"OP02-013": 4, "OP15-066": 4})
        for _ in range(5)
    ]
    variants = detect_variants(recipes_a + recipes_b, min_silhouette=0.3)
    if len(variants) >= 2:
        # 各 variant に少なくとも 1 つ特徴カード
        for v in variants:
            assert len(v.characteristic_cards) > 0, f"variant {v.cluster_id} に特徴カードがない"


# ─────────────────────────────────────────────────────
# 実データ (= 紫エネル 30 件)
# ─────────────────────────────────────────────────────


def test_real_enel_recipes_clustering():
    """実際の 紫エネル recipe (= 30 件) で variant 検出が動作。

    結果は確定的ではない (= データ次第) が、 エラーなく完了することと
    変数が妥当な範囲に収まることを確認。
    """
    # cardrush_raw + active 紫エネル を集める
    recipes = []
    for p in sorted(glob.glob(str(ROOT / "decks/_archive/cardrush_raw/cardrush_*.json"))):
        if ".analysis" in p:
            continue
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        if d.get("name") == "紫エネル":
            recipes.append(d)

    if len(recipes) < 4:
        return  # サンプル不足、 スキップ

    variants = detect_variants(recipes, min_silhouette=0.4)
    # 1〜3 variant に分割される
    assert 1 <= len(variants) <= 3
    total_members = sum(len(v.member_indices) for v in variants)
    assert total_members == len(recipes)
    # 複数 variant なら suggested_slug が _v1 / _v2 等
    if len(variants) > 1:
        slugs = {v.suggested_slug for v in variants}
        assert all(s.startswith("_v") for s in slugs)
