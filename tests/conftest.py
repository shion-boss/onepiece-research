# -*- coding: utf-8 -*-
"""pytest 共通設定: プロジェクトルートを sys.path に通す + 派生 DB の自動生成。"""

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_cards_sqlite() -> None:
    """db/cards.sqlite は cards.json 由来の派生物で gitignore 管理 (fresh clone には
    空ファイルしか無い)。 cards テーブルが未生成/空なら cards.json から再構築する。
    一部テスト (test_battle_ko_immune_by_attribute 等) が sqlite を直接参照するため、
    テスト収集前に一度だけ derive しておく (公式データ = cards.json を正とする再現)。"""
    db_path = ROOT / "db" / "cards.sqlite"
    cards_json = ROOT / "db" / "cards.json"
    if not cards_json.exists():
        return
    try:
        if db_path.exists() and db_path.stat().st_size > 0:
            conn = sqlite3.connect(db_path)
            try:
                n = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
                if n and n > 0:
                    return  # 既に populated
            except sqlite3.OperationalError:
                pass  # cards テーブル無し → 再構築へ
            finally:
                conn.close()
    except sqlite3.Error:
        pass

    # scraper と同じスキーマ・列で cards.json から再構築
    from scraper.scraper import SCHEMA

    cards = json.loads(cards_json.read_text(encoding="utf-8"))
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        series: dict[str, str] = {}
        for c in cards:
            sid = c.get("series_id")
            if sid:
                series[sid] = c.get("series_name") or ""
        for sid, nm in series.items():
            conn.execute(
                "INSERT OR REPLACE INTO series(series_id, name) VALUES(?, ?)",
                (sid, nm),
            )
        cols = [
            "card_id", "base_id", "variant", "series_id", "name", "rarity",
            "category", "cost", "life", "power", "counter", "attribute", "color",
            "block_icon", "features", "text", "trigger", "get_info", "image_url",
        ]
        placeholders = ",".join(["?"] * len(cols))
        for c in cards:
            conn.execute(
                f"INSERT OR REPLACE INTO cards({','.join(cols)}) VALUES({placeholders})",
                tuple(c.get(k) for k in cols),
            )
        conn.commit()
    finally:
        conn.close()


_ensure_cards_sqlite()
