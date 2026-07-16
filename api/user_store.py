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

import hashlib
import json
import os
import sqlite3
import uuid
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


def recipe_hash(leader: str, main: list) -> str:
    """レシピ指紋 (= leader + main の card_id/count 集合)。 名前/フォルダ変更では不変、
    採用カードが変わった時だけ変わる → 分析の再計算判定に使う。"""
    canon = json.dumps(
        {
            "leader": leader or "",
            "main": sorted((str(e.get("card_id")), int(e.get("count", 1))) for e in (main or [])),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()[:16]


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
        # 裏で回す分析ジョブのキュー (= 保存時に enqueue、 別プロセスのワーカーが処理)。
        # kind='analyze' (= AI vs AI 相性 + 役割等)。 将来 'train' (= per-deck GBM) を足せる。
        """
        CREATE TABLE IF NOT EXISTS deck_jobs (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            slug TEXT NOT NULL,
            recipe_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            priority INTEGER DEFAULT 0,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_deck_jobs_status ON deck_jobs(status, priority)",
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
            # migration: is_private (0=公開=陣取り可 / 1=非公開=陣取り不可)。 既定 0 なので
            # 既存デッキは公開扱いで grandfather (= 現状の陣取り使用可を維持)。 生成時に決定、
            # 以後不変 (save_deck の UPDATE は is_private を触らない)。
            if not _column_exists(cur, "user_decks", "is_private"):
                cur.execute("ALTER TABLE user_decks ADD COLUMN is_private INTEGER DEFAULT 0")
            # migration: is_draft (0=通常 / 1=下書き=未完成でも保存可・対戦選択肢に出さない)。
            # is_private と違い可変 (下書き→完成で 0 に、 保存ボタンで切替)。
            if not _column_exists(cur, "user_decks", "is_draft"):
                cur.execute("ALTER TABLE user_decks ADD COLUMN is_draft INTEGER DEFAULT 0")
            # migration: is_deleted (soft delete)。 公開デッキ削除は完全削除でなく非表示に
            # する (= 陣取り防衛に使われうるので row を残す)。 非公開は hard delete。
            if not _column_exists(cur, "user_decks", "is_deleted"):
                cur.execute("ALTER TABLE user_decks ADD COLUMN is_deleted INTEGER DEFAULT 0")
            # migration: 裏で回す分析 (= AI vs AI 相性・役割等) の永続用。
            # recipe_hash=今のレシピ指紋 / analyzed_hash=分析済みレシピ / analysis_json=結果 /
            # analysis_status=none|pending|running|done。 recipe_hash != analyzed_hash なら stale。
            for col, coltype in [
                ("recipe_hash", "TEXT"),
                ("analysis_json", "TEXT"),
                ("analyzed_hash", "TEXT"),
                ("analysis_status", "TEXT DEFAULT 'none'"),
            ]:
                if not _column_exists(cur, "user_decks", col):
                    cur.execute(f"ALTER TABLE user_decks ADD COLUMN {col} {coltype}")
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
    # is_private (0/1) → private (bool)。 非公開デッキは陣取りで使用不可。
    d["private"] = bool(d.get("is_private") or 0)
    # is_draft (0/1) → draft (bool)。 下書きは対戦選択肢に出さない。
    d["draft"] = bool(d.get("is_draft") or 0)
    # 分析ステータス (= none|pending|running|done)。 recipe_hash != analyzed_hash なら stale。
    d["analysis_status"] = d.get("analysis_status") or "none"
    d["analysis_stale"] = bool(d.get("recipe_hash") and d.get("recipe_hash") != d.get("analyzed_hash"))
    # 結果本体 (analysis_json) は重いので deck dict には含めない (= report は get_deck_report)。
    d.pop("analysis_json", None)
    return d


def get_deck(owner_id: str, slug: str) -> Optional[dict]:
    init_schema()
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT * FROM user_decks WHERE owner_id = {_PH} AND slug = {_PH} AND is_deleted = 0",
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
            f"SELECT * FROM user_decks WHERE owner_id = {_PH} AND is_deleted = 0 "
            f"ORDER BY updated_at DESC",
            (owner_id,),
        )
        return [_row_to_deck(r) for r in cur.fetchall()]
    finally:
        conn.close()


def save_deck(
    owner_id: str, slug: str, *, name: str, leader: str, main: list,
    regulation: Optional[str] = None, overwrite: bool = False, private: bool = False,
    draft: bool = False,
) -> None:
    """owner のデッキを保存。 既存 slug は overwrite=False で衝突 (= ValueError)。

    private (= 非公開 = 陣取りで使用不可) は **生成時 (INSERT) にのみ決定**。 overwrite の
    UPDATE では is_private を触らない = 以後変更不可 ([[project_leader_as_progression_unit]])。
    draft (= 下書き) は可変 (INSERT/UPDATE 両方で反映) = 下書き→完成で 0 に切替できる。
    既存が下書きなら overwrite=False でも上書き可 (= 完成保存で下書きを finalize する導線)。
    """
    ensure_user(owner_id)
    main_json = json.dumps(main, ensure_ascii=False)
    now = _now()
    rhash = recipe_hash(leader, main)
    should_analyze = False
    conn = _conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT is_draft, analyzed_hash FROM user_decks WHERE owner_id = {_PH} AND slug = {_PH}",
                (owner_id, slug),
            )
            existing = cur.fetchone()
            existing_is_draft = bool(existing["is_draft"]) if existing is not None else False
            if existing is not None and not overwrite and not existing_is_draft:
                raise ValueError(f"slug already exists: {slug}")
            # 完成保存 (= 非下書き) かつ「まだこのレシピを分析していない」なら分析対象。
            # 下書き保存では回さない (= 構築途中で溶かさない)。
            analyzed_hash = existing["analyzed_hash"] if existing is not None else None
            should_analyze = (not draft) and (rhash != analyzed_hash)
            new_status = "pending" if should_analyze else None
            if existing is None:
                cur.execute(
                    f"INSERT INTO user_decks (owner_id, slug, name, leader, main, regulation, "
                    f"visibility, is_private, is_draft, recipe_hash, analysis_status, "
                    f"created_at, updated_at) VALUES "
                    f"({_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH}, 'private', {_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH})",
                    (owner_id, slug, name, leader, main_json, regulation,
                     1 if private else 0, 1 if draft else 0, rhash,
                     new_status or "none", now, now),
                )
            elif should_analyze:
                cur.execute(
                    f"UPDATE user_decks SET name = {_PH}, leader = {_PH}, main = {_PH}, "
                    f"regulation = {_PH}, is_draft = {_PH}, recipe_hash = {_PH}, "
                    f"analysis_status = 'pending', updated_at = {_PH} "
                    f"WHERE owner_id = {_PH} AND slug = {_PH}",
                    (name, leader, main_json, regulation, 1 if draft else 0, rhash, now,
                     owner_id, slug),
                )
            else:
                cur.execute(
                    f"UPDATE user_decks SET name = {_PH}, leader = {_PH}, main = {_PH}, "
                    f"regulation = {_PH}, is_draft = {_PH}, recipe_hash = {_PH}, updated_at = {_PH} "
                    f"WHERE owner_id = {_PH} AND slug = {_PH}",
                    (name, leader, main_json, regulation, 1 if draft else 0, rhash, now,
                     owner_id, slug),
                )
    finally:
        conn.close()
    # 分析ジョブは commit 後に enqueue (= ワーカーが確実に見えるレコードを積む)。
    if should_analyze:
        enqueue_deck_job(owner_id, slug, rhash, kind="analyze")


def delete_deck(owner_id: str, slug: str) -> bool:
    """owner のデッキを完全削除 (hard delete)。 削除できたら True。 非公開デッキ用。"""
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


def soft_delete_deck(owner_id: str, slug: str) -> bool:
    """owner のデッキを非表示化 (soft delete = is_deleted=1)。 row は残す。 成功で True。

    公開デッキ用 (= 陣取り防衛に使われうるので完全削除しない、 マイデッキから除外だけ)。
    """
    init_schema()
    conn = _conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE user_decks SET is_deleted = 1, updated_at = {_PH} "
                f"WHERE owner_id = {_PH} AND slug = {_PH} AND is_deleted = 0",
                (_now(), owner_id, slug),
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


def set_deck_name(owner_id: str, slug: str, name: str) -> bool:
    """1 デッキの表示名を変更 (slug は不変)。 存在し owner 一致なら True。"""
    init_schema()
    conn = _conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE user_decks SET name = {_PH}, updated_at = {_PH} "
                f"WHERE owner_id = {_PH} AND slug = {_PH}",
                (name, _now(), owner_id, slug),
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


# --------------------------------------------------------------------------- #
# 分析ジョブ (= 保存時に enqueue → 別プロセスのワーカーが AI vs AI 等で分析 → 書き戻す)。
# Vercel サーバーレスは長時間計算不可なので inline 実行しない。 ワーカーは user_store を
# 直接 import して回す (scripts/deck_analysis_worker.py)。
# --------------------------------------------------------------------------- #
def enqueue_deck_job(owner_id: str, slug: str, rhash: str, *,
                     kind: str = "analyze", priority: int = 0) -> None:
    """分析ジョブを積む。 同 deck の古い pending は superseded 化 (= 最新レシピだけ処理)。
    同レシピの pending/running が既にあれば重複しない。"""
    init_schema()
    conn = _conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE deck_jobs SET status = 'superseded', updated_at = {_PH} "
                f"WHERE owner_id = {_PH} AND slug = {_PH} AND kind = {_PH} "
                f"AND status = 'pending' AND recipe_hash != {_PH}",
                (_now(), owner_id, slug, kind, rhash),
            )
            cur.execute(
                f"SELECT 1 FROM deck_jobs WHERE owner_id = {_PH} AND slug = {_PH} "
                f"AND kind = {_PH} AND recipe_hash = {_PH} AND status IN ('pending', 'running')",
                (owner_id, slug, kind, rhash),
            )
            if cur.fetchone() is not None:
                return
            jid = uuid.uuid4().hex[:16]
            cur.execute(
                f"INSERT INTO deck_jobs (id, kind, owner_id, slug, recipe_hash, status, "
                f"priority, created_at, updated_at) VALUES "
                f"({_PH}, {_PH}, {_PH}, {_PH}, {_PH}, 'pending', {_PH}, {_PH}, {_PH})",
                (jid, kind, owner_id, slug, rhash, priority, _now(), _now()),
            )
    finally:
        conn.close()


def claim_next_job(kind: str = "analyze") -> Optional[dict]:
    """ワーカー用: pending の先頭 (priority 降順→古い順) を running にして返す。 無ければ None。
    ⚠ 単一ワーカー前提の素朴 claim (= 複数ワーカーなら SELECT FOR UPDATE 等が要る)。"""
    init_schema()
    conn = _conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT * FROM deck_jobs WHERE kind = {_PH} AND status = 'pending' "
                f"ORDER BY priority DESC, created_at ASC LIMIT 1",
                (kind,),
            )
            r = cur.fetchone()
            if r is None:
                return None
            job = dict(r)
            cur.execute(
                f"UPDATE deck_jobs SET status = 'running', updated_at = {_PH} WHERE id = {_PH}",
                (_now(), job["id"]),
            )
            return job
    finally:
        conn.close()


def complete_deck_job(job_id: str, owner_id: str, slug: str, rhash: str, report: dict) -> None:
    """ワーカー用: 分析結果を書き戻し job を done に。 レシピが分析中に変わっていたら
    (= recipe_hash != rhash) デッキ側は更新しない (= 別の新ジョブが処理する)。"""
    init_schema()
    conn = _conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE deck_jobs SET status = 'done', updated_at = {_PH} WHERE id = {_PH}",
                (_now(), job_id),
            )
            cur.execute(
                f"UPDATE user_decks SET analysis_json = {_PH}, analyzed_hash = {_PH}, "
                f"analysis_status = 'done' "
                f"WHERE owner_id = {_PH} AND slug = {_PH} AND recipe_hash = {_PH}",
                (json.dumps(report, ensure_ascii=False), rhash, owner_id, slug, rhash),
            )
    finally:
        conn.close()


def fail_deck_job(job_id: str, error: str) -> None:
    """ワーカー用: job を failed に (= error 記録)。 デッキの analysis_status は none に戻す。"""
    init_schema()
    conn = _conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT owner_id, slug FROM deck_jobs WHERE id = {_PH}", (job_id,)
            )
            r = cur.fetchone()
            cur.execute(
                f"UPDATE deck_jobs SET status = 'failed', error = {_PH}, updated_at = {_PH} "
                f"WHERE id = {_PH}",
                (str(error)[:2000], _now(), job_id),
            )
            if r is not None:
                cur.execute(
                    f"UPDATE user_decks SET analysis_status = 'none' "
                    f"WHERE owner_id = {_PH} AND slug = {_PH} AND analysis_status IN ('pending', 'running')",
                    (r["owner_id"], r["slug"]),
                )
    finally:
        conn.close()


def request_analysis(owner_id: str, slug: str) -> bool:
    """手動で分析を要求 (= 再分析 / 既存デッキの初回分析)。 pending にして enqueue。
    デッキが無い / 下書きなら False。"""
    d = get_deck(owner_id, slug)
    if d is None or d.get("draft"):
        return False
    rhash = recipe_hash(d.get("leader", ""), d.get("main", []))
    conn = _conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE user_decks SET recipe_hash = {_PH}, analysis_status = 'pending' "
                f"WHERE owner_id = {_PH} AND slug = {_PH}",
                (rhash, owner_id, slug),
            )
    finally:
        conn.close()
    enqueue_deck_job(owner_id, slug, rhash, kind="analyze")
    return True


def get_deck_report(owner_id: str, slug: str) -> Optional[dict]:
    """デッキの分析レポート (= 裏で計算した AI vs AI 相性・役割等) と status を返す。
    デッキが無ければ None。 report は未計算なら None。"""
    init_schema()
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT analysis_json, analysis_status, analyzed_hash, recipe_hash "
            f"FROM user_decks WHERE owner_id = {_PH} AND slug = {_PH} AND is_deleted = 0",
            (owner_id, slug),
        )
        r = cur.fetchone()
        if r is None:
            return None
        d = dict(r)
        report = json.loads(d["analysis_json"]) if d.get("analysis_json") else None
        stale = bool(d.get("recipe_hash") and d.get("recipe_hash") != d.get("analyzed_hash"))
        return {
            "status": d.get("analysis_status") or "none",
            "stale": stale,
            "report": report,
        }
    finally:
        conn.close()
