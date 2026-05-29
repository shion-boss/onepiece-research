#!/usr/bin/env python3
"""bonus 学習用 fire log 生成 (= 2026-05-26)。

`db/meta_pool.json` の current pool 内 全 deck × 全 deck (= 16×16) で
N games の matchup を 走らせ、 各試合 で どの target entry が 何回 fire したか + 勝敗 を log。

# 出力

`db/target_fire_log.json`:
```json
{
  "meta_pool_iteration": 1,
  "n_games_per_cell": 5,
  "completed_cells": [[0,1], [0,2], ...],
  "games": [
    {
      "deck_a": "cardrush_1342", "deck_b": "cardrush_1385",
      "game_idx": 0, "winner_for_deck_a": 1,
      "fire_counts_a": {"cardrush_1342#3": 12, "generic#15": 8, ...},
      "fire_counts_b": {...}
    }, ...
  ]
}
```

# 使い方

```bash
# 全 16×16 × 5g = 1280 試合 (= 検証 用 軽量)
.venv/bin/python scripts/eval_with_entry_firings.py --n-games 5 --seed 42

# 中規模 (= 16×16 × 20g = 5120 試合)
.venv/bin/python scripts/eval_with_entry_firings.py --n-games 20 --seed 42

# resume (= 既存 fire log を 読んで 未完成 cell から 続行)
.venv/bin/python scripts/eval_with_entry_firings.py --n-games 5 --resume
```

# checkpoint + resume

各 cell (= deck_a × deck_b) 完了 後 に file 書き戻し。 途中中断 しても resume で 続行可能。
"""

from __future__ import annotations

# === 真 Phase 1.0 (= GoalDirectedAI lookup-driven) を 必ず有効化 ===
# engine/plan_search.py:_USE_GOAL_DERIVE は module-level で env を read する。
# 必ず 他 import より 上 で set すること (= fork 後の env 変更は反映されない)。
import os
os.environ.setdefault("ONEPIECE_GOAL_DERIVE", "1")
# 2026-05-29: 学習 で AUDIT default ON (= violations + effect_events 自動 蓄積)
os.environ.setdefault("ONEPIECE_AUDIT_INVARIANTS", "1")

import argparse
import json
import multiprocessing as mp
import sys
import time
import traceback
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from engine.deck import DeckList, CardRepository  # noqa: E402
from engine.harness import run_matchup  # noqa: E402


def light_ai_factory(rng, deck_analysis=None):
    """軽量 GoalDirectedAI (= beam=2, depth=4、 adaptive=False)。

    bonus 学習 eval 用。 default GoalDirectedAI (= beam=4, depth=6, adaptive=True) は
    target spec 込で 1 試合 ~8 分 と 重い (= 16x16 × 5g = 178h)。 軽量設定で 4-8x 加速。
    """
    from engine.goal_directed_ai import GoalDirectedAI
    return GoalDirectedAI(
        rng=rng,
        deck_analysis=deck_analysis,
        adaptive=False,
        beam_width=2,
        max_depth=4,
        spec_version="v1",
    )


def greedy_ai_factory(rng, deck_analysis=None):
    """固定 baseline opponent (= 学習対象 と alternating で 走らせる、 self-play noise 排除)。"""
    from engine.ai import GreedyAI
    return GreedyAI(rng=rng, deck_analysis=deck_analysis)


META_POOL_PATH = REPO_ROOT / "db" / "meta_pool.json"
FIRE_LOG_PATH = REPO_ROOT / "db" / "target_fire_log.json"
ERR_LOG_PATH = REPO_ROOT / "db" / "target_fire_log_errors.ndjson"
DECKS_DIR = REPO_ROOT / "decks"
CARDS_JSON = REPO_ROOT / "db" / "cards.json"


