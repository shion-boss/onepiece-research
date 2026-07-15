"""陣取り (territory) の占領状態を永続化し、 capture を optimistic-CAS で解決する層。

真の目的 = 「みんなで育てる AI」 の対戦→占領 pipeline のバックエンド
([[project_leader_as_progression_unit]])。 各マス (既定 1024) は占領者 (推しリーダー /
user / 使用デッキ) と version を持つ。

## ストレージ
`api/main.py` の spectate_comments と同じ 「ローカル=SQLite / 本番=Neon(Postgres)」 切替。
- ローカル開発: SQLite ${DATA_DIR}/territory.sqlite
- 本番 (Vercel + Neon): DATABASE_URL=postgres://... で Postgres。
同じ optimistic-CAS (`UPDATE ... WHERE version = :expected`) ロジックで両方動く。

## capture = optimistic CAS (ohtsuki 2026-07-15 確定)
挑戦開始時に対象マスの `version` を snapshot し、 人間が勝ったら
`resolve_capture(cell_id, expected_version, ...)` を呼ぶ。
- 現 version == expected → 誰にも先を越されていない → 占領成立 (version += 1)。
- 現 version != expected → 対戦中に別の挑戦者が先に奪取した → 占領失敗 (non_stakes)。

「同じマスを同時に複数人が攻めたら最速勝利者が奪取」 も、 最速の 1 人だけ
expected と一致し、 以降は version がズレて弾かれる = ロック不要で自然決着する。

空きマス = row 無し (= owner None, version 0)。 最初の占領は expected_version=0。
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# 盤サイズ = 32×32 = 1024 (front TerritoryBoard の N/COLS と一致)。
N_CELLS = 1024

_ROOT = Path(__file__).resolve().parent.parent
_DATABASE_URL = os.environ.get("DATABASE_URL")
_USE_POSTGRES = bool(_DATABASE_URL)
_PH = "%s" if _USE_POSTGRES else "?"

_DATA_DIR = Path(os.environ.get("DATA_DIR", str(_ROOT / "db")))
_TERRITORY_DB = _DATA_DIR / "territory.sqlite"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect():
    """sqlite3 / psycopg どちらかの Connection を返す。 両 driver 互換 I/F のみ使う。"""
    if _USE_POSTGRES:
        import psycopg
        from psycopg.rows import dict_row

        # autocommit=False: capture の CAS は明示 commit/rollback でトランザクション制御。
        return psycopg.connect(_DATABASE_URL, row_factory=dict_row)
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    # isolation_level=None = 自動 BEGIN を切り、 CAS で "BEGIN IMMEDIATE" を明示発行する。
    conn = sqlite3.connect(str(_TERRITORY_DB), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _fetchone(conn, sql: str, params: tuple = ()):
    if _USE_POSTGRES:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    return conn.execute(sql, params).fetchone()


def _fetchall(conn, sql: str, params: tuple = ()) -> list:
    if _USE_POSTGRES:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    return conn.execute(sql, params).fetchall()


def _run(conn, sql: str, params: tuple = ()) -> None:
    if _USE_POSTGRES:
        with conn.cursor() as cur:
            cur.execute(sql, params)
    else:
        conn.execute(sql, params)


def init_schema() -> None:
    """territory + territory_meta(board_version) を冪等作成。 起動時に呼ぶ。"""
    conn = _connect()
    try:
        _run(
            conn,
            """
            CREATE TABLE IF NOT EXISTS territory (
                cell_id INTEGER PRIMARY KEY,
                owner_leader_id TEXT,
                owner_variant_id TEXT,
                owner_user TEXT,
                owner_deck_slug TEXT,
                owner_deck_recipe TEXT,
                version INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
        )
        _migrate_add_deck_recipe(conn)
        _run(
            conn,
            """
            CREATE TABLE IF NOT EXISTS territory_meta (
                id INTEGER PRIMARY KEY,
                board_version INTEGER NOT NULL
            )
            """,
        )
        # 各マスの戦い (= 挑戦者 vs 防衛の対戦記録)。 per-cell 履歴の実データ源。
        id_col = "id BIGSERIAL PRIMARY KEY" if _USE_POSTGRES else "id INTEGER PRIMARY KEY AUTOINCREMENT"
        _run(
            conn,
            f"""
            CREATE TABLE IF NOT EXISTS battles (
                {id_col},
                cell_id INTEGER NOT NULL,
                ts TEXT NOT NULL,
                attacker_user TEXT,
                attacker_leader_id TEXT,
                attacker_variant_id TEXT,
                defender_user TEXT,
                defender_leader_id TEXT,
                defender_variant_id TEXT,
                attacker_won INTEGER NOT NULL,
                captured INTEGER NOT NULL,
                non_stakes INTEGER NOT NULL,
                turns INTEGER
            )
            """,
        )
        _run(conn, "CREATE INDEX IF NOT EXISTS idx_battles_cell ON battles(cell_id)")
        # 月次スナップショット (= 戦いの歴史)。 完了した月の盤 (最終陣地) + 集計を凍結保存。
        # 実データを積み上げる器 = 月替わりに lazy freeze (maybe_freeze_snapshots)。
        _run(
            conn,
            """
            CREATE TABLE IF NOT EXISTS territory_snapshots (
                month_key TEXT PRIMARY KEY,
                cells_json TEXT NOT NULL,
                occupied INTEGER NOT NULL,
                n_battles INTEGER NOT NULL,
                human_wins INTEGER NOT NULL,
                ai_wins INTEGER NOT NULL,
                frozen_at TEXT NOT NULL
            )
            """,
        )
        _migrate_add_active_month(conn)
        # board_version 行を 1 度だけ初期化 (id=1)。
        row = _fetchone(conn, "SELECT board_version FROM territory_meta WHERE id = 1")
        if row is None:
            _run(conn, f"INSERT INTO territory_meta (id, board_version) VALUES (1, 0)")
        if _USE_POSTGRES:
            conn.commit()
    finally:
        conn.close()


