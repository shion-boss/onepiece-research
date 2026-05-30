#!/usr/bin/env python3
"""round X vs round Y spec の 学習効果 数値化 (= task #13、 2026-05-29)。

各 round の spec snapshot (= db/bonus_rounds/round_N/*.target_v1.json) を 順次
decks/ に swap → GoalDirectedAI 16 deck self-mirror → 勝率 集計。
swap 後 は backup 復元 で 元 状態 を 保持。

## 使い方

```bash
.venv/bin/python scripts/compare_round_specs.py --round-a 1 --round-b 5 --n-games 20 --workers 8
```

出力:
- db/bonus_rounds/comparison_<A>_vs_<B>.json
- delta_pt per deck + 平均
"""
from __future__ import annotations

# AUDIT default ON (= 学習 + 検証 統合)
import os
os.environ.setdefault("ONEPIECE_AUDIT_INVARIANTS", "1")

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DECKS_DIR = REPO_ROOT / "decks"
ROUNDS_DIR = REPO_ROOT / "db" / "bonus_rounds"
PY = str(REPO_ROOT / ".venv" / "bin" / "python")


def _list_meta_pool_decks() -> list[str]:
    """meta_pool に 載っている current deck slugs。"""
    pool_path = REPO_ROOT / "db" / "meta_pool.json"
    if pool_path.exists():
        meta = json.loads(pool_path.read_text(encoding="utf-8"))
        decks = meta.get("decks", meta.get("current", []))
        if isinstance(decks, list):
            return [d.get("slug", "") if isinstance(d, dict) else str(d) for d in decks if d]
    # fallback: decks/*.target_v1.json の slug
    return sorted({p.stem.replace(".target_v1", "") for p in DECKS_DIR.glob("*.target_v1.json")})


def _swap_round_specs(round_dir: Path, dry_run: bool = False) -> list[Path]:
    """round_dir 内 の target_v1 spec を decks/ に コピー (= 既存 上書き)。
    swap した file path を 返す (= 後で 復元 用)。
    """
    src_specs = list(round_dir.glob("*.target_v1.json"))
    swapped = []
    for src in src_specs:
        dst = DECKS_DIR / src.name
        if dry_run:
            print(f"  would swap: {src.name}")
        else:
            shutil.copy(src, dst)
        swapped.append(dst)
    return swapped


