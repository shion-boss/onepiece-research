# -*- coding: utf-8 -*-
"""
研究セッション SQLite 永続化層 (Phase R)
=========================================

db/research_sessions.sqlite に sessions / candidates テーブルを管理。
threading.Lock で排他制御 (= replay_recorder.py パターン)。

公開 API:
- init_db(path=None)
- create_session(config) -> session_id
- update_session_status(session_id, status, ...)
- update_session_best(session_id, winrate, deck_dict)
- insert_candidate(session_id, generation, ...)
- get_session(session_id) -> dict
- list_sessions(limit=20) -> list[dict]
- get_candidates(session_id, generation=None) -> list[dict]
- get_generation_history(session_id) -> list[dict]
- get_best_candidate(session_id) -> dict
- delete_session(session_id) — テスト/クリーンアップ用
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


_DB_LOCK = threading.Lock()
_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "db" / "research_sessions.sqlite"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    target_slug TEXT NOT NULL,
    config_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    current_generation INTEGER DEFAULT 0,
    best_winrate REAL,
    best_deck_json TEXT,
    completion_reason TEXT
);

CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    generation INTEGER NOT NULL,
    candidate_idx INTEGER NOT NULL,
    deck_json TEXT NOT NULL,
    parent_id INTEGER,
    mutation_type TEXT,
    winrate REAL,
    n_games INTEGER,
    evaluated_at TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_session_gen ON candidates(session_id, generation);
CREATE INDEX IF NOT EXISTS idx_session_winrate ON candidates(session_id, winrate);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect(path: Path | str) -> sqlite3.Connection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init_db(path: Path | str | None = None) -> None:
    p = Path(path) if path else _DEFAULT_PATH
    with _DB_LOCK:
        con = _connect(p)
        try:
            con.executescript(_SCHEMA)
            con.commit()
        finally:
            con.close()


def _ensure_db():
    """Initialize DB on first use."""
    if not _DEFAULT_PATH.exists():
        init_db()


# ============================================================================ #
# Session CRUD
# ============================================================================ #

def create_session(
    target_slug: str,
    config: dict,
    *,
    path: Path | str | None = None,
) -> str:
    """新規セッション作成。 session_id (uuid hex) を返す。"""
    if path is None:
        _ensure_db()
        p = _DEFAULT_PATH
    else:
        p = Path(path)
    session_id = uuid.uuid4().hex[:16]
    now = _now()
    with _DB_LOCK:
        con = _connect(p)
        try:
            con.execute(
                """INSERT INTO sessions
                (id, target_slug, config_json, status, created_at, updated_at, current_generation)
                VALUES (?, ?, ?, ?, ?, ?, 0)""",
                (session_id, target_slug, json.dumps(config, ensure_ascii=False),
                 "running", now, now),
            )
            con.commit()
        finally:
            con.close()
    return session_id


def update_session_status(
    session_id: str,
    status: str,
    *,
    completion_reason: Optional[str] = None,
    path: Path | str | None = None,
) -> None:
    """status を更新 (running/paused/completed/stopped)。"""
    p = Path(path) if path else _DEFAULT_PATH
    now = _now()
    with _DB_LOCK:
        con = _connect(p)
        try:
            if completion_reason is not None:
                con.execute(
                    "UPDATE sessions SET status=?, updated_at=?, completion_reason=? WHERE id=?",
                    (status, now, completion_reason, session_id),
                )
            else:
                con.execute(
                    "UPDATE sessions SET status=?, updated_at=? WHERE id=?",
                    (status, now, session_id),
                )
            con.commit()
        finally:
            con.close()


def update_session_progress(
    session_id: str,
    generation: int,
    best_winrate: Optional[float],
    best_deck: Optional[dict],
    *,
    path: Path | str | None = None,
) -> None:
    """world 進捗 (= current_generation, best_winrate, best_deck) を更新。"""
    p = Path(path) if path else _DEFAULT_PATH
    now = _now()
    deck_json = json.dumps(best_deck, ensure_ascii=False) if best_deck else None
    with _DB_LOCK:
        con = _connect(p)
        try:
            con.execute(
                """UPDATE sessions
                SET current_generation=?, best_winrate=?, best_deck_json=?, updated_at=?
                WHERE id=?""",
                (generation, best_winrate, deck_json, now, session_id),
            )
            con.commit()
        finally:
            con.close()


def get_session(session_id: str, *, path: Path | str | None = None) -> Optional[dict]:
    p = Path(path) if path else _DEFAULT_PATH
    if not p.exists():
        return None
    with _DB_LOCK:
        con = _connect(p)
        try:
            row = con.execute(
                "SELECT * FROM sessions WHERE id=?", (session_id,)
            ).fetchone()
            if row is None:
                return None
            d = dict(row)
            d["config"] = json.loads(d.pop("config_json"))
            d["best_deck"] = json.loads(d.pop("best_deck_json")) if d.get("best_deck_json") else None
            return d
        finally:
            con.close()


def list_sessions(
    *, limit: int = 20, status: Optional[str] = None,
    path: Path | str | None = None,
) -> list[dict]:
    p = Path(path) if path else _DEFAULT_PATH
    if not p.exists():
        return []
    with _DB_LOCK:
        con = _connect(p)
        try:
            if status:
                rows = con.execute(
                    """SELECT id, target_slug, status, created_at, updated_at,
                       current_generation, best_winrate, completion_reason
                       FROM sessions WHERE status=? ORDER BY updated_at DESC LIMIT ?""",
                    (status, limit),
                ).fetchall()
            else:
                rows = con.execute(
                    """SELECT id, target_slug, status, created_at, updated_at,
                       current_generation, best_winrate, completion_reason
                       FROM sessions ORDER BY updated_at DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()


