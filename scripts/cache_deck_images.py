# -*- coding: utf-8 -*-
"""
デッキで使われているカード画像だけ web/public/cards/ にダウンロードする。

公式 CDN を直接叩く運用 (4,500 リクエスト/ページ) を避けるためのキャッシュ。
* decks/*.json から leader + main の card_id を収集
* https://www.onepiece-cardgame.com/images/cardlist/card/<card_id>.png から取得
* 既存ファイルはスキップ (idempotent)
* 1リクエスト毎に短い sleep でレートリミット回避

実行:
    .venv/bin/python scripts/cache_deck_images.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DECKS_DIR = ROOT / "decks"
OUT_DIR = ROOT / "web" / "public" / "cards"
URL_TEMPLATE = "https://www.onepiece-cardgame.com/images/cardlist/card/{card_id}.png"
REQUEST_DELAY_SEC = 0.3
TIMEOUT = 30


def collect_card_ids() -> list[str]:
    ids: set[str] = set()
    if not DECKS_DIR.exists():
        return []
    for path in sorted(DECKS_DIR.glob("*.json")):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"  [WARN] {path.name}: JSON parse error", file=sys.stderr)
            continue
        if leader := d.get("leader"):
            ids.add(leader)
        for entry in d.get("main", []):
            cid = entry.get("card_id")
            if cid:
                ids.add(cid)
    return sorted(ids)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    card_ids = collect_card_ids()
    if not card_ids:
        print("対象カードなし (decks/ が空 or 読み込み失敗)")
        return 1

    print(f"対象 {len(card_ids)} カード, 出力先 {OUT_DIR}")

    sess = requests.Session()
    sess.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (onepiece_research deck-image-cache; "
                "https://github.com/anthropics/claude-code)"
            )
        }
    )

    downloaded = 0
    skipped = 0
    failed: list[str] = []

    for i, cid in enumerate(card_ids, 1):
        out = OUT_DIR / f"{cid}.png"
        if out.exists() and out.stat().st_size > 0:
            skipped += 1
            continue
        url = URL_TEMPLATE.format(card_id=cid)
        try:
            r = sess.get(url, timeout=TIMEOUT)
            if r.status_code != 200:
                print(f"  [{i}/{len(card_ids)}] {cid}: HTTP {r.status_code}")
                failed.append(f"{cid}({r.status_code})")
                continue
            out.write_bytes(r.content)
            downloaded += 1
            print(f"  [{i}/{len(card_ids)}] {cid}: {len(r.content)} bytes")
        except Exception as e:
            print(f"  [{i}/{len(card_ids)}] {cid}: {e}", file=sys.stderr)
            failed.append(f"{cid}({type(e).__name__})")
        time.sleep(REQUEST_DELAY_SEC)

    print()
    print(f"完了: 取得 {downloaded}, スキップ {skipped}, 失敗 {len(failed)}")
    if failed:
        print("  失敗したカード:", ", ".join(failed))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
