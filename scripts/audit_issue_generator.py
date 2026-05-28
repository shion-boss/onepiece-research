#!/usr/bin/env python3
"""Phase 4 auto-fix loop の issue generator (= 2026-05-28、 docs/AUTO_AUDIT_SYSTEM.md Layer 4)。

Layer 1/2/3 で 検出 した violation を 構造化 issue file に 落とし、
db/auto_issues/<ts>_<cid>_<layer>.json として 1 件 1 file で 保管。

これ を Phase 4 sub-agent loop (= scripts/audit_autofix_runner.py、 別 task) が
consume → 修正案 提案 → pytest gate → auto-merge / human review queue。

risk_tier 分類:
- low : data-only change (= overlay flag 追加 等)、 既存 test 通れば auto-merge 候補
- mid : 1 primitive 実装 修正、 human 1-click approval
- high: cross-cutting / engine 改造、 通常 PR human review

実行:
  .venv/bin/python scripts/audit_issue_generator.py
  .venv/bin/python scripts/audit_issue_generator.py --layer 1  # Layer 1 のみ
  .venv/bin/python scripts/audit_issue_generator.py --max 50    # 上限 50 件
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_REPORT = REPO_ROOT / "db" / "static_audit_report.json"
RUNTIME_REPORT = REPO_ROOT / "db" / "runtime_audit_report.json"
ISSUES_DIR = REPO_ROOT / "db" / "auto_issues"


# rule_id → risk_tier 分類 (= 経験則、 後で 学習で 調整可)
RISK_TIER_MAP = {
    # Layer 1 静的 lint
    "L1": "low",       # optional flag 追加 (= overlay edit、 既存挙動 onerous → 控えめ)
    "L2": "mid",       # once_per_turn 追加 (= overlay edit + engine 確認)
    "L3": "high",      # 自他反転 (= target spec 大幅変更)
    "L4": "low",       # count limit (= ko→ko_multi 変換 / 他 は skip)
    "L5": "low",       # leader_feature 追加 (= overlay edit)
    "L6": "high",      # trigger missing (= 新規 effect 実装)
    "L7": "low",       # cost_le 追加 (= overlay edit)
    "L8": "low",       # duration 変更 (= 既 primitive の field 編集 のみ)
    # Layer 2 runtime invariant
    "INV-cannot-rest-no-attack": "high",   # engine fix 必要
    "INV-rested-no-attack": "high",
    "INV-summoning-no-attack": "high",
    "INV-life-nonneg": "high",
    "INV-hand-nonneg": "high",
    "INV-don-total": "high",
    "INV-deck-nonneg": "high",
    "INV-leader-exists": "high",
}


def _make_issue_filename(ts: str, cid: str, layer: str, rule: str) -> str:
    """auto_issues file 名 を 一意 に 決定。"""
    safe_cid = cid.replace("/", "_")
    safe_rule = rule.replace("/", "_")
    return f"{ts}_{layer}_{safe_cid}_{safe_rule}.json"


def gen_from_static_report(max_count: int | None = None) -> list[dict]:
    """Layer 1 静的 lint の report → issue list へ 変換。"""
    if not STATIC_REPORT.exists():
        print(f"WARN: {STATIC_REPORT} not found, skip Layer 1", file=sys.stderr)
        return []
    report = json.loads(STATIC_REPORT.read_text(encoding="utf-8"))
    out = []
    for v in report.get("issues", []):
        if max_count is not None and len(out) >= max_count:
            break
        cid = v.get("card_id", "?")
        rule = v.get("rule_id", "?")
        out.append({
            "layer": "static_lint",
            "rule_id": rule,
            "card_id": cid,
            "severity": v.get("severity", 3),
            "risk_tier": RISK_TIER_MAP.get(rule, "mid"),
            "message": v.get("message", ""),
            "evidence": v.get("evidence", {}),
            "suggested_fix": v.get("suggested_fix", {}),
            "source": "scripts/audit_overlay_static.py",
        })
    return out


def gen_from_runtime_report(max_count: int | None = None) -> list[dict]:
    """Layer 2 runtime invariant の report → issue list へ 変換。"""
    if not RUNTIME_REPORT.exists():
        print(f"WARN: {RUNTIME_REPORT} not found, skip Layer 2", file=sys.stderr)
        return []
    report = json.loads(RUNTIME_REPORT.read_text(encoding="utf-8"))
    out = []
    # dedup by (rule_id, message) — runtime は 試合 違い で 同じ 違反 が 多数 出る
    seen = set()
    for v in report.get("violations", []):
        key = (v.get("rule_id"), v.get("message"))
        if key in seen:
            continue
        seen.add(key)
        if max_count is not None and len(out) >= max_count:
            break
        rule = v.get("rule_id", "?")
        # runtime は card_id 不明 の case も ある (= state-level 違反)
        cid = v.get("evidence", {}).get("card_id", "_state_level")
        out.append({
            "layer": "runtime_invariant",
            "rule_id": rule,
            "card_id": cid,
            "severity": v.get("severity", 3),
            "risk_tier": RISK_TIER_MAP.get(rule, "high"),
            "message": v.get("message", ""),
            "evidence": v.get("evidence", {}),
            "suggested_fix": {
                "patch": "engine fix 必要 (= 観測 違反、 invariant 由来)",
            },
            "source": "scripts/audit_runtime_invariants.py",
            "turn": v.get("turn"),
            "phase": v.get("phase"),
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--layer", choices=["1", "2", "all"], default="all")
    ap.add_argument("--max", type=int, default=None, help="layer 毎 上限 件数")
    ap.add_argument("--clear", action="store_true", help="既存 issue 全削除 してから")
    args = ap.parse_args()

    ISSUES_DIR.mkdir(parents=True, exist_ok=True)

    if args.clear:
        n = 0
        for f in ISSUES_DIR.glob("*.json"):
            f.unlink()
            n += 1
        print(f"cleared {n} existing issues")

    issues: list[dict] = []
    if args.layer in ("1", "all"):
        issues += gen_from_static_report(args.max)
    if args.layer in ("2", "all"):
        issues += gen_from_runtime_report(args.max)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    n_created = 0
    risk_counter = {"low": 0, "mid": 0, "high": 0}
    for issue in issues:
        cid = issue["card_id"]
        rule = issue["rule_id"]
        layer = issue["layer"]
        fname = _make_issue_filename(ts, cid, layer, rule)
        path = ISSUES_DIR / fname
        issue["created_at"] = ts
        path.write_text(
            json.dumps(issue, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        n_created += 1
        risk_counter[issue["risk_tier"]] = risk_counter.get(issue["risk_tier"], 0) + 1

    print(f"created {n_created} issues in {ISSUES_DIR.relative_to(REPO_ROOT)}")
    print(f"  low : {risk_counter.get('low', 0)} (= auto-fix 候補)")
    print(f"  mid : {risk_counter.get('mid', 0)} (= 1-click human approval)")
    print(f"  high: {risk_counter.get('high', 0)} (= 通常 PR human review)")


if __name__ == "__main__":
    main()
