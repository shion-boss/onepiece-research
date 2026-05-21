#!/usr/bin/env python3
"""Step A: give_keyword grant 系 自動生成 marker entries の _text を
公式テキスト の 該当 文 に 書き戻す。

各 entry の do から keyword を 抽出し、 公式テキスト中 で 同じ keyword を含む
最初の 句 を 探して _text に 書き戻す。 内容自体 (= when/if/do) は 触らない。

run: .venv/bin/python scripts/rewrite_auto_gen_grant_text.py
"""
from __future__ import annotations
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS = {c["card_id"]: c for c in json.load(open(ROOT / "db" / "cards.json"))}
OV_PATH = ROOT / "db" / "card_effects.json"
ov = json.load(open(OV_PATH, encoding="utf-8"))


def get_text(cid: str) -> str:
    t = (CARDS.get(cid, {}).get("text") or "").strip()
    if not t:
        base = cid.split("_")[0]
        t = (CARDS.get(base, {}).get("text") or "").strip()
    return t


def keyword_from_entry(e: dict) -> str | None:
    for action in (e.get("do") or []):
        if isinstance(action, dict) and "give_keyword" in action:
            gk = action["give_keyword"]
            if isinstance(gk, dict):
                return gk.get("keyword")
    return None


def find_keyword_sentence(text: str, keyword: str) -> str | None:
    """公式テキスト中、 keyword を含む 最初の 句 (= 「。」 区切り) を返す。"""
    sentences = re.split(r"(?<=。)", text)
    for s in sentences:
        if f"【{keyword}】" in s or f"は{keyword}を得る" in s:
            return s.strip()
    return None


def main():
    changed = 0
    skipped_no_kw = 0
    skipped_no_match = 0
    for cid, es in ov.items():
        if not isinstance(es, list):
            continue
        text = get_text(cid)
        if not text:
            continue
        for e in es:
            if not isinstance(e, dict):
                continue
            t = e.get("_text") or ""
            if "自動生成" not in t:
                continue
            kw = keyword_from_entry(e)
            if not kw:
                skipped_no_kw += 1
                continue
            sentence = find_keyword_sentence(text, kw)
            if not sentence:
                skipped_no_match += 1
                continue
            new_text = f"{cid} {sentence}"
            if new_text != t:
                e["_text"] = new_text
                changed += 1
    OV_PATH.write_text(json.dumps(ov, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"changed: {changed}")
    print(f"skipped (no keyword in do): {skipped_no_kw}")
    print(f"skipped (no matching sentence): {skipped_no_match}")
    print(f"wrote: {OV_PATH}")


if __name__ == "__main__":
    main()
