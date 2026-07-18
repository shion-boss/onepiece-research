#!/usr/bin/env python3
"""Post-process fetched pros_02 bodies: strip HTML -> text, build a structured index.

Reads   db/note_pros02/bodies/*.json  (body_html)
Writes  db/note_pros02/text/<key>.txt          (clean text, for distillation)
        db/note_pros02/index.json              (per-article structured metadata)

Classifies each article by leader / color / set(弾) / category / date so the
distillation step can group by leader and pick the most-recent current-meta guide.
Idempotent + safe to re-run after new fetches (periodic updates).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "db" / "note_pros02"
BODIES = OUT / "bodies"
TEXT = OUT / "text"
INDEX = OUT / "index.json"

LEADERS = ["ルフィ", "エネル", "ナミ", "ティーチ", "ロシナンテ", "ミホーク", "ハンコック",
           "エース", "ゾロ", "カタクリ", "ドフラミンゴ", "サカズキ", "クロコダイル", "ヤマト",
           "キッド", "ボニー", "ロー", "カイドウ", "シャンクス", "サボ", "ルッチ", "リンリン",
           "モリア", "ルーシー", "クザン", "おでん", "ペローナ", "ガープ", "ベロベティ",
           "リク", "ウタ", "ドフラ", "白ひげ", "マルコ", "ベガパンク", "レベッカ", "ビビ"]
COLORS = ["赤", "青", "緑", "紫", "黒", "黄"]


def classify(title: str) -> dict:
    t = title or ""
    if re.search(r"週間環境|環境考察|環境|Tier|tier", t):
        cat = "meta_weekly"
    elif re.search(r"解説|デッキ|レシピ|回し方|構築", t):
        cat = "deck_guide"
    elif re.search(r"コツ|上達|講座|立ち回り|入門|基礎|考え方|テクニック", t):
        cat = "guide_general"
    else:
        cat = "other"
    leaders = [l for l in LEADERS if l in t]
    colors = [c for c in COLORS if c + "ルフィ" in t or c + "エース" in t or c in t]
    m = re.search(r"(\d+\.?\d*)\s*弾", t) or re.search(r"(OP\d+|EB\d+|ST\d+|PRB\d+)", t)
    set_tag = m.group(1) if m else None
    dm = re.search(r"(\d{4})投稿", t)
    return {"category": cat, "leaders": leaders, "colors": colors,
            "set_tag": set_tag, "title_date": dm.group(1) if dm else None}


def main() -> None:
    TEXT.mkdir(parents=True, exist_ok=True)
    catalog = {c["key"]: c for c in json.loads((OUT / "catalog.json").read_text("utf-8"))}
    index = []
    for fp in sorted(BODIES.glob("*.json")):
        d = json.loads(fp.read_text("utf-8"))
        key = d["key"]
        html = d.get("body_html") or ""
        text = BeautifulSoup(html, "html.parser").get_text("\n") if html else ""
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        (TEXT / f"{key}.txt").write_text(text, encoding="utf-8")
        meta = classify(d.get("title") or catalog.get(key, {}).get("title") or "")
        index.append({
            "key": key,
            "title": d.get("title"),
            "price": d.get("price"),
            "publish_at": catalog.get(key, {}).get("publish_at") or d.get("publish_at"),
            "can_read": d.get("can_read"),
            "text_chars": len(text),
            "text_path": str((TEXT / f"{key}.txt").relative_to(ROOT)),
            **meta,
        })
    # newest first
    index.sort(key=lambda x: (x.get("publish_at") or ""), reverse=True)
    INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    # summary
    from collections import Counter
    cat = Counter(x["category"] for x in index)
    print(f"indexed {len(index)} articles -> {INDEX.relative_to(ROOT)}")
    print("categories:", dict(cat))
    # per-leader: newest deck_guide article (the current pilot guide)
    guides = [x for x in index if x["category"] == "deck_guide" and x["leaders"]]
    latest_by_leader: dict[str, dict] = {}
    for x in guides:
        for l in x["leaders"]:
            if l not in latest_by_leader:  # index already sorted newest-first
                latest_by_leader[l] = x
    print(f"\nper-leader latest deck_guide ({len(latest_by_leader)} leaders):")
    for l, x in sorted(latest_by_leader.items(),
                       key=lambda kv: kv[1].get("publish_at") or "", reverse=True):
        print(f"  {l:8s} {(x.get('publish_at') or '')[:10]}  {x['text_chars']:>6d}字  "
              f"set={x.get('set_tag')}  {x['key']}  {(x['title'] or '')[:30]}")


if __name__ == "__main__":
    main()
