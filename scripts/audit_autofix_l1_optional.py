#!/usr/bin/env python3
"""Phase 1 L1 (optional 漏れ) auto-fix (= 2026-05-28 Layer 4 prototype)。

scripts/audit_overlay_static.py が 検出した L1 issue 43 件 を 機械的 に 修正。
全て 同 パターン (= replace_ko/replace_leave entry に optional: true 追加) なので
低リスク (= data-only、 既存挙動 は 「auto-fire → skip」 へ shift = ohtsuki さん 報告 と 整合)。

実行:
  .venv/bin/python scripts/audit_autofix_l1_optional.py --dry-run
  .venv/bin/python scripts/audit_autofix_l1_optional.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = REPO_ROOT / "db" / "static_audit_report.json"
OVERLAY_PATH = REPO_ROOT / "db" / "card_effects.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not REPORT_PATH.exists():
        print("ERROR: run scripts/audit_overlay_static.py first", file=sys.stderr)
        sys.exit(1)

    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    l1_issues = [i for i in report["issues"] if i["rule_id"] == "L1"]
    print(f"L1 issues to fix: {len(l1_issues)}")

    overlay = json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))
    fixed = 0
    skipped = 0
    for issue in l1_issues:
        cid = issue["card_id"]
        entry_idx = issue["evidence"].get("entry_index")
        entry_when = issue["evidence"].get("entry_when")
        entries = overlay.get(cid)
        if not isinstance(entries, list) or entry_idx is None:
            skipped += 1
            continue
        if entry_idx >= len(entries):
            skipped += 1
            continue
        target = entries[entry_idx]
        if not isinstance(target, dict):
            skipped += 1
            continue
        # 防御: when が 一致 する か 念のため
        if target.get("when") != entry_when:
            print(f"  WARN: {cid}[{entry_idx}] when mismatch "
                  f"(expected {entry_when}, got {target.get('when')})")
            skipped += 1
            continue
        if target.get("optional"):
            # 既に 修正済 (= 過去 fix と 重複)
            skipped += 1
            continue
        target["optional"] = True
        fixed += 1
        print(f"  fixed: {cid}[{entry_idx}] ({entry_when}) → optional: true")

    print()
    print(f"fixed  : {fixed}")
    print(f"skipped: {skipped}")
    if not args.dry_run and fixed > 0:
        OVERLAY_PATH.write_text(
            json.dumps(overlay, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nwrote {OVERLAY_PATH}")
    elif args.dry_run:
        print("\n[dry-run] no write")


if __name__ == "__main__":
    main()
