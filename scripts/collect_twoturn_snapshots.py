# -*- coding: utf-8 -*-
"""Plan F Phase 2 (= 2026-05-18): TwoTurn AI で self-play、 snapshot を jsonl 出力。

各 snapshot:
  - state_encoded (= 172 dim、 NN 入力用)
  - turn_player_idx (= snapshot 時の actor)
  - turn (= ターン番号)
  - deck_a / deck_b (= 試合 metadata)
  - game_idx
  - final_winner: 0=deck1, 1=deck2, -1=draw (= 試合終了後 backfill)

REINFORCE 学習用 = Colab GPU で snapshot 読んで NN update。

実行例:
  .venv/bin/python scripts/collect_twoturn_snapshots.py \\
    --n-games 1000 --workers 4 \\
    --output db/twoturn_snapshots.jsonl
"""

from __future__ import annotations

import argparse
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
_WORKER_NN_PATH = None


def _worker_init(nn_path: str):
    global _WORKER_REPO, _WORKER_OVERLAY, _WORKER_DECKS, _WORKER_NN_PATH
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
    _WORKER_NN_PATH = nn_path
    os.environ["ONEPIECE_WEIGHT_NN_PATH"] = nn_path
    os.environ["ONEPIECE_WEIGHT_NN"] = "1"
    os.environ["ONEPIECE_LIGHT_OPP_SIM"] = "1"
    os.environ["ONEPIECE_DYNAMIC_WEIGHTS"] = "1"


def _play_one_game(args: tuple[int, int]) -> list[dict]:
    """1 試合 self-play、 各 turn の自分視点 state_encoded + final_winner を記録。"""
    game_idx, seed = args
    rng = random.Random(seed + game_idx * 31)

    from engine.ai import play_one_action
    from engine.ai_experimental import WeightNNTwoTurnAI
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

    p0 = WeightNNTwoTurnAI(rng=rng)
    p1 = WeightNNTwoTurnAI(rng=rng)
    ais = [p0, p1]
    for i, ai in enumerate(ais):
        if hasattr(ai, "set_ai_opp"):
            ai.set_ai_opp(ais[1 - i])

    snapshots = []
    actions = 0
    max_actions = 200
    max_turns = 15

    while not state.game_over and actions < max_actions and state.turn_number <= max_turns:
        me = state.turn_player_idx
        # MAIN フェーズの先頭で state_encoded を取る (= choose_action 前)
        # encode_state は重いので各 action で取らず、 turn 開始時のみ
        try:
            state_enc = encode_state(state, me)
        except Exception:
            state_enc = None

        try:
            play_one_action(state, ais[me], ais[1 - me], referee=None)
        except Exception as e:
            state.declare_winner(1 - me, f"engine error: {e}")
            break
        actions += 1

        if state_enc is not None:
            snapshots.append({
                "game_idx": game_idx,
                "turn": state.turn_number,
                "actor_idx": me,
                "state_encoded": state_enc,
                "deck_a": deck_a_slug,
                "deck_b": deck_b_slug,
            })

    # 試合終了: final_winner を全 snapshot に注入
    # winner: state.players[0/1].deck = first / second player のデッキ
    # actor reward: actor が勝者なら +1、 敗者なら -1、 draw なら 0
    if state.winner is None:
        winner_actor = -1
    else:
        winner_actor = state.winner  # 0 = P0、 1 = P1
    for s in snapshots:
        if winner_actor == -1:
            s["reward"] = 0.0
        elif s["actor_idx"] == winner_actor:
            s["reward"] = 1.0
        else:
            s["reward"] = -1.0
        s["winner_actor"] = winner_actor
        s["max_turn"] = state.turn_number

    return snapshots


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-games", type=int, default=500)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--nn-path", default="db/weight_nn.pt")
    ap.add_argument("--output", default="db/twoturn_snapshots.jsonl")
    args = ap.parse_args()

    print(f"=== TwoTurn AI self-play snapshot collection ===")
    print(f"  n_games: {args.n_games}, workers: {args.workers}")
    print(f"  NN: {args.nn_path}")
    print(f"  output: {args.output}")

    nn_path = str(ROOT / args.nn_path)
    out_path = ROOT / args.output

    tasks = [(i, args.seed) for i in range(args.n_games)]
    t0 = time.time()
    total_snaps = 0
    win_count = {0: 0, 1: 0, -1: 0}

    with mp.Pool(args.workers, initializer=_worker_init, initargs=(nn_path,)) as pool, \
         open(out_path, "w", encoding="utf-8") as f:
        for i, snaps in enumerate(pool.imap_unordered(_play_one_game, tasks, chunksize=2)):
            for s in snaps:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
            total_snaps += len(snaps)
            if snaps:
                w = snaps[-1].get("winner_actor", -1)
                win_count[w] = win_count.get(w, 0) + 1
            if (i + 1) % 50 == 0:
                f.flush()
                os.fsync(f.fileno())
                elapsed = time.time() - t0
                rate = (i + 1) / elapsed
                eta = (args.n_games - i - 1) / rate
                print(
                    f"  [{i+1}/{args.n_games}] {total_snaps} snaps, "
                    f"{elapsed:.0f}s elapsed, {rate:.2f}g/s, ETA {eta:.0f}s, "
                    f"P0win={win_count[0]} P1win={win_count[1]} draw={win_count[-1]}",
                    flush=True,
                )

    elapsed = time.time() - t0
    print(f"\n=== DONE. {total_snaps} snapshots in {elapsed:.0f}s ===")
    print(f"  P0 wins: {win_count[0]}, P1 wins: {win_count[1]}, draws: {win_count[-1]}")
    print(f"  output: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
