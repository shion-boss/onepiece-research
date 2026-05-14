# -*- coding: utf-8 -*-
"""
Variant 検出 (Phase 7F / 2026-05-14)
====================================

同 leader (= 同 archetype) の複数 recipe をクラスタリングして、 構築バリエーション
(= variant) を自動検出する。

例: 紫エネル の cardrush 優勝 30 件を k-means で分割 → 「アグロ型」 「コントロール寄り」
等の variant を識別。

## 検出アルゴリズム

1. 各 recipe を **カード ID × 採用枚数** のベクトル化 (= sparse)
2. ベクトル間距離 = L1 距離 (= マンハッタン距離、 「異なるカード枚数の総和」)
3. k-means (k=1, 2, 3) で クラスタリング
4. silhouette score で最適 k を選択 (≥ 0.4 で複数 variant 判定)
5. 各 variant の「特徴的カード」 (= 採用率差最大のカード) を抽出

## 公開 API

- `detect_variants(recipes: list[dict], min_silhouette: float) -> list[Variant]`
- `Variant` dataclass: cluster_id / member_recipes / characteristic_cards / centroid
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Variant:
    """検出された 1 variant (= 構築バリエーション)。"""

    cluster_id: int
    member_indices: list[int]  # 入力 recipes リスト内 index
    centroid: dict[str, float] = field(default_factory=dict)  # card_id → 平均枚数
    characteristic_cards: list[tuple[str, float]] = field(default_factory=list)
    # 「特徴カード」 = この variant が他より高頻度で採用してるカード上位
    suggested_slug: str = ""  # _v1 / _v2 等の仮名 (= 命名済なら維持)


def _recipe_to_vector(recipe: dict) -> dict[str, int]:
    """recipe (= deck JSON dict) を {card_id: count} 形式に変換。

    main フィールドの 50 枚分のみ対象。 leader / counter は含まない。
    """
    out: dict[str, int] = {}
    for entry in recipe.get("main", []):
        cid = entry.get("card_id")
        count = entry.get("count", 0)
        if cid and count > 0:
            out[cid] = count
    return out


def _l1_distance(v1: dict[str, int], v2: dict[str, int]) -> float:
    """L1 (manhattan) 距離。 異なるカード枚数の総和。"""
    keys = set(v1.keys()) | set(v2.keys())
    return sum(abs(v1.get(k, 0) - v2.get(k, 0)) for k in keys)


def _compute_centroid(vectors: list[dict[str, int]]) -> dict[str, float]:
    """ベクトル群の重心 (= 各カードの平均枚数)。"""
    if not vectors:
        return {}
    sums: dict[str, float] = {}
    n = len(vectors)
    for v in vectors:
        for cid, cnt in v.items():
            sums[cid] = sums.get(cid, 0.0) + cnt
    return {cid: total / n for cid, total in sums.items()}


def _centroid_distance(vec: dict[str, int], centroid: dict[str, float]) -> float:
    """ベクトルと重心の距離 (= L1)。"""
    keys = set(vec.keys()) | set(centroid.keys())
    return sum(abs(vec.get(k, 0) - centroid.get(k, 0.0)) for k in keys)


def _kmeans(
    vectors: list[dict[str, int]],
    k: int,
    rng: random.Random,
    max_iter: int = 30,
) -> tuple[list[int], list[dict[str, float]]]:
    """k-means クラスタリング (= dict-based L1)。

    Returns:
        (assignments, centroids):
          assignments[i] = vectors[i] の所属クラスタ index
          centroids[c] = クラスタ c の重心
    """
    n = len(vectors)
    if n <= k:
        # 自明: 各 vector が独立クラスタ
        assignments = list(range(n))
        centroids = [{cid: float(v) for cid, v in vec.items()} for vec in vectors]
        return assignments, centroids

    # 初期 centroid を vectors からランダム sample
    init_indices = rng.sample(range(n), k)
    centroids = [
        {cid: float(v) for cid, v in vectors[idx].items()}
        for idx in init_indices
    ]

    assignments = [0] * n
    for _ in range(max_iter):
        changed = False
        # assignment step
        for i, vec in enumerate(vectors):
            best_c = 0
            best_d = _centroid_distance(vec, centroids[0])
            for c in range(1, k):
                d = _centroid_distance(vec, centroids[c])
                if d < best_d:
                    best_d = d
                    best_c = c
            if assignments[i] != best_c:
                assignments[i] = best_c
                changed = True
        if not changed:
            break
        # update step: 各クラスタの centroid を再計算
        new_centroids: list[dict[str, float]] = []
        for c in range(k):
            members = [vectors[i] for i in range(n) if assignments[i] == c]
            if members:
                new_centroids.append(_compute_centroid(members))
            else:
                # 空クラスタ: 既存 centroid 維持
                new_centroids.append(centroids[c])
        centroids = new_centroids
    return assignments, centroids


def _silhouette_score(
    vectors: list[dict[str, int]],
    assignments: list[int],
    k: int,
) -> float:
    """silhouette score (= クラスタ品質指標、 -1.0 〜 1.0)。

    1.0 に近いほどクラスタが分離良好。 ≥ 0.4 で「意味のある分割」 と判定。
    k=1 では 0.0 を返す (= 単一クラスタ)。
    """
    if k <= 1 or len(vectors) < 2:
        return 0.0
    n = len(vectors)
    scores = []
    for i in range(n):
        own_cluster = assignments[i]
        own_members = [j for j in range(n) if assignments[j] == own_cluster and j != i]
        # a(i) = 同クラスタ内 平均距離
        if not own_members:
            scores.append(0.0)
            continue
        a_i = sum(_l1_distance(vectors[i], vectors[j]) for j in own_members) / len(own_members)
        # b(i) = 他クラスタへの最小平均距離
        b_i = float("inf")
        for c in range(k):
            if c == own_cluster:
                continue
            other_members = [j for j in range(n) if assignments[j] == c]
            if not other_members:
                continue
            avg = sum(_l1_distance(vectors[i], vectors[j]) for j in other_members) / len(other_members)
            if avg < b_i:
                b_i = avg
        if b_i == float("inf"):
            scores.append(0.0)
            continue
        denom = max(a_i, b_i)
        if denom == 0:
            scores.append(0.0)
        else:
            scores.append((b_i - a_i) / denom)
    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def _characteristic_cards(
    own_centroid: dict[str, float],
    other_centroids: list[dict[str, float]],
    top_n: int = 5,
) -> list[tuple[str, float]]:
    """この variant が他より高頻度で採用してるカード上位 N 件。

    各カードについて (own_centroid - 他 centroid の平均) の差を計算、 差が大きい順に返す。
    """
    if not other_centroids:
        return sorted(own_centroid.items(), key=lambda x: -x[1])[:top_n]
    all_cards = set(own_centroid.keys())
    for c in other_centroids:
        all_cards.update(c.keys())

    diffs: list[tuple[str, float]] = []
    for cid in all_cards:
        own_v = own_centroid.get(cid, 0.0)
        other_avg = sum(c.get(cid, 0.0) for c in other_centroids) / len(other_centroids)
        diff = own_v - other_avg
        if diff > 0.5:  # 0.5 枚以上の差で「特徴」 判定
            diffs.append((cid, diff))
    diffs.sort(key=lambda x: -x[1])
    return diffs[:top_n]


def detect_variants(
    recipes: list[dict],
    min_silhouette: float = 0.4,
    max_k: int = 3,
    seed: int = 42,
) -> list[Variant]:
    """同 archetype の recipe 群を variant 別にクラスタリング。

    Args:
        recipes: 同 archetype の deck JSON dict のリスト
        min_silhouette: 最適 k 選択の閾値 (= 0.4 で複数 variant 判定)
        max_k: 検討する最大クラスタ数 (= 3 で アグロ/ミッド/コントロール 3 分割相当)
        seed: k-means 初期化乱数

    Returns:
        list[Variant]: 検出された variant 群。
          単一 variant の場合は 1 件のリスト (= 全 recipe が 1 cluster)。
    """
    n = len(recipes)
    if n < 4:
        # サンプル不足 → 単一 variant
        vec_all = [_recipe_to_vector(r) for r in recipes]
        return [
            Variant(
                cluster_id=0,
                member_indices=list(range(n)),
                centroid=_compute_centroid(vec_all) if vec_all else {},
                characteristic_cards=[],
                suggested_slug="",
            )
        ]

    vectors = [_recipe_to_vector(r) for r in recipes]
    rng = random.Random(seed)

    # k=1 baseline + k=2, 3 で best silhouette を選ぶ
    best_k = 1
    best_assignments = [0] * n
    best_centroids = [_compute_centroid(vectors)]
    best_score = 0.0

    for k in range(2, max_k + 1):
        # 各 k で 複数回試行 (= local optima 回避)
        best_inner_score = -1.0
        best_inner_assign = None
        best_inner_cent = None
        for trial in range(3):
            trial_rng = random.Random(seed + trial)
            assigns, cents = _kmeans(vectors, k, trial_rng)
            score = _silhouette_score(vectors, assigns, k)
            if score > best_inner_score:
                best_inner_score = score
                best_inner_assign = assigns
                best_inner_cent = cents
        if best_inner_score > best_score and best_inner_score >= min_silhouette:
            best_k = k
            best_score = best_inner_score
            best_assignments = best_inner_assign
            best_centroids = best_inner_cent

    # Variant 構築
    variants: list[Variant] = []
    for c in range(best_k):
        member_indices = [i for i in range(n) if best_assignments[i] == c]
        if not member_indices:
            continue
        other_centroids = [best_centroids[oc] for oc in range(best_k) if oc != c]
        char_cards = _characteristic_cards(best_centroids[c], other_centroids)
        suggested_slug = f"_v{c + 1}" if best_k > 1 else ""
        variants.append(
            Variant(
                cluster_id=c,
                member_indices=member_indices,
                centroid=best_centroids[c],
                characteristic_cards=char_cards,
                suggested_slug=suggested_slug,
            )
        )
    return variants
