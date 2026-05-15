#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 2 / Step 2B: outcome regression 学習用 self-play データ収集 (並列版)。

DeepPlanningAI vs (DeepPlanningAI / LookaheadAI / GreedyAI / RandomAI) を rotation。
multiprocessing.Pool で 8 worker 並列実行 (= 約 5-6x 高速化)。

各 apply_action 後に compute_breakdown の 43 dim features + 試合終了時の outcome を
JSONL で記録。 train_eval_weights.py で ridge regression / LogisticRegression 学習。

Usage:
  .venv/bin/python scripts/collect_self_play_data.py --n-games 5000 --workers 8
  .venv/bin/python scripts/collect_self_play_data.py --n-games 100 --output /tmp/test.jsonl --workers 4
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import random
import sys
import time
import traceback
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.ai import DeepPlanningAI, GreedyAI, LightDeepPlanningAI, LookaheadAI, RandomAI, play_one_action  # noqa: E402
from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.effects import load_effect_overlay  # noqa: E402
from engine.eval import compute_breakdown  # noqa: E402
from engine.game import play_until_main, setup_game  # noqa: E402
from engine.harness import _construct_ai, _try_load_deck_analysis  # noqa: E402


# (name, factory, sampling_probability) — 計画書: peer 33% + others 22% × 3
# 軽量 DeepAI + Lookahead/Greedy/Random rotation で 5000 試合 ~14h 想定
OPP_POOL = [
    ("LightDeepPlanningAI", LightDeepPlanningAI, 0.334),
    ("LookaheadAI", LookaheadAI, 0.222),
    ("GreedyAI", GreedyAI, 0.222),
    ("RandomAI", RandomAI, 0.222),
]


# --------------------------------------------------------------------------- #
# worker-side global (= initializer で 1 度だけロード)
# --------------------------------------------------------------------------- #
_WORKER_REPO: Optional[CardRepository] = None
_WORKER_OVERLAY: Optional[dict] = None
_WORKER_DECK_POOL: Optional[list[tuple[str, DeckList, Optional[dict]]]] = None


def _worker_init() -> None:
    """各 worker で 1 度だけ呼ばれる。 重いリソース (= cards.json / overlay / deck pool) をロード。"""
    global _WORKER_REPO, _WORKER_OVERLAY, _WORKER_DECK_POOL
    _WORKER_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
    _WORKER_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")
    _WORKER_DECK_POOL = []
    for pattern in ("cardrush_*.json", "tcgportal_*.json"):
        for path in sorted((ROOT / "decks").glob(pattern)):
            if path.name.endswith(".analysis.json"):
                continue
            slug = path.stem
            try:
                deck = DeckList.from_json(path, _WORKER_REPO)
                deck.slug = slug
                ana = _try_load_deck_analysis(deck)
                _WORKER_DECK_POOL.append((slug, deck, ana))
            except Exception:
                pass