def _cell_worker(task: dict) -> dict:
    """並列 worker: 1 cell (= deck_a vs deck_b) を n_games 走らせて 結果 dict を返す。

    task = {
        "i", "j", "slug_a", "slug_b",
        "deck_a_path", "deck_b_path",
        "n_games", "base_seed", "ai_mode", "opponent",
    }
    opponent: "self" = 両側 GoalDirected (= 旧 self-play)
              "greedy" = alternating side swap で 学習対象 vs GreedyAI
    """
    # 環境 setup (= fork 後 でも spawn でも 動くよう defensive set)
    import os
    os.environ.setdefault("ONEPIECE_GOAL_DERIVE", "1")
    os.environ.setdefault("ONEPIECE_AUDIT_INVARIANTS", "1")
    import traceback
    try:
        # lazy import (= worker 起動 時 import で env を 確実 反映)
        from engine.deck import DeckList, CardRepository
        from engine.harness import run_matchup

        i = task["i"]
        j = task["j"]
        slug_a = task["slug_a"]
        slug_b = task["slug_b"]
        n_games = task["n_games"]
        base_seed = task["base_seed"]
        ai_mode = task["ai_mode"]
        opponent = task["opponent"]

        repo = CardRepository.from_json(str(CARDS_JSON))
        deck_a = DeckList.from_json(task["deck_a_path"], repo)
        deck_b = DeckList.from_json(task["deck_b_path"], repo)

        # AI factory 構築
        goal_factory = light_ai_factory if ai_mode == "light" else None
        # ai_mode "default" は run_matchup の default (= 完全 GoalDirectedAI) に任せる
        greedy_factory = greedy_ai_factory

        games_out = []
        for g_idx in range(n_games):
            if opponent == "greedy":
                # alternating side swap = 両 deck が 学習信号 を 受ける
                if g_idx % 2 == 0:
                    af1, af2, goal_side = goal_factory, greedy_factory, 0
                else:
                    af1, af2, goal_side = greedy_factory, goal_factory, 1
            else:  # "self"
                af1, af2, goal_side = goal_factory, goal_factory, None

            kwargs = {}
            if af1 is not None:
                kwargs["ai_factory_1"] = af1
            if af2 is not None:
                kwargs["ai_factory_2"] = af2

            rep = run_matchup(
                deck_a, deck_b,
                n_games=1, seed=base_seed + g_idx,
                enable_fire_logging=True,
                **kwargs,
            )
            g = rep.games[0]
            games_out.append({
                "deck_a": slug_a,
                "deck_b": slug_b,
                "game_idx": g_idx,
                "winner_for_deck_a": g.winner,
                "first_player": g.first_player,
                "turns": g.turns,
                "fire_counts_a": g.fire_counts[0],
                "fire_counts_b": g.fire_counts[1],
                "goal_side": goal_side,
            })

        return {
            "ok": True,
            "i": i, "j": j, "slug_a": slug_a, "slug_b": slug_b,
            "games": games_out,
        }
    except Exception as e:
        return {
            "ok": False,
            "i": task.get("i"), "j": task.get("j"),
            "slug_a": task.get("slug_a"), "slug_b": task.get("slug_b"),
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


def load_meta_pool() -> dict:
    return json.loads(META_POOL_PATH.read_text(encoding="utf-8"))


def load_fire_log() -> Optional[dict]:
    if not FIRE_LOG_PATH.exists():
        return None
    try:
        return json.loads(FIRE_LOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_fire_log(log: dict) -> None:
    FIRE_LOG_PATH.write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-games", type=int, default=5, help="cell ごと 試合数 (= 軽量検証なら 5、 本番 20)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--resume", action="store_true", help="既存 fire log を 読んで 未完成 cell から 続行")
    ap.add_argument("--limit-cells", type=int, default=None, help="先頭 N cells のみ (= debug)")
    ap.add_argument("--limit-decks", type=int, default=None, help="先頭 N decks のみ で 縮小 matrix")
    ap.add_argument(
        "--ai-mode", choices=["default", "light"], default="light",
        help="default=GoalDirectedAI 標準 (= 1g 8 分)、 light=beam=2 depth=4 (= 1g 1-2 分)",
    )
    ap.add_argument(
        "--workers", type=int, default=1,
        help="並列 worker 数 (default 1 = sequential、 推奨 8)",
    )
    ap.add_argument(
        "--opponent", choices=["self", "greedy"], default="self",
        help="self = 両側 学習対象 AI (= self-play)、 greedy = 学習対象 vs GreedyAI alternating (= clean baseline)",
    )
    args = ap.parse_args()

    pool = load_meta_pool()
    iteration = pool["current"]["iteration"]
    slugs = pool["current"]["slugs"]
    if args.limit_decks:
        slugs = slugs[: args.limit_decks]
    print(f"meta pool iteration {iteration}: {len(slugs)} decks (ai_mode={args.ai_mode})")

    repo = CardRepository.from_json(str(CARDS_JSON))
    decks = {}
    for slug in slugs:
        p = DECKS_DIR / f"{slug}.json"
        decks[slug] = DeckList.from_json(str(p), repo)

    # 既存 log 読み込み (= resume 用)
    if args.resume and FIRE_LOG_PATH.exists():
        log = load_fire_log() or {}
        if log.get("meta_pool_iteration") != iteration:
            print(f"WARN: 既存 log iteration={log.get('meta_pool_iteration')} != current={iteration}, 上書き")
            log = None
    else:
        log = None

    if log is None:
        log = {
            "meta_pool_iteration": iteration,
            "n_games_per_cell": args.n_games,
            "completed_cells": [],
            "games": [],
        }

    completed = set(tuple(c) for c in log["completed_cells"])

    # 16×16 cell を 順番に
    all_cells = [(i, j) for i in range(len(slugs)) for j in range(len(slugs))]
    if args.limit_cells:
        all_cells = all_cells[: args.limit_cells]
    todo_cells = [c for c in all_cells if c not in completed]

    print(f"cells: total={len(all_cells)}, completed={len(completed)}, todo={len(todo_cells)}")

    # task list を 構築 (= worker 用、 path で 渡す)
    tasks = []
    for (i, j) in todo_cells:
        slug_a, slug_b = slugs[i], slugs[j]
        tasks.append({
            "i": i, "j": j,
            "slug_a": slug_a, "slug_b": slug_b,
            "deck_a_path": str(DECKS_DIR / f"{slug_a}.json"),
            "deck_b_path": str(DECKS_DIR / f"{slug_b}.json"),
            "n_games": args.n_games,
            "base_seed": args.seed + i * 1000 + j,
            "ai_mode": args.ai_mode,
            "opponent": args.opponent,
        })

    print(f"opponent={args.opponent}, workers={args.workers}", flush=True)
    t0 = time.time()

    def _consume_result(result, ci):
        """1 cell の結果 を log に 追記 + 進捗 print。"""
        slug_a = result["slug_a"]
        slug_b = result["slug_b"]
        if not result.get("ok"):
            err_line = json.dumps(
                {"i": result["i"], "j": result["j"], "slug_a": slug_a, "slug_b": slug_b,
                 "error": result.get("error"), "traceback": result.get("traceback")},
                ensure_ascii=False,
            )
            with open(ERR_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(err_line + "\n")
            print(f"  [{ci}/{len(todo_cells)}] ERROR {slug_a} vs {slug_b}: {result.get('error')}", flush=True)
            return
        log["games"].extend(result["games"])
        log["completed_cells"].append([result["i"], result["j"]])
        save_fire_log(log)  # per-cell save (= 並列 driver で I/O 集約)
        a_wins = sum(1 for g in result["games"] if g["winner_for_deck_a"] == 0)
        b_wins = sum(1 for g in result["games"] if g["winner_for_deck_a"] == 1)
        draws = sum(1 for g in result["games"] if g["winner_for_deck_a"] == -1)
        elapsed = time.time() - t0
        eta_sec = elapsed / max(ci, 1) * (len(todo_cells) - ci)
        print(
            f"  [{ci}/{len(todo_cells)}] {slug_a} vs {slug_b}: "
            f"{a_wins}-{b_wins}-{draws}/{args.n_games} "
            f"({elapsed:.0f}s elapsed, ETA {eta_sec:.0f}s)",
            flush=True,
        )

    if args.workers <= 1:
        # sequential (= 後方互換)
        for ci, task in enumerate(tasks, 1):
            result = _cell_worker(task)
            _consume_result(result, ci)
    else:
        # 並列 (= multiprocessing.Pool)
        ctx = mp.get_context("fork")  # Linux default、 env-at-import を 親 から 継承
        with ctx.Pool(args.workers) as pool:
            for ci, result in enumerate(pool.imap_unordered(_cell_worker, tasks, chunksize=1), 1):
                _consume_result(result, ci)

    print(f"\nDONE: {len(log['games'])} games total, log written to {FIRE_LOG_PATH}", flush=True)


if __name__ == "__main__":
    main()
