#!/usr/bin/env python3
"""overlay 各 entry の cost 構造 vs 公式テキスト 語彙 整合 audit。

検出する 不整合 パターン:
- 公式テキスト「ドン‼N枚をレスト」 → overlay は rest_self_don N であるべき (pay_don N は誤り)
- 公式テキスト「ドン‼-N」 → overlay は pay_don N であるべき (rest_self_don N は誤り)
- 公式テキスト「手札N枚捨てる」 → overlay は discard_hand N であるべき
- 公式テキスト「このキャラをレストにする」 → cost.rest_self: true であるべき
- 公式テキスト「このキャラをトラッシュ」 → cost.trash_self: true であるべき
- 公式テキスト「ターン1回」 → once_per_turn: true であるべき

Run: .venv/bin/python scripts/audit_overlay_cost_vs_text.py
Outputs: db/cost_vs_text_audit.json (= 全 issue list、 fix 対象一覧)
"""
from __future__ import annotations
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS = json.load(open(ROOT / "db" / "cards.json"))
OVERLAY = json.load(open(ROOT / "db" / "card_effects.json"))
CARD_BY_ID = {c["card_id"]: c for c in CARDS}

WHEN_TO_SECTION = {
    "activate_main": ["【起動メイン】"],
    "main": ["【メイン】"],
    "counter": ["【カウンター】"],
    "on_play": ["【登場時】"],
    "on_attack": ["【アタック時】"],
    "on_ko": ["【KO時】"],
    "on_block": ["【ブロック時】"],
    "on_turn_end": ["【ターン終了時】"],
    "opp_attack": ["【相手のアタック時】"],
    "opp_chara_played": ["【相手のキャラ登場時】"],
    "trigger": ["【トリガー】"],
    "leader_passive": [""],
    "main_event": ["【メイン】"],
    "counter_event": ["【カウンター】"],
}

ALL_SECTION_HEADERS = [
    "【リーダー効果】", "【起動メイン】", "【メイン】", "【カウンター】",
    "【登場時】", "【アタック時】", "【KO時】", "【ブロック時】",
    "【ターン終了時】", "【ターン開始時】", "【相手のアタック時】",
    "【相手のキャラ登場時】", "【相手のターン中】", "【トリガー】",
    "【自分のターン中】",
]
ALL_HEADER_PATTERN = re.compile(
    "(" + "|".join(re.escape(h) for h in ALL_SECTION_HEADERS) + ")"
)


def get_text(cid: str) -> str:
    text = (CARD_BY_ID.get(cid, {}).get("text") or "").strip()
    if not text:
        base = cid.split("_")[0]
        text = (CARD_BY_ID.get(base, {}).get("text") or "").strip()
    return text


def split_by_section(text: str) -> list[tuple[str, str]]:
    parts = ALL_HEADER_PATTERN.split(text)
    result: list[tuple[str, str]] = []
    if parts[0]:
        result.append(("", parts[0]))
    i = 1
    while i < len(parts):
        if i + 1 < len(parts):
            result.append((parts[i], parts[i + 1]))
            i += 2
        else:
            result.append((parts[i], ""))
            i += 1
    return result


def get_section_for_when(text: str, when: str) -> str:
    headers = WHEN_TO_SECTION.get(when)
    if not headers:
        return ""  # unknown when → skip (= false-positive 防止)
    sections = split_by_section(text)
    for h, content in sections:
        if h in headers:
            return content
    return ""


def text_has_rest_don(text: str, when_marker: str = "") -> bool:
    """テキストに「ドン‼N枚をレスト」 系の rest_self_don パターンが含まれるか。

    when_marker は 「メイン」 「カウンター」 等で sub-section を 絞り込む 補助情報。
    現状は単純検出 (= section 分解しない)。
    """
    return bool(re.search(r"自分のドン‼\s*\d+\s*枚.*?レスト", text))


def text_has_paydon(text: str) -> bool:
    """テキストに「ドン‼-N」 (= return to deck) パターンが含まれるか。"""
    return bool(re.search(r"ドン‼\s*[-－]\s*\d+", text))


def text_has_discard(text: str) -> bool:
    return bool(re.search(r"手札\s*\d*\s*枚.*?捨", text)) or bool(
        re.search(r"自分の手札\s*\d+\s*枚を捨", text)
    )


def text_has_rest_self(text: str) -> bool:
    return bool(re.search(r"このキャラをレスト", text)) or bool(
        re.search(r"このキャラを.*?レストにできる", text)
    )


def text_has_trash_self(text: str) -> bool:
    return bool(re.search(r"このキャラをトラッシュ", text))


def text_has_once_per_turn(text: str) -> bool:
    return "【ターン1回】" in text or "ターン1回" in text


def section_has_cost_clause(section: str) -> bool:
    """section に 「...できる：」 形式 の cost 句 が あるか。"""
    return "できる：" in section or "できる:" in section


