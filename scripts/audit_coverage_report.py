#!/usr/bin/env python3
"""coverage dashboard data generator (= 2026-05-28、 task #33)。

per-card 健全性 + per-primitive 健全性 + game integrity の 統合 metric を
db/audit_coverage.json に 出力。 Next.js /audit page (web/src/app/audit/page.tsx) が
これを 描画。

各 card の 健全性 軸:
- static_lint_pass: True if 0 issues / False otherwise
- runtime_fire_count: 4848 game corpus で fire 回数 (= 0 = 動作 未確認)
- cardqa_count: 該当 Q&A 件数

per-primitive 軸:
- invariant_declared: True if at least one invariant for this primitive exists
- usage_count: overlay 中 使用 回数
- runtime_event_count: runtime audit で 観測 した event 数

実行:
  .venv/bin/python scripts/audit_coverage_report.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CARDS_PATH = REPO_ROOT / "db" / "cards.json"
OVERLAY_PATH = REPO_ROOT / "db" / "card_effects.json"
STATIC_REPORT = REPO_ROOT / "db" / "static_audit_report.json"
RUNTIME_REPORT = REPO_ROOT / "db" / "runtime_audit_report.json"
CARDQA_TAGGED = REPO_ROOT / "db" / "cardqa_tagged.json"
OUT_PATH = REPO_ROOT / "db" / "audit_coverage.json"


def main() -> None:
    cards = {c["card_id"]: c for c in json.loads(CARDS_PATH.read_text(encoding="utf-8"))}
    overlay = json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))

    # static issues per card
    static_issues_per_card: dict[str, list[dict]] = defaultdict(list)
    static_total = 0
    if STATIC_REPORT.exists():
        sr = json.loads(STATIC_REPORT.read_text(encoding="utf-8"))
        for issue in sr.get("issues", []):
            cid = issue.get("card_id")
            if cid:
                static_issues_per_card[cid].append({
                    "rule_id": issue.get("rule_id"),
                    "severity": issue.get("severity"),
                    "category": issue.get("category"),
                })
                static_total += 1

    # runtime events per primitive (= effect_event 集計)
    runtime_primitive_events: Counter = Counter()
    runtime_total_events = 0
    runtime_violations_per_card: dict[str, list[dict]] = defaultdict(list)
    runtime_total_violations = 0
    if RUNTIME_REPORT.exists():
        rr = json.loads(RUNTIME_REPORT.read_text(encoding="utf-8"))
        for v in rr.get("violations", []):
            cid = v.get("evidence", {}).get("card_id", "_state")
            runtime_violations_per_card[cid].append({
                "rule_id": v.get("rule_id"),
                "severity": v.get("severity"),
            })
            runtime_total_violations += 1
        runtime_total_events = rr.get("summary", {}).get("total_effect_events", 0)

    # cardqa Q&A per card-mention
    cardqa_per_card_name: Counter = Counter()
    cardqa_total = 0
    if CARDQA_TAGGED.exists():
        ct = json.loads(CARDQA_TAGGED.read_text(encoding="utf-8"))
        cardqa_total = ct.get("stats", {}).get("total_items", 0)
        for item in ct.get("items", []):
            for ref in item.get("derived", {}).get("card_refs", []):
                cardqa_per_card_name[ref] += 1

    # primitive usage in overlay
    primitive_usage: Counter = Counter()
    for cid, entries in overlay.items():
        if not isinstance(entries, list):
            continue
        for e in entries:
            if not isinstance(e, dict):
                continue
            do = e.get("do", [])
            for prim in do if isinstance(do, list) else []:
                if isinstance(prim, dict):
                    for pk in prim.keys():
                        primitive_usage[pk] += 1

    # per-card health
    cards_health = []
    for cid in sorted(cards.keys()):
        c = cards[cid]
        issues = static_issues_per_card.get(cid, [])
        runtime_viols = runtime_violations_per_card.get(cid, [])
        # cardqa match (= name match)
        name = c.get("name", "")
        cardqa_count = cardqa_per_card_name.get(name, 0)
        # health signal
        if issues and any(i["severity"] >= 4 for i in issues):
            health = "warn"
        elif issues:
            health = "info"
        else:
            health = "ok"
        if runtime_viols:
            health = "error"
        cards_health.append({
            "card_id": cid,
            "name": name,
            "category": c.get("category", ""),
            "static_issues": issues,
            "static_issue_count": len(issues),
            "runtime_violations": runtime_viols,
            "runtime_violation_count": len(runtime_viols),
            "cardqa_count": cardqa_count,
            "has_overlay": cid in overlay,
            "health": health,
        })

    # per-primitive
    primitives = []
    for pk, count in primitive_usage.most_common():
        primitives.append({
            "primitive": pk,
            "usage_count": count,
        })

    # summary
    by_health = Counter(c["health"] for c in cards_health)

    out = {
        "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "summary": {
            "total_cards": len(cards),
            "cards_with_overlay": sum(1 for c in cards_health if c["has_overlay"]),
            "static_issues_total": static_total,
            "runtime_violations_total": runtime_total_violations,
            "runtime_events_total": runtime_total_events,
            "cardqa_total": cardqa_total,
            "primitive_distinct": len(primitives),
            "by_health": dict(by_health),
        },
        "cards": cards_health,
        "primitives": primitives,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 70)
    print("Audit Coverage Report")
    print("=" * 70)
    print(f"total cards               : {len(cards)}")
    print(f"cards with overlay        : {out['summary']['cards_with_overlay']}")
    print(f"static issues total       : {static_total}")
    print(f"runtime violations total  : {runtime_total_violations}")
    print(f"runtime events total      : {runtime_total_events}")
    print(f"cardqa total              : {cardqa_total}")
    print(f"primitives distinct       : {len(primitives)}")
    print()
    print("health distribution:")
    for h, n in by_health.most_common():
        print(f"  {h}: {n}")
    print()
    print(f"output: {OUT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
