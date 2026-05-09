# -*- coding: utf-8 -*-
"""
全カード画像を web/public/cards/ にダウンロードする (約 4,500 枚 / 1〜2GB / 約30〜60分)。

cache_deck_images.py の上位互換: cards.json の全 card_id を対象にする。

* 既存ファイルはスキップ (idempotent)
* レートリミット配慮で 1リクエスト 0.4s 間隔
* HTTP 失敗は集計だけして続行
* 中断/再開可能 (再実行で残りだけ取得)

実行:
    .venv/bin/python scripts/cache_all_images.py
    .venv/bin/python scripts/cache_all_images.py --limit 100   # 最初の100枚だけ試す
    .venv/bin/python scripts/cache_all_images.py --concurrency 4  # 並列 (注意: レートリミット)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CARDS_JSON = ROOT / "db" / "cards.json"
OUT_DIR = ROOT / "web" / "public" / "cards"
URL_TEMPLATE = "https://www.onepiece-cardgame.com/images/cardlist/card/{card_id}.png"
DEFAULT_DELAY_SEC = 0.4
TIMEOUT = 30


def collect_all_card_ids() -> list[str]:
    rows = json.loads(CARDS_JSON.read_text(encoding="utf-8"))
    ids: list[str] = []
    seen: set[str] = set()
    for row in rows:
        cid = row.get("card_id")
        if not cid or cid in seen:
            continue
        seen.add(cid)
        ids.append(cid)
    return ids


def fetch_one(sess: requests.Session, cid: str) -> tuple[str, int, str | None]:
    """戻り値: (cid, status_code, error_message_or_None)。
    既存ファイルは status=0 を返す (skipped マーカー)。
    """
    out = OUT_DIR / f"{cid}.png"
    if out.exists() and out.stat().st_size > 0:
        return cid, 0, None
    url = URL_TEMPLATE.format(card_id=cid)
    try:
        r = sess.get(url, timeout=TIMEOUT)
        if r.status_code != 200:
            return cid, r.status_code, None
        out.write_bytes(r.content)
        return cid, 200, None
    except Exception as e:
        return cid, -1, f"{type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="先頭 N 枚で試す")
    ap.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY_SEC,
        help="リクエスト間隔 (秒)",
    )
    ap.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="並列数 (デフォルト 1。増やすとレートリミット注意)",
    )
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    card_ids = collect_all_card_ids()
    if args.limit:
        card_ids = card_ids[: args.limit]

    print(f"対象 {len(card_ids)} カード, 出力先 {OUT_DIR}")

    sess = requests.Session()
    sess.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (onepiece_research bulk-image-cache; "
                "https://github.com/anthropics/claude-code)"
            )
        }
    )

    downloaded = 0
    skipped = 0
    failed: list[str] = []
    started = time.time()

    if args.concurrency <= 1:
        for i, cid in enumerate(card_ids, 1):
            _, code, err = fetch_one(sess, cid)
            if code == 0:
                skipped += 1
            elif code == 200:
                downloaded += 1
                if downloaded % 100 == 0:
                    elapsed = time.time() - started
                    rate = downloaded / elapsed if elapsed > 0 else 0
                    remaining = (len(card_ids) - i) / rate if rate > 0 else 0
                    print(
                        f"  [{i}/{len(card_ids)}] downloaded={downloaded} "
                        f"skipped={skipped} failed={len(failed)}  "
                        f"elapsed={elapsed:.0f}s  ETA~{remaining:.0f}s"
                    )
            else:
                failed.append(f"{cid}({code if code > 0 else err})")
            if code != 0:  # skipped はスリープ不要
                time.sleep(args.delay)
    else:
        # 並列モード (--concurrency N)。delay は無視されるので注意。
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = {pool.submit(fetch_one, sess, cid): cid for cid in card_ids}
            for i, fut in enumerate(as_completed(futures), 1):
                _, code, err = fut.result()
                if code == 0:
                    skipped += 1
                elif code == 200:
                    downloaded += 1
                else:
                    failed.append(f"{futures[fut]}({code if code > 0 else err})")
                if i % 100 == 0:
                    elapsed = time.time() - started
                    print(
                        f"  [{i}/{len(card_ids)}] downloaded={downloaded} "
                        f"skipped={skipped} failed={len(failed)}  "
                        f"elapsed={elapsed:.0f}s"
                    )

    elapsed = time.time() - started
    print()
    print(
        f"完了: 取得 {downloaded}, スキップ {skipped}, 失敗 {len(failed)}, "
        f"経過 {elapsed:.0f}s"
    )
    if failed:
        print(f"  失敗 {len(failed)} 件 (先頭10):", ", ".join(failed[:10]))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
