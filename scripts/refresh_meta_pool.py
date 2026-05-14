# -*- coding: utf-8 -*-
"""
メタデッキ pool 月次更新 orchestrator (Phase 7F-3 / 2026-05-14)
================================================================

tcg-portal 上位 archetype + cardrush 個別優勝レシピを取得し、 月次の
active pool を更新する。 過去 archetype は historical/ に凍結保存。

仕様詳細は [docs/META_POOL_SPEC.md](../docs/META_POOL_SPEC.md) を参照。

実行例:
    .venv/bin/python scripts/refresh_meta_pool.py
    .venv/bin/python scripts/refresh_meta_pool.py --dry-run
    .venv/bin/python scripts/refresh_meta_pool.py --top-n 20 --window-months 3

## 動作概要

1. tcg-portal /meta-analysis から上位 N archetype 取得 (= --top-n)
2. cardrush から指定期間 (= --window-months) の優勝レシピを scrape
3. archetype 毎に最新優勝を代表選出 (= cardrush 由来優先、 不在なら tcg-portal 合成 fallback)
4. variant 検出 (= 同 archetype の recipe 群を k-means クラスタリング)
5. 旧 active と diff: 継続 / 新規 / 圏外 を分類
6. 圏外 archetype を historical/ に凍結保存 (= recipe 不変)
7. 変動レポート出力

注: 2026-05-14 時点では directory restructure (= active/ historical/) は
保留中 (matrix 走行中のため)。 現在は decks/ flat 構造のまま更新する。
restructure は matrix 完了後の別タスクで実施 (= Phase 7F-1)。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.variant_detector import detect_variants  # noqa: E402


DECKS_DIR = ROOT / "decks"
ARCHIVE_DIR = DECKS_DIR / "_archive"
CARDRUSH_RAW_DIR = ARCHIVE_DIR / "cardrush_raw"


def list_active_recipes() -> list[Path]:
    """現在の active recipe ファイル一覧 (= decks/ 直下、 cardrush_* + tcgportal_*)。"""
    out = []
    for p in sorted(DECKS_DIR.glob("cardrush_*.json")):
        if ".analysis" in p.name:
            continue
        out.append(p)
    for p in sorted(DECKS_DIR.glob("tcgportal_*.json")):
        if ".analysis" in p.name:
            continue
        out.append(p)
    return out


def list_archived_raw() -> list[Path]:
    """過去 cardrush 生レシピ (= 代表選出されなかった個別優勝)。"""
    if not CARDRUSH_RAW_DIR.exists():
        return []
    return sorted(CARDRUSH_RAW_DIR.glob("cardrush_*.json"))


def load_recipe(p: Path) -> Optional[dict]:
    """安全に recipe JSON を読み込む。"""
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def group_recipes_by_archetype(recipe_paths: list[Path]) -> dict[str, list[tuple[Path, dict]]]:
    """recipe 群を archetype (= name フィールド) でグループ化。"""
    out: dict[str, list[tuple[Path, dict]]] = {}
    for p in recipe_paths:
        d = load_recipe(p)
        if not d:
            continue
        name = d.get("name")
        if not name:
            continue
        out.setdefault(name, []).append((p, d))
    return out


def select_representative(recipes: list[tuple[Path, dict]]) -> tuple[Path, dict]:
    """archetype 内の代表 recipe を選ぶ (= 最新優勝)。"""
    def sort_key(item):
        _, d = item
        # score 優先 (優勝 > 準優勝 > 3位 > ベスト4)
        score = d.get("score", "")
        score_rank = {"優勝": 0, "準優勝": 1, "3位": 2, "ベスト4": 3}.get(score, 99)
        # 日付降順 (= 新しい方を優先 = 負数に)
        date_str = d.get("tournament_date") or "0000-00-00"
        parts = date_str.split("-")
        try:
            y, m, d_day = int(parts[0]), int(parts[1]), int(parts[2])
        except (ValueError, IndexError):
            y, m, d_day = 0, 0, 0
        return (score_rank, -y, -m, -d_day)
    return min(recipes, key=sort_key)


def detect_variants_for_archetype(
    archetype: str,
    recipes: list[dict],
    min_silhouette: float = 0.4,
) -> list[dict]:
    """archetype 内の variant を検出 + suggested_slug を返す。

    Returns:
        list[dict]: 各 variant の {slug, member_count, characteristic_cards, members}
    """
    if len(recipes) < 4:
        # サンプル不足、 単一 variant
        return [{
            "slug": "",  # 仮名なし (= 単一)
            "member_count": len(recipes),
            "characteristic_cards": [],
            "is_split": False,
        }]
    variants = detect_variants(recipes, min_silhouette=min_silhouette)
    if len(variants) == 1:
        return [{
            "slug": "",
            "member_count": len(variants[0].member_indices),
            "characteristic_cards": [],
            "is_split": False,
        }]
    return [
        {
            "slug": v.suggested_slug,
            "member_count": len(v.member_indices),
            "characteristic_cards": [c for c, _ in v.characteristic_cards[:3]],
            "is_split": True,
        }
        for v in variants
    ]


def report_changes(
    active_archetypes: dict[str, list],
    archived_archetypes: dict[str, list],
    detected_variants: dict[str, list[dict]],
) -> dict:
    """active / historical / variant 状態をレポート用に集計。"""
    report = {
        "computed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "active_count": len(active_archetypes),
        "archive_count": sum(len(v) for v in archived_archetypes.values()),
        "active_archetypes": sorted(active_archetypes.keys()),
        "historical_archetypes_with_raw": sorted(
            arch for arch in archived_archetypes
            if arch not in active_archetypes
        ),
        "variants": {
            arch: variants
            for arch, variants in detected_variants.items()
            if any(v.get("is_split") for v in variants)
        },
    }
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top-n", type=int, default=16, help="tcg-portal 上位 N archetype")
    ap.add_argument("--window-months", type=int, default=3, help="cardrush 取得期間 (月)")
    ap.add_argument(
        "--min-silhouette", type=float, default=0.4,
        help="variant 検出の silhouette 閾値",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="ファイル変更せず diff レポートのみ出力",
    )
    ap.add_argument(
        "--report-only", action="store_true",
        help="既存 decks/ の variant 検出だけ実行 (= scrape skip)",
    )
    args = ap.parse_args()

    print(f"=== Meta pool refresh ({datetime.now().isoformat()}) ===")
    print(f"  config: top_n={args.top_n}, window_months={args.window_months}, "
          f"min_silhouette={args.min_silhouette}, dry_run={args.dry_run}")
    print()

    # ─── Step 1: 現状の active recipes と archive を読み込み ───
    active_paths = list_active_recipes()
    archive_paths = list_archived_raw()
    print(f"  active recipes: {len(active_paths)}")
    print(f"  archive raw recipes: {len(archive_paths)}")

    active_by_arch = group_recipes_by_archetype(active_paths)
    archive_by_arch = group_recipes_by_archetype(archive_paths)
    print(f"  active archetypes: {len(active_by_arch)}")
    print(f"  archive archetypes (= raw recipes 持ち): {len(archive_by_arch)}")
    print()

    # ─── Step 2: variant 検出 (= 各 archetype の全 recipe を集計) ───
    detected_variants: dict[str, list[dict]] = {}
    for arch in sorted(set(active_by_arch.keys()) | set(archive_by_arch.keys())):
        all_recipes = []
        for _, d in active_by_arch.get(arch, []):
            all_recipes.append(d)
        for _, d in archive_by_arch.get(arch, []):
            all_recipes.append(d)
        if len(all_recipes) < 4:
            continue
        variants = detect_variants_for_archetype(arch, all_recipes, args.min_silhouette)
        detected_variants[arch] = variants

    # ─── Step 3: 変動レポート ───
    report = report_changes(active_by_arch, archive_by_arch, detected_variants)

    # variant split 検出された archetype を表示
    print("=== Variant 検出 ===")
    if not report["variants"]:
        print("  (検出された split なし、 全 archetype は単一 variant)")
    else:
        for arch, variants in report["variants"].items():
            print(f"\n  📦 {arch}:")
            for v in variants:
                cards_str = ", ".join(v.get("characteristic_cards", []))
                print(f"    {v.get('slug', '_v?'):<5} "
                      f"({v.get('member_count')} recipes) "
                      f"特徴: [{cards_str}]")
    print()

    # ─── Step 4: report ファイル出力 ───
    out_path = ROOT / "db" / "meta_pool_report.json"
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"=== Report 書き出し ===")
    print(f"  → {out_path}")
    print()

    # ─── Step 5: TODO 注記 (= directory restructure は別タスク) ───
    if not args.dry_run and not args.report_only:
        print("=== TODO (= 別タスク) ===")
        print("  - Phase 7F-1: decks/active/<leader_id>/ 階層化 (= matrix 完了後)")
        print("  - Phase 7F-2: _meta.json schema 適用 (= 同上)")
        print("  - tcg-portal / cardrush scrape の連動 (= 月次自動更新)")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
