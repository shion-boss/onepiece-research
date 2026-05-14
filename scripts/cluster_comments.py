#!/usr/bin/env python3
"""観戦コメントをクラスタ化して整形表示。

Usage:
    .venv/bin/python scripts/cluster_comments.py
    .venv/bin/python scripts/cluster_comments.py --replay-key '黒イム__紫エネル__0__1__18__258'
    .venv/bin/python scripts/cluster_comments.py --json  # JSON 出力

Claude (= 私) が「コメント確認して」 と言われた時、 個別コメントを 1 件ずつ
読むのではなく このスクリプトを叩いて クラスタ単位で対応する想定。
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine.comment_clustering import cluster_comments, format_clusters_text  # noqa: E402


# 優先: SQLite (= 本番 + ローカル両方使う)。 fallback: 旧 JSON (= 後方互換)。
_DATA_DIR = Path(os.environ.get("DATA_DIR", str(_ROOT / "db")))
_DB_PATH = _DATA_DIR / "spectate_comments.sqlite"
_JSON_PATH = _ROOT / "db" / "spectate_comments.json"


def _load_from_sqlite() -> list[dict]:
    if not _DB_PATH.exists():
        return []
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM comments ORDER BY created_at ASC"
        ).fetchall()
        ids = [r["id"] for r in rows]
        agree_map: dict[str, list[str]] = {i: [] for i in ids}
        if ids:
            qmarks = ",".join("?" for _ in ids)
            for ar in conn.execute(
                f"SELECT comment_id, author FROM agreements WHERE comment_id IN ({qmarks}) ORDER BY created_at ASC",
                ids,
            ).fetchall():
                agree_map.setdefault(ar["comment_id"], []).append(ar["author"])
        out: list[dict] = []
        for r in rows:
            out.append({
                "id": r["id"],
                "replay_key": r["replay_key"],
                "deck_a": r["deck_a"],
                "deck_b": r["deck_b"],
                "first_player": r["first_player"],
                "winner": r["winner"],
                "turns": r["turns"],
                "snapshot_idx": r["snapshot_idx"],
                "snapshot_log": r["snapshot_log"] or "",
                "snapshot_turn": r["snapshot_turn"],
                "text": r["text"],
                "created_at": r["created_at"],
                "author": r["author"],
                "agreed_by": agree_map.get(r["id"], []),
            })
        return out
    finally:
        conn.close()


def _load_from_json() -> list[dict]:
    if not _JSON_PATH.exists():
        return []
    try:
        data = json.loads(_JSON_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def load_comments() -> list[dict]:
    # 優先 SQLite、 fallback JSON。 両方なければ空。
    rows = _load_from_sqlite()
    if rows:
        return rows
    return _load_from_json()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay-key", help="特定 replay のみを対象")
    ap.add_argument("--json", action="store_true", help="JSON で出力 (= 機械処理用)")
    args = ap.parse_args()

    comments = load_comments()
    if args.replay_key:
        comments = [c for c in comments if c.get("replay_key") == args.replay_key]

    clusters = cluster_comments(comments)

    if args.json:
        out = [cl.to_dict() for cl in clusters]
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(format_clusters_text(clusters))
    return 0


if __name__ == "__main__":
    sys.exit(main())
