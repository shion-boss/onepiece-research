# -*- coding: utf-8 -*-
"""Plan D (= 2026-05-18): MCTS rollout で各 state の P(win|state) を計算、 snapshot 出力。

AlphaZero 風 value NN の学習データ生成:
  1. self-play で試合進める (= TwoTurn AI を player として)
  2. 各 state で MCTS rollout 実行 (= GreedyAI で 10 試合 sim) → wins/total = P(win)
  3. (state_encoded, P(win)) を jsonl 記録

軽量設計:
  - 各 state で 10 rollout × 各 rollout 最大 8 ターン sim = 1 snapshot 3-5 秒
  - 1 試合 ~10-15 state を sample (= 全 state ではなく Sparse)
  - 100 試合 / worker × 4 worker × 各 snapshot 4 秒 ≈ 90 分
  - overnight で 5000+ snapshot

実行例:
  .venv/bin/python scripts/collect_mcts_rollout_snapshots.py \\
    --n-games 100 --workers 4 \\
    --rollouts-per-state 10 --max-rollout-turns 8 \\
    --output db/mcts_rollout_snapshots.jsonl
"""

from __future__ import annotations

import argparse
import copy
import json
import multiprocessing as mp
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


_WORKER_REPO = None
_WORKER_OVERLAY = None
_WORKER_DECKS = None


def _worker_init(_unused: int = 0):
    global _WORKER_REPO, _WORKER_OVERLAY, _WORKER_DECKS
    from engine.deck import CardRepository, DeckList
    from engine.effects import load_effect_overlay
    _WORKER_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
    _WORKER_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")
    deck_paths = sorted((ROOT / "decks").glob("cardrush_*.json"))
    deck_paths += sorted((ROOT / "decks").glob("tcgportal_*.json"))
    deck_paths = [p for p in deck_paths if ".analysis" not in p.name]
    _WORKER_DECKS = []
    for p in deck_paths:
        try:
            d = DeckList.from_json(p, _WORKER_REPO)
            _WORKER_DECKS.append((p.stem, d))
        except Exception:
            pass


def _rollout_one(state, me_idx: int, max_turns: int = 8) -> int:
    """1 rollout: GreedyAI で max_turns ターン sim → 勝者を返す (= +1/-1/0)。"""
    from engine.ai import GreedyAI, play_one_action
    sim_state = copy.deepcopy(state)
    rng = random.Random()
    p0 = GreedyAI(rng=rng)
    p1 = GreedyAI(rng=rng)
    ais = [p0, p1]
    for i, ai in enumerate(ais):
        if hasattr(ai, "set_ai_opp"):
            ai.set_ai_opp(ais[1 - i])

    actions = 0
    start_turn = sim_state.turn_number
    while not sim_state.game_over and actions < 200 and sim_state.turn_number <= start_turn + max_turns:
        me = sim_state.turn_player_idx
        try:
            play_one_action(sim_state, ais[me], ais[1 - me], referee=None)
        except Exception:
            return 0
        actions += 1

    if sim_state.winner is None:
        return 0
    return 1 if sim_state.winner == me_idx else -1


def _compute_p_win(state, me_idx: int, n_rollouts: int = 10, max_turns: int = 8) -> float:
    """n_rollouts 回 rollout して P(win | state) を計算。"""
    if state.game_over:
        if state.winner == me_idx:
            return 1.0
        elif state.winner is not None:
            return 0.0
        return 0.5
    wins = 0
    draws = 0
    for _ in range(n_rollouts):
        r = _rollout_one(state, me_idx, max_turns)
        if r > 0:
            wins += 1
        elif r == 0:
            draws += 1
    # draw = 0.5 として扱う
    return (wins + 0.5 * draws) / n_rollouts


def _play_one_game(args: tuple[int, int, int, int]) -> list[dict]:
    """1 試合 self-play、 各 turn の自分視点 state を sample、 P(win) を MCTS rollout で計算。

    args: (game_idx, seed, n_rollouts, max_turns)
    """
    game_idx, seed, n_rollouts, max_turns = args
    rng = random.Random(seed + game_idx * 31)

    from engine.ai import GreedyAI, play_one_action
    from engine.game import setup_game, play_until_main
    from engine.state_encoder import encode_state

    deck_a_slug, deck_a = rng.choice(_WORKER_DECKS)
    deck_b_slug, deck_b = rng.choice(_WORKER_DECKS)

    first_player = game_idx % 2
    state = setup_game(
        deck_a, deck_b, rng=rng, first_player=first_player,
        effects_overlay=_WORKER_OVERLAY,
    )
    play_until_main(state)

    # self-play AI = GreedyAI (= 軽量、 速い)
    p0 = GreedyAI(rng=rng)
    p1 = GreedyAI(rng=rng)
    ais = [p0, p1]
    for i, ai in enumerate(ais):
        if hasattr(ai, "set_ai_opp"):
            ai.set_ai_opp(ais[1 - i])

    snapshots = []
    actions = 0
    max_actions = 200
    max_game_turns = 15
    sample_every_n_action = 5  # 各 5 action ごとに 1 snapshot (= Sparse)

    while not state.game_over and actions < max_actions and state.turn_number <= max_game_turns:
        me = state.turn_player_idx
        # Sparse sampling: 5 action ごとに rollout 実行 (= 重いので)
        if actions % sample_every_n_action == 0:
            try:
                state_enc = encode_state(state, me)
                p_win = _compute_p_win(state, me, n_rollouts, max_turns)
                snapshots.append({
                    "game_idx": game_idx,
                    "turn": state.turn_number,
                    "actor_idx": me,
                    "state_encoded": state_enc,
                    "p_win": p_win,
                    "deck_a": deck_a_slug,
                    "deck_b": deck_b_slug,
                })
            except Exception:
                pass

        try:
            play_one_action(state, ais[me], ais[1 - me], referee=None)
        except Exception:
            break
        actions += 1

    return snapshots


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-games", type=int, default=100)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--rollouts-per-state", type=int, default=10)
    ap.add_argument("--max-rollout-turns", type=int, default=8)
    ap.add_argument("--output", default="db/mcts_rollout_snapshots.jsonl")
    args = ap.parse_args()

    print(f"=== MCTS rollout snapshot collection (= Plan D) ===")
    print(f"  n_games: {args.n_games}, workers: {args.workers}")
    print(f"  rollouts_per_state: {args.rollouts_per_state}, max_rollout_turns: {args.max_rollout_turns}")
    print(f"  output: {args.output}")

    out_path = ROOT / args.output
    tasks = [(i, args.seed, args.rollouts_per_state, args.max_rollout_turns) for i in range(args.n_games)]
    t0 = time.time()
    total_snaps = 0

    with mp.Pool(args.workers, initializer=_worker_init) as pool, \
         open(out_path, "w", encoding="utf-8") as f:
        for i, snaps in enumerate(pool.imap_unordered(_play_one_game, tasks, chunksize=1)):
            for s in snaps:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
            total_snaps += len(snaps)
            if (i + 1) % 10 == 0:
                f.flush()
                elapsed = time.time() - t0
                rate = (i + 1) / elapsed
                eta = (args.n_games - i - 1) / rate
                print(
                    f"  [{i+1}/{args.n_games}] {total_snaps} snaps, "
                    f"elapsed {elapsed:.0f}s, rate {rate:.2f}g/s, ETA {eta:.0f}s",
                    flush=True,
                )

    elapsed = time.time() - t0
    print(f"\n=== DONE. {total_snaps} snapshots in {elapsed:.0f}s ===")
    print(f"  output: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
