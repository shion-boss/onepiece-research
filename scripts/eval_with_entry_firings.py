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

import argparse
import json
import sys
import time
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

META_POOL_PATH = REPO_ROOT / "db" / "meta_pool.json"
FIRE_LOG_PATH = REPO_ROOT / "db" / "target_fire_log.json"
DECKS_DIR = REPO_ROOT / "decks"
CARDS_JSON = REPO_ROOT / "db" / "cards.json"


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

    t0 = time.time()
    for ci, (i, j) in enumerate(todo_cells):
        slug_a, slug_b = slugs[i], slugs[j]
        deck_a, deck_b = decks[slug_a], decks[slug_b]

        ai_factory = light_ai_factory if args.ai_mode == "light" else None
        kwargs = {}
        if ai_factory is not None:
            kwargs["ai_factory_1"] = ai_factory
            kwargs["ai_factory_2"] = ai_factory
        report = run_matchup(
            deck_a, deck_b,
            n_games=args.n_games,
            seed=args.seed + i * 1000 + j,
            enable_fire_logging=True,
            **kwargs,
        )

        for gi, g in enumerate(report.games):
            log["games"].append({
                "deck_a": slug_a,
                "deck_b": slug_b,
                "game_idx": gi,
                "winner_for_deck_a": g.winner,  # 0=a, 1=b, -1=draw
                "first_player": g.first_player,
                "turns": g.turns,
                "fire_counts_a": g.fire_counts[0],
                "fire_counts_b": g.fire_counts[1],
            })
        log["completed_cells"].append([i, j])

        save_fire_log(log)

        elapsed = time.time() - t0
        eta_sec = elapsed / (ci + 1) * (len(todo_cells) - ci - 1)
        print(
            f"  [{ci+1}/{len(todo_cells)}] {slug_a} vs {slug_b}: "
            f"{report.deck1_wins}-{report.deck2_wins}-{report.draws}/{args.n_games} "
            f"({elapsed:.0f}s elapsed, ETA {eta_sec:.0f}s)"
        )

    print(f"\nDONE: {len(log['games'])} games total, log written to {FIRE_LOG_PATH}")


if __name__ == "__main__":
    main()
