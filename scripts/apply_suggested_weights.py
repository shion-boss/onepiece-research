#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 2 / Step 2D 補助: 学習結果 (= ai_params.suggested.json) を ai_params.json に
マージする半 automatic スクリプト。

現 ai_params.json を ai_params.<timestamp>.bak.json に退避してから、 suggested の
params を上書きマージ。 既存キー (= w_life 等の base 15 個) も学習で更新。

`--dry-run` で変更内容のみ表示、 適用しない。

Usage:
  .venv/bin/python scripts/apply_suggested_weights.py --dry-run
  .venv/bin/python scripts/apply_suggested_weights.py
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--current",
        type=Path,
        default=ROOT / "db" / "ai_params.json",
    )
    ap.add_argument(
        "--suggested",
        type=Path,
        default=ROOT / "db" / "ai_params.suggested.json",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.suggested.exists():
        print(f"ERROR: {args.suggested} not found")
        sys.exit(1)
    if not args.current.exists():
        print(f"ERROR: {args.current} not found")
        sys.exit(1)

    suggested = json.loads(args.suggested.read_text(encoding="utf-8"))
    current = json.loads(args.current.read_text(encoding="utf-8"))

    new_params = dict(current.get("params", {}))
    s_params = suggested.get("params", {})

    print("=== weight diff (current → suggested) ===")
    n_changed = 0
    for key, new_val in sorted(s_params.items()):
        old_val = new_params.get(key, 0)
        if old_val != new_val:
            print(f"  {key}: {old_val} → {new_val}  (Δ {new_val - old_val:+d})")
            n_changed += 1
        new_params[key] = new_val
    print(f"\n変更: {n_changed} keys")

    # training stats も保存
    stats = suggested.get("training_stats", {})
    note = suggested.get("note", "")

    if args.dry_run:
        print("\n--dry-run: 適用しない")
        return

    # backup
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = args.current.with_suffix(f".{ts}.bak.json")
    shutil.copy2(args.current, backup)
    print(f"\nbackup: {backup}")

    # write new
    new_doc = dict(current)
    new_doc["params"] = new_params
    new_doc["saved_at"] = datetime.now(timezone.utc).isoformat()
    new_doc["note"] = f"Phase 2 outcome regression apply: {note}"
    history = new_doc.get("_history", [])
    history.append({
        "ts": ts,
        "source": "outcome_regression",
        "n_changed": n_changed,
        "training_stats": stats,
    })
    new_doc["_history"] = history

    args.current.write_text(
        json.dumps(new_doc, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"applied: {args.current}")
    print("注意: engine.eval.reload_default_weights() を呼ぶか、 サーバ再起動で反映")


if __name__ == "__main__":
    main()