def _play_one_game(
    deck_a: DeckList,
    ana_a: Optional[dict],
    deck_b: DeckList,
    ana_b: Optional[dict],
    opp_factory: type,
    overlay: dict,
    rng: random.Random,
    max_actions: int = 200,
    max_turns: int = 15,
) -> tuple[list[dict], int]:
    """1 ゲーム実行。 LightDeepAI = P0、 opp = P1 (= snapshot は P0 視点)。

    Returns (snapshots, winner_for_lightdeepai) where winner = 1 / -1 / 0(draw).

    OPTCG は通常 6-9 ターンで終わるので max_turns=15 でほぼ全試合をカバー。
    ループ抑止と peer 対戦の長期化対策で max_actions=200 も併用。
    """
    state = setup_game(
        deck_a, deck_b, rng=rng, first_player=0,
        effects_overlay=overlay,
        deck1_analysis=ana_a, deck2_analysis=ana_b,
    )
    state.record_action_evals = False
    play_until_main(state)

    deepai = _construct_ai(LightDeepPlanningAI, rng, ana_a)
    opp = _construct_ai(opp_factory, rng, ana_b)
    ais = [deepai, opp]
    for i, ai in enumerate(ais):
        if hasattr(ai, "set_ai_opp"):
            ai.set_ai_opp(ais[1 - i])

    snapshots: list[dict] = []
    actions = 0
    while (
        not state.game_over
        and actions < max_actions
        and state.turn_number <= max_turns
    ):
        me = state.turn_player_idx
        opp_idx = 1 - me
        try:
            play_one_action(state, ais[me], ais[opp_idx], referee=None)
        except Exception as e:
            state.declare_winner(opp_idx, f"engine error: {e}")
            break
        actions += 1
        try:
            bd = compute_breakdown(state, 0)
        except Exception:
            continue
        snap_features = {k: float(v["diff"]) for k, v in bd.items()}
        snapshots.append({
            "turn": state.turn_number,
            "phase": state.phase.name if hasattr(state.phase, "name") else str(state.phase),
            "actor_idx": me,
            "features": snap_features,
        })

    if state.winner is None:
        winner = 0
    else:
        winner = 1 if state.winner == 0 else -1
    return snapshots, winner


def _worker_play(args: tuple) -> dict:
    """worker から呼ばれる。 task = (game_idx, seed, opp_idx_in_pool, a_idx, b_idx, max_actions, max_turns)"""
    game_idx, seed, opp_idx_in_pool, a_idx, b_idx, max_actions, max_turns = args
    rng = random.Random(seed)
    opp_name, opp_factory, _ = OPP_POOL[opp_idx_in_pool]
    deck_a_slug, deck_a, ana_a = _WORKER_DECK_POOL[a_idx]
    deck_b_slug, deck_b, ana_b = _WORKER_DECK_POOL[b_idx]
    t0 = time.time()
    try:
        snapshots, winner = _play_one_game(
            deck_a, ana_a, deck_b, ana_b,
            opp_factory, _WORKER_OVERLAY, rng,
            max_actions=max_actions, max_turns=max_turns,
        )
        return {
            "game_idx": game_idx,
            "snapshots": snapshots,
            "winner": winner,
            "opp_name": opp_name,
            "deck_a": deck_a_slug,
            "deck_b": deck_b_slug,
            "elapsed": time.time() - t0,
        }
    except Exception as e:
        traceback.print_exc()
        return {
            "game_idx": game_idx,
            "snapshots": [],
            "winner": 0,
            "opp_name": opp_name,
            "deck_a": deck_a_slug,
            "deck_b": deck_b_slug,
            "elapsed": time.time() - t0,
            "error": str(e),
        }


