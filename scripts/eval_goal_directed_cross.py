#!/usr/bin/env python3
"""v2 cross-trained spec 効果検証 用 cross matchup eval (= 2026-05-20)。

deck_a (= goal AI、 spec_version=v2) vs deck_b (= baseline、 spec_version=v1) で 30g cross。
v2 deck の 対 他 leader entries が 発火 → spec 効果 確認。

# 使い方

```bash
.venv/bin/python scripts/eval_goal_directed_cross.py \\
  --deck-a cardrush_1456 --spec-version-a v2 \\
  --deck-b cardrush_1342 --spec-version-b v1 \\
  --n-games 30 --seeds 50
```
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

from engine.deck import CardRepository, make_deck_from_dict
from engine.harness import run_matchup
from engine.goal_directed_ai import GoalDirectedAI

_CARDS_JSON = REPO_ROOT / "db" / "cards.json"
_REPO = CardRepository.from_json(_CARDS_JSON)


def make_goal_factory(deck_slug: str, spec_version: str, adaptive: bool = True, light_opp_sim: bool = True):
    def factory(rng, deck_analysis=None):
        return GoalDirectedAI(
            rng=rng,
            deck_analysis=deck_analysis,
            deck_slug=deck_slug,
            goal_target_w=1.0,
            beam_width=2,
            max_depth=4,
            adaptive=adaptive,
            spec_version=spec_version,
        )
    return factory


def eval_cross_matchup(deck_a_slug: str, spec_a: str, deck_b_slug: str, spec_b: str, n_games: int, seed: int, progress_every: int = 5, record_snapshots: bool = False, snapshot_out_dir=None) -> dict:
    deck_a = make_deck_from_dict(json.loads((REPO_ROOT / "decks" / f"{deck_a_slug}.json").read_text(encoding="utf-8")), _REPO)
    deck_b = make_deck_from_dict(json.loads((REPO_ROOT / "decks" / f"{deck_b_slug}.json").read_text(encoding="utf-8")), _REPO)

    rng_master = random.Random(seed)
    wins, losses, draws = 0, 0, 0
    t0 = time.time()
    games_done = 0
    n_pairs = (n_games + 1) // 2

    for pair_idx in range(n_pairs):
        sub_seed = rng_master.randrange(2**31)
        pair_n = min(2, n_games - games_done)
        report = run_matchup(
            deck_a, deck_b,
            n_games=pair_n,
            seed=sub_seed,
            ai_factory_1=make_goal_factory(deck_a_slug, spec_a),
            ai_factory_2=make_goal_factory(deck_b_slug, spec_b),
            keep_logs=record_snapshots,
            record_snapshots=record_snapshots,
        )
        for game_idx, r in enumerate(report.games):
            if r.winner == 0:
                wins += 1
            elif r.winner == 1:
                losses += 1
            else:
                draws += 1
            if record_snapshots and snapshot_out_dir is not None and r.snapshots:
                import os as _os
                _os.makedirs(snapshot_out_dir, exist_ok=True)
                first_player = game_idx % 2
                out_path = f"{snapshot_out_dir}/{deck_a_slug}_vs_{deck_b_slug}_seed{seed}_g{games_done + game_idx:03d}.jsonl"
                with open(out_path, "w") as fh:
                    meta = {
                        "deck_a": deck_a_slug, "spec_a": spec_a,
                        "deck_b": deck_b_slug, "spec_b": spec_b,
                        "seed": seed, "game_idx": games_done + game_idx,
                        "winner": r.winner, "turns": r.turns,
                        "first_player": first_player,
                    }
                    fh.write(json.dumps(meta) + "\n")
                    for snap in r.snapshots:
                        fh.write(json.dumps(snap) + "\n")
        games_done += pair_n

        if games_done % progress_every == 0 or games_done == n_games:
            elapsed = time.time() - t0
            wr = wins / max(1, wins + losses)
            print(f"    [{time.strftime('%H:%M:%S')}] g {games_done}/{n_games}: W{wins}-L{losses} D{draws} winrate={wr:.3f} avg={elapsed/games_done:.1f}s/g elapsed={elapsed:.0f}s", flush=True)

    winrate = wins / max(1, wins + losses)
    delta_pt = (winrate - 0.5) * 100
    elapsed = time.time() - t0
    return {
        "deck_a": deck_a_slug, "spec_a": spec_a,
        "deck_b": deck_b_slug, "spec_b": spec_b,
        "n_games": n_games, "seed": seed,
        "wins": wins, "losses": losses, "draws": draws,
        "winrate": winrate, "delta_pt": delta_pt, "elapsed": elapsed,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck-a", required=True)
    ap.add_argument("--spec-version-a", default="v2")
    ap.add_argument("--deck-b", required=True)
    ap.add_argument("--spec-version-b", default="v1")
    ap.add_argument("--n-games", type=int, default=30)
    ap.add_argument("--seeds", type=int, nargs="+", default=[42])
    ap.add_argument("--progress-every", type=int, default=5)
    ap.add_argument("--light-opp-sim", action="store_true", default=True)
    ap.add_argument("--record-snapshots", action="store_true")
    ap.add_argument("--snapshot-out", type=str, default=None)
    args = ap.parse_args()

    import os as _os
    if args.light_opp_sim:
        _os.environ["ONEPIECE_LIGHT_OPP_SIM"] = "1"

    print(f"=== v1 vs v2 cross matchup eval ===", flush=True)
    print(f"  player 1: {args.deck_a} (spec={args.spec_version_a})", flush=True)
    print(f"  player 2: {args.deck_b} (spec={args.spec_version_b})", flush=True)
    print(f"  n_games={args.n_games}, seeds={args.seeds}", flush=True)
    print(f"  start: {time.strftime('%H:%M:%S')}", flush=True)
    print()

    all_results = []
    for seed in args.seeds:
        print(f">>> seed={seed}", flush=True)
        r = eval_cross_matchup(args.deck_a, args.spec_version_a, args.deck_b, args.spec_version_b, args.n_games, seed, args.progress_every, record_snapshots=args.record_snapshots, snapshot_out_dir=args.snapshot_out)
        print(f"  DONE: {r['wins']}W-{r['losses']}L (draws={r['draws']}) winrate={r['winrate']:.3f} delta={r['delta_pt']:+.1f}pt [{r['elapsed']:.1f}s]", flush=True)
        all_results.append(r)
        print()

    print("=" * 60, flush=True)
    avg_delta = sum(r["delta_pt"] for r in all_results) / max(1, len(all_results))
    print(f"SUMMARY: {args.deck_a}({args.spec_version_a}) vs {args.deck_b}({args.spec_version_b}) avg delta = {avg_delta:+.1f}pt", flush=True)


if __name__ == "__main__":
    main()
