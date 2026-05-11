# -*- coding: utf-8 -*-
"""
試合 replay 永続化 (SQLite)
============================

`run_matchup` の各試合を `db/match_replays.sqlite` 1 ファイルに集約保存し、
後から `loss_classifier` や `scripts/learn_ai_params.py` で再分析する。

設計判断:
- gzip ファイル群 (旧設計、 10 万ファイル規模) は inode を浪費しスキャンが遅い
  ので、 SQLite + BLOB (gzip 圧縮 payload) に集約
- 1 行 = 1 試合 = meta フィールド + payload BLOB
- LRU はペアごとに最新 max_per_pair 件を保持し、 古い行を DELETE
- インデックス: (deck_a, deck_b), (deck_a, winner_for_deck_a) で集計クエリ高速化

公開 API:
- `save_replay(...) -> int`               # 戻り値 = row id
- `load_replay(replay_id: int) -> dict`   # {"meta": {...}, "log": [...], "snapshots": [...]}
- `list_replays(...) -> list[int]`         # row id リスト
- `count_replays(...) -> int`             # 高速カウント
"""

from __future__ import annotations

import gzip
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional


DB_PATH = Path(__file__).resolve().parent.parent / "db" / "match_replays.sqlite"
DEFAULT_MAX_PER_PAIR = 500
_DB_LOCK = threading.Lock()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS replays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deck_a TEXT NOT NULL,
    deck_b TEXT NOT NULL,
    game_idx INTEGER,
    winner_for_deck_a INTEGER,   -- 0 = deck_a 勝, 1 = deck_b 勝, -1 = 引き分け
    first_player INTEGER,
    turns INTEGER,
    seed INTEGER,
    saved_at TEXT,
    extra_meta TEXT,              -- JSON テキスト
    payload BLOB                  -- gzip 圧縮された JSON ({"log": [...], "snapshots": [...]})
);
CREATE INDEX IF NOT EXISTS idx_pair ON replays(deck_a, deck_b);
CREATE INDEX IF NOT EXISTS idx_loser_a ON replays(deck_a, winner_for_deck_a);
CREATE INDEX IF NOT EXISTS idx_loser_b ON replays(deck_b, winner_for_deck_a);
"""


def _connect(path: Optional[Path] = None) -> sqlite3.Connection:
    """SQLite 接続。 初回呼び出しでスキーマを作成。"""
    p = path or DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.executescript(_SCHEMA)
    return conn


def save_replay(
    deck_a: str,
    deck_b: str,
    game_idx: int,
    winner_for_deck_a: int,
    first_player: int,
    turns: int,
    log: list[str],
    snapshots: list[dict],
    seed: int,
    extra_meta: Optional[dict] = None,
    db_path: Optional[Path] = None,
    max_per_pair: int = DEFAULT_MAX_PER_PAIR,
) -> int:
    """1 試合の replay を保存し、 ペアあたり max_per_pair を超えたら古い行を削除。

    Returns: 挿入された row id。
    """
    payload_json = json.dumps({"log": log, "snapshots": snapshots}, ensure_ascii=False)
    payload_gz = gzip.compress(payload_json.encode("utf-8"))
    saved_at = datetime.utcnow().isoformat() + "Z"
    extra_json = json.dumps(extra_meta or {}, ensure_ascii=False)

    with _DB_LOCK:
        conn = _connect(db_path)
        try:
            cur = conn.execute(
                """
                INSERT INTO replays (
                    deck_a, deck_b, game_idx, winner_for_deck_a, first_player,
                    turns, seed, saved_at, extra_meta, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    deck_a, deck_b, game_idx, winner_for_deck_a, first_player,
                    turns, seed, saved_at, extra_json, payload_gz,
                ),
            )
            row_id = cur.lastrowid
            # LRU prune: このペアの行数が上限超なら最古を削除
            _prune_pair(conn, deck_a, deck_b, max_per_pair)
            conn.commit()
            return row_id
        finally:
            conn.close()