def _migrate_add_deck_recipe(conn) -> None:
    """既存 DB に owner_deck_recipe 列が無ければ追加 (= 占領者の実デッキ recipe を保存)。"""
    if _USE_POSTGRES:
        _run(conn, "ALTER TABLE territory ADD COLUMN IF NOT EXISTS owner_deck_recipe TEXT")
        return
    cols = [r["name"] for r in _fetchall(conn, "PRAGMA table_info(territory)")]
    if "owner_deck_recipe" not in cols:
        _run(conn, "ALTER TABLE territory ADD COLUMN owner_deck_recipe TEXT")


def _migrate_add_active_month(conn) -> None:
    """territory_meta に active_month 列を追加 (= 現盤が属する月。 月替わり検知で凍結する)。"""
    if _USE_POSTGRES:
        _run(conn, "ALTER TABLE territory_meta ADD COLUMN IF NOT EXISTS active_month TEXT")
        return
    cols = [r["name"] for r in _fetchall(conn, "PRAGMA table_info(territory_meta)")]
    if "active_month" not in cols:
        _run(conn, "ALTER TABLE territory_meta ADD COLUMN active_month TEXT")


def _begin_write(conn) -> None:
    """書き込みトランザクション開始 (= capture の CAS を直列化)。"""
    if _USE_POSTGRES:
        # psycopg は最初の execute で自動 BEGIN。 SELECT ... FOR UPDATE で行ロック。
        return
    conn.execute("BEGIN IMMEDIATE")


def _read_board_version(conn) -> int:
    row = _fetchone(conn, "SELECT board_version FROM territory_meta WHERE id = 1")
    if row is None:
        return 0
    return int(row["board_version"])


def _bump_board_version(conn) -> int:
    _run(conn, "UPDATE territory_meta SET board_version = board_version + 1 WHERE id = 1")
    return _read_board_version(conn)


