#!/usr/bin/env python3
"""multi-opponent corpus collector (= 2026-05-29、 task #46)。

GoalDirectedAI を 1 side 固定、 もう 1 side を {RandomAI, GreedyAI, PlanningAI, GoalDirectedAI}
で rotate。 全 16 deck × 16 deck で 各 opp 種別 × N games 蓄積。

[[feedback_corpus_methodology]]: corpus は raw、 derived/ で 集計。
[[feedback_adversarial_entry_mining]]: 対戦 相手 の 勝ち パターン を 後 から mine。
[[feedback_no_pipe_for_long_bg]]: pipe 禁止、 直接 file 出力。
[[feedback_progress_interval]]: 10 分 おき に 進捗 表示。

## 使い方

```bash
# smoke (= 1 deck × 4 opp × 2 game)
.venv/bin/python -u scripts/collect_corpus_multi_opponent.py \\
    --decks cardrush_1342 --opponents random greedy planning mirror \\
    --n-games 2 --workers 1 --round-name smoke

# 本番 (= 全 16 deck × 16 deck × 4 opp × 10 games = 10,240 試合)
ONEPIECE_AUDIT_INVARIANTS=1 nohup .venv/bin/python -u \\
    scripts/collect_corpus_multi_opponent.py \\
    --opponents random greedy planning mirror \\
    --n-games 10 --workers 8 --round-name round_1 \\
    > logs/corpus_collect_round1_$(date +%Y%m%d_%H%M).log 2>&1 &
```

出力: db/game_corpus/<round-name>/game_<seed>.json (= per-game JSON)
"""
from __future__ import annotations

# AUDIT default ON (= 学習 + 検証 統合、 [[feedback_corpus_methodology]])
import os
os.environ.setdefault("ONEPIECE_AUDIT_INVARIANTS", "1")

import argparse
import json
import multiprocessing
import random as _random
import sys
import time
import traceback
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

CARDS_JSON_PATH = REPO_ROOT / "db" / "cards.json"
CORPUS_ROOT = REPO_ROOT / "db" / "game_corpus"

DEFAULT_DECKS = [
    "cardrush_1342", "cardrush_1385", "cardrush_1392", "cardrush_1399",
    "cardrush_1439", "cardrush_1453", "cardrush_1454", "cardrush_1455",
    "cardrush_1456", "tcgportal_bonney", "tcgportal_calgara", "tcgportal_coby",
    "tcgportal_corazon", "tcgportal_hancock", "tcgportal_op11_luffy",
    "tcgportal_op13_luffy",
]

OPPONENT_CHOICES = ["random", "greedy", "planning", "mirror"]


# ===========================================================================
# AI factory (= side B 側 を rotate、 side A は 常に GoalDirectedAI)
# ===========================================================================


def _make_ai_factory(kind: str):
    """opponent kind → factory function (= rng, deck_analysis=None → AI instance)。"""
    if kind == "random":
        from engine.ai import RandomAI
        def factory(rng, deck_analysis=None):
            return RandomAI(rng=rng)
        factory.__name__ = "RandomAI_factory"
        factory._corpus_ai_class = "RandomAI"
        return factory
    if kind == "greedy":
        from engine.ai import GreedyAI
        def factory(rng, deck_analysis=None):
            return GreedyAI(rng=rng, deck_analysis=deck_analysis)
        factory.__name__ = "GreedyAI_factory"
        factory._corpus_ai_class = "GreedyAI"
        return factory
    if kind == "planning":
        from engine.ai import PlanningAI
        def factory(rng, deck_analysis=None):
            return PlanningAI(rng=rng, deck_analysis=deck_analysis,
                              beam_width=2, max_depth=4)  # = light (= 速度 優先)
        factory.__name__ = "PlanningAI_factory"
        factory._corpus_ai_class = "PlanningAI"
        return factory
    if kind == "mirror":
        from engine.goal_directed_ai import GoalDirectedAI
        def factory(rng, deck_analysis=None):
            return GoalDirectedAI(rng=rng, deck_analysis=deck_analysis,
                                   beam_width=2, max_depth=4)
        factory.__name__ = "GoalDirectedAI_factory_mirror"
        factory._corpus_ai_class = "GoalDirectedAI"
        return factory
    raise ValueError(f"unknown opponent kind: {kind}")


def _make_goal_factory():
    """side A 固定 = GoalDirectedAI (= 現 spec follow)。"""
    from engine.goal_directed_ai import GoalDirectedAI
    def factory(rng, deck_analysis=None):
        return GoalDirectedAI(rng=rng, deck_analysis=deck_analysis,
                               beam_width=2, max_depth=4)
    factory.__name__ = "GoalDirectedAI_factory_main"
    factory._corpus_ai_class = "GoalDirectedAI"
    return factory


# ===========================================================================
# cell worker (= 1 deck pair × 1 opp kind × N games)
# ===========================================================================


