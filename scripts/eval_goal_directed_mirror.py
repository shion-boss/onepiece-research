#!/usr/bin/env python3
"""Plan H custom target spec を 検証 する mirror eval。

GoalDirectedAI (= custom spec auto-load) vs PlanningAI baseline で 同 deck mirror。
30g × N deck × 1-3 seed で delta_pt 計算。

進捗 リアルタイム: 5 game 毎 に W/L/D + 平均 s/g を 出力 (= flush=True、 stdout 即時)。

# 使い方
```bash
.venv/bin/python scripts/eval_goal_directed_mirror.py --decks cardrush_1455 cardrush_1342 tcgportal_op11_luffy
.venv/bin/python scripts/eval_goal_directed_mirror.py --decks cardrush_1455 --n-games 60 --seeds 42 1337 7
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

# stdout を line-buffered に (= pipe 経由でも flush 即時)
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

from engine.deck import CardRepository, make_deck_from_dict
from engine.harness import run_matchup
from engine.ai import PlanningAI
from engine.goal_directed_ai import GoalDirectedAI

_CARDS_JSON = REPO_ROOT / "db" / "cards.json"
_REPO = CardRepository.from_json(_CARDS_JSON)


def make_goal_factory(deck_slug: str, goal_target_w: float = 1.0, beam_width: int = 2, max_depth: int = 4, adaptive: bool = False, adaptive_max_turns_cap=None, spec_version: str = "v1"):
    """軽量化 settings (beam=2, depth=4 = 1/16 計算量) で pilot eval 高速化。"""
    def factory(rng, deck_analysis=None):
        return GoalDirectedAI(
            rng=rng,
            deck_analysis=deck_analysis,
            deck_slug=deck_slug,
            goal_target_w=goal_target_w,
            beam_width=beam_width,
            max_depth=max_depth,
            adaptive=adaptive,
            adaptive_max_turns_cap=adaptive_max_turns_cap,
            spec_version=spec_version,
        )
    return factory


def make_planning_factory(beam_width: int = 2, max_depth: int = 4, adaptive: bool = False, adaptive_max_turns_cap=None):
    """baseline も 同 settings (= 公平比較)。"""
    def factory(rng, deck_analysis=None):
        return PlanningAI(rng=rng, deck_analysis=deck_analysis, beam_width=beam_width, max_depth=max_depth, adaptive=adaptive, adaptive_max_turns_cap=adaptive_max_turns_cap)
    return factory


def make_baseline_goal_factory(deck_slug: str, spec_version: str = "v1", beam_width: int = 2, max_depth: int = 4, adaptive: bool = False, adaptive_max_turns_cap=None):
    """v1 vs v2 比較用: baseline を GoalDirectedAI(spec_version=v1) に 切替。"""
    def factory(rng, deck_analysis=None):
        return GoalDirectedAI(
            rng=rng,
            deck_analysis=deck_analysis,
            deck_slug=deck_slug,
            goal_target_w=1.0,
            beam_width=beam_width,
            max_depth=max_depth,
            adaptive=adaptive,
            adaptive_max_turns_cap=adaptive_max_turns_cap,
            spec_version=spec_version,
        )
    return factory


def eval_one_deck(
    deck_slug: str,
    n_games: int,
    seeds: list[int],
    progress_every: int = 5,
    beam_width: int = 2,
    max_depth: int = 4,
    goal_adaptive: bool = False,
    baseline_adaptive: bool = False,
    adaptive_max_turns_cap=None,
    record_snapshots: bool = False,
    snapshot_out_dir=None,
    goal_spec_version: str = "v1",
    baseline_goal: bool = False,
    baseline_spec_version: str = "v1",
) -> dict:
    deck_path = REPO_ROOT / "decks" / f"{deck_slug}.json"
    deck = make_deck_from_dict(json.loads(deck_path.read_text(encoding="utf-8")), _REPO)

    results = []
    for seed in seeds:
        rng_master = random.Random(seed)
        wins, losses, draws = 0, 0, 0
        t0 = time.time()
        games_done = 0

        # n_games を pair (= 先攻/後攻 各 1) で 走らせ、 進捗 5 game 毎 print
        n_pairs = (n_games + 1) // 2  # 切り上げ (= odd 数 でも 対応)
        for pair_idx in range(n_pairs):
            sub_seed = rng_master.randrange(2**31)
            pair_n = min(2, n_games - games_done)
            report = run_matchup(
                deck, deck,
                n_games=pair_n,
                seed=sub_seed,
                ai_factory_1=make_goal_factory(deck_slug, beam_width=beam_width, max_depth=max_depth, adaptive=goal_adaptive, adaptive_max_turns_cap=adaptive_max_turns_cap, spec_version=goal_spec_version),
                ai_factory_2=(
                    make_baseline_goal_factory(deck_slug, spec_version=baseline_spec_version, beam_width=beam_width, max_depth=max_depth, adaptive=baseline_adaptive, adaptive_max_turns_cap=adaptive_max_turns_cap)
                    if baseline_goal else
                    make_planning_factory(beam_width=beam_width, max_depth=max_depth, adaptive=baseline_adaptive, adaptive_max_turns_cap=adaptive_max_turns_cap)
                ),
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
                # snapshot を 教師 label 用 に 書き出し (= record_snapshots=True 時のみ)
                if record_snapshots and snapshot_out_dir is not None and r.snapshots:
                    import os as _os
                    _os.makedirs(snapshot_out_dir, exist_ok=True)
                    out_path = f"{snapshot_out_dir}/{deck_slug}_seed{seed}_g{games_done + game_idx:03d}.jsonl"
                    with open(out_path, "w") as fh:
                        # first_player = game_idx % 2 (harness の規約: 0=deck1 先攻 = GoalDirectedAI 先攻)
                        # player_0_is_goal: true なら snapshot.players[0] = GoalDirectedAI
                        first_player = game_idx % 2
                        player_0_is_goal = (first_player == 0)
                        meta = {
                            "deck": deck_slug, "seed": seed, "game_idx": games_done + game_idx,
                            "winner": r.winner, "turns": r.turns,
                            "first_player": first_player,
                            "player_0_is_goal": player_0_is_goal,
                        }
                        fh.write(json.dumps(meta) + "\n")
                        for snap in r.snapshots:
                            fh.write(json.dumps(snap) + "\n")
            games_done += pair_n

            if games_done % progress_every == 0 or games_done == n_games:
                elapsed = time.time() - t0
                wr_now = wins / max(1, wins + losses)
                print(f"    [{time.strftime('%H:%M:%S')}] game {games_done}/{n_games}: W{wins}-L{losses} D{draws} winrate={wr_now:.3f} avg={elapsed/games_done:.1f}s/g elapsed={elapsed:.0f}s", flush=True)

        winrate = wins / max(1, wins + losses)
        delta_pt = (winrate - 0.5) * 100
        elapsed = time.time() - t0
        results.append({
            "seed": seed,
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "winrate": winrate,
            "delta_pt": delta_pt,
            "elapsed": elapsed,
        })
        print(f"  seed={seed} DONE: {wins}W-{losses}L (draws={draws}) winrate={winrate:.3f} delta={delta_pt:+.1f}pt [{elapsed:.1f}s total]", flush=True)

    avg_delta = sum(r["delta_pt"] for r in results) / max(1, len(results))
    avg_winrate = sum(r["winrate"] for r in results) / max(1, len(results))
    return {
        "deck": deck_slug,
        "n_games": n_games,
        "seeds": seeds,
        "results": results,
        "avg_winrate": avg_winrate,
        "avg_delta_pt": avg_delta,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--decks", nargs="+", required=True, help="deck slugs (mirror eval)")
    ap.add_argument("--n-games", type=int, default=30, help="games per seed")
    ap.add_argument("--seeds", type=int, nargs="+", default=[42], help="random seeds")
    ap.add_argument("--progress-every", type=int, default=5, help="print progress every N games")
    ap.add_argument("--beam-width", type=int, default=2, help="plan_search beam width (default 2 = light)")
    ap.add_argument("--max-depth", type=int, default=4, help="plan_search max depth (default 4 = light)")
    ap.add_argument("--baseline-adaptive", action="store_true", help="baseline PlanningAI で adaptive=True (per-deck NN pref)")
    ap.add_argument("--goal-adaptive", action="store_true", help="GoalDirectedAI で adaptive=True (per-deck NN pref)")
    ap.add_argument("--adaptive-max-turns-cap", type=int, default=None, help="adaptive=True 時 _compute_adaptive_params の max_turns を cap (= T6+ plan-to-end 抑制)")
    ap.add_argument("--light-opp-sim", action="store_true", help="ONEPIECE_LIGHT_OPP_SIM=1 で 相手 sim を GreedyAI 固定 (10-20x 高速化)")
    ap.add_argument("--record-snapshots", action="store_true", help="GameResult.snapshots を 教師 label 用に保存")
    ap.add_argument("--snapshot-out", type=str, default=None, help="snapshot 出力 ディレクトリ (= --record-snapshots と セット)")
    ap.add_argument("--goal-spec-version", type=str, default="v1", help="GoalDirectedAI spec version (v1/v2)")
    ap.add_argument("--baseline-goal", action="store_true", help="baseline を GoalDirectedAI(spec_version) に 切替 (= v1 vs v2 比較)")
    ap.add_argument("--baseline-spec-version", type=str, default="v1", help="baseline GoalDirectedAI spec version (= --baseline-goal と セット)")
    args = ap.parse_args()

    # 環境変数 set (= plan_search が起動時 1 回だけ参照、 main で set すれば全 game に効く)
    import os
    if args.light_opp_sim:
        os.environ["ONEPIECE_LIGHT_OPP_SIM"] = "1"

    print(f"=== Plan H custom target spec mirror eval ===", flush=True)
    print(f"  GoalDirectedAI (custom spec, auto-load, adaptive={args.goal_adaptive}) vs PlanningAI (adaptive={args.baseline_adaptive})", flush=True)
    print(f"  decks={args.decks}, n_games={args.n_games}, seeds={args.seeds}", flush=True)
    print(f"  beam_width={args.beam_width}, max_depth={args.max_depth}, adaptive_max_turns_cap={args.adaptive_max_turns_cap}, light_opp_sim={args.light_opp_sim}", flush=True)
    print(f"  start time: {time.strftime('%H:%M:%S')}", flush=True)
    print(flush=True)

    all_results = []
    for deck_slug in args.decks:
        print(f">>> deck: {deck_slug}  [{time.strftime('%H:%M:%S')}]", flush=True)
        result = eval_one_deck(
            deck_slug, args.n_games, args.seeds,
            progress_every=args.progress_every,
            beam_width=args.beam_width,
            max_depth=args.max_depth,
            goal_adaptive=args.goal_adaptive,
            baseline_adaptive=args.baseline_adaptive,
            adaptive_max_turns_cap=args.adaptive_max_turns_cap,
            record_snapshots=args.record_snapshots,
            snapshot_out_dir=args.snapshot_out,
            goal_spec_version=args.goal_spec_version,
            baseline_goal=args.baseline_goal,
            baseline_spec_version=args.baseline_spec_version,
        )
        print(f"    avg delta = {result['avg_delta_pt']:+.1f}pt (winrate {result['avg_winrate']:.3f})", flush=True)
        print(flush=True)
        all_results.append(result)

    print("=" * 60, flush=True)
    print("SUMMARY", flush=True)
    print("=" * 60, flush=True)
    for r in all_results:
        gate = "PASS" if r["avg_delta_pt"] >= 2.0 else ("MARGINAL" if r["avg_delta_pt"] >= 0 else "FAIL")
        print(f"  {r['deck']:30s} delta={r['avg_delta_pt']:+6.1f}pt  [{gate}]", flush=True)
    overall_avg = sum(r["avg_delta_pt"] for r in all_results) / max(1, len(all_results))
    print(f"  {'OVERALL avg':30s} delta={overall_avg:+6.1f}pt", flush=True)


if __name__ == "__main__":
    main()
