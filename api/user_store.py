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
from datetime import datetime, timedelta, timezone
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


# --------------------------------------------------------------------------- #
# 分析レポートの検証・サニタイズ (= 保存前の choke point)。
# ⚠ ブラウザ (ユーザー CPU) で計算した結果は **信頼できない** (= クライアントが捏造/巨大化
# 可能)。 永続化する全経路 (worker 直・将来のブラウザ upload) は必ずここを通す。
# --------------------------------------------------------------------------- #
_META_SLUGS_FILE = _ROOT / "db" / "meta_decks.json"
_ANALYSIS_META_SLUGS: Optional[frozenset] = None
_MAX_REPORT_BYTES = 256 * 1024  # 256KB 上限 (= 正常な report は数KB)


def _known_meta_slugs() -> frozenset:
    global _ANALYSIS_META_SLUGS
    if _ANALYSIS_META_SLUGS is None:
        try:
            d = json.loads(_META_SLUGS_FILE.read_text(encoding="utf-8"))
            _ANALYSIS_META_SLUGS = frozenset(d.get("meta_deck_slugs", []))
        except Exception:
            _ANALYSIS_META_SLUGS = frozenset()
    return _ANALYSIS_META_SLUGS


def _ci(v, lo: int, hi: int, default: int = 0) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def _cf(v, lo: float, hi: float, default: float = 0.0) -> float:
    try:
        return round(max(lo, min(hi, float(v))), 4)
    except (TypeError, ValueError):
        return default


def _cs(v, maxlen: int) -> str:
    return str(v)[:maxlen] if v is not None else ""


