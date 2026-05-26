#!/usr/bin/env python3
"""GoalDirectedAI bonus 学習用 meta pool snapshot (= 2026-05-26)。

`db/meta_pool.json` の current を 現状 deck 一覧 で 更新、 旧 current を history に push。
GoalDirectedAI bonus 学習 が 「現環境 のみ」 対象 とするため の 識別 source。

# 既存 scripts/refresh_meta_pool.py との 違い

- refresh_meta_pool.py: variant 検出 + active/archive 管理 (= 月次 meta 更新 orchestrator)
- snapshot_meta_pool.py (= 本 script): bonus 学習対象 slug snapshot 管理 のみ (= 軽量)

# 使い方

```bash
# decks/*.json から 自動検出 (= cardrush_* / tcgportal_* prefix)
.venv/bin/python scripts/snapshot_meta_pool.py

# dry-run: 差分 表示 のみ
.venv/bin/python scripts/snapshot_meta_pool.py --dry-run

# 明示的に slugs 指定
.venv/bin/python scripts/snapshot_meta_pool.py --slugs cardrush_1342 cardrush_1456
```

# 設計

- decks/<slug>.json の `slug` field が cardrush_/tcgportal_ で 始まる もの を 自動 meta pool として 採用
  (= ユーザー独自 deck は decks/<slug>.json を作っても prefix が 違うので 除外)
- current.slugs が 変わった 場合 のみ history に 旧 current を push、 iteration を 1 増加
- 変化なし なら 何もしない (= idempotent)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DECKS_DIR = REPO_ROOT / "decks"
META_POOL_PATH = REPO_ROOT / "db" / "meta_pool.json"

META_PREFIXES = ("cardrush_", "tcgportal_")


def discover_meta_pool_slugs() -> list[str]:
    """decks/*.json から meta pool slug 一覧 を 抽出 (= prefix で 判別)。"""
    slugs: set[str] = set()
    for p in sorted(DECKS_DIR.glob("*.json")):
        if "_archive" in str(p) or ".target_" in p.name or ".analysis" in p.name:
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        slug = d.get("slug")
        if not slug:
            continue
        if any(slug.startswith(pre) for pre in META_PREFIXES):
            slugs.add(slug)
    return sorted(slugs)


def load_meta_pool() -> dict:
    if not META_POOL_PATH.exists():
        return {
            "description": (
                "GoalDirectedAI bonus 学習対象 deck snapshot。 "
                "current = 現環境、 history = 過去環境 (= 凍結 entries の 由来)。"
            ),
            "current": {"snapshot_date": str(date.today()), "iteration": 0, "slugs": []},
            "history": [],
        }
    return json.loads(META_POOL_PATH.read_text(encoding="utf-8"))


def save_meta_pool(pool: dict) -> None:
    META_POOL_PATH.write_text(
        json.dumps(pool, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--slugs", nargs="+", default=None,
        help="明示的に meta pool slugs 指定 (= 自動検出 を override)",
    )
    ap.add_argument("--dry-run", action="store_true", help="変更 適用 せず 差分 のみ")
    args = ap.parse_args()

    new_slugs = sorted(args.slugs) if args.slugs else discover_meta_pool_slugs()
    if not new_slugs:
        print("ERROR: meta pool slug が 検出 できません", file=sys.stderr)
        sys.exit(1)

    pool = load_meta_pool()
    old_slugs = sorted(pool["current"].get("slugs", []))

    added = sorted(set(new_slugs) - set(old_slugs))
    removed = sorted(set(old_slugs) - set(new_slugs))

    print(f"current iteration: {pool['current'].get('iteration', 0)}")
    print(f"  old slugs ({len(old_slugs)}):")
    for s in old_slugs:
        print(f"    - {s}")
    print(f"  new slugs ({len(new_slugs)}):")
    for s in new_slugs:
        print(f"    - {s}")
    print(f"  added: {added}")
    print(f"  removed: {removed}")

    if not added and not removed:
        print("変化 なし、 更新 skip")
        return

    if args.dry_run:
        print("[dry-run] 上記 差分 で 更新 予定 (= history に 旧 current push、 iteration +1)")
        return

    # history に 旧 current を push
    old_current = dict(pool["current"])
    pool["history"].append(old_current)
    pool["current"] = {
        "snapshot_date": str(date.today()),
        "iteration": old_current.get("iteration", 0) + 1,
        "slugs": new_slugs,
    }
    save_meta_pool(pool)
    print(f"OK: iteration={pool['current']['iteration']}, history_len={len(pool['history'])}")


if __name__ == "__main__":
    main()
