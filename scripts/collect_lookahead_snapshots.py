# -*- coding: utf-8 -*-
"""2026-05-18: 汎用 lookahead AI self-play snapshot collection。

1-turn lookahead と 3-turn lookahead の 両 AI で snapshot 取得可能。
--ai-class で AI を切替: oneturn / threeturn (= WeightNNPlanningAI / WeightNNThreeTurnAI)。

各 snapshot:
  - state_encoded (= 172 dim、 NN 入力用)
  - turn_player_idx
  - turn
  - deck_a / deck_b
  - reward (= +1 勝、 -1 負、 0 draw)
  - max_turn

REINFORCE 学習 (= Colab GPU) で 各 AI の 評価関数 NN を 独立学習。
1-turn AI 用 NN ≠ 3-turn AI 用 NN (= 共進化)。

実行例:
  .venv/bin/python scripts/collect_lookahead_snapshots.py \\
    --ai-class oneturn --n-games 1500 --workers 4 \\
    --output db/snapshots_oneturn.jsonl

  .venv/bin/python scripts/collect_lookahead_snapshots.py \\
    --ai-class threeturn --n-games 1000 --workers 2 \\
    --output db/snapshots_threeturn.jsonl
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
_WORKER_AI_CLASS = None


def _worker_init(nn_path: str, ai_class_name: str):
    global _WORKER_REPO, _WORKER_OVERLAY, _WORKER_DECKS, _WORKER_AI_CLASS
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

    # AI class 解決 (= oneturn / threeturn)
    from engine.ai_experimental import WeightNNPlanningAI, WeightNNThreeTurnAI
    mapping = {
        "oneturn": WeightNNPlanningAI,
        "threeturn": WeightNNThreeTurnAI,
    }
    if ai_class_name not in mapping:
        raise ValueError(f"unknown ai_class: {ai_class_name}")
    _WORKER_AI_CLASS = mapping[ai_class_name]

    # NN path 設定 (= 各 AI が ONEPIECE_WEIGHT_NN_PATH を見て model load)
    if nn_path:
        os.environ["ONEPIECE_WEIGHT_NN_PATH"] = nn_path


def _play_one_game(args: tuple[int, int]) -> list[dict]:
    """1 試合 self-play、 各 action 前の state_encoded + final_winner を記録。"""
    game_idx, seed = args
    rng = random.Random(seed + game_idx * 31)

    from engine.ai import play_one_action
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

    p0 = _WORKER_AI_CLASS(rng=rng)
    p1 = _WORKER_AI_CLASS(rng=rng)
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

    if state.winner is None:
        winner_actor = -1
    else:
        winner_actor = state.winner
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
    ap.add_argument("--ai-class", required=True, choices=["oneturn", "threeturn"],
                    help="oneturn = WeightNNPlanningAI, threeturn = WeightNNThreeTurnAI")
    ap.add_argument("--n-games", type=int, default=500)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--nn-path", default="",
                    help="empty = NN なし (= 線形 fallback)、 cycle 2+ で 学習済 NN を渡す")
    ap.add_argument("--output", required=True)
    ap.add_argument("--checkpoint-every", type=int, default=50,
                    help="N 試合 ごとに fsync + progress 出力")
    args = ap.parse_args()

    print(f"=== {args.ai_class} AI self-play snapshot collection ===")
    print(f"  n_games: {args.n_games}, workers: {args.workers}")
    print(f"  NN: {args.nn_path or '(なし、 線形 fallback)'}")
    print(f"  output: {args.output}", flush=True)

    nn_path = str(ROOT / args.nn_path) if args.nn_path else ""
    out_path = ROOT / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 既存 output があれば 末尾の game_idx + 1 から resume
    start_game_idx = 0
    if out_path.exists():
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        d = json.loads(line)
                        gi = d.get("game_idx", -1)
                        if gi >= start_game_idx:
                            start_game_idx = gi + 1
                    except Exception:
                        pass
            print(f"  resume from game_idx={start_game_idx} (= 既存 {out_path.name} 解析)", flush=True)
        except Exception:
            pass

    if start_game_idx >= args.n_games:
        print(f"  既に完了済 ({start_game_idx}/{args.n_games})、 終了")
        return 0

    tasks = [(i, args.seed) for i in range(start_game_idx, args.n_games)]
    t0 = time.time()
    total_snaps = 0
    win_count = {0: 0, 1: 0, -1: 0}

    mode = "a" if start_game_idx > 0 else "w"
    with mp.Pool(args.workers, initializer=_worker_init,
                 initargs=(nn_path, args.ai_class)) as pool, \
         open(out_path, mode, encoding="utf-8") as f:
        for i, snaps in enumerate(pool.imap_unordered(_play_one_game, tasks, chunksize=2)):
            for s in snaps:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
            total_snaps += len(snaps)
            if snaps:
                w = snaps[-1].get("winner_actor", -1)
                win_count[w] = win_count.get(w, 0) + 1
            if (i + 1) % args.checkpoint_every == 0:
                f.flush()
                os.fsync(f.fileno())
                elapsed = time.time() - t0
                done = start_game_idx + i + 1
                rate = (i + 1) / elapsed
                remaining = args.n_games - done
                eta = remaining / rate if rate > 0 else 0
                print(
                    f"  [{done}/{args.n_games}] {total_snaps} snaps, "
                    f"{elapsed:.0f}s elapsed, {rate:.2f}g/s, ETA {eta:.0f}s, "
                    f"P0win={win_count[0]} P1win={win_count[1]} draw={win_count[-1]}",
                    flush=True,
                )

    elapsed = time.time() - t0
    print(f"\n=== DONE. {total_snaps} new snapshots in {elapsed:.0f}s ===")
    print(f"  P0 wins: {win_count[0]}, P1 wins: {win_count[1]}, draws: {win_count[-1]}")
    print(f"  output: {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