def sanitize_report(report) -> dict:
    """信頼できない report dict を検証・クランプして安全な dict にする。

    形が壊れていたら ValueError。 個々の値は範囲/長さ/件数を強制。 matchup_summary は
    捏造を許さないよう matchups から再計算する。 相手 slug は既知メタのみ許可。"""
    if not isinstance(report, dict):
        raise ValueError("report must be an object")
    # 巨大 payload 拒否 (= DoS / storage 爆発防止)。
    if len(json.dumps(report, ensure_ascii=False)) > _MAX_REPORT_BYTES:
        raise ValueError("report too large")

    roles_in = report.get("roles") if isinstance(report.get("roles"), list) else []
    roles = [
        {"role": _cs(r.get("role"), 40), "label": _cs(r.get("label"), 40),
         "count": _ci(r.get("count"), 0, 500)}
        for r in roles_in[:20] if isinstance(r, dict)
    ]

    keys_in = report.get("key_cards") if isinstance(report.get("key_cards"), list) else []
    key_cards = [
        {"card_id": _cs(k.get("card_id"), 30), "name": _cs(k.get("name"), 80),
         "role": _cs(k.get("role"), 40), "label": _cs(k.get("label"), 40),
         "threat_level": _ci(k.get("threat_level"), 0, 10), "count": _ci(k.get("count"), 0, 4)}
        for k in keys_in[:20] if isinstance(k, dict)
    ]

    known = _known_meta_slugs()
    mus_in = report.get("matchups") if isinstance(report.get("matchups"), list) else []
    matchups = []
    seen_slugs = set()
    for m in mus_in[:64]:
        if not isinstance(m, dict):
            continue
        slug = _cs(m.get("slug"), 64)
        # 既知メタ + ミラー (__mirror__) のみ許可 (= 空 whitelist 環境は全許容)。 重複除外。
        if (known and slug not in known and slug != "__mirror__") or slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        matchups.append({
            "slug": slug,
            "name": _cs(m.get("name"), 80),
            "leader": _cs(m.get("leader"), 30),
            "leader_name": _cs(m.get("leader_name"), 80),
            "win_rate": _cf(m.get("win_rate"), 0.0, 1.0),
            "n": _ci(m.get("n"), 0, 100000),
        })

    ins_in = report.get("insights") if isinstance(report.get("insights"), list) else []
    insights = [
        {"kind": _cs(x.get("kind"), 20), "title": _cs(x.get("title"), 120),
         "detail": _cs(x.get("detail"), 500), "strength": _cf(x.get("strength"), 0.0, 1.0)}
        for x in ins_in[:8] if isinstance(x, dict)
    ]

    # 回り方プロファイル (= 記述統計、 数値のみ)。
    prof_in = report.get("profile") if isinstance(report.get("profile"), dict) else {}
    _PROFILE_KEYS = ("avg_turns", "first_attack_turn", "attacks_per_game", "attacks_landed",
                     "ko_dealt", "ko_lost", "opp_attacks", "blocker_uses", "counter_uses")
    profile = {k: _cf(prof_in.get(k), 0.0, 100.0) for k in _PROFILE_KEYS if prof_in.get(k) is not None}

    # よく出るカード (使用率つき)。
    tc_in = report.get("top_cards") if isinstance(report.get("top_cards"), list) else []
    top_cards = [
        {"card_id": _cs(x.get("card_id"), 30), "name": _cs(x.get("name"), 80),
         "play_rate": _cf(x.get("play_rate"), 0.0, 1.0)}
        for x in tc_in[:8] if isinstance(x, dict)
    ]

    # 相手タイプ別プラン (#8)。
    mp_in = report.get("matchup_plans") if isinstance(report.get("matchup_plans"), list) else []
    matchup_plans = [
        {"archetype": _cs(x.get("archetype"), 20), "win_rate": _cf(x.get("win_rate"), 0.0, 1.0),
         "n": _ci(x.get("n"), 0, 100000), "detail": _cs(x.get("detail"), 300)}
        for x in mp_in[:6] if isinstance(x, dict)
    ]

    # 勝ちに繋がるコンボ (#5)。
    wc_in = report.get("win_combos") if isinstance(report.get("win_combos"), list) else []
    win_combos = [
        {"cards": [_cs(c, 80) for c in (x.get("cards") or [])[:5] if isinstance(c, str)],
         "label": _cs(x.get("label"), 60), "win_rate": _cf(x.get("win_rate"), 0.0, 1.0),
         "base_win_rate": _cf(x.get("base_win_rate"), 0.0, 1.0), "n": _ci(x.get("n"), 0, 100000),
         "strength": _cf(x.get("strength"), 0.0, 1.0)}
        for x in wc_in[:6] if isinstance(x, dict)
    ]

    # 初手キープすべき札 (#1)。
    mu_in = report.get("mulligan") if isinstance(report.get("mulligan"), list) else []
    mulligan = [
        {"name": _cs(x.get("name"), 80), "win_rate_with": _cf(x.get("win_rate_with"), 0.0, 1.0),
         "win_rate_without": _cf(x.get("win_rate_without"), 0.0, 1.0), "n": _ci(x.get("n"), 0, 100000),
         "strength": _cf(x.get("strength"), 0.0, 1.0)}
        for x in mu_in[:8] if isinstance(x, dict)
    ]

    # 序盤の動き方(#3) + 防御の考え方(#7) prescriptive guides。
    gd_in = report.get("guides") if isinstance(report.get("guides"), list) else []
    guides = [
        {"kind": _cs(x.get("kind"), 20), "title": _cs(x.get("title"), 60), "detail": _cs(x.get("detail"), 300)}
        for x in gd_in[:4] if isinstance(x, dict)
    ]

    # 惜しい負けの攻略チャレンジ (= 同じ引きを強い探索AIで指し直して勝てたか)。
    ch_in = report.get("challenges") if isinstance(report.get("challenges"), list) else []
    challenges = [
        {
            "opponent": _cs(x.get("opponent"), 60),
            "opp_leader": _cs(x.get("opp_leader"), 60),
            "opp_archetype": _cs(x.get("opp_archetype"), 20),
            "loss_margin": _ci(x.get("loss_margin"), 0, 20),
            "winnable": bool(x.get("winnable")),
            "how_to_win": _cs(x.get("how_to_win"), 300),
        }
        for x in ch_in[:8] if isinstance(x, dict)
    ]

    def _buckets(d, keys):
        d = d if isinstance(d, dict) else {}
        return {k: _ci(d.get(k), 0, 500) for k in keys}

    # summary は client を信じず matchups から再計算。
    played = [x for x in matchups if x["n"]]
    avg = round(sum(x["win_rate"] for x in played) / len(played), 3) if played else 0.0
    ranked = sorted(played, key=lambda x: -x["win_rate"])
    summary = {
        "avg": avg,
        "best": ranked[:3],
        "worst": list(reversed(ranked[-3:])) if len(ranked) >= 3 else [],
    }

    return {
        "computed_at": _cs(report.get("computed_at"), 40),
        "ai_version": _cs(report.get("ai_version"), 40),
        "n_games_per_matchup": _ci(report.get("n_games_per_matchup"), 1, 1000, 1),
        "recipe_hash": _cs(report.get("recipe_hash"), 64),
        "roles": roles,
        "key_cards": key_cards,
        "archetype": _cs(report.get("archetype"), 20),
        "speed_dist": _buckets(report.get("speed_dist"), ("early", "mid", "late")),
        "curve_buckets": _buckets(report.get("curve_buckets"), ("low", "mid", "high")),
        "matchups": matchups,
        "n_opponents": _ci(report.get("n_opponents"), 0, 64),
        "matchup_summary": summary,
        "insights": insights,
        "profile": profile,
        "top_cards": top_cards,
        "matchup_plans": matchup_plans,
        "win_combos": win_combos,
        "mulligan": mulligan,
        "guides": guides,
        "challenges": challenges,
        "partial": bool(report.get("partial")),
    }


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


