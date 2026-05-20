#!/usr/bin/env python3
"""公式テキスト の 効果記述 vs overlay primitive の マッチ 検査。

検出 パターン:
- 「カード N 枚 を 引く」 → overlay に draw: N があるか
- 「ライフ N 枚 を 手札 に 加える」 → overlay に life_to_hand: N
- 「ドン!! を N 枚 アクティブ で 追加」 → overlay に add_don: N
- 「N 枚 までを 公開し、 手札 に 加える」 → overlay に search_top_n + limit=N

Run: .venv/bin/python scripts/audit_effect_text_vs_overlay.py
"""
from __future__ import annotations
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS = {c["card_id"]: c for c in json.load(open(ROOT / "db" / "cards.json"))}
OVERLAY = json.load(open(ROOT / "db" / "card_effects.json"))


def get_text(cid: str) -> str:
    text = (CARDS.get(cid, {}).get("text") or "").strip()
    if not text:
        base = cid.split("_")[0]
        text = (CARDS.get(base, {}).get("text") or "").strip()
    return text


def has_primitive_in_entries(entries: list, key: str, value_check=None) -> bool:
    """各 entry の do/then/else 配列 内 に key 持つ primitive が あるか。
    value_check が 与えられれば 該当 value で 一致確認。"""
    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == key:
                    if value_check is None or value_check(v):
                        return True
                if walk(v):
                    return True
        elif isinstance(node, list):
            for x in node:
                if walk(x):
                    return True
        return False
    return walk(entries)


def audit_card(cid: str, entries: list) -> list[dict]:
    text = get_text(cid)
    if not text:
        return []
    issues = []

    # 1) 「カード N 枚 を 引く」 → draw: N
    for m in re.finditer(r"カード\s*(\d+)\s*枚を引く", text):
        n = int(m.group(1))
        # 条件付き draw (= 「N 枚 以下 の 場合、 引く」) は section 内 で 別 primitive 経由
        # 簡易 check: overlay に draw: N 同等値 が ある か
        if not has_primitive_in_entries(
            entries, "draw",
            value_check=lambda v: (isinstance(v, int) and v == n) or v == n,
        ):
            # 動的 draw (draw_per_*) かもしれない → 確認
            has_dynamic = (
                has_primitive_in_entries(entries, "draw_per_self_hand_discarded")
                or has_primitive_in_entries(entries, "draw_per_hand_to_deck_bottom")
            )
            if not has_dynamic:
                issues.append({
                    "card_id": cid,
                    "kind": "missing_draw",
                    "expected_n": n,
                    "text": text[:140],
                    "severity": 4,
                })
                break  # 1 度 検出 で 十分

    # 2) 「自分のライフ N 枚 を 手札 に 加える」 → life_to_hand: N
    # 注: 「相手は自身のライフ」 は mill_opp_life_to_hand なので 別 primitive (= audit 対象外)
    for m in re.finditer(r"自分のライフ\s*(\d+)\s*枚.{0,15}手札に加える", text):
        n = int(m.group(1))
        if not has_primitive_in_entries(
            entries, "life_to_hand",
            value_check=lambda v: int(v) == n if not isinstance(v, dict) else int(v.get("amount", 0)) == n,
        ):
            issues.append({
                "card_id": cid,
                "kind": "missing_life_to_hand",
                "expected_n": n,
                "text": text[:140],
                "severity": 4,
            })
            break

    # 3) 「ドン!!デッキ から ドン!! N 枚 まで を、 アクティブ で 追加」 → add_don: N
    for m in re.finditer(r"ドン‼デッキから.*?ドン‼\s*(\d+)\s*枚まで.{0,15}アクティブで追加", text):
        n = int(m.group(1))
        if not has_primitive_in_entries(
            entries, "add_don",
            value_check=lambda v: int(v) == n if isinstance(v, int) else False,
        ) and not has_primitive_in_entries(
            entries, "add_don_active",
            value_check=lambda v: int(v) == n if isinstance(v, int) else False,
        ):
            issues.append({
                "card_id": cid,
                "kind": "missing_add_don",
                "expected_n": n,
                "text": text[:140],
                "severity": 4,
            })
            break

    # 4-6) text を 「...できる：」 で 分割 し、 effect 側 (= 後半) で 検査。
    # cost 句 (= 前半) に 含まれる primitive は overlay 必須 ではない (= cost として 別 処理)。
    effect_only = text
    # 全 「...できる：」 で 分割 → 効果側 (= ":" 以降) を 連結
    parts = re.split(r"(?:こと)?できる(?:：|:)", text)
    if len(parts) > 1:
        # 偶数 index は cost、 奇数 index は effect (= 厳密 ではない が 簡略)
        # 全 ":...：" 後 を effect として 連結
        effect_only = " ".join(parts[1:])

    if re.search(r"相手の.*?キャラ\s*\d*\s*枚.{0,30}(?:KO|ＫＯ)する", effect_only):
        if not has_primitive_in_entries(entries, "ko") and \
           not has_primitive_in_entries(entries, "ko_multi") and \
           not has_primitive_in_entries(entries, "ko_all_others"):
            issues.append({
                "card_id": cid,
                "kind": "missing_ko",
                "text": text[:140],
                "severity": 4,
            })

    if re.search(r"キャラ\s*\d*\s*枚.{0,30}持ち主の手札に戻す", effect_only):
        if not has_primitive_in_entries(entries, "return_to_hand") and \
           not has_primitive_in_entries(entries, "return_to_hand_multi"):
            issues.append({
                "card_id": cid,
                "kind": "missing_return_to_hand",
                "text": text[:140],
                "severity": 4,
            })

    if re.search(r"相手の.*?キャラ\s*\d*\s*枚.{0,30}をレストにする", effect_only):
        if not has_primitive_in_entries(entries, "rest"):
            issues.append({
                "card_id": cid,
                "kind": "missing_rest_opp",
                "text": text[:140],
                "severity": 4,
            })

    return issues


def main():
    print("=== effect text vs overlay audit ===")
    all_issues: list[dict] = []
    for cid, entries in OVERLAY.items():
        if not isinstance(entries, list):
            continue
        all_issues.extend(audit_card(cid, entries))

    by_kind: dict[str, int] = {}
    for iss in all_issues:
        by_kind[iss["kind"]] = by_kind.get(iss["kind"], 0) + 1
    print(f"\nTotal issues: {len(all_issues)}")
    for k, v in sorted(by_kind.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")

    out_path = ROOT / "db" / "effect_text_vs_overlay_audit.json"
    out_path.write_text(json.dumps(all_issues, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote: {out_path}")

    if all_issues:
        print("\n--- 上位 20 件 ---")
        for iss in all_issues[:20]:
            print(f"  {iss['card_id']} {iss['kind']} (expected_n={iss.get('expected_n')})")
            print(f"    text: {iss['text']}")

    return len(all_issues)


if __name__ == "__main__":
    raise SystemExit(main())