def select_opponent_idx(rng: random.Random) -> int:
    r = rng.random()
    cum = 0.0
    for i, (_, _, p) in enumerate(OPP_POOL):
        cum += p
        if r < cum:
            return i
    return len(OPP_POOL) - 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n-games", type=int, default=5000)
    ap.add_argument(
        "--output",
        type=Path,
        default=ROOT / "db" / "self_play_snapshots.jsonl",
    )
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--verbose-every", type=int, default=50)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--max-actions", type=int, default=200, help="1 試合の action 上限 (= ~13-15 ターン相当)")
    ap.add_argument("--max-turns", type=int, default=15, help="1 試合のターン上限 (= 公式平均 6-9 の 1.5-2x)")
    args = ap.parse_args()

    rng_master = random.Random(args.seed)

    # deck pool を main process でも一度ロード (= count 表示用)
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    n_decks = 0
    for pattern in ("cardrush_*.json", "tcgportal_*.json"):
        for path in (ROOT / "decks").glob(pattern):
            if not path.name.endswith(".analysis.json"):
                n_decks += 1
    print(f"deck pool: {n_decks} decks, {args.workers} workers, {args.n_games} games")

    # === resume: 既存 output から完了済 game_idx を集める ===
    args.output.parent.mkdir(parents=True, exist_ok=True)
    completed_idxs: set[int] = set()
    if args.output.exists():
        with args.output.open("r", encoding="utf-8") as rf:
            for line in rf:
                try:
                    snap = json.loads(line)
                    gi = snap.get("game_idx")
                    if gi is not None:
                        completed_idxs.add(int(gi))
                except json.JSONDecodeError:
                    continue
        print(f"resume: existing {args.output.name} → {len(completed_idxs)} games completed, skipping")

    # task list 生成 (= 全 game_idx 0..n_games-1 から完了済を除外)
    tasks: list[tuple] = []
    for g in range(args.n_games):
        seed = rng_master.randrange(2**31)
        if g in completed_idxs:
            continue
        sub_rng = random.Random(seed)
        opp_idx = select_opponent_idx(sub_rng)
        a_idx = sub_rng.randrange(n_decks)
        b_idx = sub_rng.randrange(n_decks)
        tasks.append((g, seed, opp_idx, a_idx, b_idx, args.max_actions, args.max_turns))
    print(f"tasks to run: {len(tasks)} (= {args.n_games} - {len(completed_idxs)} completed)")

    if not tasks:
        print("nothing to do (all games complete)")
        return

    # 既存があれば append、 なければ create で開始
    f = args.output.open("a", encoding="utf-8")

    t0 = time.time()
    n_snapshots = 0
    n_done_session = 0
    win_counts = {name: [0, 0, 0] for name, _, _ in OPP_POOL}  # [W, L, D]
    elapsed_per_game: list[float] = []

    try:
        with mp.Pool(processes=args.workers, initializer=_worker_init) as pool:
            for i, res in enumerate(pool.imap_unordered(_worker_play, tasks, chunksize=1)):
                snapshots = res["snapshots"]
                winner = res["winner"]
                opp_name = res["opp_name"]
                game_idx = res["game_idx"]
                for snap in snapshots:
                    snap["game_idx"] = game_idx
                    snap["deck_a"] = res["deck_a"]
                    snap["deck_b"] = res["deck_b"]
                    snap["opp_type"] = opp_name
                    snap["final_winner"] = winner
                    f.write(json.dumps(snap, ensure_ascii=False, separators=(",", ":")) + "\n")
                # === per-game flush + fsync (= crash 耐性) ===
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
                n_snapshots += len(snapshots)
                n_done_session += 1
                elapsed_per_game.append(res["elapsed"])

                if winner == 1:
                    win_counts[opp_name][0] += 1
                elif winner == -1:
                    win_counts[opp_name][1] += 1
                else:
                    win_counts[opp_name][2] += 1

                if (i + 1) % args.verbose_every == 0 or (i + 1) == len(tasks):
                    elapsed = time.time() - t0
                    rate = (i + 1) / elapsed
                    eta = (len(tasks) - i - 1) / rate if rate else 0
                    avg_g = sum(elapsed_per_game) / len(elapsed_per_game)
                    print(
                        f"  [{i+1}/{len(tasks)}] (= total {len(completed_idxs)+i+1}/{args.n_games}) "
                        f"{n_snapshots} snapshots this session, "
                        f"{rate:.2f} g/s wall (avg {avg_g:.1f}s/g raw), "
                        f"ETA {eta/60:.1f}min"
                    )
                    for k, (w, l, d) in win_counts.items():
                        tot = w + l + d
                        wr = w / tot if tot else 0
                        print(f"    vs {k}: {w}W-{l}L-{d}D ({wr:.1%})")
    finally:
        f.close()
        elapsed = time.time() - t0
        print(
            f"DONE: {args.n_games} games / {n_snapshots} snapshots "
            f"in {elapsed/60:.1f}min ({elapsed/3600:.1f}h)"
        )
        print(f"output: {args.output}")


if __name__ == "__main__":
    main()