def _cell_worker(task: dict) -> dict:
    """1 cell の corpus 収集 (= multiprocessing.Pool 用)。

    task = {
        "deck_a_slug", "deck_b_slug", "opp_kind", "n_games",
        "seed_base", "round_name", "corpus_root"
    }
    """
    # spawn 後 の env 再 set (= ONEPIECE_AUDIT_INVARIANTS は 親 process から 継承 される)
    os.environ.setdefault("ONEPIECE_AUDIT_INVARIANTS", "1")

    deck_a_slug = task["deck_a_slug"]
    deck_b_slug = task["deck_b_slug"]
    opp_kind = task["opp_kind"]
    n_games = task["n_games"]
    seed_base = task["seed_base"]
    round_name = task["round_name"]
    corpus_root = Path(task["corpus_root"])

    try:
        from engine.deck import CardRepository, DeckList
        from engine.harness import run_matchup

        repo = CardRepository.from_json(CARDS_JSON_PATH)
        deck_a = DeckList.from_json(REPO_ROOT / "decks" / f"{deck_a_slug}.json", repo)
        deck_b = DeckList.from_json(REPO_ROOT / "decks" / f"{deck_b_slug}.json", repo)

        af_a = _make_goal_factory()
        af_b = _make_ai_factory(opp_kind)

        dump_dir = corpus_root / round_name / f"{deck_a_slug}_vs_{deck_b_slug}_{opp_kind}"
        dump_dir.mkdir(parents=True, exist_ok=True)

        rep = run_matchup(
            deck_a, deck_b,
            n_games=n_games,
            seed=seed_base,
            ai_factory_1=af_a,
            ai_factory_2=af_b,
            corpus_dump_dir=dump_dir,
            corpus_behavior_policy=f"goal_vs_{opp_kind}",
            enforce_rules=True,
            referee_strict=False,
            verbose=False,
        )
        return {
            "ok": True,
            "deck_a_slug": deck_a_slug,
            "deck_b_slug": deck_b_slug,
            "opp_kind": opp_kind,
            "n_games": n_games,
            "wins_a": rep.deck1_wins,
            "wins_b": rep.deck2_wins,
            "draws": rep.draws,
        }
    except Exception as e:
        return {
            "ok": False,
            "deck_a_slug": deck_a_slug,
            "deck_b_slug": deck_b_slug,
            "opp_kind": opp_kind,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


# ===========================================================================
# driver
# ===========================================================================


def _build_task_list(
    decks: list[str], opponents: list[str], n_games: int,
    seed_base: int, round_name: str, corpus_root: Path,
) -> list[dict]:
    """全 (deck_a, deck_b, opp_kind) cell を 列挙。"""
    tasks = []
    cell_idx = 0
    for a in decks:
        for b in decks:
            for opp in opponents:
                tasks.append({
                    "deck_a_slug": a,
                    "deck_b_slug": b,
                    "opp_kind": opp,
                    "n_games": n_games,
                    # cell 別 base seed (= 全 cell で 重複 ない ように cell_idx 経由)
                    "seed_base": seed_base + cell_idx * 100,
                    "round_name": round_name,
                    "corpus_root": str(corpus_root),
                })
                cell_idx += 1
    return tasks


def _count_violations_since(start_iso: str) -> int:
    """run 開始 後 の auto_issues file 数 を 数える。"""
    issues_dir = REPO_ROOT / "db" / "auto_issues"
    if not issues_dir.is_dir():
        return 0
    count = 0
    for p in issues_dir.glob("runtime_*.json"):
        # filename: runtime_TIMESTAMP_..., TIMESTAMP は UTC ISO YYYYMMDDTHHMMSSZ
        name = p.name
        idx = name.find("_") + 1
        end = name.find("_", idx)
        if end < 0:
            continue
        ts = name[idx:end]
        if ts >= start_iso:
            count += 1
    return count


def _print_violation_summary(start_iso: str) -> None:
    """audit_violation_watcher の logic を 流用 して 簡易 集計 出力。"""
    try:
        from scripts.audit_violation_watcher import scan_issues, print_report  # type: ignore
    except Exception:
        # path 問題 で import 失敗 → silent skip
        return
    meta, _ = scan_issues(since_ts=start_iso)
    print_report(meta, label=f"(since run start, n={meta['n_issues']})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--decks", nargs="*", default=DEFAULT_DECKS,
                    help=f"default = 16 deck pool ({len(DEFAULT_DECKS)} decks)")
    ap.add_argument("--opponents", nargs="*", default=OPPONENT_CHOICES,
                    choices=OPPONENT_CHOICES,
                    help="side B AI 種別 を rotate")
    ap.add_argument("--n-games", type=int, default=10)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed-base", type=int, default=1000)
    ap.add_argument("--round-name", type=str, required=True,
                    help="出力 dir 名 = db/game_corpus/<round-name>/")
    ap.add_argument("--limit-cells", type=int, default=None,
                    help="先頭 N cell のみ (= smoke test 用)")
    args = ap.parse_args()

    corpus_root = CORPUS_ROOT
    tasks = _build_task_list(args.decks, args.opponents, args.n_games,
                              args.seed_base, args.round_name, corpus_root)
    if args.limit_cells:
        tasks = tasks[:args.limit_cells]

    total_games = sum(t["n_games"] for t in tasks)
    print(f"[corpus] round={args.round_name}", flush=True)
    print(f"[corpus] decks: {len(args.decks)}, opponents: {args.opponents}", flush=True)
    print(f"[corpus] cells: {len(tasks):,}  total games: {total_games:,}", flush=True)
    print(f"[corpus] workers: {args.workers}", flush=True)
    print(f"[corpus] output: {corpus_root / args.round_name}", flush=True)
    print()

    t0 = time.time()
    # run 開始 UTC ISO (= violation filter 用)
    from datetime import datetime, timezone
    run_start_iso = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print(f"[corpus] run_start_utc: {run_start_iso}", flush=True)
    last_progress = t0

    results = []
    ok_cells = 0
    err_cells = 0
    completed_games = 0

    if args.workers <= 1:
        for i, task in enumerate(tasks):
            r = _cell_worker(task)
            results.append(r)
            if r.get("ok"):
                ok_cells += 1
                completed_games += task["n_games"]
            else:
                err_cells += 1
                print(f"  [{i+1}/{len(tasks)}] ERROR {task['deck_a_slug']}_vs_{task['deck_b_slug']}_{task['opp_kind']}: {r.get('error')}", flush=True)
            now = time.time()
            if now - last_progress > 60 or i < 5:
                elapsed = now - t0
                rate = (i + 1) / elapsed if elapsed > 0 else 0
                eta_s = (len(tasks) - i - 1) / rate if rate > 0 else 0
                print(f"  [{i+1}/{len(tasks)}] OK={ok_cells} ERR={err_cells} games={completed_games} "
                      f"elapsed={elapsed:.0f}s rate={rate*60:.1f}/min ETA={eta_s/60:.1f}min",
                      flush=True)
                last_progress = now
    else:
        with multiprocessing.Pool(args.workers) as pool:
            for i, r in enumerate(pool.imap_unordered(_cell_worker, tasks)):
                results.append(r)
                if r.get("ok"):
                    ok_cells += 1
                    completed_games += r["n_games"]
                else:
                    err_cells += 1
                    print(f"  [{i+1}/{len(tasks)}] ERROR: {r.get('error')}", flush=True)
                now = time.time()
                # [[feedback_progress_interval]]: 長時間 batch は 10 min おきに 進捗
                if now - last_progress > 60 or i < 5:
                    elapsed = now - t0
                    rate = (i + 1) / elapsed if elapsed > 0 else 0
                    eta_s = (len(tasks) - i - 1) / rate if rate > 0 else 0
                    # violation 数 を 計算 (= run 開始 後 のみ、 file 名 timestamp で 絞り込み)
                    vio_count = _count_violations_since(run_start_iso)
                    print(f"  [{i+1}/{len(tasks)}] OK={ok_cells} ERR={err_cells} games={completed_games} "
                          f"violations={vio_count} "
                          f"elapsed={elapsed:.0f}s rate={rate*60:.1f}/min ETA={eta_s/60:.1f}min",
                          flush=True)
                    last_progress = now
                    # 100 cell おき に violation pattern 詳細
                    if (i + 1) % 100 == 0 and vio_count > 0:
                        _print_violation_summary(run_start_iso)

    elapsed = time.time() - t0
    print()
    print("=" * 60, flush=True)
    print(f"[corpus] DONE: {ok_cells} cells ok, {err_cells} cells err", flush=True)
    print(f"[corpus] total games: {completed_games:,} / target {total_games:,}", flush=True)
    print(f"[corpus] elapsed: {elapsed:.0f}s = {elapsed/60:.1f} min", flush=True)

    # corpus 容量
    dump_root = corpus_root / args.round_name
    if dump_root.exists():
        total_size = sum(p.stat().st_size for p in dump_root.rglob("*.json"))
        total_files = sum(1 for _ in dump_root.rglob("*.json"))
        print(f"[corpus] size: {total_size/1024/1024:.1f} MB across {total_files:,} files", flush=True)

    # summary を JSON で 出力 (= 集計 script の input 用)
    summary_path = dump_root / "_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps({
        "round_name": args.round_name,
        "decks": args.decks,
        "opponents": args.opponents,
        "n_games_per_cell": args.n_games,
        "ok_cells": ok_cells,
        "err_cells": err_cells,
        "total_games": completed_games,
        "elapsed_s": round(elapsed, 1),
        "cell_results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[corpus] summary: {summary_path.relative_to(REPO_ROOT)}", flush=True)


if __name__ == "__main__":
    main()