def _prune_pair(conn: sqlite3.Connection, deck_a: str, deck_b: str, keep: int) -> None:
    """指定ペアの行数が keep を超えていれば、 古いものから削除。"""
    cur = conn.execute(
        "SELECT COUNT(*) FROM replays WHERE deck_a=? AND deck_b=?",
        (deck_a, deck_b),
    )
    count = cur.fetchone()[0]
    if count <= keep:
        return
    excess = count - keep
    conn.execute(
        """
        DELETE FROM replays
        WHERE id IN (
            SELECT id FROM replays
            WHERE deck_a=? AND deck_b=?
            ORDER BY id ASC
            LIMIT ?
        )
        """,
        (deck_a, deck_b, excess),
    )


def load_replay(replay_id: int, db_path: Optional[Path] = None) -> dict:
    """row id から 1 試合の replay を読み込み。

    返り値: {"meta": {...}, "log": [...], "snapshots": [...]}
    """
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            """
            SELECT deck_a, deck_b, game_idx, winner_for_deck_a, first_player,
                   turns, seed, saved_at, extra_meta, payload
            FROM replays WHERE id = ?
            """,
            (replay_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"replay id={replay_id} not found")
        (deck_a, deck_b, game_idx, winner_for_deck_a, first_player,
         turns, seed, saved_at, extra_meta_json, payload_gz) = row
        payload = json.loads(gzip.decompress(payload_gz).decode("utf-8"))
        try:
            extra = json.loads(extra_meta_json) if extra_meta_json else {}
        except Exception:
            extra = {}
        meta = {
            "id": replay_id,
            "deck_a": deck_a,
            "deck_b": deck_b,
            "game_idx": game_idx,
            "winner_for_deck_a": winner_for_deck_a,
            "first_player": first_player,
            "turns": turns,
            "seed": seed,
            "saved_at": saved_at,
            **extra,
        }
        return {"meta": meta, "log": payload.get("log", []), "snapshots": payload.get("snapshots", [])}
    finally:
        conn.close()


def list_replays(
    deck_a: Optional[str] = None,
    deck_b: Optional[str] = None,
    only_losses_for: Optional[str] = None,
    db_path: Optional[Path] = None,
    limit: Optional[int] = None,
) -> list[int]:
    """条件に一致する replay の row id を返す (新しい順)。

    - deck_a / deck_b 両方指定でペア固定
    - deck_a だけ指定で「deck_a を含むペア (a 側 or b 側)」
    - only_losses_for: 指定デッキが敗北した試合のみ
    """
    conn = _connect(db_path)
    try:
        clauses: list[str] = []
        params: list = []
        if deck_a and deck_b:
            clauses.append("deck_a = ? AND deck_b = ?")
            params.extend([deck_a, deck_b])
        elif deck_a:
            clauses.append("(deck_a = ? OR deck_b = ?)")
            params.extend([deck_a, deck_a])
        elif deck_b:
            clauses.append("(deck_a = ? OR deck_b = ?)")
            params.extend([deck_b, deck_b])

        if only_losses_for:
            # only_losses_for デッキが敗者である試合
            # = (deck_a = only_losses_for AND winner_for_deck_a = 1)
            #   OR (deck_b = only_losses_for AND winner_for_deck_a = 0)
            clauses.append(
                "((deck_a = ? AND winner_for_deck_a = 1) "
                "OR (deck_b = ? AND winner_for_deck_a = 0))"
            )
            params.extend([only_losses_for, only_losses_for])

        sql = "SELECT id FROM replays"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        cur = conn.execute(sql, params)
        return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def count_replays(db_path: Optional[Path] = None) -> int:
    """総 replay 件数 (高速確認用)。"""
    conn = _connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM replays").fetchone()[0]
    finally:
        conn.close()


def clear_all(db_path: Optional[Path] = None) -> None:
    """全 replay を削除 (テスト用)。"""
    conn = _connect(db_path)
    try:
        conn.execute("DELETE FROM replays")
        conn.commit()
    finally:
        conn.close()