def delete_session(session_id: str, *, path: Path | str | None = None) -> None:
    p = Path(path) if path else _DEFAULT_PATH
    with _DB_LOCK:
        con = _connect(p)
        try:
            con.execute("DELETE FROM candidates WHERE session_id=?", (session_id,))
            con.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            con.commit()
        finally:
            con.close()


# ============================================================================ #
# Candidate CRUD
# ============================================================================ #

def insert_candidate(
    session_id: str,
    generation: int,
    candidate_idx: int,
    deck_dict: dict,
    *,
    parent_id: Optional[int] = None,
    mutation_type: str = "initial",
    winrate: Optional[float] = None,
    n_games: Optional[int] = None,
    path: Path | str | None = None,
) -> int:
    """新規 candidate を insert。 id を返す。"""
    p = Path(path) if path else _DEFAULT_PATH
    now = _now() if winrate is not None else None
    deck_json = json.dumps(deck_dict, ensure_ascii=False)
    with _DB_LOCK:
        con = _connect(p)
        try:
            cur = con.execute(
                """INSERT INTO candidates
                (session_id, generation, candidate_idx, deck_json, parent_id,
                 mutation_type, winrate, n_games, evaluated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, generation, candidate_idx, deck_json,
                 parent_id, mutation_type, winrate, n_games, now),
            )
            con.commit()
            return cur.lastrowid
        finally:
            con.close()


def update_candidate_evaluation(
    candidate_id: int,
    winrate: float,
    n_games: int,
    *,
    path: Path | str | None = None,
) -> None:
    p = Path(path) if path else _DEFAULT_PATH
    now = _now()
    with _DB_LOCK:
        con = _connect(p)
        try:
            con.execute(
                "UPDATE candidates SET winrate=?, n_games=?, evaluated_at=? WHERE id=?",
                (winrate, n_games, now, candidate_id),
            )
            con.commit()
        finally:
            con.close()


def get_candidates(
    session_id: str,
    *,
    generation: Optional[int] = None,
    only_evaluated: bool = False,
    limit: Optional[int] = None,
    path: Path | str | None = None,
) -> list[dict]:
    p = Path(path) if path else _DEFAULT_PATH
    if not p.exists():
        return []
    with _DB_LOCK:
        con = _connect(p)
        try:
            sql = "SELECT * FROM candidates WHERE session_id=?"
            params: list[Any] = [session_id]
            if generation is not None:
                sql += " AND generation=?"
                params.append(generation)
            if only_evaluated:
                sql += " AND winrate IS NOT NULL"
            sql += " ORDER BY winrate DESC NULLS LAST, generation, candidate_idx"
            if limit:
                sql += " LIMIT ?"
                params.append(limit)
            rows = con.execute(sql, params).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["deck"] = json.loads(d.pop("deck_json"))
                out.append(d)
            return out
        finally:
            con.close()


def get_best_candidate(
    session_id: str, *, path: Path | str | None = None,
) -> Optional[dict]:
    """全 generation を通じて winrate 最大の candidate を返す。"""
    cands = get_candidates(session_id, only_evaluated=True, limit=1, path=path)
    return cands[0] if cands else None


def get_generation_history(
    session_id: str, *, path: Path | str | None = None,
) -> list[dict]:
    """世代別サマリ ([{gen, n_candidates, best_winrate, avg_winrate}, ...])。"""
    p = Path(path) if path else _DEFAULT_PATH
    if not p.exists():
        return []
    with _DB_LOCK:
        con = _connect(p)
        try:
            rows = con.execute(
                """SELECT generation,
                          COUNT(*) AS n_candidates,
                          MAX(winrate) AS best_winrate,
                          AVG(winrate) AS avg_winrate
                   FROM candidates
                   WHERE session_id=? AND winrate IS NOT NULL
                   GROUP BY generation
                   ORDER BY generation""",
                (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()


def get_top_candidates_in_generation(
    session_id: str, generation: int, top_k: int = 5,
    *, path: Path | str | None = None,
) -> list[dict]:
    return get_candidates(
        session_id,
        generation=generation,
        only_evaluated=True,
        limit=top_k,
        path=path,
    )
