#!/usr/bin/env python3
"""post-round pipeline (= 2026-05-29、 task #49 続)。

corpus dir を 受け取り、 mining + bonus learning + build_spec + mirror eval (= A/B)
を 自動 実行。 round_1_quick / round_2_full 完了 後 1 発 で 結果 を 出す。

## 使い方

```bash
# 全 工程 (= ~80 min for 16 deck eval at 5 games)
.venv/bin/python -u scripts/round_pipeline.py \\
    --corpus-dir db/game_corpus/round_1_quick \\
    --eval-n-games 5 \\
    --eval-decks all

# eval スキップ で 単純 spec 生成 のみ
.venv/bin/python scripts/round_pipeline.py \\
    --corpus-dir db/game_corpus/round_2_full \\
    --skip-eval

# 限定 deck で 高速 検証
.venv/bin/python scripts/round_pipeline.py \\
    --corpus-dir db/game_corpus/round_1_quick \\
    --eval-decks cardrush_1342 tcgportal_coby \\
    --eval-n-games 10
```

## 工程

1. corpus sanity check (= file 数 + 1 game inspect)
2. mining (= mine_entries_from_opponents.py)
3. bonus learning (= learn_bonus_off_policy.py)
4. backup current decks/*.target_v1.json → db/spec_backups/<timestamp>/
5. build_spec_from_corpus → 新 spec を decks/ に 書く
6. mirror eval with 新 spec → 結果 記録
7. restore 旧 spec from backup
8. mirror eval with 旧 spec → 結果 記録
9. delta_pt 比較 + report 出力
10. 新 spec を 再 配置 (= decks/ に back) — ohtsuki さん 採用 判断 用

出力: db/derived/round_pipeline/<round_name>/report.json
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DECKS_DIR = REPO_ROOT / "decks"
BACKUP_ROOT = REPO_ROOT / "db" / "spec_backups"
DERIVED_ROOT = REPO_ROOT / "db" / "derived" / "round_pipeline"
PY = str(REPO_ROOT / ".venv" / "bin" / "python")

DEFAULT_DECKS = [
    "cardrush_1342", "cardrush_1385", "cardrush_1392", "cardrush_1399",
    "cardrush_1439", "cardrush_1453", "cardrush_1454", "cardrush_1455",
    "cardrush_1456", "tcgportal_bonney", "tcgportal_calgara", "tcgportal_coby",
    "tcgportal_corazon", "tcgportal_hancock", "tcgportal_op11_luffy",
    "tcgportal_op13_luffy",
]


def sanity_check_corpus(corpus_dir: Path) -> dict:
    """corpus dir の 中身 を 軽く 検証。"""
    game_files = list(corpus_dir.rglob("game_*.json"))
    n_files = len(game_files)
    if n_files == 0:
        raise RuntimeError(f"no game files in {corpus_dir}")
    sample = json.loads(game_files[0].read_text(encoding="utf-8"))
    return {
        "n_files": n_files,
        "sample_seed": sample.get("seed"),
        "sample_actions": len(sample.get("actions", [])),
        "sample_winner": (sample.get("result") or {}).get("winner_for_deck_a"),
    }


def run_mining(corpus_dir: Path, min_count: int) -> Path:
    """adversarial mining → candidates.json。"""
    out_path = REPO_ROOT / "db" / "derived" / "adversarial_entries" / corpus_dir.name / "candidates.json"
    cmd = [
        PY, "-u", "scripts/mine_entries_from_opponents.py",
        "--corpus-dir", str(corpus_dir),
        "--min-count", str(min_count),
        "--output", str(out_path),
        "--top", "20",
    ]
    print(f"[pipeline] running mining (min_count={min_count})...", flush=True)
    r = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        print(f"[pipeline] mining ERROR: {r.stderr[-1000:]}", flush=True)
        return Path()
    print(f"  → {out_path.relative_to(REPO_ROOT)}", flush=True)
    return out_path


def run_learning(corpus_dir: Path, min_count: int) -> Path:
    """off-policy bonus learning → value_table.json。"""
    out_path = REPO_ROOT / "db" / "derived" / "bonus_learning" / corpus_dir.name / "value_table.json"
    cmd = [
        PY, "-u", "scripts/learn_bonus_off_policy.py",
        "--corpus-dir", str(corpus_dir),
        "--min-count", str(min_count),
        "--output", str(out_path),
        "--top", "20",
    ]
    print(f"[pipeline] running bonus learning (min_count={min_count})...", flush=True)
    r = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        print(f"[pipeline] learning ERROR: {r.stderr[-1000:]}", flush=True)
        return Path()
    print(f"  → {out_path.relative_to(REPO_ROOT)}", flush=True)
    return out_path


def backup_decks() -> Path:
    """現 decks/*.target_v1.json を backup dir に コピー。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = BACKUP_ROOT / ts
    backup_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in DECKS_DIR.glob("*.target_v1.json"):
        shutil.copy(p, backup_dir / p.name)
        n += 1
    print(f"[pipeline] backed up {n} spec files to {backup_dir.relative_to(REPO_ROOT)}",
          flush=True)
    return backup_dir


def restore_decks(backup_dir: Path) -> int:
    """backup から 現 decks/ に コピー (= 元 spec 復元)。"""
    n = 0
    for p in backup_dir.glob("*.target_v1.json"):
        shutil.copy(p, DECKS_DIR / p.name)
        n += 1
    print(f"[pipeline] restored {n} spec files from {backup_dir.relative_to(REPO_ROOT)}",
          flush=True)
    return n


def run_build_spec(corpus_dir: Path, min_count: int, baseline: float, scale: float) -> int:
    """build_spec_from_corpus → decks/ 上書き。"""
    cmd = [
        PY, "-u", "scripts/build_spec_from_corpus.py",
        "--corpus-dir", str(corpus_dir),
        "--output-dir", str(DECKS_DIR),
        "--min-count", str(min_count),
        "--baseline", str(baseline),
        "--scale", str(scale),
    ]
    print(f"[pipeline] running build_spec ...", flush=True)
    r = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        print(f"[pipeline] build_spec ERROR: {r.stderr[-1000:]}", flush=True)
        return 0
    # output 末尾 から written count 抽出
    for line in r.stdout.splitlines():
        print(f"  {line}", flush=True)
    return 1


def run_mirror_eval(decks: list[str], n_games: int, seed: int = 42) -> dict:
    """eval_goal_directed_mirror.py を deck 別 に 走らせて 結果 集計。

    Returns: {deck_slug: {wins, losses, draws, winrate, delta_pt}}
    """
    results = {}
    t0 = time.time()
    for i, slug in enumerate(decks):
        print(f"  [{i+1}/{len(decks)}] eval {slug} ...", flush=True)
        cmd = [
            PY, "-u", "scripts/eval_goal_directed_mirror.py",
            "--decks", slug,
            "--n-games", str(n_games),
            "--seeds", str(seed),
        ]
        try:
            r = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True,
                              timeout=300)
        except subprocess.TimeoutExpired:
            print(f"      ⚠ timeout 300s → skip", flush=True)
            results[slug] = {"wins": 0, "losses": 0, "draws": 0,
                             "winrate": 0.0, "delta_pt": 0.0, "timeout": True}
            continue
        # parse output
        import re as _re
        wins = losses = draws = 0
        winrate = 0.0
        delta_pt = 0.0
        for line in r.stdout.splitlines():
            m = _re.search(r"DONE:\s+(\d+)W-(\d+)L\s+\(draws=(\d+)\)\s+winrate=([\d.]+)\s+delta=([+-]?[\d.]+)pt", line)
            if m:
                wins = int(m.group(1))
                losses = int(m.group(2))
                draws = int(m.group(3))
                winrate = float(m.group(4))
                delta_pt = float(m.group(5))
        results[slug] = {
            "wins": wins, "losses": losses, "draws": draws,
            "winrate": round(winrate, 3),
            "delta_pt": delta_pt,
        }
        print(f"      W={wins} L={losses} D={draws} winrate={winrate:.0%} delta={delta_pt:+.1f}pt",
              flush=True)
    elapsed = time.time() - t0
    print(f"[pipeline] mirror eval done in {elapsed:.0f}s = {elapsed/60:.1f} min", flush=True)
    return results


def compute_delta_report(old_results: dict, new_results: dict) -> dict:
    """旧/新 比較 report。"""
    deltas = []
    for slug in sorted(set(old_results) | set(new_results)):
        o = old_results.get(slug, {})
        n = new_results.get(slug, {})
        old_dp = o.get("delta_pt", 0.0)
        new_dp = n.get("delta_pt", 0.0)
        deltas.append({
            "deck": slug,
            "old_delta_pt": old_dp,
            "new_delta_pt": new_dp,
            "improvement_pt": round(new_dp - old_dp, 2),
        })
    avg_old = sum(d["old_delta_pt"] for d in deltas) / max(1, len(deltas))
    avg_new = sum(d["new_delta_pt"] for d in deltas) / max(1, len(deltas))
    return {
        "deltas": deltas,
        "avg_old_delta_pt": round(avg_old, 2),
        "avg_new_delta_pt": round(avg_new, 2),
        "avg_improvement_pt": round(avg_new - avg_old, 2),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus-dir", type=Path, required=True)
    ap.add_argument("--min-count", type=int, default=5)
    ap.add_argument("--baseline", type=float, default=1500.0)
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--eval-decks", nargs="*", default=None,
                    help="default = 16 deck pool、 'all' で 同じ")
    ap.add_argument("--eval-n-games", type=int, default=5)
    ap.add_argument("--eval-seed", type=int, default=42)
    ap.add_argument("--skip-eval", action="store_true",
                    help="mining + learning + build_spec のみ、 mirror eval スキップ")
    ap.add_argument("--keep-new-spec", action="store_true",
                    help="eval 後 に 新 spec を decks/ に 残す (= default は 残す)")
    args = ap.parse_args()

    if not args.corpus_dir.is_dir():
        print(f"ERROR: corpus dir not found: {args.corpus_dir}", file=sys.stderr)
        sys.exit(1)

    t_global = time.time()
    print(f"=== round_pipeline for {args.corpus_dir.name} ===", flush=True)
    print(f"corpus: {args.corpus_dir}", flush=True)
    print()

    # 1. sanity check
    print("=== step 1: sanity check ===", flush=True)
    sanity = sanity_check_corpus(args.corpus_dir)
    print(f"  games: {sanity['n_files']:,}", flush=True)
    print(f"  sample: seed={sanity['sample_seed']} actions={sanity['sample_actions']} winner={sanity['sample_winner']}",
          flush=True)
    print()

    # 2. mining + learning (= parallel 可能 だが 単純 順 実行)
    print("=== step 2-3: mining + bonus learning ===", flush=True)
    run_mining(args.corpus_dir, args.min_count)
    run_learning(args.corpus_dir, args.min_count)
    print()

    # eval 用 deck list
    decks = args.eval_decks or DEFAULT_DECKS
    if decks == ["all"]:
        decks = DEFAULT_DECKS

    # 3. backup current spec (= 旧 git HEAD spec)
    print("=== step 4: backup current decks/ ===", flush=True)
    backup_dir = backup_decks()
    print()

    # 4. build new spec → 上書き
    print("=== step 5: build_spec ===", flush=True)
    run_build_spec(args.corpus_dir, args.min_count, args.baseline, args.scale)
    print()

    if args.skip_eval:
        print("[pipeline] skip-eval, exiting", flush=True)
        return

    # 5. eval new spec
    print(f"=== step 6: mirror eval NEW spec ({len(decks)} decks × {args.eval_n_games} games) ===",
          flush=True)
    new_results = run_mirror_eval(decks, args.eval_n_games, args.eval_seed)
    print()

    # 6. restore old spec
    print("=== step 7: restore OLD spec ===", flush=True)
    restore_decks(backup_dir)
    print()

    # 7. eval old spec
    print(f"=== step 8: mirror eval OLD spec ===", flush=True)
    old_results = run_mirror_eval(decks, args.eval_n_games, args.eval_seed)
    print()

    # 8. delta report
    print("=== step 9: delta report ===", flush=True)
    report = compute_delta_report(old_results, new_results)
    print(f"  avg OLD delta: {report['avg_old_delta_pt']:+.2f}pt", flush=True)
    print(f"  avg NEW delta: {report['avg_new_delta_pt']:+.2f}pt", flush=True)
    print(f"  avg IMPROVEMENT: {report['avg_improvement_pt']:+.2f}pt", flush=True)
    print()
    print("  per-deck breakdown (sorted by improvement):", flush=True)
    for d in sorted(report["deltas"], key=lambda x: -x["improvement_pt"]):
        marker = "✓" if d["improvement_pt"] > 1.0 else "→" if abs(d["improvement_pt"]) <= 1.0 else "✗"
        print(f"    {marker} {d['deck']:22s}  OLD={d['old_delta_pt']:+6.1f}  NEW={d['new_delta_pt']:+6.1f}  Δ={d['improvement_pt']:+6.1f}pt",
              flush=True)
    print()

    # 9. 新 spec を 戻して 採用 状態 で 終わる (= ohtsuki さん 採用 判断 用)
    if args.keep_new_spec or report["avg_improvement_pt"] > 0:
        print("=== step 10: re-apply NEW spec (= avg improvement positive or --keep-new-spec) ===",
              flush=True)
        # backup → temp, build_spec を 再 実行 で 上書き
        # → backup ディレクトリ に は 「OLD」、 decks/ に は 「NEW」 が 復活
        # 簡単 化: build_spec 再 実行
        run_build_spec(args.corpus_dir, args.min_count, args.baseline, args.scale)
    else:
        print("=== step 10: keep OLD spec (= avg improvement non-positive) ===", flush=True)

    # report 出力
    out_dir = DERIVED_ROOT / args.corpus_dir.name
    out_dir.mkdir(parents=True, exist_ok=True)
    full_report = {
        "corpus_dir": str(args.corpus_dir.relative_to(REPO_ROOT)),
        "config": {
            "min_count": args.min_count,
            "baseline": args.baseline,
            "scale": args.scale,
            "eval_n_games": args.eval_n_games,
            "eval_seed": args.eval_seed,
            "eval_decks": decks,
        },
        "sanity": sanity,
        "backup_dir": str(backup_dir.relative_to(REPO_ROOT)),
        "old_results": old_results,
        "new_results": new_results,
        "delta_report": report,
        "elapsed_s": round(time.time() - t_global, 1),
    }
    out_path = out_dir / "report.json"
    out_path.write_text(json.dumps(full_report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[pipeline] report: {out_path.relative_to(REPO_ROOT)}", flush=True)
    print(f"[pipeline] total elapsed: {(time.time() - t_global)/60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
