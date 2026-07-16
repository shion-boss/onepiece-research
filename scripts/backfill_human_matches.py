#!/usr/bin/env python3
"""既存の人間 vs AI ログ (db/human_play_log/*.json) を human_matches テーブルに取り込む。

per-deck「直近の対戦履歴」機能の導入前に遊んだ試合 (= 記録コードが live になる前の試合)
を後から履歴に載せるための一回性/冪等バックフィル。 id = ファイル名 stem なので再実行安全。

中断 (game_over 無し = winner_idx None) は結果が無いので除外。 leader は deck slug から解決。
本番 (Blob) は対象外 (= ここは local dev の db/human_play_log/ のみ)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api import user_store  # noqa: E402

LOG_DIR = ROOT / "db" / "human_play_log"


def _resolve_leader(slug: str) -> str | None:
    """deck slug → leader card_id。 meta は decks/<slug>.json、 user は user_decks から。"""
    if not slug:
        return None
    p = ROOT / "decks" / f"{slug}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8")).get("leader")
        except Exception:
            pass
    # user デッキ (owner 不問で slug 一致を探す)。
    try:
        conn = user_store._conn()
        cur = conn.cursor()
        cur.execute(
            f"SELECT leader FROM user_decks WHERE slug = {user_store._PH} LIMIT 1", (slug,)
        )
        row = cur.fetchone()
        conn.close()
        if row is not None:
            return dict(row).get("leader")
    except Exception:
        pass
    return None


def main() -> None:
    if not LOG_DIR.exists():
        print(f"no log dir: {LOG_DIR}")
        return
    files = sorted(LOG_DIR.glob("*.json"))
    added = skipped_abandoned = failed = 0
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  skip (parse) {f.name}: {e}")
            failed += 1
            continue
        meta = d.get("metadata") or {}
        result = d.get("result") or {}
        # 中断 (game_over 無し) は winner_idx が None → 履歴に載せない。
        if result.get("winner_idx") is None:
            skipped_abandoned += 1
            continue
        deck_human = meta.get("deck_human_slug")
        deck_ai = meta.get("deck_ai_slug")
        if not deck_human:
            failed += 1
            continue
        terr = d.get("territory") or {}
        source = "territory" if terr.get("cell_id") is not None else "practice"
        try:
            user_store.record_human_match(
                sid=f.stem,  # ファイル名 stem を id に (= 冪等)
                deck_human_slug=deck_human,
                deck_ai_slug=deck_ai,
                human_leader=_resolve_leader(deck_human),
                ai_leader=_resolve_leader(deck_ai),
                winner_for_human=result.get("winner_for_human"),
                turns=result.get("turns"),
                human_first=bool(meta.get("human_first")),
                human_life_left=result.get("p_human_life_left"),
                ai_life_left=result.get("p_ai_life_left"),
                source=source,
                non_stakes=bool(terr.get("non_stakes")),
                user_id=None,  # ログに owner 情報が無い (= 履歴の privacy は deck 所有で判定)
                created_at=(d.get("timestamp_utc") or "")[:19].replace("+00:00", "") + "Z"
                if d.get("timestamp_utc") else None,
            )
            added += 1
        except Exception as e:
            print(f"  skip (record) {f.name}: {e}")
            failed += 1
    print(f"done: {added} recorded, {skipped_abandoned} abandoned skipped, {failed} failed "
          f"({len(files)} files)")


if __name__ == "__main__":
    main()