def claim_next_job(kind: str = "analyze", stale_running_seconds: int = 300) -> Optional[dict]:
    """ワーカー用: pending、 または「running のまま stale (= ワーカーがスリープ/クラッシュ)」を
    再取得して running にして返す。 無ければ None。 stale 再取得により中断ジョブを再開できる。
    ⚠ 単一ワーカー前提 (= 複数なら SELECT FOR UPDATE SKIP LOCKED が要る)。"""
    init_schema()
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=stale_running_seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    conn = _conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT * FROM deck_jobs WHERE kind = {_PH} AND "
                f"(status = 'pending' OR (status = 'running' AND updated_at < {_PH})) "
                f"ORDER BY CASE WHEN status = 'pending' THEN 0 ELSE 1 END, "
                f"priority DESC, created_at ASC LIMIT 1",
                (kind, cutoff),
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


def touch_job(job_id: str) -> None:
    """ワーカー用: job の updated_at を更新 (= heartbeat)。 stale 判定で生きているジョブが
    横取りされないように、 進捗があるたびに呼ぶ。"""
    init_schema()
    conn = _conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE deck_jobs SET updated_at = {_PH} WHERE id = {_PH}", (_now(), job_id)
            )
    finally:
        conn.close()


def save_deck_partial(owner_id: str, slug: str, rhash: str, partial_report: dict) -> None:
    """ワーカー/ブラウザ用: 途中経過 (= 1マッチずつ) を保存。 status='running'。
    ⚠ report は信頼できない可能性があるので sanitize してから保存 (= 保存の choke point)。
    レシピが変わっていたら (recipe_hash != rhash) 書かない。"""
    init_schema()
    clean = sanitize_report(partial_report)
    conn = _conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE user_decks SET analysis_json = {_PH}, analysis_status = 'running' "
                f"WHERE owner_id = {_PH} AND slug = {_PH} AND recipe_hash = {_PH}",
                (json.dumps(clean, ensure_ascii=False), owner_id, slug, rhash),
            )
    finally:
        conn.close()


def complete_deck_job(job_id: str, owner_id: str, slug: str, rhash: str, report: dict) -> None:
    """ワーカー/ブラウザ用: 分析結果を書き戻し job を done に。 レシピが分析中に変わっていたら
    (= recipe_hash != rhash) デッキ側は更新しない (= 別の新ジョブが処理する)。
    ⚠ report は保存前に必ず sanitize (= 信頼できない client 計算結果でも安全に永続)。"""
    init_schema()
    clean = sanitize_report(report)
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
                (json.dumps(clean, ensure_ascii=False), rhash, owner_id, slug, rhash),
            )
    finally:
        conn.close()


def fail_deck_job(job_id: str, error: str) -> None:
    """ワーカー用: job を failed に (= error 記録)。 デッキの analysis_status も 'failed' にして
    詳細画面から再分析できるようにする。 途中経過 (analysis_json) は残す (= 再分析で再開)。"""
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
                    f"UPDATE user_decks SET analysis_status = 'failed' "
                    f"WHERE owner_id = {_PH} AND slug = {_PH} AND analysis_status IN ('pending', 'running')",
                    (r["owner_id"], r["slug"]),
                )
    finally:
        conn.close()


def request_analysis(owner_id: str, slug: str) -> bool:
    """手動で分析を要求 (= 再分析 / 失敗リトライ / 既存デッキの初回分析)。 pending にして
    強制的に新ジョブを積む (= 既存の pending/running/failed を superseded にしてから enqueue、
    途中経過 analysis_json は残すので再開できる)。 デッキが無い / 下書きなら False。"""
    d = get_deck(owner_id, slug)
    if d is None or d.get("draft"):
        return False
    rhash = recipe_hash(d.get("leader", ""), d.get("main", []))
    conn = _conn()
    try:
        with conn:
            cur = conn.cursor()
            # 手動再分析は full 再計算にする (= 途中経過を消す)。 resume で matchup を skip すると
            # 試合ログが取れず戦略 insights が出ないため、 明示リトライは常にゼロから回す。
            cur.execute(
                f"UPDATE user_decks SET recipe_hash = {_PH}, analysis_status = 'pending', "
                f"analysis_json = NULL, analyzed_hash = NULL "
                f"WHERE owner_id = {_PH} AND slug = {_PH}",
                (rhash, owner_id, slug),
            )
            # 既存ジョブを片付けてから fresh 発行 (= リトライで確実に走る)。
            cur.execute(
                f"UPDATE deck_jobs SET status = 'superseded', updated_at = {_PH} "
                f"WHERE owner_id = {_PH} AND slug = {_PH} AND kind = 'analyze' "
                f"AND status IN ('pending', 'running')",
                (_now(), owner_id, slug),
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
