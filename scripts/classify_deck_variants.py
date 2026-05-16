# -*- coding: utf-8 -*-
"""各リーダー × 最大 4 variant の代表レシピを抽出する (Step 0.1 / 0.2)。

入力ソース:
- decks/_archive/cardrush_raw/*.json (= 93 件、 過去 3 ヶ月の優勝レシピ)
- decks/tcgportal_*.json (= 7 件)
- decks/cardrush_*.json (= 9 件、 既存代表、 analysis.json 除外)

処理:
1. 全レシピを leader 別にグルーピング
2. 各 leader 内で jaccard 類似度行列を計算 (= 採用カード set の重複度)
3. agglomerative clustering で 最大 4 cluster (= サンプル数が 4 未満ならそのまま)
4. 各 cluster の medoid (= cluster 内で平均距離最小) を代表として採用

出力:
- decks/<leader_slug>/variant_<n>.json (= 0 .. n_variants-1)
- db/data_layer_64_status.json (= ステータス + 統計)

Usage:
  .venv/bin/python scripts/classify_deck_variants.py
  .venv/bin/python scripts/classify_deck_variants.py --max-variants 4
  .venv/bin/python scripts/classify_deck_variants.py --dry-run
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
from sklearn.cluster import AgglomerativeClustering

ROOT = Path(__file__).resolve().parent.parent
DECKS_DIR = ROOT / "decks"
ARCHIVE_DIR = DECKS_DIR / "_archive" / "cardrush_raw"
DB_DIR = ROOT / "db"

# leader card_id → human-readable slug
# 既存 tcgportal / cardrush の slug 命名を踏襲しつつ、 一意性を保つ
LEADER_SLUG_MAP: dict[str, str] = {
    "OP15-058": "enel_op15",
    "OP11-041": "nami_op11",
    "OP15-098": "luffy_op15",
    "OP14-020": "mihawk_op14",
    "OP15-002": "lucy_op15",
    "OP14-041": "hancock_op14",
    "OP13-079": "im_op13",
    "OP13-002": "ace_op13",
    "OP14-079": "crocodile_op14",
    "EB02-010": "luffy_eb02",
    "OP12-041": "sanji_op12",
}


def _make_slug(leader_id: str) -> str:
    """leader card_id を slug に変換。 未登録は card_id を lowercase + dash→underscore で。"""
    if leader_id in LEADER_SLUG_MAP:
        return LEADER_SLUG_MAP[leader_id]
    return leader_id.lower().replace("-", "_")


def _normalize_leader(d: dict) -> tuple[str, str]:
    """deck dict から (leader_id, leader_name) を取り出す。 構造差異を吸収。"""
    leader = d.get("leader")
    if isinstance(leader, dict):
        return leader.get("card_id", ""), leader.get("name", "")
    if isinstance(leader, str):
        return leader, d.get("leader_name", "")
    return "", ""


def load_all_recipes() -> list[dict]:
    """全ソースからレシピを読み込み統一形式で返す。"""
    out: list[dict] = []

    # cardrush_raw archive
    if ARCHIVE_DIR.exists():
        for p in sorted(ARCHIVE_DIR.glob("*.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"  WARN skip {p.name}: {e}")
                continue
            leader_id, leader_name = _normalize_leader(d)
            if not leader_id:
                continue
            out.append({
                "source": "cardrush_raw",
                "source_path": p.name,
                "leader": leader_id,
                "leader_name": leader_name,
                "main": d.get("main", []),
                "score": d.get("score", ""),
                "tournament_date": d.get("tournament_date", ""),
            })

    # 既存 decks/*.json (= analysis.json + _archive/ 除外)
    for p in sorted(DECKS_DIR.glob("*.json")):
        if ".analysis" in p.name:
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        leader_id, leader_name = _normalize_leader(d)
        if not leader_id:
            continue
        out.append({
            "source": "existing",
            "source_path": p.name,
            "leader": leader_id,
            "leader_name": leader_name,
            "main": d.get("main", []),
            "score": d.get("score", ""),
            "tournament_date": d.get("tournament_date", ""),
        })

    return out


def _card_set(recipe: dict) -> set[str]:
    """採用カード set を返す (= count は無視、 card_id だけ集合化)。"""
    cards: set[str] = set()
    for entry in recipe.get("main", []):
        cid = entry.get("card_id")
        if cid:
            cards.add(cid)
    return cards


def _jaccard_distance(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return 1.0 - (inter / union if union else 0.0)


def _pick_medoid(indices: list[int], card_sets: list[set[str]]) -> int:
    """cluster 内で他メンバーへの平均距離が最小の medoid index を返す。"""
    if len(indices) == 1:
        return indices[0]
    best_idx = indices[0]
    best_avg = float("inf")
    for i in indices:
        avg = np.mean([
            _jaccard_distance(card_sets[i], card_sets[j])
            for j in indices if j != i
        ])
        if avg < best_avg:
            best_avg = avg
            best_idx = i
    return best_idx


def cluster_leader_variants(
    group: list[dict],
    max_variants: int,
) -> list[tuple[int, list[int]]]:
    """leader 内のレシピを最大 max_variants cluster に分け、 各 cluster (= variant_id, member_indices) を返す。"""
    n = len(group)
    n_variants = min(max_variants, n)
    card_sets = [_card_set(r) for r in group]

    if n_variants == 1:
        labels = [0] * n
    else:
        # jaccard distance 行列
        dist_matrix = np.zeros((n, n))
        for i in range(n):
            for j in range(i + 1, n):
                d = _jaccard_distance(card_sets[i], card_sets[j])
                dist_matrix[i, j] = d
                dist_matrix[j, i] = d

        clustering = AgglomerativeClustering(
            n_clusters=n_variants,
            metric="precomputed",
            linkage="average",
        )
        labels = clustering.fit_predict(dist_matrix).tolist()

    clusters: list[tuple[int, list[int]]] = []
    for vid in range(n_variants):
        members = [i for i, lbl in enumerate(labels) if lbl == vid]
        if members:
            clusters.append((vid, members))
    return clusters


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-variants", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    recipes = load_all_recipes()
    print(f"Loaded {len(recipes)} recipes total")

    by_leader: dict[str, list[dict]] = defaultdict(list)
    for r in recipes:
        by_leader[r["leader"]].append(r)

    print(f"Unique leaders: {len(by_leader)}")
    print()
    print(f"{'leader_id':<12} {'leader_name':<24} {'n':>3} → {'v':>2}  slug")
    print("-" * 70)

    status: dict = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "max_variants": args.max_variants,
        "total_recipes": len(recipes),
        "leaders": {},
    }

    for leader_id, group in sorted(by_leader.items(), key=lambda x: (-len(x[1]), x[0])):
        n = len(group)
        slug = _make_slug(leader_id)
        leader_name = group[0]["leader_name"]
        card_sets = [_card_set(r) for r in group]

        clusters = cluster_leader_variants(group, args.max_variants)
        n_variants = len(clusters)
        print(f"{leader_id:<12} {leader_name:<24} {n:>3} → {n_variants:>2}  {slug}")

        variants_info: list[dict] = []
        for vid, members in clusters:
            medoid_idx = _pick_medoid(members, card_sets)
            rep = group[medoid_idx]

            variants_info.append({
                "variant_id": vid,
                "size": len(members),
                "medoid_source": rep["source_path"],
                "score": rep["score"],
                "tournament_date": rep["tournament_date"],
                "member_sources": [group[i]["source_path"] for i in members],
            })

            if not args.dry_run:
                leader_dir = DECKS_DIR / slug
                leader_dir.mkdir(parents=True, exist_ok=True)
                out_path = leader_dir / f"variant_{vid}.json"
                deck_data = {
                    "name": f"{leader_name} variant {vid}",
                    "slug": f"{slug}_variant_{vid}",
                    "leader": rep["leader"],
                    "leader_name": leader_name,
                    "source": rep["source"],
                    "source_path": rep["source_path"],
                    "variant_id": vid,
                    "cluster_size": len(members),
                    "score": rep["score"],
                    "tournament_date": rep["tournament_date"],
                    "main": rep["main"],
                }
                out_path.write_text(
                    json.dumps(deck_data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

        status["leaders"][leader_id] = {
            "slug": slug,
            "name": leader_name,
            "n_samples": n,
            "n_variants": n_variants,
            "variants": variants_info,
        }

    total_variants = sum(s["n_variants"] for s in status["leaders"].values())
    status["total_variants"] = total_variants
    print()
    print(f"Total variants generated: {total_variants}")

    if not args.dry_run:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        status_path = DB_DIR / "data_layer_64_status.json"
        status_path.write_text(
            json.dumps(status, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Status written: {status_path}")


if __name__ == "__main__":
    main()
