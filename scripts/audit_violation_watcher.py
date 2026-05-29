#!/usr/bin/env python3
"""runtime violation watcher (= 2026-05-29、 task #49 関連)。

db/auto_issues/ を polling で 監視 → 新規 violation の pattern 集計 + 報告。
collect_corpus_multi_opponent.py から 並行 起動 して 進捗 中 visibility を 上げる。

## 使い方

```bash
# 単発 集計 (= 現状 スナップ ショット)
.venv/bin/python scripts/audit_violation_watcher.py --once

# 定期 監視 (= 5 min おき に 出力、 ctrl+c で 停止)
.venv/bin/python scripts/audit_violation_watcher.py --interval 300

# since 指定 (= round_1_quick 開始 後 のみ)
.venv/bin/python scripts/audit_violation_watcher.py --since 20260529T081800Z
```
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ISSUES_DIR = REPO_ROOT / "db" / "auto_issues"


def _ts_from_filename(p: Path) -> str:
    """runtime_TIMESTAMP_REFEREE__... → TIMESTAMP."""
    m = re.match(r"runtime_(\d{8}T\d{6}Z)_", p.name)
    return m.group(1) if m else ""


def _normalize_message(msg: str) -> str:
    """違反 message から 個別 iid / index を 除去 して pattern key 化。"""
    s = msg
    s = re.sub(r"iid=\d+", "iid=*", s)
    s = re.sub(r"hand_idx=\d+", "hand_idx=*", s)
    s = re.sub(r"attacker_iid=\d+", "attacker_iid=*", s)
    s = re.sub(r"target_iid=\d+", "target_iid=*", s)
    s = re.sub(r"合法手 \d+ 件", "合法手 N 件", s)
    return s


def scan_issues(since_ts: str = "", until_ts: str = "") -> tuple[dict, list[dict]]:
    """db/auto_issues/runtime_*.json を scan して 集計。

    Returns: (meta, issues_list)
    """
    patterns: Counter = Counter()
    rule_counts: Counter = Counter()
    deck_pairs: Counter = Counter()
    by_severity: Counter = Counter()
    all_issues = []

    for p in sorted(ISSUES_DIR.glob("runtime_*.json")):
        ts = _ts_from_filename(p)
        if since_ts and ts < since_ts:
            continue
        if until_ts and ts > until_ts:
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        all_issues.append(d)
        msg = d.get("message", "")
        rule_counts[d.get("rule_id", "?")] += 1
        patterns[_normalize_message(msg)] += 1
        by_severity[d.get("severity", "?")] += 1
        ctx = d.get("game_context") or {}
        pair = (ctx.get("deck_a", "?"), ctx.get("deck_b", "?"))
        deck_pairs[pair] += 1

    meta = {
        "n_issues": len(all_issues),
        "n_unique_patterns": len(patterns),
        "n_unique_rules": len(rule_counts),
        "top_patterns": patterns.most_common(5),
        "by_rule": dict(rule_counts.most_common(5)),
        "by_severity": dict(by_severity.most_common()),
        "top_deck_pairs": deck_pairs.most_common(5),
    }
    return meta, all_issues


def print_report(meta: dict, label: str = "") -> None:
    print(f"=== violation report{' ' + label if label else ''} ===", flush=True)
    print(f"  total: {meta['n_issues']:,} issues, {meta['n_unique_patterns']:,} unique patterns",
          flush=True)
    print(f"  severity: {meta['by_severity']}", flush=True)
    print(f"  by rule: {meta['by_rule']}", flush=True)
    print(f"  top patterns:", flush=True)
    for pat, n in meta["top_patterns"]:
        print(f"    [{n:>4}] {pat[:100]}", flush=True)
    if meta["top_deck_pairs"]:
        print(f"  hot deck pairs:", flush=True)
        for (a, b), n in meta["top_deck_pairs"]:
            print(f"    [{n:>3}] {a} vs {b}", flush=True)
    print(flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true",
                    help="1 回 だけ 集計 → 出力 → 終了")
    ap.add_argument("--interval", type=int, default=300,
                    help="polling 間隔 sec (= default 300 = 5 min)")
    ap.add_argument("--since", default="",
                    help="開始 timestamp filter (= 例 20260529T081800Z)")
    ap.add_argument("--until", default="",
                    help="終了 timestamp filter")
    args = ap.parse_args()

    if args.once:
        meta, _ = scan_issues(since_ts=args.since, until_ts=args.until)
        print_report(meta)
        return

    last_count = 0
    print(f"[watcher] polling {ISSUES_DIR}, interval={args.interval}s, since={args.since or 'all'}",
          flush=True)
    while True:
        meta, _ = scan_issues(since_ts=args.since, until_ts=args.until)
        cur = meta["n_issues"]
        delta = cur - last_count
        label = f"[+{delta} new]" if delta else "[no change]"
        if delta or last_count == 0:
            now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
            print_report(meta, label=f"{now} {label}")
        last_count = cur
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n[watcher] interrupted")
            break


if __name__ == "__main__":
    main()
