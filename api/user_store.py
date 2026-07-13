# -*- coding: utf-8 -*-
"""マルチユーザー化 P2: ユーザーデッキの per-user 永続化レイヤ。

[[docs/multiuser_plan.md]]。 ストレージ方針は既存の spectate_comments と同じ:
  - DATABASE_URL env あり → Postgres (= 本番 Vercel/Neon)。
  - なし → SQLite ${DATA_DIR}/user_data.sqlite (= ローカル開発・テスト)。
両方とも同じ I/F。 schema は起動時に CREATE IF NOT EXISTS で冪等作成。

メタ(環境)デッキはここに入れない (= リポジトリ JSON のまま、 全ユーザー共通)。 ここは
**ユーザー作成デッキだけ** を owner_id で隔離して持つ。
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
_DATABASE_URL = os.environ.get("DATABASE_URL")
_USE_POSTGRES = bool(_DATABASE_URL)
_DATA_DIR = Path(os.environ.get("DATA_DIR", str(_ROOT / "db")))
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_USER_DB = _DATA_DIR / "user_data.sqlite"
_PH = "%s" if _USE_POSTGRES else "?"  # placeholder: psycopg=%s / sqlite=?

_SCHEMA_READY = False


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _conn():
    """sqlite3 or psycopg コネクション (両 driver 互換 I/F のみ使う)。"""
    if _USE_POSTGRES:
        import psycopg
        return psycopg.connect(_DATABASE_URL, row_factory=psycopg.rows.dict_row)
    conn = sqlite3.connect(str(_USER_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    ddl = [
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS user_decks (
            owner_id TEXT NOT NULL,
            slug TEXT NOT NULL,
            name TEXT,
            leader TEXT,
            main TEXT NOT NULL,
            regulation TEXT,
            visibility TEXT DEFAULT 'private',
            folder TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (owner_id, slug)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_user_decks_owner ON user_decks(owner_id)",
    ]
    conn = _conn()
    try:
        with conn:
            cur = conn.cursor()
            for stmt in ddl:
                cur.execute(stmt)
            # migration: 既存 DB に folder 列を追加 (無ければ)。 事前チェックで失敗文を
            # 出さない (= Postgres の transaction abort を避ける)。
            if not _column_exists(cur, "user_decks", "folder"):
                cur.execute("ALTER TABLE user_decks ADD COLUMN folder TEXT DEFAULT ''")
    finally:
        conn.close()
    _SCHEMA_READY = True


def _column_exists(cur, table: str, col: str) -> bool:
    if _USE_POSTGRES:
        cur.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
            (table, col),
        )
        return cur.fetchone() is not None
    cur.execute(f"PRAGMA table_info({table})")
    return any(r["name"] == col for r in cur.fetchall())


def ensure_user(user_id: str, email: Optional[str] = None) -> None:
    init_schema()
    conn = _conn()
    try:
        with conn:
            cur = conn.cursor()
            # idempotent upsert (= 両 driver 共通の "存在チェック→insert")
            cur.execute(f"SELECT 1 FROM users WHERE id = {_PH}", (user_id,))
            if cur.fetchone() is None:
                cur.execute(
                    f"INSERT INTO users (id, email, created_at) VALUES ({_PH}, {_PH}, {_PH})",
                    (user_id, email, _now()),
                )
    finally:
        conn.close()


def _row_to_deck(r) -> dict:
    d = dict(r)
    d["main"] = json.loads(d["main"]) if isinstance(d.get("main"), str) else d.get("main")
    return d


def get_deck(owner_id: str, slug: str) -> Optional[dict]:
    init_schema()
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT * FROM user_decks WHERE owner_id = {_PH} AND slug = {_PH}",
            (owner_id, slug),
        )
        r = cur.fetchone()
        return _row_to_deck(r) if r else None
    finally:
        conn.close()


def list_decks(owner_id: str) -> list[dict]:
    init_schema()
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT * FROM user_decks WHERE owner_id = {_PH} ORDER BY updated_at DESC",
            (owner_id,),
        )
        return [_row_to_deck(r) for r in cur.fetchall()]
    finally:
        conn.close()


def save_deck(
    owner_id: str, slug: str, *, name: str, leader: str, main: list,
    regulation: Optional[str] = None, overwrite: bool = False,
) -> None:
    """owner のデッキを保存。 既存 slug は overwrite=False で衝突 (= ValueError)。"""
    ensure_user(owner_id)
    main_json = json.dumps(main, ensure_ascii=False)
    now = _now()
    conn = _conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT created_at FROM user_decks WHERE owner_id = {_PH} AND slug = {_PH}",
                (owner_id, slug),
            )
            existing = cur.fetchone()
            if existing is not None and not overwrite:
                raise ValueError(f"slug already exists: {slug}")
            if existing is None:
                cur.execute(
                    f"INSERT INTO user_decks (owner_id, slug, name, leader, main, regulation, "
                    f"visibility, created_at, updated_at) VALUES "
                    f"({_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH}, 'private', {_PH}, {_PH})",
                    (owner_id, slug, name, leader, main_json, regulation, now, now),
                )
            else:
                cur.execute(
                    f"UPDATE user_decks SET name = {_PH}, leader = {_PH}, main = {_PH}, "
                    f"regulation = {_PH}, updated_at = {_PH} WHERE owner_id = {_PH} AND slug = {_PH}",
                    (name, leader, main_json, regulation, now, owner_id, slug),
                )
    finally:
        conn.close()


def delete_deck(owner_id: str, slug: str) -> bool:
    """owner のデッキを削除。 削除できたら True (= 存在し owner 一致)。"""
    init_schema()
    conn = _conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute(
                f"DELETE FROM user_decks WHERE owner_id = {_PH} AND slug = {_PH}",
                (owner_id, slug),
            )
            return cur.rowcount > 0
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# フォルダ管理 (= マイデッキを VSCode の explorer 風にフォルダで整理)。
# folder は単なるパス文字列 (例 "赤単" / "aggro/red"、 "" = ルート)。 フォルダ実体は
# デッキの folder 値から導出する (= 空フォルダは持たない、 別テーブル不要)。
# --------------------------------------------------------------------------- #
def set_deck_folder(owner_id: str, slug: str, folder: str) -> bool:
    """1 デッキの所属フォルダを設定。 存在し owner 一致なら True。"""
    init_schema()
    conn = _conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE user_decks SET folder = {_PH}, updated_at = {_PH} "
                f"WHERE owner_id = {_PH} AND slug = {_PH}",
                (folder or "", _now(), owner_id, slug),
            )
            return cur.rowcount > 0
    finally:
        conn.close()


def rename_folder(owner_id: str, old: str, new: str) -> int:
    """フォルダ名変更 (= folder == old の全デッキを new に)。 移動件数を返す。"""
    init_schema()
    conn = _conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE user_decks SET folder = {_PH}, updated_at = {_PH} "
                f"WHERE owner_id = {_PH} AND folder = {_PH}",
                (new or "", _now(), owner_id, old),
            )
            return cur.rowcount
    finally:
        conn.close()


def remove_folder(owner_id: str, folder: str) -> int:
    """フォルダを解体 (= 中のデッキをルートへ)。 デッキ自体は消さない。"""
    return rename_folder(owner_id, folder, "")
