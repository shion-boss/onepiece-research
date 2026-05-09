# -*- coding: utf-8 -*-
"""
ONE PIECE Card Game - 公式カードリスト スクレイパー
==================================================

公式サイト( https://www.onepiece-cardgame.com/cardlist/ )から
全弾のカード情報を取得し、JSON/SQLite に保存するスクレイパー。

使い方:
    python scraper.py --all               # 全弾取得
    python scraper.py --series 550115     # 特定の弾だけ取得 (OP-15)
    python scraper.py --list-series       # 利用可能な弾のIDを一覧

出力:
    db/cards.json        - 全カード情報(人間が読める形式)
    db/cards.sqlite      - 構造化DB(後段の分析・対戦シミュレータ用)
    images/<card_id>.png - カード画像 (--with-images 指定時)

公式サイトに優しいクロールにするため、リクエスト間に 1.0s の sleep を入れている。
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass
from html import unescape
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.onepiece-cardgame.com/cardlist/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
REQUEST_DELAY_SEC = 0.4  # 連続リクエスト間の待機

ROOT = Path(__file__).resolve().parent.parent  # outputs/onepiece_research/
DB_DIR = ROOT / "db"
IMG_DIR = ROOT / "images"
CACHE_DIR = Path("/tmp/onepiece_html")  # /tmp は SQLite I/O 制約のないネイティブ FS
DB_DIR.mkdir(exist_ok=True, parents=True)
IMG_DIR.mkdir(exist_ok=True, parents=True)
CACHE_DIR.mkdir(exist_ok=True, parents=True)


# --------------------------------------------------------------------------- #
# データモデル
# --------------------------------------------------------------------------- #
@dataclass
class Card:
    """1 枚のカード(パラレル違いは別レコード)"""

    card_id: str
    base_id: str
    variant: str
    series_id: str
    series_name: str
    name: str
    rarity: str
    category: str
    cost: str | None = None
    life: str | None = None
    power: str | None = None
    counter: str | None = None
    attribute: str | None = None
    color: str | None = None
    block_icon: str | None = None
    features: str | None = None
    text: str | None = None
    trigger: str | None = None
    get_info: str | None = None
    image_url: str | None = None


@dataclass
class Series:
    series_id: str
    name: str
    raw_label: str


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def fetch_page(
    session: requests.Session,
    series_id: str | None = None,
    use_cache: bool = True,
) -> str:
    """指定弾の HTML を取得。キャッシュ済みならネットに行かない。"""
    cache_path = CACHE_DIR / (f"{series_id}.html" if series_id else "_top.html")
    if use_cache and cache_path.exists() and cache_path.stat().st_size > 1000:
        return cache_path.read_text(encoding="utf-8")

    params = {"series": series_id} if series_id else {}
    resp = session.get(BASE_URL, params=params, timeout=30, allow_redirects=True)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    cache_path.write_text(resp.text, encoding="utf-8")
    return resp.text


# --------------------------------------------------------------------------- #
# パース
# --------------------------------------------------------------------------- #
_SERIES_OPTION_RE = re.compile(
    r'<option value="(?P<id>\d+)"\s*(?:selected)?\s*>(?P<label>.*?)</option>',
    re.DOTALL,
)


def parse_series_list(html: str) -> list[Series]:
    out: list[Series] = []
    for m in _SERIES_OPTION_RE.finditer(html):
        sid = m.group("id")
        raw = m.group("label")
        clean = re.sub(r"<[^>]+>", " ", unescape(raw))
        clean = re.sub(r"\s+", " ", clean).strip()
        out.append(Series(series_id=sid, name=clean, raw_label=raw))
    seen: set[str] = set()
    deduped: list[Series] = []
    for s in out:
        if s.series_id in seen:
            continue
        seen.add(s.series_id)
        deduped.append(s)
    return deduped


def _text(node) -> str:
    if node is None:
        return ""
    for br in node.find_all("br"):
        br.replace_with("\n")
    return re.sub(r"[ \t]+", " ", node.get_text("", strip=True)).strip()


_HEAD_WORDS = (
    "ライフ", "コスト", "属性", "パワー", "カウンター", "色",
    "ブロックアイコン", "ブロック\nアイコン", "特徴", "テキスト",
    "入手情報", "トリガー",
)


def _strip_h3(text: str) -> str:
    for head in _HEAD_WORDS:
        if text.startswith(head):
            return text[len(head):].strip()
    return text.strip()


_SERIES_PREFIX_RE = re.compile(r"^(OP|EB|PRB|ST)(\d+)-")


def _guess_series_id(base_id: str) -> str:
    m = _SERIES_PREFIX_RE.match(base_id)
    if not m:
        return ""
    prefix, num = m.group(1), m.group(2)
    table = {"ST": "5500", "OP": "5501", "EB": "5502", "PRB": "5503"}
    base = table.get(prefix)
    if base is None:
        return ""
    return f"{base}{int(num):02d}"


def parse_cards(html: str, series_lookup: dict[str, str]) -> list[Card]:
    soup = BeautifulSoup(html, "html.parser")
    cards: list[Card] = []

    for dl in soup.select("dl.modalCol"):
        card_id = (dl.get("id") or "").strip()
        if not card_id:
            continue

        if "_" in card_id:
            base_id, variant = card_id.split("_", 1)
            variant = "_" + variant
        else:
            base_id, variant = card_id, ""

        info_spans = dl.select(".infoCol span")
        rarity = info_spans[1].get_text(strip=True) if len(info_spans) >= 2 else ""
        category = info_spans[2].get_text(strip=True) if len(info_spans) >= 3 else ""

        name_node = dl.select_one(".cardName")
        name_text = name_node.get_text(strip=True) if name_node else ""

        # 画像
        img = dl.select_one(".frontCol img")
        image_url: str | None = None
        if img is not None:
            ds = img.get("data-src") or img.get("src") or ""
            if ds and "dummy" not in ds:
                image_url = urljoin(BASE_URL, ds.split("?")[0])

        def cell_text(selector: str) -> str | None:
            n = dl.select_one(selector)
            if n is None:
                return None
            return _strip_h3(_text(n)) or None

        attribute_node = dl.select_one(".attribute img")
        attribute = (
            attribute_node.get("alt", "").strip() if attribute_node is not None else None
        )

        # コスト/ライフはセル名が同じなので h3 ラベルで判別
        cost_val: str | None = None
        life_val: str | None = None
        cost_node = dl.select_one(".cost")
        if cost_node is not None:
            head = _text(cost_node).split("\n", 1)[0]
            value = _strip_h3(_text(cost_node)) or None
            if head.startswith("ライフ"):
                life_val = value
            else:
                cost_val = value

        power = cell_text(".power")
        counter = cell_text(".counter")
        color = cell_text(".color")
        block_icon = cell_text(".block")
        features = cell_text(".feature")
        text = cell_text(".text")
        trigger = cell_text(".trigger")
        get_info = cell_text(".getInfo")

        series_id_guess = _guess_series_id(base_id)
        series_name = series_lookup.get(series_id_guess, "")

        cards.append(
            Card(
                card_id=card_id,
                base_id=base_id,
                variant=variant,
                series_id=series_id_guess,
                series_name=series_name,
                name=name_text,
                rarity=rarity,
                category=category,
                cost=cost_val,
                life=life_val,
                power=power,
                counter=counter,
                attribute=attribute,
                color=color,
                block_icon=block_icon,
                features=features,
                text=text,
                trigger=trigger,
                get_info=get_info,
                image_url=image_url,
            )
        )

    return cards


# --------------------------------------------------------------------------- #
# 永続化
# --------------------------------------------------------------------------- #
SCHEMA = """
CREATE TABLE IF NOT EXISTS series (
    series_id TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cards (
    card_id TEXT PRIMARY KEY,
    base_id TEXT NOT NULL,
    variant TEXT NOT NULL DEFAULT '',
    series_id TEXT,
    name TEXT NOT NULL,
    rarity TEXT,
    category TEXT,
    cost TEXT,
    life TEXT,
    power TEXT,
    counter TEXT,
    attribute TEXT,
    color TEXT,
    block_icon TEXT,
    features TEXT,
    text TEXT,
    trigger TEXT,
    get_info TEXT,
    image_url TEXT,
    FOREIGN KEY (series_id) REFERENCES series(series_id)
);

CREATE INDEX IF NOT EXISTS idx_cards_base ON cards(base_id);
CREATE INDEX IF NOT EXISTS idx_cards_series ON cards(series_id);
CREATE INDEX IF NOT EXISTS idx_cards_color ON cards(color);
CREATE INDEX IF NOT EXISTS idx_cards_category ON cards(category);
"""


def open_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    # マウント FS では WAL の補助ファイルが作れない場合があるので無効化
    conn.execute("PRAGMA journal_mode=MEMORY")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def upsert_cards(conn: sqlite3.Connection, cards: Iterable[Card], series: Iterable[Series]) -> None:
    cur = conn.cursor()
    for s in series:
        cur.execute(
            "INSERT OR REPLACE INTO series(series_id, name) VALUES (?, ?)",
            (s.series_id, s.name),
        )
    for c in cards:
        cur.execute(
            """
            INSERT OR REPLACE INTO cards(
                card_id, base_id, variant, series_id, name, rarity, category,
                cost, life, power, counter, attribute, color, block_icon,
                features, text, trigger, get_info, image_url
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                c.card_id, c.base_id, c.variant, c.series_id, c.name, c.rarity,
                c.category, c.cost, c.life, c.power, c.counter, c.attribute,
                c.color, c.block_icon, c.features, c.text, c.trigger,
                c.get_info, c.image_url,
            ),
        )
    conn.commit()


