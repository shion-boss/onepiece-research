# -*- coding: utf-8 -*-
"""
プロジェクト全体のリフレッシュフロー (月次・前進ごとに 1 回実行する想定)。

実行内容 (順番):
1. check_official_updates.py — PDF / FAQ / banlist の更新検知
2. scrape_cardrush_decks.py — cardrush.media から大会上位入賞デッキを再取得
3. select_cardrush_representatives.py — アーキタイプごとに代表 1 つに集約
4. compute_matchup_matrix.py — N×N マッチアップ行列を再計算

`--skip-X` オプションで個別ステップをスキップ可能。

実行:
    .venv/bin/python scripts/refresh_all.py
    .venv/bin/python scripts/refresh_all.py --skip-meta-scrape  # メタは触らずに行列だけ更新
    .venv/bin/python scripts/refresh_all.py --matrix-n-games 50
    .venv/bin/python scripts/refresh_all.py --cardrush-since 2026-01-01
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / ".venv" / "bin" / "python"
SCRIPTS = ROOT / "scripts"


def run(args: list[str]) -> int:
    print(f"\n$ {' '.join(args)}")
    return subprocess.call(args)


def step_official_updates() -> int:
    return run([str(PYTHON), str(SCRIPTS / "check_official_updates.py")])


def step_cardrush_scrape(scores: list[str], since: str | None, max_pages: int) -> int:
    """cardrush.media から大会上位デッキを再取得 (既存は --overwrite で更新)。"""
    args = [
        str(PYTHON), str(SCRIPTS / "scrape_cardrush_decks.py"),
        "--scores", *scores,
        "--max-pages", str(max_pages),
        "--overwrite",
    ]
    if since:
        args.extend(["--since", since])
    return run(args)


def step_cardrush_select() -> int:
    """アーキタイプごとに代表 1 デッキを残し、他は _archive/cardrush_raw/ へ。"""
    return run([str(PYTHON), str(SCRIPTS / "select_cardrush_representatives.py")])


def step_matrix(n_games: int, seed: int) -> int:
    return run([
        str(PYTHON),
        str(SCRIPTS / "compute_matchup_matrix.py"),
        "--n-games", str(n_games),
        "--seed", str(seed),
    ])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-official", action="store_true", help="PDF/FAQ/banlist チェックをスキップ")
    ap.add_argument("--skip-meta-scrape", action="store_true",
                    help="cardrush 再 scrape + 代表選出をスキップ")
    ap.add_argument("--skip-matrix", action="store_true",
                    help="マッチアップ行列再計算をスキップ")
    ap.add_argument("--cardrush-scores", nargs="+", default=["優勝", "準優勝"],
                    choices=["優勝", "準優勝", "3位", "ベスト4"])
    ap.add_argument("--cardrush-since", default=None, help="cardrush 取得期間 (YYYY-MM-DD)")
    ap.add_argument("--cardrush-max-pages", type=int, default=10)
    ap.add_argument("--matrix-n-games", type=int, default=20, help="行列の各セル試合数")
    ap.add_argument("--matrix-seed", type=int, default=42, help="行列計算 seed")
    args = ap.parse_args()

    print("=" * 60)
    print("ONE PIECE Research: 月次リフレッシュ開始")
    print("=" * 60)

    rcs = []
    if not args.skip_official:
        rcs.append(("official", step_official_updates()))
    if not args.skip_meta_scrape:
        rcs.append((
            "cardrush-scrape",
            step_cardrush_scrape(
                args.cardrush_scores, args.cardrush_since, args.cardrush_max_pages,
            ),
        ))
        rcs.append(("cardrush-select", step_cardrush_select()))
    if not args.skip_matrix:
        rcs.append(("matrix", step_matrix(args.matrix_n_games, args.matrix_seed)))

    print()
    print("=" * 60)
    print("リフレッシュ完了")
    for name, rc in rcs:
        status = "OK" if rc == 0 else f"FAIL ({rc})"
        print(f"  [{status}] {name}")
    print("=" * 60)

    return 0 if all(rc in (0, 1) for _, rc in rcs) else 2


if __name__ == "__main__":
    raise SystemExit(main())
