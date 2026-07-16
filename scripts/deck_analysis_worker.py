# -*- coding: utf-8 -*-
"""ユーザーデッキ分析ジョブのワーカー。

user_store の pending 分析ジョブを poll → AI vs AI 等で分析 → 結果を DB に書き戻す。
Vercel サーバーレスは長時間計算不可なので、 これは **自己ホスト/ローカルの常駐プロセス**
として回す (= 本番は Neon を、 ローカルは db/user_data.sqlite を同じ env で見る)。

  .venv/bin/python scripts/deck_analysis_worker.py           # 常駐 poll
  .venv/bin/python scripts/deck_analysis_worker.py --once    # pending 1 件だけ処理 (cron/テスト)
  .venv/bin/python scripts/deck_analysis_worker.py --n-games 20
"""
from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import user_store as us  # noqa: E402
from api.deck_report import compute_deck_report  # noqa: E402


def process_one(n_games: int, pause_between: float = 0.0) -> bool:
    """pending (or stale-running) 1 件を処理。 処理したら True、 無しなら False。

    - 1マッチずつ save_deck_partial で永続 + touch_job で heartbeat
      → スリープ/クラッシュで中断しても「最大1マッチやり直し」で再開できる。
    - 中断ジョブは claim_next_job の stale 再取得で拾い、 途中経過から resume する。
    """
    job = us.claim_next_job("analyze")
    if job is None:
        return False
    owner, slug, rhash, jid = job["owner_id"], job["slug"], job["recipe_hash"], job["id"]
    print(f"[worker] analyzing {slug} (owner={owner[:8]} hash={rhash})", flush=True)
    try:
        deck = us.get_deck(owner, slug)
        if deck is None:
            us.fail_deck_job(jid, "deck not found")
            print(f"[worker] {slug}: deck not found → failed", flush=True)
            return True

        # 途中経過があり、 かつ同じレシピの計算なら resume (= 計算済みマッチを skip)。
        done_matchups = []
        existing = us.get_deck_report(owner, slug)
        if existing and existing.get("report") and existing["report"].get("recipe_hash") == rhash:
            done_matchups = existing["report"].get("matchups", [])
            if done_matchups:
                print(f"[worker]   {slug}: resume from {len(done_matchups)} done matchups", flush=True)

        def on_progress(done: int, total: int, label: str, partial: dict) -> None:
            us.save_deck_partial(owner, slug, rhash, partial)  # 1マッチ毎に永続
            us.touch_job(jid)                                  # heartbeat (stale 再取得防止)
            print(f"[worker]   {slug}: {done}/{total} vs {label}", flush=True)

        report = compute_deck_report(
            deck, n_games=n_games, recipe_hash=rhash,
            done_matchups=done_matchups, on_progress=on_progress, pause_between=pause_between,
        )
        us.complete_deck_job(jid, owner, slug, rhash, report)
        print(f"[worker] done {slug}: avg winrate {report['matchup_summary']['avg']}", flush=True)
    except Exception as e:  # noqa: BLE001 (ジョブ単位で握って worker 継続)
        traceback.print_exc()
        us.fail_deck_job(jid, str(e))
        print(f"[worker] {slug}: FAILED {e}", flush=True)
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="pending 1 件だけ処理して終了")
    ap.add_argument("--n-games", type=int, default=8, help="マッチアップ毎の対戦数")
    ap.add_argument("--interval", type=float, default=5.0, help="poll 間隔 (秒)")
    ap.add_argument("--pause-between", type=float, default=0.0,
                    help="マッチアップ間の休止秒 (= CPU に優しくする)")
    args = ap.parse_args()

    if args.once:
        did = process_one(args.n_games, args.pause_between)
        print("[worker] processed 1" if did else "[worker] no pending job", flush=True)
        return

    print(f"[worker] polling every {args.interval}s (n_games={args.n_games}) ...", flush=True)
    while True:
        did = process_one(args.n_games, args.pause_between)
        if not did:
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
