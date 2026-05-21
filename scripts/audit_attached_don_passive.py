#!/usr/bin/env python3
"""【ドン!!×N】 を 機械的に passive +1000 リーダー と 解釈した overlay の 誤り 検出。

公式 text パターン:
- 「【ドン!!×N】リーダーはパワー+M」 → 真の passive (= overlay 正しい)
- 「【ドン!!×N】このリーダーはパワー+M」 → 真の passive
- 「【ドン!!×N】【XXX】...」 → 条件付/トリガー (= passive +1000 は 誤り)

Run: .venv/bin/python scripts/audit_attached_don_passive.py
"""
from __future__ import annotations
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS = {c["card_id"]: c for c in json.load(open(ROOT / "db" / "cards.json"))}
OVERLAY = json.load(open(ROOT / "db" / "card_effects.json"))


def has_simple_passive_pump(entries: list) -> bool:
    """overlay に on_attached_don + power_pump self_leader が ある か。"""
    for e in entries:
        if not isinstance(e, dict):
            continue
        if e.get("when") != "on_attached_don":
            continue
        for op in e.get("do") or []:
            if isinstance(op, dict) and "power_pump" in op:
                pp = op["power_pump"]
                if isinstance(pp, dict) and pp.get("target") == "self_leader":
                    return True
    return False


def text_has_passive_pump(text: str) -> bool:
    """公式 text に 「【ドン!!×N】 (このリーダーは|リーダーは) パワー+M」 単純 passive あり。"""
    return bool(re.search(
        r"【ドン[!‼]+×\d+】[^【]*?(?:リーダー|このリーダー)は?[^【]*?パワー[+＋][\d-]+",
        text,
    ))


def text_has_attached_don_section(text: str) -> bool:
    """公式 text に 「【ドン!!×N】」 セクション マーカー が ある か。"""
    return bool(re.search(r"【ドン[!‼]+×\d+】", text))


def main():
    print("=== attached_don passive 誤検出 audit ===")
    issues = []
    for cid, entries in OVERLAY.items():
        if not isinstance(entries, list):
            continue
        if not has_simple_passive_pump(entries):
            continue
        text = (CARDS.get(cid, {}).get("text") or "").strip()
        if not text:
            base = cid.split("_")[0]
            text = (CARDS.get(base, {}).get("text") or "").strip()
        if not text:
            continue
        if not text_has_attached_don_section(text):
            # overlay は ドン×N だが text に 該当 section なし → 別問題
            continue
        if not text_has_passive_pump(text):
            # text に passive pump pattern が ない → overlay 誤り
            issues.append({
                "card_id": cid,
                "kind": "miscoded_attached_don_passive",
                "text": text[:200],
                "severity": 5,
            })

    print(f"\n誤検出 候補: {len(issues)} 件")
    out = ROOT / "db" / "attached_don_passive_audit.json"
    out.write_text(json.dumps(issues, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote: {out}")

    for iss in issues[:15]:
        print(f"\n{iss['card_id']}:")
        print(f"  text: {iss['text']}")

    return len(issues)


if __name__ == "__main__":
    raise SystemExit(main())
