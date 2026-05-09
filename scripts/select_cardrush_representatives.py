# -*- coding: utf-8 -*-
"""cardrush_*.json の中からアーキタイプ毎に最新の優勝デッキを代表として選び、
既存メタ ( meta_*.json + red_zoro.json + blue_doflamingo.json + red_green_law.json )
を _archive/ へ退避する。

スコア優先順位: 優勝 > 準優勝 > 3位 > ベスト4
同 score 内では tournament_date が新しい方を採用。

使い方:
    .venv/bin/python scripts/select_cardrush_representatives.py
    .venv/bin/python scripts/select_cardrush_representatives.py --dry-run
    .venv/bin/python scripts/select_cardrush_representatives.py --keep-existing-meta
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECKS_DIR = ROOT / "decks"
ARCHIVE_DIR = DECKS_DIR / "_archive"

SCORE_RANK = {"優勝": 0, "準優勝": 1, "3位": 2, "ベスト4": 3}


def load_cardrush_decks() -> list[dict]:
    out = []
    for p in sorted(DECKS_DIR.glob("cardrush_*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            d["__path"] = p
            out.append(d)
        except Exception as e:
            print(f"  WARN parse failed: {p.name}: {e}")
    return out


def select_representative_per_archetype(decks: list[dict]) -> dict[str, dict]:
    """archetype.name 毎に 1 つ代表を選ぶ。score 優先 + 日付新しい順。"""
    grouped: dict[str, list[dict]] = {}
    for d in decks:
        key = d.get("name", "(unknown)")
        grouped.setdefault(key, []).append(d)

    result = {}
    for arch, group in grouped.items():
        ranked = sorted(
            group,
            key=lambda d: (
                SCORE_RANK.get(d.get("score", ""), 99),
                # 日付降順 (新しい方が小さい): 新しい日付ほど高評価
                # tournament_date が None/"" の場合は最低
                tuple(reversed([int(x) for x in (d.get("tournament_date") or "0-0-0").split("-")])),
            ),
        )
        # 同 score 内で日付新しい順にしたいので score, -date でソート
        ranked = sorted(
            group,
            key=lambda d: (
                SCORE_RANK.get(d.get("score", ""), 99),
                # 日付降順: minus の代わりに reverse=False のままで負号トリック
                _date_sort_key(d.get("tournament_date") or "0000-00-00"),
            ),
        )
        result[arch] = ranked[0]
    return result


def _date_sort_key(date_str: str) -> tuple:
    """日付の昇順キーを返す。新しい日付ほど **小さい** タプルにしたい(score 内で新しい方を選ぶため)
    → 各成分の負数を返す。"""
    parts = (date_str or "0000-00-00").split("-")
    try:
        y, m, day = int(parts[0]), int(parts[1]), int(parts[2])
    except (ValueError, IndexError):
        y, m, day = 0, 0, 0
    return (-y, -m, -day)


def archive_existing_meta(dry_run: bool) -> list[Path]:
    """既存 meta_*.json + 個別 deck (red_zoro 等) を _archive/ へ移動。
    cardrush_*.json は対象外。"""
    targets = []
    for p in sorted(DECKS_DIR.glob("*.json")):
        n = p.name
        if n.startswith("cardrush_"):
            continue
        targets.append(p)

    if not dry_run and targets:
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    for p in targets:
        dest = ARCHIVE_DIR / p.name
        if dry_run:
            print(f"  DRY archive: {p.name} -> _archive/")
        else:
            shutil.move(str(p), str(dest))
            print(f"  archive: {p.name} -> _archive/")
    return targets


def remove_non_representative_cardrush(reps: dict[str, dict], dry_run: bool) -> int:
    """選ばれなかった cardrush_*.json は削除 (raw data は残したい場合 _archive/cardrush_raw/ などに退避)。"""
    rep_paths = {d["__path"] for d in reps.values()}
    removed = 0
    keep_dir = ARCHIVE_DIR / "cardrush_raw"
    if not dry_run:
        keep_dir.mkdir(parents=True, exist_ok=True)
    for p in sorted(DECKS_DIR.glob("cardrush_*.json")):
        if p in rep_paths:
            continue
        if dry_run:
            print(f"  DRY archive (non-rep): {p.name}")
        else:
            shutil.move(str(p), str(keep_dir / p.name))
        removed += 1
    return removed


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--keep-existing-meta", action="store_true",
        help="既存 meta_*.json を退避しない (重複が起きる、検証用)"
    )
    args = ap.parse_args()

    decks = load_cardrush_decks()
    print(f"=== cardrush_*.json 読込: {len(decks)} 件 ===\n")

    reps = select_representative_per_archetype(decks)
    print(f"=== アーキタイプ {len(reps)} 種を代表選出 ===")
    for arch, d in sorted(reps.items()):
        print(f"  {arch:20s}  cardrush_{d['__path'].stem.split('_')[-1]:5s}  "
              f"{d.get('score','?')}  {d.get('tournament_date','?')}")
    print()

    if not args.keep_existing_meta:
        print("=== 既存メタを _archive/ へ退避 ===")
        archive_existing_meta(args.dry_run)
        print()

    print("=== 非代表 cardrush_*.json を _archive/cardrush_raw/ へ退避 ===")
    removed = remove_non_representative_cardrush(reps, args.dry_run)
    print(f"  移動: {removed} 件\n")

    if args.dry_run:
        print("(dry-run なので実ファイルは変更されていない)")
    else:
        remaining = sorted(DECKS_DIR.glob("*.json"))
        print(f"=== 完了: decks/ に残ったデッキファイル {len(remaining)} 件 ===")


if __name__ == "__main__":
    main()