def _cell_to_dict(row) -> dict:
    return {
        "cell_id": int(row["cell_id"]),
        "leader_id": row["owner_leader_id"],
        "variant_id": row["owner_variant_id"] or row["owner_leader_id"],
        "user": row["owner_user"],
        "deck_slug": row["owner_deck_slug"],
        "version": int(row["version"]),
        # ブロックの表示 variant を「最後に占領/戦闘した人の柄」にするための recency キー。
        "updated_at": row["updated_at"],
    }


def board_version() -> int:
    """盤全体の変更カウンタ。 client が 「変化あったか」 を安く判定するのに使う。"""
    conn = _connect()
    try:
        return _read_board_version(conn)
    finally:
        conn.close()


def get_board() -> dict:
    """占領済みマスの一覧 + board_version。 空きマスは省略 (client は欠落=空きと扱う)。"""
    conn = _connect()
    try:
        rows = _fetchall(
            conn,
            "SELECT cell_id, owner_leader_id, owner_variant_id, owner_user, "
            "owner_deck_slug, version, updated_at FROM territory ORDER BY cell_id",
        )
        return {
            "board_version": _read_board_version(conn),
            "n_cells": N_CELLS,
            "cells": [_cell_to_dict(r) for r in rows],
        }
    finally:
        conn.close()


def get_cell(cell_id: int) -> dict:
    """1 マスの現状 (占領者 + version)。 空きマスは version=0 / owner None。

    対戦中の race 検知 (= 挑戦中マスの version だけ短間隔ポーリング) に使う。
    """
    conn = _connect()
    try:
        row = _fetchone(
            conn,
            "SELECT cell_id, owner_leader_id, owner_variant_id, owner_user, "
            f"owner_deck_slug, version, updated_at FROM territory WHERE cell_id = {_PH}",
            (cell_id,),
        )
        if row is None:
            return {
                "cell_id": int(cell_id),
                "leader_id": None,
                "variant_id": None,
                "user": None,
                "deck_slug": None,
                "version": 0,
            }
        return _cell_to_dict(row)
    finally:
        conn.close()


def defender_deck(cell_id: int) -> Optional[dict]:
    """占領マスに保存された占領者のデッキ recipe を返す (= 防衛 AI が操縦する)。

    空きマス / recipe 未保存なら None。 挑戦開始時にだけ呼ぶ (= 重いので board/cell
    ポーリングには含めない)。
    """
    conn = _connect()
    try:
        row = _fetchone(
            conn,
            f"SELECT owner_deck_recipe FROM territory WHERE cell_id = {_PH}",
            (cell_id,),
        )
        if row is None or not row["owner_deck_recipe"]:
            return None
        try:
            return json.loads(row["owner_deck_recipe"])
        except Exception:
            return None
    finally:
        conn.close()


