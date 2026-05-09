# -*- coding: utf-8 -*-
"""cardrush.media から大会上位入賞デッキを取得して decks/cardrush_<id>.json に保存。

使い方:
    .venv/bin/python scripts/scrape_cardrush_decks.py
    .venv/bin/python scripts/scrape_cardrush_decks.py --scores 優勝 準優勝 3位 ベスト4
    .venv/bin/python scripts/scrape_cardrush_decks.py --since 2026-01-01 --max-pages 10 --limit 50
    .venv/bin/python scripts/scrape_cardrush_decks.py --dry-run

検索条件:
    - format: スタンダード (デフォルト)
    - is_winning: true (大会入賞のみ)
    - sort: created_at DESC (新しい順)

出力フォーマット (既存 decks/meta_*.json と互換):
    {
      "name": "緑ミホーク",
      "slug": "cardrush_1437",
      "leader": "OP14-020",
      "leader_name": "ジュラキュール・ミホーク",
      "source": "https://cardrush.media/onepiece/decks/1437",
      "score": "優勝",
      "tournament_name": "フラッグシップバトル",
      "tournament_date": "2026-05-05",
      "fetched_at": "2026-05-10T...",
      "main": [{"card_id": "OP12-034", "count": 4}, ...]
    }

サイト構造:
    Next.js SSR で <script id="__NEXT_DATA__"> に全データ JSON が埋まっている。
    一覧ページ: pageProps.decks (30件/page) + pageProps.lastPage
    詳細ページ: pageProps.deck.recipes (リーダー含む 16〜20 種)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "decks"
CARDS_PATH = ROOT / "db" / "cards.json"

LIST_URL = "https://cardrush.media/onepiece/decks/list"
DECK_URL = "https://cardrush.media/onepiece/decks/{id}"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 onepiece-research-bot"

VALID_SCORES = ["優勝", "準優勝", "3位", "ベスト4"]

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S
)


def extract_next_data(html: str) -> dict:
    m = _NEXT_DATA_RE.search(html)
    if not m:
        raise ValueError("__NEXT_DATA__ not found in HTML")
    return json.loads(m.group(1))


def http_get(url: str, params=None) -> str:
    r = requests.get(
        url, params=params, headers={"User-Agent": UA}, timeout=30
    )
    r.raise_for_status()
    return r.text


def list_decks(scores, format_name, since, until, max_pages, sleep):
    """一覧ページを順に叩いて (id, archetype, score, date) を集める。"""
    out = []
    for page in range(1, max_pages + 1):
        params = [
            ("format[name]", format_name),
            ("is_winning", "true"),
            ("trigger", "true"),
            ("page", str(page)),
            ("sort[key]", "created_at"),
            ("sort[order]", "DESC"),
        ]
        for s in scores:
            params.append(("score[]", s))
        if since:
            params.append(("created_at[min]", since))
        if until:
            params.append(("created_at[max]", until))

        html = http_get(LIST_URL, params)
        data = extract_next_data(html)
        pp = data["props"]["pageProps"]
        decks = pp.get("decks", [])
        last = pp.get("lastPage") or 1
        if not decks:
            break
        for d in decks:
            out.append({
                "id": d["id"],
                "archetype": (d.get("archetype") or {}).get("name", ""),
                "score": d.get("score", ""),
                "tournament_name": d.get("tournament_name", ""),
                "tournament_date": d.get("tournament_date", ""),
            })
        print(f"  page {page}/{last}: +{len(decks)} (cumulative {len(out)})")
        if page >= last:
            break
        time.sleep(sleep)
    return out


def fetch_deck_detail(deck_id: int) -> dict:
    html = http_get(DECK_URL.format(id=deck_id))
    data = extract_next_data(html)
    return data["props"]["pageProps"]["deck"]


def deck_to_meta(deck: dict, valid_card_ids: set) -> tuple[dict, list[str]]:
    """cardrush deck dict を既存 meta_*.json 形式へ。未知 card_id は warnings に。"""
    leader = None
    leader_name = ""
    main: list[dict] = []
    warnings: list[str] = []
    for r in deck["recipes"]:
        cid = r["card"]["card_number"]
        cnt = r["count"]
        kind = r["deck_type"]
        if kind == "リーダー":
            leader = cid
            leader_name = r["card"]["name"]
        else:
            if cid not in valid_card_ids:
                warnings.append(
                    f"deck {deck['id']}: unknown card_id {cid} ({r['card'].get('name','')})"
                )
            main.append({"card_id": cid, "count": cnt})

    archetype = (deck.get("archetype") or {}).get("name", "")
    deck_id = deck["id"]
    return (
        {
            "name": archetype,
            "slug": f"cardrush_{deck_id}",
            "leader": leader,
            "leader_name": leader_name,
            "source": f"https://cardrush.media/onepiece/decks/{deck_id}",
            "score": deck.get("score", ""),
            "tournament_name": deck.get("tournament_name", ""),
            "tournament_date": deck.get("tournament_date", ""),
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "main": main,
        },
        warnings,
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--scores", nargs="+", default=["優勝"],
        choices=VALID_SCORES,
        help="絞り込み大会成績 (複数指定可)",
    )
    ap.add_argument("--format", default="スタンダード", help="フォーマット名")
    ap.add_argument("--since", default=None, help="YYYY-MM-DD (作成日 min)")
    ap.add_argument("--until", default=None, help="YYYY-MM-DD (作成日 max)")
    ap.add_argument("--max-pages", type=int, default=10)
    ap.add_argument("--limit", type=int, default=None, help="保存数上限")
    ap.add_argument("--sleep", type=float, default=1.0, help="リクエスト間隔(秒)")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--dry-run", action="store_true",
                    help="ファイル出力せず内容を表示")
    ap.add_argument("--overwrite", action="store_true",
                    help="既存 cardrush_*.json を上書き (default: skip)")
    args = ap.parse_args()

    cards = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
    valid_ids = {c["card_id"] for c in cards}
    print(f"cards.json から {len(valid_ids)} 個の card_id を読み込み")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"\n=== fetch list "
        f"scores={args.scores} format={args.format} "
        f"since={args.since} until={args.until} ==="
    )
    deck_list = list_decks(
        args.scores, args.format, args.since, args.until,
        args.max_pages, args.sleep,
    )
    print(f"\n{len(deck_list)} デッキ発見")

    if args.limit:
        deck_list = deck_list[: args.limit]
        print(f"  --limit により {len(deck_list)} 件に制限")

    written = 0
    skipped = 0
    failed = 0
    warnings_total: list[str] = []
    for i, d in enumerate(deck_list, 1):
        out_path = out_dir / f"cardrush_{d['id']}.json"
        if out_path.exists() and not args.overwrite:
            skipped += 1
            print(f"  [{i}/{len(deck_list)}] SKIP existing {out_path.name}")
            continue
        try:
            deck = fetch_deck_detail(d["id"])
        except Exception as e:
            failed += 1
            print(f"  [{i}/{len(deck_list)}] FAIL fetch {d['id']}: {e}")
            continue
        meta, warnings = deck_to_meta(deck, valid_ids)
        warnings_total.extend(warnings)
        msg = f"{meta['name']} ({meta['score']}, {meta['tournament_date']})"
        if args.dry_run:
            total_main = sum(e["count"] for e in meta["main"])
            print(f"  [{i}/{len(deck_list)}] DRY {meta['slug']} {msg} main={total_main}")
        else:
            out_path.write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"  [{i}/{len(deck_list)}] WROTE {out_path.name} {msg}")
            written += 1
        time.sleep(args.sleep)

    print("\n=== summary ===")
    print(f"  written: {written}")
    print(f"  skipped (existing): {skipped}")
    print(f"  failed: {failed}")
    print(f"  total discovered: {len(deck_list)}")
    if warnings_total:
        print(f"\n  unknown card_ids ({len(warnings_total)}):")
        for w in warnings_total[:20]:
            print(f"    - {w}")
        if len(warnings_total) > 20:
            print(f"    ... +{len(warnings_total) - 20} more")


if __name__ == "__main__":
    main()
