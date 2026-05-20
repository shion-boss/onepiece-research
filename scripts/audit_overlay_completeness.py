# -*- coding: utf-8 -*-
"""
overlay 完全性 audit (= 公式テキスト ベース)
==========================================

目的:
    db/card_effects.json の overlay が 公式テキスト (db/cards.json の text フィールド)
    を 100% 公式準拠で 実装しているか 突合検査。

    audit_overlay_vs_faq.py は cardqa Q&A ベース だが、 cardqa が無いカードは検査不能。
    本 script は 全カード の 公式テキスト を 直接ベース に、 効果マーカー
    (= 【登場時】【アタック時】 等) と overlay 内 when=on_play 等 の 対応を 検査。

出力:
    db/overlay_completeness.json (= 全 issue + severity)
    db/overlay_completeness.md (= top issues + 統計)

ロジック:
    1. 全カード走査
    2. text から 公式効果マーカー 検出 → 期待される overlay entry を 推定
    3. overlay 実装 と 突合
    4. severity:
       - 5: 致命的 (text の 主要効果 が overlay 完全欠如)
       - 3-4: 部分欠如 (条件付き grant 未実装 等)
       - 1-2: 補助欠如 (オプション句 漏れ 等)
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS_JSON = ROOT / "db" / "cards.json"
OVERLAY_JSON = ROOT / "db" / "card_effects.json"
ACK_JSON = ROOT / "db" / "audit_acknowledged.json"
OUTPUT_JSON = ROOT / "db" / "overlay_completeness.json"
OUTPUT_MD = ROOT / "db" / "overlay_completeness.md"


# 公式マーカー → 期待される overlay when
TRIGGER_MARKERS = {
    "【登場時】": "on_play",
    "【アタック時】": "on_attack",
    "【KO時】": "on_ko",
    "【起動メイン】": "activate_main",
    "【メイン】": "main",
    "【トリガー】": "trigger",
    "【カウンター】": "counter",
    "【ブロック時】": "on_block",
    "【ターン終了時】": "on_turn_end",
    "【相手のターン中】": "_passive_opp_turn",  # 静的、 when マッチ不要
    "【自分のターン中】": "_passive_self_turn",
    "【ライフ】": "_leader_life",
}


# 条件付き keyword 検出 (= Phase 1A heuristic)
def is_conditional_keyword(text: str, keyword: str) -> bool:
    bracket = f"【{keyword}】"
    if bracket not in text:
        return False
    sentences = text.replace("\n", "。").split("。")
    innate_found = False
    for s in sentences:
        idx = s.find(bracket)
        if idx == -1:
            continue
        after = s[idx + len(bracket) : idx + len(bracket) + 20]
        before = s[:idx]
        if after.startswith(("を得", "を発動", "になる", "を持つ", "を持た")):
            continue
        if "発動できない" in after[:10]:
            continue
        if "場合" in before:
            continue
        if "：" in before or ":" in before:
            continue
        if before.endswith("】"):
            last = before.rfind("【")
            if last >= 0:
                marker = before[last:]
                if "ドン" in marker or "×" in marker or "ターン1回" in marker:
                    continue
        innate_found = True
    return not innate_found


def has_conditional_grant_with_overlay(
    text: str, keyword: str, overlay_entries: list[dict]
) -> bool:
    """text に 条件付き 【kw】 grant あり、 かつ overlay で give_keyword(kw) 実装あり。"""
    bracket = f"【{keyword}】"
    if bracket not in text:
        return False
    # 条件付き grant 文 を 検出
    has_grant_text = False
    sentences = text.replace("\n", "。").split("。")
    for s in sentences:
        if bracket not in s:
            continue
        after = s[s.find(bracket) + len(bracket) :][:20]
        if after.startswith("を得"):
            has_grant_text = True
            break
    if not has_grant_text:
        return False
    # overlay で grant あるか
    for ent in overlay_entries:
        for d in ent.get("do") or []:
            if not isinstance(d, dict):
                continue
            if "give_keyword" in d:
                spec = d["give_keyword"]
                if isinstance(spec, dict):
                    if spec.get("keyword") == keyword or keyword in (
                        spec.get("keywords") or []
                    ):
                        return True
                elif isinstance(spec, str) and spec == keyword:
                    return True
            if keyword == "速攻" and "give_rush" in d:
                return True
    return False


def expected_when_set_from_text(text: str) -> set[str]:
    """text から 期待される overlay when を 集合 で返す。

    False positive 抑制:
    - 「【トリガー】を持つカード」 「【登場時】を持たない」 等 property 参照 は除外
    - 「【メイン】/【カウンター】」 dual-mode は main OR counter どちらか で OK
    - 「自分の【登場時】効果」 のような property 参照 も除外
    """
    out = set()
    for marker, when in TRIGGER_MARKERS.items():
        if marker not in text or when.startswith("_"):
            continue
        # property 参照 を除外: 直後 が 「を持つ」 「を持た」 「効果」
        idx = 0
        is_real_trigger = False
        while True:
            idx = text.find(marker, idx)
            if idx == -1:
                break
            after = text[idx + len(marker) : idx + len(marker) + 10]
            if after.startswith(("を持つ", "を持た", "効果")):
                idx += len(marker)
                continue
            is_real_trigger = True
            break
        if is_real_trigger:
            out.add(when)
    # dual-mode イベント (= 【メイン】/【カウンター】): どちらか で OK
    # → ここでは out には 両方含めず、 検査時 OR で判定する
    return out


def is_dual_main_counter(text: str) -> bool:
    """「【メイン】/【カウンター】」 dual-mode イベントか。"""
    return (
        "【メイン】/【カウンター】" in text
        or "【メイン】 / 【カウンター】" in text
        or "/【カウンター】" in text
    )


def actual_when_set_from_overlay(entries: list[dict]) -> set[str]:
    """overlay entries から 実装されている when を 集合 で返す。

    別表記 を 正規化:
    - opp_event_or_trigger_fired / opp_event_played / opp_trigger_fired → trigger
    - on_attack_finish → on_attack (= alias)
    """
    out: set[str] = set()
    alias = {
        "opp_event_or_trigger_fired": "trigger",
        "opp_event_played": "trigger",
        "opp_trigger_fired": "trigger",
        "self_event_played": "trigger",
        "on_attack_finish": "on_attack",
        "on_attack_start": "on_attack",
        "on_self_event_played": "trigger",
    }
    for e in entries:
        w = e.get("when")
        if not w:
            continue
        out.add(alias.get(w, w))
    return out


def detect_issues(card: dict, overlay_entries: list[dict]) -> list[dict]:
    """各カードの issues を返す。 各 issue: {kind, severity, detail}"""
    text = card.get("text") or ""
    issues = []
    if not text:
        return issues

    # 1. 効果マーカー vs overlay when 突合
    expected = expected_when_set_from_text(text)
    actual = actual_when_set_from_overlay(overlay_entries)
    # dual-mode (= 【メイン】/【カウンター】): main OR counter どちらか実装で OK
    if is_dual_main_counter(text):
        if "main" in expected and "counter" in expected:
            if "main" in actual or "counter" in actual:
                expected.discard("main")
                expected.discard("counter")
    missing_whens = expected - actual
    for w in missing_whens:
        issues.append(
            {
                "kind": "missing_when",
                "severity": 5,
                "detail": f"text に {w} 系マーカー あるが overlay に when={w} entry 無し",
            }
        )

    # 2. 条件付き キーワード grant 未実装
    for kw in ("速攻", "ブロッカー", "ダブルアタック", "バニッシュ", "ブロック不可"):
        if f"【{kw}】" not in text:
            continue
        # 条件付き 使用 で innate=False、 かつ text に 「を得」 がある = grant 必要
        if is_conditional_keyword(text, kw):
            # text に 「【kw】を得」 含む?
            bracket_grant = (
                f"【{kw}】を得" in text or f"[{kw}]を得" in text
            )
            if bracket_grant:
                if not has_conditional_grant_with_overlay(text, kw, overlay_entries):
                    issues.append(
                        {
                            "kind": f"missing_conditional_{kw}_grant",
                            "severity": 4,
                            "detail": f"text に 条件付き 【{kw}】を得 あるが overlay に give_keyword({kw}) 実装 無し",
                        }
                    )

    # 3. 「ターン1回」 必須 = overlay cost.once_per_turn か
    if "【ターン1回】" in text:
        any_once = False
        for e in overlay_entries:
            cost = e.get("cost") or {}
            if isinstance(cost, dict) and cost.get("once_per_turn"):
                any_once = True
                break
        if not any_once and overlay_entries:
            issues.append(
                {
                    "kind": "missing_once_per_turn",
                    "severity": 3,
                    "detail": "text に 【ターン1回】 あるが overlay に once_per_turn 制約 無し",
                }
            )

    # 4. overlay に _unimplemented フラグ 残存
    for e in overlay_entries:
        if "_unimplemented" in e:
            issues.append(
                {
                    "kind": "unimplemented",
                    "severity": 5,
                    "detail": f"_unimplemented: {e['_unimplemented']}",
                }
            )

    # 5. overlay 完全空 だが text に 効果マーカーあり
    if not overlay_entries and expected:
        issues.append(
            {
                "kind": "empty_overlay_with_effect_text",
                "severity": 5,
                "detail": f"overlay 空 だが text に {sorted(expected)} 効果マーカー あり",
            }
        )

    return issues


def main():
    cards = json.load(open(CARDS_JSON, encoding="utf-8"))
    overlay = json.load(open(OVERLAY_JSON, encoding="utf-8"))

    # ACK is for issues we've previously confirmed as intrinsic / OK
    acks: set[str] = set()
    if ACK_JSON.exists():
        try:
            ack_data = json.load(open(ACK_JSON, encoding="utf-8"))
            for it in ack_data.get("issues") or []:
                key = f"{it.get('card_id')}|{it.get('kind')}"
                acks.add(key)
        except Exception:
            pass

    results: list[dict] = []
    severity_count: dict[int, int] = defaultdict(int)
    kind_count: dict[str, int] = defaultdict(int)
    for c in cards:
        cid = c["card_id"]
        if cid == "_meta":
            continue
        entries = overlay.get(cid, [])
        if not isinstance(entries, list):
            continue
        issues = detect_issues(c, entries)
        # ACK filter
        issues = [
            i for i in issues if f"{cid}|{i['kind']}" not in acks
        ]
        if not issues:
            continue
        max_sev = max(i["severity"] for i in issues)
        results.append(
            {
                "card_id": cid,
                "name": c.get("name"),
                "category": c.get("category"),
                "text": c.get("text") or "",
                "overlay_count": len(entries),
                "issues": issues,
                "max_severity": max_sev,
            }
        )
        severity_count[max_sev] += 1
        for i in issues:
            kind_count[i["kind"]] += 1

    results.sort(key=lambda r: (-r["max_severity"], r["card_id"]))

    OUTPUT_JSON.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Markdown: top 80 + 統計
    md = ["# Overlay Completeness Audit", ""]
    md.append(f"全カード: {len(cards)}, issue あり: {len(results)}")
    md.append("")
    md.append("## Severity 分布")
    for sev in sorted(severity_count.keys(), reverse=True):
        md.append(f"- sev {sev}: {severity_count[sev]} cards")
    md.append("")
    md.append("## Issue Kind 分布")
    for kind, n in sorted(kind_count.items(), key=lambda x: -x[1]):
        md.append(f"- {kind}: {n}")
    md.append("")
    md.append("## Top 80 sev≥4")
    for r in results[:80]:
        if r["max_severity"] < 4:
            break
        md.append(f"### {r['card_id']} {r['name']} (sev {r['max_severity']})")
        md.append(f"text: {r['text'][:200]}")
        for i in r["issues"]:
            md.append(f"- sev{i['severity']} {i['kind']}: {i['detail']}")
        md.append("")
    OUTPUT_MD.write_text("\n".join(md), encoding="utf-8")

    print(f"Output: {OUTPUT_JSON}")
    print(f"Output: {OUTPUT_MD}")
    print(f"Total cards with issues: {len(results)}")
    print(f"Severity distribution:")
    for sev in sorted(severity_count.keys(), reverse=True):
        print(f"  sev {sev}: {severity_count[sev]}")


if __name__ == "__main__":
    main()