def resolve_capture(
    cell_id: int,
    expected_version: int,
    *,
    leader_id: str,
    variant_id: Optional[str] = None,
    user: Optional[str] = None,
    deck_slug: Optional[str] = None,
    deck_recipe: Optional[dict] = None,
) -> dict:
    """挑戦者の勝利を占領に反映する optimistic-CAS。

    現 version == expected_version の時だけ占領成立 (version += 1、 board_version += 1)。
    ズレていたら = 対戦中に別の挑戦者が先に奪取済 → captured=False (呼び元で non_stakes 扱い)。

    返り値:
      {"captured": True,  "cell_id", "version", "board_version", "owner": {...}}
      {"captured": False, "cell_id", "current_version"}
    """
    if not (0 <= int(cell_id) < N_CELLS):
        raise ValueError(f"cell_id out of range: {cell_id}")
    # 占領で盤が変わる前に、 月替わりなら直前月の最終盤を凍結する (独立 conn なので先に呼ぶ)。
    maybe_freeze_snapshots()
    conn = _connect()
    try:
        _begin_write(conn)
        # 現 version を読む (Postgres は FOR UPDATE で行ロック)。
        lock = " FOR UPDATE" if _USE_POSTGRES else ""
        row = _fetchone(
            conn,
            f"SELECT version FROM territory WHERE cell_id = {_PH}{lock}",
            (cell_id,),
        )
        current = int(row["version"]) if row is not None else 0
        if current != int(expected_version):
            # 先を越された (or expectation 不一致) → 占領しない。
            if _USE_POSTGRES:
                conn.rollback()
            else:
                conn.execute("ROLLBACK")
            return {
                "captured": False,
                "cell_id": int(cell_id),
                "current_version": current,
            }

        new_version = current + 1
        now = _now_iso()
        recipe_json = json.dumps(deck_recipe, ensure_ascii=False) if deck_recipe else None
        if row is not None:
            _run(
                conn,
                f"UPDATE territory SET owner_leader_id = {_PH}, owner_variant_id = {_PH}, "
                f"owner_user = {_PH}, owner_deck_slug = {_PH}, owner_deck_recipe = {_PH}, "
                f"version = {_PH}, updated_at = {_PH} WHERE cell_id = {_PH}",
                (leader_id, variant_id, user, deck_slug, recipe_json, new_version, now, cell_id),
            )
        else:
            _run(
                conn,
                f"INSERT INTO territory (cell_id, owner_leader_id, owner_variant_id, "
                f"owner_user, owner_deck_slug, owner_deck_recipe, version, updated_at) "
                f"VALUES ({_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH})",
                (cell_id, leader_id, variant_id, user, deck_slug, recipe_json, new_version, now),
            )
        bv = _bump_board_version(conn)
        if _USE_POSTGRES:
            conn.commit()
        else:
            conn.execute("COMMIT")
        return {
            "captured": True,
            "cell_id": int(cell_id),
            "version": new_version,
            "board_version": bv,
            "owner": {
                "leader_id": leader_id,
                "variant_id": variant_id or leader_id,
                "user": user,
                "deck_slug": deck_slug,
            },
        }
    finally:
        conn.close()


def seed_board(entries: list[dict], *, reset: bool = False) -> dict:
    """デモ / テスト用の一括占領。 各 entry = {cell_id, leader_id, variant_id?, user?, deck_slug?}。

    本番の盤は空スタートで実占領のみで埋まる。 これは開発時に盤を賑やかにする / テスト用。
    """
    conn = _connect()
    try:
        _begin_write(conn)
        if reset:
            _run(conn, "DELETE FROM territory")
        now = _now_iso()
        for e in entries:
            cid = int(e["cell_id"])
            if not (0 <= cid < N_CELLS):
                continue
            _run(
                conn,
                f"INSERT INTO territory (cell_id, owner_leader_id, owner_variant_id, "
                f"owner_user, owner_deck_slug, version, updated_at) "
                f"VALUES ({_PH}, {_PH}, {_PH}, {_PH}, {_PH}, 1, {_PH}) "
                + (
                    "ON CONFLICT (cell_id) DO UPDATE SET "
                    "owner_leader_id = EXCLUDED.owner_leader_id, "
                    "owner_variant_id = EXCLUDED.owner_variant_id, "
                    "owner_user = EXCLUDED.owner_user, "
                    "owner_deck_slug = EXCLUDED.owner_deck_slug, "
                    "version = territory.version + 1, "
                    "updated_at = EXCLUDED.updated_at"
                    if _USE_POSTGRES
                    else
                    "ON CONFLICT(cell_id) DO UPDATE SET "
                    "owner_leader_id = excluded.owner_leader_id, "
                    "owner_variant_id = excluded.owner_variant_id, "
                    "owner_user = excluded.owner_user, "
                    "owner_deck_slug = excluded.owner_deck_slug, "
                    "version = territory.version + 1, "
                    "updated_at = excluded.updated_at"
                ),
                (
                    cid,
                    e["leader_id"],
                    e.get("variant_id"),
                    e.get("user"),
                    e.get("deck_slug"),
                    now,
                ),
            )
        bv = _bump_board_version(conn)
        if _USE_POSTGRES:
            conn.commit()
        else:
            conn.execute("COMMIT")
        return {"seeded": len(entries), "board_version": bv}
    finally:
        conn.close()


