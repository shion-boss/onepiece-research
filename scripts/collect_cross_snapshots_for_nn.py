#!/usr/bin/env python3
"""Phase H-3 NN 学習データ取得: cross matchup で state_encoded + winner を 記録。

GoalDirectedAI(v1) 同士 で 14 deck × 13 opp = 182 matchup × N game で snapshot。
各 turn の state を encode_state で 172 dim vector 化、 game winner を ラベル。

# 使い方

```bash
.venv/bin/python scripts/collect_cross_snapshots_for_nn.py \\
  --deck-a cardrush_1456 --deck-b cardrush_1342 \\
  --n-games 10 --seed 90 \\
  --output /tmp/nn_snapshots/1456_vs_1342.jsonl
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
from engine.game import setup_game, play_until_main
from engine.ai import play_one_action
from engine.goal_directed_ai import GoalDirectedAI
from engine.state_encoder import encode_state
from engine.effects import load_effect_overlay

_CARDS_JSON = REPO_ROOT / "db" / "cards.json"
_REPO = CardRepository.from_json(_CARDS_JSON)
_OVERLAY = load_effect_overlay(REPO_ROOT / "db" / "card_effects.json")


def play_one_game(deck_a_slug: str, deck_b_slug: str, seed: int, sample_every_n_action: int = 3, max_actions: int = 1500) -> list[dict]:
    """1 game self-play (= GoalDirectedAI v1 vs v1)、 各 N action ごとに encoded snapshot 取得。"""
    rng = random.Random(seed)
    deck_a = make_deck_from_dict(json.loads((REPO_ROOT / "decks" / f"{deck_a_slug}.json").read_text(encoding="utf-8")), _REPO)
    deck_b = make_deck_from_dict(json.loads((REPO_ROOT / "decks" / f"{deck_b_slug}.json").read_text(encoding="utf-8")), _REPO)

    first_player = seed % 2  # alternate
    state = setup_game(deck_a, deck_b, rng=rng, first_player=first_player, effects_overlay=_OVERLAY)
    play_until_main(state)

    p0 = GoalDirectedAI(rng=rng, deck_slug=deck_a_slug, spec_version="v1", adaptive=True)
    p1 = GoalDirectedAI(rng=rng, deck_slug=deck_b_slug, spec_version="v1", adaptive=True)
    ais = [p0, p1]
    for i, ai in enumerate(ais):
        if hasattr(ai, "set_ai_opp"):
            ai.set_ai_opp(ais[1 - i])

    snapshots = []
    actions = 0
    while not state.game_over and actions < max_actions:
        me = state.turn_player_idx
        # Sparse sampling
        if actions % sample_every_n_action == 0:
            try:
                state_enc_p0 = encode_state(state, 0)
                state_enc_p1 = encode_state(state, 1)
                snapshots.append({
                    "turn": state.turn_number,
                    "actor_idx": me,
                    "state_encoded_p0": state_enc_p0,
                    "state_encoded_p1": state_enc_p1,
                    "p0_life": len(state.players[0].life),
                    "p1_life": len(state.players[1].life),
                })
            except Exception:
                pass

        try:
            play_one_action(state, ais[me], ais[1 - me], referee=None)
        except Exception:
            break
        actions += 1

    # winner 確定: state.winner = 0 (= p0 = deck_a 勝) / 1 (= p1 = deck_b 勝) / None (= draw)
    winner = state.winner if state.winner is not None else -1
    # 各 snapshot に winner を 付与 (= 全 snapshot 同 winner = 同 game 結果)
    for s in snapshots:
        s["game_winner"] = winner
        s["deck_a"] = deck_a_slug
        s["deck_b"] = deck_b_slug
        s["first_player"] = first_player
    return snapshots


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck-a", required=True)
    ap.add_argument("--deck-b", required=True)
    ap.add_argument("--n-games", type=int, default=10)
    ap.add_argument("--seed", type=int, default=90)
    ap.add_argument("--output", required=True)
    ap.add_argument("--sample-every", type=int, default=3)
    args = ap.parse_args()

    import os
    os.environ["ONEPIECE_LIGHT_OPP_SIM"] = "1"  # 速度確保

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    n_snapshots = 0
    t0 = time.time()
    with open(args.output, "w") as f:
        for g in range(args.n_games):
            game_seed = args.seed + g * 31
            try:
                snapshots = play_one_game(args.deck_a, args.deck_b, game_seed, sample_every_n_action=args.sample_every)
                for s in snapshots:
                    f.write(json.dumps(s) + "\n")
                    n_snapshots += 1
                elapsed = time.time() - t0
                print(f"  [{time.strftime('%H:%M:%S')}] game {g+1}/{args.n_games} done: +{len(snapshots)} snapshots (winner={snapshots[0]['game_winner'] if snapshots else '?'}), total={n_snapshots} [{elapsed:.0f}s]", flush=True)
            except Exception as e:
                print(f"  game {g+1} error: {e}", flush=True)
                continue

    print(f"=== {args.deck_a} vs {args.deck_b} DONE: {n_snapshots} snapshots → {args.output} ===", flush=True)


if __name__ == "__main__":
    main()