def _run_mirror_eval(deck_slugs: list[str], n_games: int, workers: int, seed: int,
                      label: str) -> dict:
    """GoalDirectedAI mirror eval を 1 deck ずつ 走らせて 勝率 集計。"""
    results = {}
    t0 = time.time()
    for i, slug in enumerate(deck_slugs):
        print(f"  [{i+1}/{len(deck_slugs)}] {slug} ({label}) ...", flush=True)
        cmd = [
            PY, "-u", "scripts/eval_goal_directed_mirror.py",
            "--decks", slug,
            "--n-games", str(n_games),
            "--seeds", str(seed),
        ]
        # per-deck timeout = 5 分 (= [[project_long_game_pathology]] 対策)
        try:
            r = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            print(f"      ⚠ {slug} ({label}): timeout 300s → skip", flush=True)
            results[slug] = {
                "wins": 0, "losses": 0, "draws": 0,
                "total": 0, "win_rate_pt": 0.0, "delta_pt": 0.0,
                "timeout": True,
            }
            continue
        # eval_goal_directed_mirror.py 出力 format:
        # 「seed=N DONE: WW-LL (draws=D) winrate=0.XXX delta=+X.Xpt [Xs total]」
        wins, losses, draws = 0, 0, 0
        delta_pt = 0.0
        winrate = 0.0
        import re as _re
        for line in r.stdout.splitlines():
            m = _re.search(r"DONE:\s+(\d+)W-(\d+)L\s+\(draws=(\d+)\)\s+winrate=([\d.]+)\s+delta=([+-]?[\d.]+)pt", line)
            if m:
                wins = int(m.group(1))
                losses = int(m.group(2))
                draws = int(m.group(3))
                winrate = float(m.group(4))
                delta_pt = float(m.group(5))
        total = wins + losses + draws
        results[slug] = {
            "wins": wins, "losses": losses, "draws": draws,
            "total": total,
            "win_rate_pt": round(winrate * 100, 2),
            "delta_pt": delta_pt,
        }
        print(f"      {slug}: W={wins} L={losses} D={draws} → {round(winrate*100, 2)}% "
              f"(delta vs PlanningAI: {delta_pt:+.1f}pt)", flush=True)
    elapsed = time.time() - t0
    return {"label": label, "results": results, "elapsed_s": round(elapsed, 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--round-a", type=str, required=True, help="baseline round name (= int or '5_after' 等)")
    ap.add_argument("--round-b", type=str, required=True, help="comparison round name")
    ap.add_argument("--n-games", type=int, default=20)
    ap.add_argument("--workers", type=int, default=8, help="(現状 未使用、 1 deck per subprocess)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--decks", nargs="*", default=None, help="特定 deck のみ (default: meta_pool 全件)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    round_a_dir = ROUNDS_DIR / f"round_{args.round_a}"
    round_b_dir = ROUNDS_DIR / f"round_{args.round_b}"
    if not round_a_dir.is_dir():
        print(f"ERROR: {round_a_dir} not found", file=sys.stderr)
        sys.exit(1)
    if not round_b_dir.is_dir():
        print(f"ERROR: {round_b_dir} not found", file=sys.stderr)
        sys.exit(1)

    deck_slugs = args.decks or _list_meta_pool_decks()
    print(f"comparing round_{args.round_a} vs round_{args.round_b}")
    print(f"decks: {deck_slugs}")
    print(f"n_games={args.n_games}, seed={args.seed}")
    print()

    # 現 状態 (= round 5 = 最新) を 一時 退避
    backup_dir = ROUNDS_DIR / f"_pre_compare_backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    print(f"backup current → {backup_dir.relative_to(REPO_ROOT)}")
    for p in DECKS_DIR.glob("*.target_v1.json"):
        shutil.copy(p, backup_dir / p.name)
    print()

    try:
        # round A
        print(f"=== round {args.round_a} (baseline) ===")
        _swap_round_specs(round_a_dir, dry_run=args.dry_run)
        result_a = _run_mirror_eval(deck_slugs, args.n_games, args.workers, args.seed,
                                    f"round_{args.round_a}")
        print()

        # round B
        print(f"=== round {args.round_b} (comparison) ===")
        _swap_round_specs(round_b_dir, dry_run=args.dry_run)
        result_b = _run_mirror_eval(deck_slugs, args.n_games, args.workers, args.seed,
                                    f"round_{args.round_b}")
        print()

        # delta 集計
        deltas = []
        for slug in deck_slugs:
            a = result_a["results"].get(slug, {}).get("win_rate_pt", 0)
            b = result_b["results"].get(slug, {}).get("win_rate_pt", 0)
            deltas.append({"deck": slug, "round_a_pt": a, "round_b_pt": b, "delta_pt": round(b - a, 2)})

        avg_a = sum(d["round_a_pt"] for d in deltas) / max(1, len(deltas))
        avg_b = sum(d["round_b_pt"] for d in deltas) / max(1, len(deltas))
        avg_delta = sum(d["delta_pt"] for d in deltas) / max(1, len(deltas))

        report = {
            "round_a": args.round_a,
            "round_b": args.round_b,
            "n_games": args.n_games,
            "seed": args.seed,
            "round_a_results": result_a,
            "round_b_results": result_b,
            "deltas": deltas,
            "summary": {
                "avg_round_a_pt": round(avg_a, 2),
                "avg_round_b_pt": round(avg_b, 2),
                "avg_delta_pt": round(avg_delta, 2),
            },
        }
        out_path = ROUNDS_DIR / f"comparison_{args.round_a}_vs_{args.round_b}.json"
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                            encoding="utf-8")

        print("=" * 60)
        print(f"avg round_{args.round_a}: {round(avg_a, 2)}%")
        print(f"avg round_{args.round_b}: {round(avg_b, 2)}%")
        print(f"avg Δpt          : {round(avg_delta, 2):+.2f}")
        print()
        print("per-deck delta:")
        for d in sorted(deltas, key=lambda x: -x["delta_pt"]):
            print(f"  {d['deck']:20s} {d['round_a_pt']:6.2f} → {d['round_b_pt']:6.2f} "
                  f"({d['delta_pt']:+6.2f})")
        print()
        print(f"output: {out_path.relative_to(REPO_ROOT)}")
    finally:
        # 復元: backup から
        print()
        print("restoring decks/ from backup ...")
        for p in backup_dir.glob("*.target_v1.json"):
            shutil.copy(p, DECKS_DIR / p.name)
        shutil.rmtree(backup_dir)
        print("done")


if __name__ == "__main__":
    main()