def record_battle(
    *,
    cell_id: int,
    attacker_user: Optional[str],
    attacker_leader_id: Optional[str],
    attacker_variant_id: Optional[str],
    defender_user: Optional[str],
    defender_leader_id: Optional[str],
    defender_variant_id: Optional[str],
    attacker_won: bool,
    captured: bool,
    non_stakes: bool,
    turns: Optional[int],
) -> None:
    """1 回の陣取り対戦を記録 (= per-cell 戦い履歴)。 完了 (勝敗ついた) 対戦のみ。

    non_stakes (= 対戦中に他人が先に奪取したので占領できなかった継続試合) も保存するが、
    list_battles の既定では履歴表示から除外する (ohtsuki 確定「残すが履歴からは除外」)。
    """
    conn = _connect()
    try:
        _run(
            conn,
            f"INSERT INTO battles (cell_id, ts, attacker_user, attacker_leader_id, "
            f"attacker_variant_id, defender_user, defender_leader_id, defender_variant_id, "
            f"attacker_won, captured, non_stakes, turns) VALUES "
            f"({_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH})",
            (
                int(cell_id), _now_iso(), attacker_user, attacker_leader_id,
                attacker_variant_id, defender_user, defender_leader_id, defender_variant_id,
                1 if attacker_won else 0, 1 if captured else 0, 1 if non_stakes else 0, turns,
            ),
        )
        if _USE_POSTGRES:
            conn.commit()
    finally:
        conn.close()


def list_battles(cell_id: int, *, exclude_non_stakes: bool = True, limit: int = 20) -> list[dict]:
    """マスの戦い履歴 (新しい順)。 既定で non_stakes を除外する。"""
    conn = _connect()
    try:
        sql = (
            "SELECT id, cell_id, ts, attacker_user, attacker_leader_id, attacker_variant_id, "
            "defender_user, defender_leader_id, defender_variant_id, attacker_won, captured, "
            f"non_stakes, turns FROM battles WHERE cell_id = {_PH}"
        )
        if exclude_non_stakes:
            sql += " AND non_stakes = 0"
        sql += f" ORDER BY id DESC LIMIT {int(limit)}"
        rows = _fetchall(conn, sql, (int(cell_id),))
        return [
            {
                "id": int(r["id"]),
                "cell_id": int(r["cell_id"]),
                "ts": r["ts"],
                "attacker_user": r["attacker_user"],
                "attacker_leader_id": r["attacker_leader_id"],
                "attacker_variant_id": r["attacker_variant_id"],
                "defender_user": r["defender_user"],
                "defender_leader_id": r["defender_leader_id"],
                "defender_variant_id": r["defender_variant_id"],
                "attacker_won": bool(r["attacker_won"]),
                "captured": bool(r["captured"]),
                "non_stakes": bool(r["non_stakes"]),
                "turns": r["turns"],
            }
            for r in rows
        ]
    finally:
        conn.close()


# ── 月次スナップショット (= 戦いの歴史。 実データを積み上げる) ──────────────────
# 現盤 (territory) は「今」の状態しか持たない。 完了した月の最終陣地を後から振り返れる
# ように、 月替わりの瞬間に現盤 + その月の対戦集計を凍結保存する (lazy freeze)。
# ⚠ 過去 (機能導入前) の月は履歴が無いので遡って作らない = 空スタート、 今後積み上がる。


def _current_month() -> str:
    """現在の月キー (UTC, "YYYY-MM")。"""
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _board_cells(conn) -> list[dict]:
    rows = _fetchall(
        conn,
        "SELECT cell_id, owner_leader_id, owner_variant_id, owner_user, "
        "owner_deck_slug, version, updated_at FROM territory ORDER BY cell_id",
    )
    return [_cell_to_dict(r) for r in rows]


