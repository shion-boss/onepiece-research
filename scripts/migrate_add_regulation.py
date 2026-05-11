# -*- coding: utf-8 -*-
"""既存デッキ JSON に regulation フィールドを追加するマイグレーション。

cardrush_*.json は全て大会上位入賞 (2026年4月以降のスタンダード施行後) なので
"standard" を設定する。user_*.json は "extra" を設定する (制限なし寄り)。
その他は "standard" をデフォルトとする。

実行:
    .venv/bin/python scripts/migrate_add_regulation.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECKS_DIR = ROOT / "decks"


def main() -> None:
    paths = sorted(
        p for p in DECKS_DIR.glob("*.json") if not p.name.endswith(".analysis.json")
    )
    updated = 0
    skipped = 0
    for path in paths:
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"  SKIP (read error): {path.name}: {e}")
            skipped += 1
            continue

        if "regulation" in d:
            print(f"  already has regulation={d['regulation']}: {path.name}")
            skipped += 1
            continue

        slug = d.get("slug") or path.stem
        if slug.startswith("user_"):
            regulation = "extra"
        else:
            regulation = "standard"

        d["regulation"] = regulation
        path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  updated ({regulation}): {path.name}")
        updated += 1

    print(f"\n完了: {updated} 件更新, {skipped} 件スキップ")


if __name__ == "__main__":
    main()
