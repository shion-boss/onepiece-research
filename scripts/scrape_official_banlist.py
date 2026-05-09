# -*- coding: utf-8 -*-
"""
公式の禁止・制限カード ページをスクレイプ。

対象:
- マスター頁: https://www.onepiece-cardgame.com/rules/restriction/
  (302 リダイレクト先に「施行済みの禁止・制限カード」セクションあり)
- 出力: db/banlist/master.json
  {
    fetched_at,
    source_url,
    forbidden:        [{"card_id": "OP06-047", "name": "..."}],
    restricted:       [{"card_id": "...", "name": "..."}],
    forbidden_pairs:  [{"a": {"card_id": "...", "name": "..."}, "b": {...}}],
    upcoming: {effective_date: "YYYY-MM-DD", ...}     # 「適用内容」セクションがあれば
  }

実行:
    .venv/bin/python scripts/scrape_official_banlist.py
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "db" / "banlist"
URL_MASTER = "https://www.onepiece-cardgame.com/rules/restriction/"
HEADERS = {"User-Agent": "Mozilla/5.0 (onepiece_research banlist-scraper)"}


def fetch(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
    r.raise_for_status()
    return r.text


CARD_LINK_RE = re.compile(r"freewords=([A-Z]{2,4}\d{2}-\d{3})")


def _extract_cards_from_ul(ul: Tag) -> list[dict]:
    """ul 内の <li><a href="...freewords=XXX">XXX 名前</a></li> から card_id + name を抽出。"""
    out: list[dict] = []
    for li in ul.find_all("li"):
        a = li.find("a")
        if a is None:
            continue
        m = CARD_LINK_RE.search(a.get("href", ""))
        if not m:
            continue
        cid = m.group(1)
        # テキストから "OP06-047 シャーロット・プリン" を分割
        text = a.get_text(strip=True)
        name = text.replace(cid, "").strip(" 　・|")
        out.append({"card_id": cid, "name": name})
    return out


def _next_uls_until_next_h(start: Tag) -> list[Tag]:
    """start から次の h3/h4 までの間にある ul をすべて返す。"""
    uls: list[Tag] = []
    sib = start.find_next()
    stop_tags = {"h3", "h4"}
    while sib is not None:
        if isinstance(sib, Tag):
            if sib.name in stop_tags:
                break
            if sib.name == "ul":
                uls.append(sib)
            # 子の中の ul も拾う
            for inner_ul in sib.find_all("ul"):
                if inner_ul not in uls:
                    uls.append(inner_ul)
        sib = sib.find_next_sibling() or sib.find_next()
        # 安全装置: h3/h4 までで止める (find_next で深く潜らないように)
        # 実装簡略化のため、後ろの全 sibling を見るアプローチに切替
        break
    return uls


def parse_master(html: str) -> dict:
    """マスターページの「施行済みの禁止・制限カード」セクションを抽出。"""
    soup = BeautifulSoup(html, "html.parser")

    # 該当 h3 を探す
    target_h3 = None
    for h3 in soup.find_all("h3"):
        if "施行済み" in h3.get_text():
            target_h3 = h3
            break
    if target_h3 is None:
        raise RuntimeError("「施行済みの禁止・制限カード」セクションが見つかりません")

    # h3 以降の要素を線形に走査し、h4 ごとにセクションを切る
    forbidden: list[dict] = []
    restricted: list[dict] = []
    forbidden_pairs: list[list[dict]] = []  # 各ペアは [a, b] の 2 要素

    current_section: str | None = None
    pair_buffer: list[dict] = []

    # 走査: h3 の親階層内をすべて走査
    # シンプルに、h3 以降に出現する全要素を順次見る
    for el in target_h3.find_all_next():
        if not isinstance(el, Tag):
            continue
        if el.name == "h3":
            # 別の h3 が来たら停止
            if el is not target_h3:
                break
        if el.name == "h4":
            label = el.get_text(strip=True)
            if "禁止カード" in label and "ペア" not in label:
                current_section = "forbidden"
            elif "制限カード" in label:
                current_section = "restricted"
            elif "禁止ペア" in label:
                current_section = "pair"
                # 新しいペアグループ開始
                if pair_buffer:
                    if len(pair_buffer) == 2:
                        forbidden_pairs.append(pair_buffer)
                    pair_buffer = []
            else:
                current_section = None
            continue

        if el.name == "ul" and current_section is not None:
            cards = _extract_cards_from_ul(el)
            if not cards:
                continue
            if current_section == "forbidden":
                for c in cards:
                    if c not in forbidden:
                        forbidden.append(c)
            elif current_section == "restricted":
                for c in cards:
                    if c not in restricted:
                        restricted.append(c)
            elif current_section == "pair":
                # 各 ul = 1 つの「対象カード」ブロック (A or B)。2 つ続いたら 1 ペア
                pair_buffer.extend(cards)
                while len(pair_buffer) >= 2:
                    pair = pair_buffer[:2]
                    pair_buffer = pair_buffer[2:]
                    if pair not in forbidden_pairs:
                        forbidden_pairs.append(pair)

    # 残った pair_buffer はフラッシュ (奇数なら捨てる)
    return {
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_url": URL_MASTER,
        "forbidden": forbidden,
        "restricted": restricted,
        "forbidden_pairs": [
            {"a": pair[0], "b": pair[1]} for pair in forbidden_pairs
        ],
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"取得元: {URL_MASTER}")
    html = fetch(URL_MASTER)
    data = parse_master(html)

    out_path = OUT_DIR / "master.json"
    out_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print()
    print(f"禁止カード:    {len(data['forbidden'])} 件")
    for c in data["forbidden"]:
        print(f"  - {c['card_id']} {c['name']}")
    print(f"制限カード:    {len(data['restricted'])} 件")
    for c in data["restricted"]:
        print(f"  - {c['card_id']} {c['name']}")
    print(f"禁止ペア:      {len(data['forbidden_pairs'])} 件")
    for p in data["forbidden_pairs"]:
        print(f"  - {p['a']['card_id']} {p['a']['name']}  ⇔  {p['b']['card_id']} {p['b']['name']}")
    print()
    print(f"→ {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