# --------------------------------------------------------------------------- #
# 画像ダウンロード
# --------------------------------------------------------------------------- #
def download_images(session: requests.Session, cards: Iterable[Card]) -> None:
    for c in cards:
        if not c.image_url:
            continue
        out = IMG_DIR / f"{c.card_id}.png"
        if out.exists():
            continue
        try:
            r = session.get(c.image_url, timeout=30)
            r.raise_for_status()
            out.write_bytes(r.content)
            print(f"  画像取得: {c.card_id}")
        except Exception as e:
            print(f"  [WARN] 画像失敗 {c.card_id}: {e}", file=sys.stderr)
        time.sleep(REQUEST_DELAY_SEC)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def cmd_list_series() -> None:
    sess = _session()
    html = fetch_page(sess)
    serieses = parse_series_list(html)
    print(f"利用可能な弾: {len(serieses)} 件")
    for s in serieses:
        print(f"  {s.series_id}  {s.name}")


def cmd_scrape(target_series: list[str] | None, with_images: bool) -> None:
    sess = _session()

    print("[1/3] 弾一覧を取得 ...")
    html_top = fetch_page(sess)
    serieses = parse_series_list(html_top)
    series_lookup = {s.series_id: s.name for s in serieses}
    print(f"      -> {len(serieses)} 件")

    if target_series:
        target = [s for s in serieses if s.series_id in target_series]
    else:
        target = serieses
    print(f"[2/3] {len(target)} 弾を取得 ...")

    all_cards: list[Card] = []
    for i, s in enumerate(target, start=1):
        cache_path = CACHE_DIR / f"{s.series_id}.html"
        cached = cache_path.exists() and cache_path.stat().st_size > 1000
        tag = "(cache)" if cached else "(net)"
        print(f"  ({i}/{len(target)}) {s.series_id} {tag} {s.name}")
        html = fetch_page(sess, s.series_id)
        cards = parse_cards(html, series_lookup)
        for c in cards:
            if not c.series_id:
                c.series_id = s.series_id
                c.series_name = s.name
        all_cards.extend(cards)
        if not cached:
            time.sleep(REQUEST_DELAY_SEC)

    by_id: dict[str, Card] = {}
    for c in all_cards:
        by_id[c.card_id] = c
    deduped = list(by_id.values())
    print(f"      -> 取得カード合計 {len(deduped)} 種(重複除去後)")

    print("[3/3] DB / JSON 保存 ...")
    json_path = DB_DIR / "cards.json"
    json_path.write_text(
        json.dumps([asdict(c) for c in deduped], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    sqlite_path = DB_DIR / "cards.sqlite"
    # マウント FS で SQLite が直接書き込めない/削除できないことがあるので、
    # 一旦 /tmp に作って中身を bytes で書き戻す。
    import os, tempfile

    tmp_dir = Path(tempfile.mkdtemp(prefix="opcg_"))
    tmp_sqlite = tmp_dir / "cards.sqlite"
    try:
        conn = open_db(tmp_sqlite)
        upsert_cards(conn, deduped, serieses)
        conn.close()
        data = tmp_sqlite.read_bytes()
        sqlite_path.write_bytes(data)
        print(f"      ({len(data):,} bytes written)")
    finally:
        for p in tmp_dir.iterdir():
            try:
                p.unlink()
            except OSError:
                pass
        try:
            tmp_dir.rmdir()
        except OSError:
            pass

    print(f"  -> {json_path}")
    print(f"  -> {sqlite_path}")

    if with_images:
        print("[4/4] 画像ダウンロード ...")
        download_images(sess, deduped)
        print(f"  -> {IMG_DIR}")


def main() -> int:
    p = argparse.ArgumentParser(
        description="ONE PIECE Card Game cardlist scraper"
    )
    p.add_argument("--all", action="store_true", help="all sets (default)")
    p.add_argument("--series", action="append", help="series_id filter (repeatable)")
    p.add_argument("--with-images", action="store_true", help="also download card images")
    p.add_argument("--list-series", action="store_true", help="list series and exit")
    args = p.parse_args()

    if args.list_series:
        cmd_list_series()
        return 0

    cmd_scrape(args.series, args.with_images)
    return 0


if __name__ == "__main__":
    sys.exit(main())
