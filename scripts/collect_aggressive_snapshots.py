# -*- coding: utf-8 -*-
"""Plan A (= 2026-05-17): アグレッシブ self-play で短期決着 snapshot を収集。

既存 v2 collector は P0 = GreedyAI で長期戦 (= 平均 11-13 ターン) に偏り、
turn 0-4 勝利 snapshot が 0 件だった (= NN が「攻撃して勝つ」 を学習できない原因)。

本 script は P0/P1 ともに PlanningAI(NN無効、 線形 eval、 lethal 探索可能) を使う。
線形 eval は W_LIFE/W_LETHAL hardcoded でアグレッシブ、 plan_search の depth=3 で
リーサル発見できる → 短期決着 snapshot が生成される。

実行例:
    .venv/bin/python scripts/collect_aggressive_snapshots.py \\
        --n-games 3000 --output db/self_play_snapshots_aggressive.jsonl \\
        --workers 4

per-100-game checkpoint + resume 対応。
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

# NN を強制無効化 (= collector の plan_search を線形 eval にする)
os.environ["ONEPIECE_NN_DISABLE"] = "1"

from engine.ai import PlanningAI, play_one_action  # noqa: E402
from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.effects import load_effect_overlay  # noqa: E402
from engine.eval import compute_breakdown  # noqa: E402
from engine.game import play_until_main, setup_game  # noqa: E402
from engine.nn_eval import ACTION_CATEGORY_TO_IDX  # noqa: E402
from engine.state_encoder import encode_state  # noqa: E402


_WORKER_REPO = None
_WORKER_OVERLAY = None
_WORKER_DECKS: list[tuple[str, DeckList]] = []


def _worker_init() -> None:
    global _WORKER_REPO, _WORKER_OVERLAY, _WORKER_DECKS
    # worker 内でも NN を再度無効化 (= os.environ は引き継ぐが念のため)
    os.environ["ONEPIECE_NN_DISABLE"] = "1"
    _WORKER_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
    _WORKER_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")
    deck_paths = sorted((ROOT / "decks").glob("cardrush_*.json"))
    deck_paths += sorted((ROOT / "decks").glob("tcgportal_*.json"))
    deck_paths = [p for p in deck_paths if ".analysis" not in p.name]
    for p in deck_paths:
        try:
            d = DeckList.from_json(p, _WORKER_REPO)
            _WORKER_DECKS.append((p.stem, d))
        except Exception:
            pass


def _play_one_game(args: tuple[int, int, int]) -> list[dict]:
    """1 試合 self-play して snapshot list を返す。

    args: (game_idx, seed, max_turns)
    """
    game_idx, seed, max_turns = args
    rng = random.Random(seed + game_idx * 31)

    deck_a_slug, deck_a = rng.choice(_WORKER_DECKS)
    deck_b_slug, deck_b = rng.choice(_WORKER_DECKS)

    try:
        state = setup_game(
            deck_a, deck_b, rng=rng, first_player=game_idx % 2,
            effects_overlay=_WORKER_OVERLAY,
        )
        play_until_main(state)

        # 両側 PlanningAI(NN無効 = ONEPIECE_NN_DISABLE=1)、 beam=2 depth=3 で軽量
        p0 = PlanningAI(rng=rng, beam_width=2, max_depth=3, adaptive=False)
        p1 = PlanningAI(rng=rng, beam_width=2, max_depth=3, adaptive=False)
        ais = [p0, p1]
        for i, ai in enumerate(ais):
            if hasattr(ai, "set_ai_opp"):
                ai.set_ai_opp(ais[1 - i])
        state.record_action_evals = True

        snapshots: list[dict] = []
        actions = 0
        prev_eval_count = 0
        while not state.game_over and actions < 200 and state.turn_number <= max_turns:
            me = state.turn_player_idx
            try:
                play_one_action(state, ais[me], ais[1 - me], referee=None)
            except Exception as e:
                state.declare_winner(1 - me, f"engine error: {e}")
                break
            actions += 1

            try:
                bd = compute_breakdown(state, 0)
            except Exception:
                continue
            features = {k: float(v["diff"]) for k, v in bd.items()}

            last_action: str | None = None
            last_action_idx: int = -1
            if len(state.action_evals) > prev_eval_count:
                latest = state.action_evals[-1]
                last_action = latest.get("action")
                if last_action in ACTION_CATEGORY_TO_IDX:
                    last_action_idx = ACTION_CATEGORY_TO_IDX[last_action]
            prev_eval_count = len(state.action_evals)

            try:
                state_enc = encode_state(state, 0)
            except Exception:
                state_enc = []

            snapshots.append({
                "game_idx": game_idx,
                "turn": state.turn_number,
                "actor_idx": me,
                "features": features,
                "action_taken": last_action,
                "action_idx": last_action_idx,
                "state_encoded": state_enc,
                "deck_a": deck_a_slug,
                "deck_b": deck_b_slug,
            })

        # final_winner を全 snapshot に注入 (= P0 視点で +1=勝ち、 -1=負け、 0=引分)
        if state.winner is None:
            fw = 0
        elif state.winner == 0:
            fw = 1
        else:
            fw = -1
        max_turn = state.turn_number
        for s in snapshots:
            s["final_winner"] = fw
            s["game_max_turn"] = max_turn
        return snapshots
    except Exception as e:
        return [{"error": str(e), "game_idx": game_idx}]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-games", type=int, default=3000)
    ap.add_argument("--output", default="db/self_play_snapshots_aggressive.jsonl")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-turns", type=int, default=15)
    ap.add_argument("--checkpoint-every", type=int, default=100)
    args = ap.parse_args()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # resume: 既存 file から完了済 game_idx を集める
    done_game_ids: set[int] = set()
    if out_path.exists():
        with open(out_path) as f:
            for line in f:
                try:
                    snap = json.loads(line)
                    gi = snap.get("game_idx")
                    if gi is not None:
                        done_game_ids.add(gi)
                except Exception:
                    pass
        print(f"  既存 file: {len(done_game_ids)} 試合分の snapshot を resume", flush=True)

    tasks = [
        (gi, args.seed, args.max_turns)
        for gi in range(args.n_games)
        if gi not in done_game_ids
    ]
    print(f"  残 {len(tasks)} 試合 / 総 {args.n_games}", flush=True)
    if not tasks:
        print("  全試合完了済 → exit", flush=True)
        return 0

    t0 = time.time()
    completed = 0
    short_win_count = 0  # turn <= 6 で勝利した試合数

    with mp.Pool(args.workers, initializer=_worker_init) as pool, \
         open(out_path, "a", encoding="utf-8") as f:
        for snaps in pool.imap_unordered(_play_one_game, tasks, chunksize=4):
            completed += 1
            for s in snaps:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
            if snaps and "final_winner" in snaps[-1]:
                fw = snaps[-1]["final_winner"]
                mt = snaps[-1].get("game_max_turn", 99)
                if fw == 1 and mt <= 6:
                    short_win_count += 1

            if completed % args.checkpoint_every == 0:
                f.flush()
                os.fsync(f.fileno())
                elapsed = time.time() - t0
                rate = completed / elapsed if elapsed > 0 else 0
                eta = (len(tasks) - completed) / rate if rate > 0 else 0
                pct_short = 100 * short_win_count / completed
                print(
                    f"  [{completed}/{len(tasks)}] elapsed {elapsed:.0f}s rate {rate:.2f}g/s "
                    f"ETA {eta:.0f}s short_wins {short_win_count} ({pct_short:.1f}%)",
                    flush=True,
                )

    elapsed = time.time() - t0
    print(f"\n完了: {out_path}, {elapsed:.1f}s, {completed} 試合, short_win {short_win_count} ({100*short_win_count/max(1,completed):.1f}%)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