def _month_battle_stats(conn, month_key: str) -> tuple[int, int, int]:
    """month_key ("YYYY-MM") の対戦集計 (n_battles, human_wins, ai_wins)。 non_stakes 除外。

    挑戦者 (attacker) = 人間 / 防衛 (defender) = AI が操縦。 attacker_won=1 → 人間勝ち。
    ts は ISO ("YYYY-MM-...") なので前方一致で月抽出。
    """
    like = f"{month_key}%"
    total = _fetchone(
        conn, f"SELECT COUNT(*) AS c FROM battles WHERE non_stakes = 0 AND ts LIKE {_PH}", (like,)
    )
    hwin = _fetchone(
        conn,
        f"SELECT COUNT(*) AS c FROM battles WHERE non_stakes = 0 AND attacker_won = 1 AND ts LIKE {_PH}",
        (like,),
    )
    n = int(total["c"]) if total else 0
    h = int(hwin["c"]) if hwin else 0
    return n, h, n - h


def maybe_freeze_snapshots() -> None:
    """月替わりを検知し、 直前の active_month の盤 (最終陣地) + 集計を凍結保存する。

    lazy freeze: 履歴閲覧時 / capture 時に呼ぶ。 冪等 (ON CONFLICT DO NOTHING + 条件付き
    active_month 更新) で並行呼び出しにも安全。 active_month 未設定なら現在月で初期化のみ。
    """
    now_month = _current_month()
    conn = _connect()
    try:
        _begin_write(conn)
        row = _fetchone(conn, "SELECT active_month FROM territory_meta WHERE id = 1")
        active = row["active_month"] if row else None
        if active is None:
            # 初回: 現在月を baseline に (凍結はしない)。
            _run(conn, f"UPDATE territory_meta SET active_month = {_PH} WHERE id = 1", (now_month,))
        elif active != now_month:
            # 月が進んだ → active (直前月) の最終盤を凍結。
            cells = _board_cells(conn)
            n_battles, human_wins, ai_wins = _month_battle_stats(conn, active)
            _run(
                conn,
                f"INSERT INTO territory_snapshots (month_key, cells_json, occupied, "
                f"n_battles, human_wins, ai_wins, frozen_at) VALUES "
                f"({_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH}) "
                f"ON CONFLICT (month_key) DO NOTHING",
                (active, json.dumps(cells), len(cells), n_battles, human_wins, ai_wins, _now_iso()),
            )
            _run(
                conn,
                f"UPDATE territory_meta SET active_month = {_PH} WHERE id = 1 AND active_month = {_PH}",
                (now_month, active),
            )
        if _USE_POSTGRES:
            conn.commit()
        else:
            conn.execute("COMMIT")
    finally:
        conn.close()


def list_snapshots() -> list[dict]:
    """凍結済み月次スナップショットの一覧 (新しい月順、 盤 cells は含めない軽量サマリ)。"""
    maybe_freeze_snapshots()
    conn = _connect()
    try:
        rows = _fetchall(
            conn,
            "SELECT month_key, occupied, n_battles, human_wins, ai_wins, frozen_at "
            "FROM territory_snapshots ORDER BY month_key DESC",
        )
        return [
            {
                "month_key": r["month_key"],
                "occupied": int(r["occupied"]),
                "n_battles": int(r["n_battles"]),
                "human_wins": int(r["human_wins"]),
                "ai_wins": int(r["ai_wins"]),
                "frozen_at": r["frozen_at"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def get_snapshot(month_key: str) -> Optional[dict]:
    """1 月分の凍結スナップショット (盤 cells 込み)。 無ければ None。"""
    conn = _connect()
    try:
        row = _fetchone(
            conn,
            "SELECT month_key, cells_json, occupied, n_battles, human_wins, ai_wins, frozen_at "
            f"FROM territory_snapshots WHERE month_key = {_PH}",
            (month_key,),
        )
        if row is None:
            return None
        try:
            cells = json.loads(row["cells_json"])
        except Exception:
            cells = []
        return {
            "month_key": row["month_key"],
            "occupied": int(row["occupied"]),
            "n_battles": int(row["n_battles"]),
            "human_wins": int(row["human_wins"]),
            "ai_wins": int(row["ai_wins"]),
            "frozen_at": row["frozen_at"],
            # board は get_board と同形 (buildCellsFromBoard で描画)。 version は凍結なので 0。
            "board": {"board_version": 0, "n_cells": N_CELLS, "cells": cells},
        }
    finally:
        conn.close()
