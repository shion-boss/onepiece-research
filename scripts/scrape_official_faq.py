# -*- coding: utf-8 -*-
"""
公式サイトの Q&A (よくある質問 + カードQ&A) を全件スクレイプして db/faq/ に保存。

対象:
1. FAQ (よくある質問): 4 カテゴリ
   - 基本ルール / キーワード効果 / キーワード / 詳細ルール
2. カードQ&A (cardqa): 弾別 index → 各弾ページの Q&A 全件

出力:
- db/faq/<category_slug>.json   : { category, source_url, fetched_at, items: [{q, a}] }
- db/faq/cardqa_<series_slug>.json : { series, series_id, source_url, fetched_at, items: [...] }
- db/faq/INDEX.md : 全件の summary (件数 + 直近の Q&A サンプル)

実行:
    .venv/bin/python scripts/scrape_official_faq.py
    .venv/bin/python scripts/scrape_official_faq.py --skip-cardqa  # FAQ のみ高速
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs, unquote

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "db" / "faq"

BASE = "https://www.onepiece-cardgame.com/rules/qa.php"
HEADERS = {"User-Agent": "Mozilla/5.0 (onepiece_research faq-scraper)"}
DELAY = 0.5  # サーバ配慮

FAQ_CATEGORIES = [
    ("base", "基本ルール"),
    ("keyword_effect", "キーワード効果"),
    ("keyword", "キーワード"),
    ("detail", "詳細ルール"),
]


def fetch(sess: requests.Session, url: str) -> str:
    r = sess.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def parse_qa_areas(html: str) -> list[dict]:
    """`<div class="qaArea">` から Q/A を抽出。"""
    soup = BeautifulSoup(html, "html.parser")
    items: list[dict] = []
    for area in soup.select("div.qaArea"):
        q = area.select_one("dl.questions dd")
        a = area.select_one("dl.answer dd")
        if q is None or a is None:
            continue
        items.append({
            "q": _clean_text(q),
            "a": _clean_text(a),
        })
    return items


def _clean_text(node) -> str:
    """改行を保ちつつ余計な空白を整理。"""
    # <br> を改行に変換
    for br in node.find_all("br"):
        br.replace_with("\n")
    text = node.get_text(separator="").strip()
    # 連続空白を1つに、行頭末尾の空白除去
    lines = [ln.strip() for ln in text.split("\n")]
    text = "\n".join(ln for ln in lines if ln)
    return text


def scrape_faq(sess: requests.Session) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for slug, jp in FAQ_CATEGORIES:
        url = f"{BASE}?{urlencode({'tab': 'faq', 'type': '0', 'maincat-faq': jp})}"
        html = fetch(sess, url)
        items = parse_qa_areas(html)
        out[slug] = {
            "category": jp,
            "category_slug": slug,
            "source_url": url,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "items": items,
        }
        print(f"  [FAQ] {slug:18} {jp:10} → {len(items)} 件")
        time.sleep(DELAY)
    return out


def scrape_cardqa(sess: requests.Session) -> dict[str, dict]:
    """cardqa index → 各弾ページの Q&A を取得。"""
    index_url = f"{BASE}?tab=cardqa"
    html = fetch(sess, index_url)
    soup = BeautifulSoup(html, "html.parser")

    # series link 抽出: "?tab=cardqa&type=1&series=..."
    series_links: list[tuple[str, str]] = []  # (jp_name, url)
    for a in soup.select("div.area.js-area_cardqa a[href*='tab=cardqa']"):
        href = a.get("href", "")
        if "series=" not in href:
            continue
        # series= の値をデコード
        qs = parse_qs(urlparse(href).query)
        series_jp = qs.get("series", [None])[0]
        if not series_jp:
            continue
        series_jp = unquote(series_jp)
        full_url = href if href.startswith("http") else f"https://www.onepiece-cardgame.com/rules/{href}" if href.startswith("?") else f"https://www.onepiece-cardgame.com{href}"
        # ?tab=... のような相対は補完
        if href.startswith("?"):
            full_url = f"{BASE}{href}"
        series_links.append((series_jp, full_url))

    # 重複除去 (同じ series が複数箇所にある可能性)
    seen = set()
    unique_series = []
    for jp, url in series_links:
        if jp in seen:
            continue
        seen.add(jp)
        unique_series.append((jp, url))

    print(f"  [cardqa] series 検出: {len(unique_series)}")

    out: dict[str, dict] = {}
    for jp, url in unique_series:
        # 弾コード抽出 (例: 【OP-15】、【ST-24】、【EB-04】、【PRB-02】)
        m = re.search(r"【([A-Z]+)-?(\d+)】", jp)
        if m:
            slug = f"{m.group(1).lower()}_{int(m.group(2)):02d}"
        else:
            slug = re.sub(r"[^a-z0-9_]", "", jp.lower().replace(" ", "_"))[:30]

        try:
            html = fetch(sess, url)
        except Exception as e:
            print(f"    [WARN] {jp}: {e}")
            continue
        items = parse_qa_areas(html)
        out[slug] = {
            "series": jp,
            "series_slug": slug,
            "source_url": url,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "items": items,
        }
        print(f"  [cardqa] {slug:14} {jp[:40]:40s}  → {len(items)} 件")
        time.sleep(DELAY)
    return out


def write_json(data: dict, path: Path) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_index(faq: dict, cardqa: dict) -> None:
    lines: list[str] = []
    lines.append("# Q&A データ INDEX")
    lines.append("")
    lines.append(f"取得日: {datetime.utcnow().isoformat()}Z")
    lines.append("")
    lines.append("## よくある質問 (FAQ)")
    lines.append("")
    lines.append("| カテゴリ | 件数 | ファイル |")
    lines.append("|---|---|---|")
    for slug, d in faq.items():
        lines.append(f"| {d['category']} | {len(d['items'])} | `db/faq/{slug}.json` |")
    lines.append("")
    lines.append("## カード Q&A (弾別)")
    lines.append("")
    lines.append("| 弾 | 件数 | ファイル |")
    lines.append("|---|---|---|")
    for slug, d in sorted(cardqa.items()):
        lines.append(f"| {d['series']} | {len(d['items'])} | `db/faq/cardqa_{slug}.json` |")
    lines.append("")
    lines.append("## 検索方法")
    lines.append("")
    lines.append("```bash")
    lines.append("# 全FAQから「トリガー」を含む Q を grep")
    lines.append("jq -r '.items[] | select(.q | contains(\"トリガー\")) | .q + \"\\n\" + .a' db/faq/*.json")
    lines.append("```")

    (OUT_DIR / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-cardqa", action="store_true", help="cardqa の取得をスキップ (FAQ のみ)")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sess = requests.Session()
    sess.headers.update(HEADERS)

    print("=== FAQ (よくある質問) ===")
    faq = scrape_faq(sess)
    for slug, d in faq.items():
        write_json(d, OUT_DIR / f"{slug}.json")

    cardqa: dict[str, dict] = {}
    if not args.skip_cardqa:
        print()
        print("=== cardqa (カード個別 Q&A) ===")
        cardqa = scrape_cardqa(sess)
        for slug, d in cardqa.items():
            write_json(d, OUT_DIR / f"cardqa_{slug}.json")

    write_index(faq, cardqa)

    total_faq = sum(len(d["items"]) for d in faq.values())
    total_cardqa = sum(len(d["items"]) for d in cardqa.values())
    print()
    print(f"完了: FAQ {total_faq} 件 / cardqa {total_cardqa} 件 → {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