def audit_card(cid: str, entries: list) -> list[dict]:
    text = get_text(cid)
    if not text:
        return []
    issues = []

    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            continue
        when = e.get("when", "")
        section = get_section_for_when(text, when)
        if not section:
            continue
        cost = e.get("cost") or {}
        if not isinstance(cost, dict):
            continue

        # cost 句 が ない section は cost 不要 (= skip)
        if not section_has_cost_clause(section):
            continue

        # cost_part だけ で 判定 (= "...できる：" 前)
        if "できる：" in section:
            cost_part = section.split("できる：")[0]
        else:
            cost_part = section.split("できる:")[0]

        sec_has_rest_don = bool(re.search(r"自分のドン‼\s*\d+\s*枚.*?レスト", cost_part))
        sec_has_paydon = bool(re.search(r"ドン‼\s*[-－]\s*\d+", cost_part))

        # Pattern 1: section に "ドン‼N枚レスト" あるのに pay_don しか ない → 誤分類
        if sec_has_rest_don and not sec_has_paydon and "pay_don" in cost and "rest_self_don" not in cost:
            issues.append({
                "card_id": cid,
                "entry_idx": i,
                "kind": "pay_don_should_be_rest_self_don",
                "when": when,
                "cost": cost,
                "text": section[:160],
                "severity": 5,
            })

        # Pattern 2: section に "ドン‼N枚レスト" あるのに rest_self_don 抜け
        if sec_has_rest_don and not sec_has_paydon and "rest_self_don" not in cost:
            issues.append({
                "card_id": cid,
                "entry_idx": i,
                "kind": "missing_rest_self_don_in_cost",
                "when": when,
                "cost": cost,
                "text": section[:160],
                "severity": 4,
            })

        # Pattern 3: section に "このキャラをレスト" あるのに rest_self 抜け
        if re.search(r"このキャラを(?:.*?)?レスト", cost_part) and not cost.get("rest_self"):
            issues.append({
                "card_id": cid,
                "entry_idx": i,
                "kind": "missing_rest_self_in_cost",
                "when": when,
                "cost": cost,
                "text": section[:160],
                "severity": 4,
            })

        # Pattern 4: section に "このキャラをトラッシュ" あるのに trash_self 抜け
        if re.search(r"このキャラを(?:.*?)?トラッシュ", cost_part) and not cost.get("trash_self"):
            issues.append({
                "card_id": cid,
                "entry_idx": i,
                "kind": "missing_trash_self_in_cost",
                "when": when,
                "cost": cost,
                "text": section[:160],
                "severity": 4,
            })

        # Pattern 5: section に "手札N枚捨てる" あるのに discard_hand 抜け
        m_disc = re.search(r"自分の手札\s*(\d+)\s*枚を(?:.*?)?捨て", cost_part)
        if m_disc:
            expected_n = int(m_disc.group(1))
            actual_n = int(cost.get("discard_hand", 0))
            has_disc_filter = "discard_hand_with_filter" in cost
            if actual_n != expected_n and not has_disc_filter:
                issues.append({
                    "card_id": cid,
                    "entry_idx": i,
                    "kind": "discard_hand_count_mismatch",
                    "when": when,
                    "cost": cost,
                    "expected_n": expected_n,
                    "text": section[:160],
                    "severity": 4,
                })

        # Pattern 6: section に "【ターン1回】" あるのに once_per_turn 抜け
        if "【ターン1回】" in section and not cost.get("once_per_turn"):
            issues.append({
                "card_id": cid,
                "entry_idx": i,
                "kind": "missing_once_per_turn",
                "when": when,
                "cost": cost,
                "text": section[:160],
                "severity": 3,
            })

    return issues


def main():
    print("=== overlay cost vs text audit ===")
    all_issues: list[dict] = []
    for cid, entries in OVERLAY.items():
        if not isinstance(entries, list):
            continue
        all_issues.extend(audit_card(cid, entries))

    # severity 降順 で 出力
    all_issues.sort(key=lambda x: -x["severity"])

    by_kind: dict[str, int] = {}
    for iss in all_issues:
        by_kind[iss["kind"]] = by_kind.get(iss["kind"], 0) + 1

    print(f"\nTotal issues: {len(all_issues)}")
    for k, v in sorted(by_kind.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")

    out_path = ROOT / "db" / "cost_vs_text_audit.json"
    out_path.write_text(
        json.dumps(all_issues, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nWrote: {out_path}")

    # sev 5 (= 確定バグ) は head 出力
    sev5 = [i for i in all_issues if i["severity"] >= 5]
    if sev5:
        print(f"\n--- Severity 5+ ({len(sev5)} issues) ---")
        for iss in sev5[:30]:
            print(
                f"  {iss['card_id']} [{iss['when']}] {iss['kind']}\n"
                f"    cost: {iss['cost']}\n"
                f"    text: {iss['text']}"
            )

    return len(all_issues)


if __name__ == "__main__":
    raise SystemExit(main())
