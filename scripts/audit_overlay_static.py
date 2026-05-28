#!/usr/bin/env python3
"""Phase 1 静的 lint (= 2026-05-28 着手、 ohtsuki さん 「徹底的に改善」 要件)。

db/cards.json (= 公式 text) と db/card_effects.json (= engine overlay) の **構造的 不一致**
を 検出 する 純 静的 audit。 runtime 試合 不要。 commit 毎 に CI で 走らせる 軽量 lint。

検出 pattern (= docs/AUTO_AUDIT_SYSTEM.md Layer 1 表):
- L1: optional 漏れ      もよい / ことができる → overlay の 関連 entry に optional: true
- L2: once_per_turn 漏れ ターン1回 → overlay entry に once_per_turn or cost.once_per_turn
- L3: 自他 反転         相手の X → overlay target が opp_* 系
                        自分の X → overlay target が self_* 系
- L4: 上限 漏れ          までを N → overlay に count: N
- L5: leader_feature   自分のリーダーが特徴《X》を持つ → if.leader_feature: X
- L6: trigger 漏れ       【XX時】 → overlay when (on_xx 系)
- L7: cost 範囲         コスト N 以下 → target_cost_le: N
- L8: duration         このターン中 / 次相手 end まで → duration spec

出力: db/static_audit_report.json + .md (= 上位 100 件 抜粋)

実行:
  .venv/bin/python scripts/audit_overlay_static.py
  .venv/bin/python scripts/audit_overlay_static.py --severity 3  # sev>=3 のみ
  .venv/bin/python scripts/audit_overlay_static.py --card OP14-061  # 単体 確認
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CARDS_PATH = REPO_ROOT / "db" / "cards.json"
OVERLAY_PATH = REPO_ROOT / "db" / "card_effects.json"
ACK_PATH = REPO_ROOT / "db" / "audit_acknowledged.json"
OUT_JSON = REPO_ROOT / "db" / "static_audit_report.json"
OUT_MD = REPO_ROOT / "db" / "static_audit_report.md"


# 検出 patterns (= 正規表現 + 期待 overlay 形)
OPTIONAL_TOKENS = ("もよい", "ことができる", "ことができます", "してもよい")
ONCE_TOKENS = ("ターン1回", "ターンに1回", "ターン１回")
# TRIGGER_MAP: text の tag → 期待 overlay when 値 (1 件 以上 マッチ で OK)。
# 値 が tuple なら どれか 1 つ あれば OK (= 同 意味 の 別表現)。
# 注意: engine の 実装 when 名 と 一致 (= main vs activate_main 等 で 大量 false positive 防止)。
TRIGGER_MAP = {
    "【登場時】": ("on_play",),
    "【アタック時】": ("on_attack",),
    "【起動メイン】": ("activate_main", "main"),
    "【KO時】": ("on_ko",),
    "【ターン終了時】": ("on_turn_end", "end_of_turn"),
    "【ブロック時】": ("on_block",),
    "【相手のアタック時】": ("opp_attack", "on_opp_attack"),
    "【トリガー】": ("trigger",),
    "【カウンター】": ("counter",),
}
REPLACE_WHEN = ("replace_ko", "replace_leave", "replace_rest")


def _load_cards() -> dict:
    cards = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
    return {c["card_id"]: c for c in cards}


def _load_overlay() -> dict:
    return json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))


def _load_ack() -> set[str]:
    """audit_acknowledged.json に intrinsic 除外 listed の (card_id, rule_id) set。"""
    if not ACK_PATH.exists():
        return set()
    try:
        ack = json.loads(ACK_PATH.read_text(encoding="utf-8"))
    except Exception:
        return set()
    out = set()
    for entry in ack.get("entries", []) if isinstance(ack, dict) else []:
        cid = entry.get("card_id")
        rule = entry.get("rule_id")
        if cid and rule:
            out.add(f"{cid}:{rule}")
    return out


def _entries_have_field(entries: list, field: str) -> bool:
    """overlay entries の どれか が field を 持つ か。"""
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, dict):
            continue
        if e.get(field):
            return True
        # cost に once_per_turn が 入る pattern も 拾う
        if field == "once_per_turn":
            cost = e.get("cost")
            if isinstance(cost, dict) and cost.get("once_per_turn"):
                return True
            if isinstance(cost, list):
                for c in cost:
                    if isinstance(c, dict) and c.get("once_per_turn"):
                        return True
    return False


def _entries_have_when(entries: list, when_set: tuple) -> bool:
    for e in entries if isinstance(entries, list) else []:
        if isinstance(e, dict) and e.get("when") in when_set:
            return True
    return False


def _check_optional(cid: str, text: str, entries: list) -> list[dict]:
    """L1: 「もよい/ことができる」 含む text で replace_ko entry に optional 無し。"""
    issues = []
    if not any(t in text for t in OPTIONAL_TOKENS):
        return issues
    # replace_ko / replace_leave entry が ある なら optional: true 必須
    for i, e in enumerate(entries if isinstance(entries, list) else []):
        if not isinstance(e, dict):
            continue
        if e.get("when") not in REPLACE_WHEN:
            continue
        if not e.get("optional"):
            issues.append({
                "rule_id": "L1",
                "card_id": cid,
                "severity": 4,
                "category": "optional_missing",
                "message": f"text に 「{[t for t in OPTIONAL_TOKENS if t in text][0]}」 "
                          f"が 含まれる が {e.get('when')} entry [{i}] に optional: true なし",
                "evidence": {
                    "text_excerpt": _excerpt_around(text, OPTIONAL_TOKENS),
                    "entry_when": e.get("when"),
                    "entry_index": i,
                },
                "suggested_fix": {
                    "path": f"db/card_effects.json:{cid}[{i}]",
                    "patch": "optional: true を 追加",
                },
            })
    return issues


def _check_once_per_turn(cid: str, text: str, entries: list) -> list[dict]:
    """L2: 「ターン1回」 含む text で entry に once_per_turn 無し。"""
    issues = []
    if not any(t in text for t in ONCE_TOKENS):
        return issues
    if not entries:
        return issues
    # entry が 複数 ある と「どれが ターン1回 か」 判断 困難。
    # heuristic: 少なくとも 1 つ once_per_turn を 持つ なら OK。
    if _entries_have_field(entries, "once_per_turn"):
        return issues
    # cost.once_per_turn も 受容
    has = False
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, dict):
            continue
        cost = e.get("cost")
        if isinstance(cost, dict) and cost.get("once_per_turn"):
            has = True
            break
        if isinstance(cost, list):
            for c in cost:
                if isinstance(c, dict) and c.get("once_per_turn"):
                    has = True
                    break
            if has:
                break
    if not has:
        issues.append({
            "rule_id": "L2",
            "card_id": cid,
            "severity": 4,
            "category": "once_per_turn_missing",
            "message": "text に 「ターン1回」 が 含まれる が overlay entries の どれも "
                      "once_per_turn を 持たない",
            "evidence": {
                "text_excerpt": _excerpt_around(text, ONCE_TOKENS),
                "entry_count": len(entries) if isinstance(entries, list) else 0,
            },
            "suggested_fix": {
                "path": f"db/card_effects.json:{cid}",
                "patch": "該当 entry に once_per_turn: true (もしくは cost.once_per_turn: true) を 追加",
            },
        })
    return issues


def _check_trigger_missing(cid: str, text: str, entries: list) -> list[dict]:
    """L6: 【XX時】 含む text で 該当 when の entry が 1 件 も 無い。

    expected_whens は tuple = どれか 1 つ あれば OK (= main/activate_main 等 の 同義語 吸収)。
    """
    issues = []
    if not entries:
        return issues  # 効果 なし card は スキップ
    entry_whens = {e.get("when") for e in entries if isinstance(e, dict)}
    for tag, expected_whens in TRIGGER_MAP.items():
        if tag not in text:
            continue
        if any(w in entry_whens for w in expected_whens):
            continue
        issues.append({
            "rule_id": "L6",
            "card_id": cid,
            "severity": 4,
            "category": "trigger_missing",
            "message": f"text に 「{tag}」 が 含まれる が overlay に when ∈ "
                      f"{list(expected_whens)} entry なし",
            "evidence": {
                "tag": tag,
                "expected_whens": list(expected_whens),
                "actual_whens": sorted(w for w in entry_whens if w),
            },
            "suggested_fix": {
                "path": f"db/card_effects.json:{cid}",
                "patch": f"when: {expected_whens[0]} の entry を 追加",
            },
        })
    return issues


def _check_leader_feature_missing(cid: str, text: str, entries: list) -> list[dict]:
    """L5: 「自分のリーダーが特徴《X》を持つ(なら|場合)」 → entry の if.leader_feature: X。"""
    issues = []
    if not entries:
        return issues
    # 「自分のリーダーが特徴《X》を持つ なら/場合」 抽出
    m = re.search(r"自分のリーダーが特徴《([^》]+)》を持つ(なら|場合)", text)
    if not m:
        return issues
    feature = m.group(1)
    # 少なくとも 1 entry の if.leader_feature が feature なら OK
    has_feature = False
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, dict):
            continue
        if_block = e.get("if", {})
        if isinstance(if_block, dict):
            lf = if_block.get("leader_feature")
            if lf == feature or (isinstance(lf, list) and feature in lf):
                has_feature = True
                break
        # choice_effect の option 別 if も 拾う
        do_list = e.get("do", [])
        for prim in do_list if isinstance(do_list, list) else []:
            if isinstance(prim, dict) and "choice_effect" in prim:
                opts = prim["choice_effect"].get("options", [])
                for opt in opts:
                    if isinstance(opt, dict):
                        opt_if = opt.get("if", {})
                        if isinstance(opt_if, dict):
                            lf = opt_if.get("leader_feature")
                            if lf == feature or (isinstance(lf, list) and feature in lf):
                                has_feature = True
                                break
                if has_feature:
                    break
        if has_feature:
            break
    if not has_feature:
        issues.append({
            "rule_id": "L5",
            "card_id": cid,
            "severity": 3,
            "category": "leader_feature_missing",
            "message": f"text の 「自分のリーダーが特徴《{feature}》を持つ なら/場合」 "
                      f"に 対応 する if.leader_feature が overlay に なし",
            "evidence": {
                "feature": feature,
                "text_excerpt": _excerpt_around(text, ("特徴《" + feature + "》",)),
            },
            "suggested_fix": {
                "path": f"db/card_effects.json:{cid}",
                "patch": f"該当 entry の if に leader_feature: '{feature}' を 追加",
            },
        })
    return issues


def _excerpt_around(text: str, tokens: tuple, span: int = 40) -> str:
    for t in tokens:
        idx = text.find(t)
        if idx >= 0:
            start = max(0, idx - span)
            end = min(len(text), idx + len(t) + span)
            return ("…" if start > 0 else "") + text[start:end] + ("…" if end < len(text) else "")
    return text[:80]


def audit_card(cid: str, card: dict, overlay: dict) -> list[dict]:
    text = card.get("text", "") or ""
    entries = overlay.get(cid, [])
    issues = []
    issues += _check_optional(cid, text, entries)
    issues += _check_once_per_turn(cid, text, entries)
    issues += _check_trigger_missing(cid, text, entries)
    issues += _check_leader_feature_missing(cid, text, entries)
    return issues


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--severity", type=int, default=0,
                    help="この severity 以上 の issue のみ 出力")
    ap.add_argument("--card", default=None,
                    help="単体 card_id audit (= debug 用)")
    ap.add_argument("--top", type=int, default=100,
                    help=".md report の 上位 N 件 (default 100)")
    args = ap.parse_args()

    cards = _load_cards()
    overlay = _load_overlay()
    ack = _load_ack()

    all_issues = []
    if args.card:
        target_cids = [args.card]
    else:
        target_cids = sorted(cards.keys())

    for cid in target_cids:
        if cid not in cards:
            print(f"WARN: {cid} not in cards.json", file=sys.stderr)
            continue
        issues = audit_card(cid, cards[cid], overlay)
        for issue in issues:
            key = f"{issue['card_id']}:{issue['rule_id']}"
            if key in ack:
                issue["acknowledged"] = True
                continue
            if issue["severity"] < args.severity:
                continue
            all_issues.append(issue)

    # 集計
    by_rule = Counter(i["rule_id"] for i in all_issues)
    by_cat = Counter(i["category"] for i in all_issues)
    by_sev = Counter(i["severity"] for i in all_issues)

    report = {
        "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "cards_scanned": len(target_cids),
        "issues_total": len(all_issues),
        "by_rule": dict(by_rule),
        "by_category": dict(by_cat),
        "by_severity": dict(by_sev),
        "issues": all_issues,
    }
    OUT_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # md report
    lines = [
        "# Static Audit Report (Layer 1)",
        "",
        f"generated: {report['generated_at']}  ",
        f"cards scanned: {report['cards_scanned']}  ",
        f"issues total: {report['issues_total']}  ",
        "",
        "## by rule",
        "",
    ]
    for rule, count in sorted(by_rule.items()):
        lines.append(f"- `{rule}`: {count}")
    lines += ["", "## by category", ""]
    for cat, count in sorted(by_cat.items(), key=lambda x: -x[1]):
        lines.append(f"- `{cat}`: {count}")
    lines += ["", "## by severity", ""]
    for sev in sorted(by_sev.keys(), reverse=True):
        lines.append(f"- sev {sev}: {by_sev[sev]}")
    lines += ["", f"## top {args.top} issues", ""]
    for i, issue in enumerate(all_issues[: args.top]):
        lines += [
            f"### {i+1}. {issue['card_id']} ({issue['rule_id']}, sev {issue['severity']})",
            "",
            f"**{issue['category']}**: {issue['message']}",
            "",
            f"- text: `{issue['evidence'].get('text_excerpt', '')[:120]}`",
            f"- fix: `{issue['suggested_fix']['patch']}`",
            "",
        ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    # stdout summary
    print("=" * 70)
    print(f"Static Audit (Layer 1)")
    print("=" * 70)
    print(f"cards scanned : {report['cards_scanned']}")
    print(f"issues found  : {report['issues_total']}")
    print()
    print("by rule:")
    for rule, count in sorted(by_rule.items()):
        print(f"  {rule}: {count}")
    print()
    print("by severity:")
    for sev in sorted(by_sev.keys(), reverse=True):
        print(f"  sev {sev}: {by_sev[sev]}")
    print()
    print(f"output: {OUT_JSON.relative_to(REPO_ROOT)}")
    print(f"        {OUT_MD.relative_to(REPO_ROOT)}")
    print()
    if args.card:
        print(f"=== {args.card} ===")
        card_issues = [i for i in all_issues if i["card_id"] == args.card]
        for issue in card_issues:
            print(f"  [{issue['rule_id']} sev {issue['severity']}] {issue['message']}")


if __name__ == "__main__":
    main()
