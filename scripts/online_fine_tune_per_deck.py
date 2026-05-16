#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 2B: deck slug 別 評価関数 fine-tune (= base から SGD で 派生)。

各 deck slug に対して、 自 deck 固定 / opp 全 deck rotation で N 試合 SGD。
db/ai_params_decks/<slug>.json に保存。

Usage:
  .venv/bin/python scripts/online_fine_tune_per_deck.py --deck-slug cardrush_1399 --n-games 300
"""

from __future__ import annotations

import argparse
import json
import random
import signal
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.ai import (  # noqa: E402
    GreedyAI, LightDeepPlanningAI, LookaheadAI, RandomAI, play_one_action,
)
from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.effects import load_effect_overlay  # noqa: E402
from engine import eval as eval_mod  # noqa: E402
from engine.eval import compute_breakdown, invalidate_archetype_cache  # noqa: E402
from engine.game import play_until_main, setup_game  # noqa: E402
from engine.harness import _try_load_deck_analysis  # noqa: E402

from scripts.train_eval_weights import FEATURE_TO_WEIGHT_FIELD  # noqa: E402
from scripts.online_self_play import (  # noqa: E402
    OPP_POOL, GameTimeout, _timeout_handler,
    sgd_update_weights, load_initial_weights, select_opponent,
)


def load_self_and_full_pool(self_slug: str) -> tuple[
    tuple[str, DeckList, dict],   # 自 deck
    list[tuple[str, DeckList, dict]],  # 全 deck (= opp pool)
]:
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    full_pool: list = []
    self_entry: Optional[tuple] = None
    for pat in ("cardrush_*.json", "tcgportal_*.json"):
        for path in sorted((ROOT / "decks").glob(pat)):
            if path.name.endswith(".analysis.json"):
                continue
            slug = path.stem
            try:
                deck = DeckList.from_json(path, repo)
                deck.slug = slug
                ana = _try_load_deck_analysis(deck)
                full_pool.append((slug, deck, ana))
                if slug == self_slug:
                    self_entry = (slug, deck, ana)
            except Exception:
                pass
    if self_entry is None:
        raise SystemExit(f"deck not found: {self_slug}")
    return self_entry, full_pool


def play_one_game_with_timeout(
    self_deck, self_ana, opp_deck, opp_ana,
    opp_factory, overlay, rng,
    timeout_s: int = 60,
    max_actions: int = 200, max_turns: int = 15,
) -> tuple[list[dict], int, bool]:
    state = setup_game(
        self_deck, opp_deck, rng=rng, first_player=0,
        effects_overlay=overlay,
        deck1_analysis=self_ana, deck2_analysis=opp_ana,
    )
    state.record_action_evals = False
    play_until_main(state)

    deepai = LightDeepPlanningAI(rng=rng)
    opp = opp_factory(rng=rng)
    ais = [deepai, opp]
    for i, ai in enumerate(ais):
        if hasattr(ai, "set_ai_opp"):
            ai.set_ai_opp(ais[1 - i])

    snapshots: list[dict] = []
    actions = 0
    completed = True
    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(timeout_s)
    try:
        while (
            not state.game_over and actions < max_actions
            and state.turn_number <= max_turns
        ):
            me = state.turn_player_idx
            opp_idx_p = 1 - me
            try:
                play_one_action(state, ais[me], ais[opp_idx_p], referee=None)
            except Exception as e:
                state.declare_winner(opp_idx_p, f"engine error: {e}")
                break
            actions += 1
            try:
                bd = compute_breakdown(state, 0)
                snap_features = {k: float(v["diff"]) for k, v in bd.items()}
                snapshots.append({
                    "turn": state.turn_number, "actor_idx": me,
                    "features": snap_features,
                })
            except Exception:
                continue
    except GameTimeout:
        completed = False
    finally:
        signal.alarm(0)

    if state.winner is None:
        winner = 0
    else:
        winner = 1 if state.winner == 0 else -1
    return snapshots, winner, completed


def persist_deck_weights(weights_dict: dict, deck_slug: str, note: str) -> Path:
    out_dir = ROOT / "db" / "ai_params_decks"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{deck_slug}.json"
    if path.exists():
        doc = json.loads(path.read_text(encoding="utf-8"))
    else:
        doc = {"version": "1", "deck_slug": deck_slug, "params": {}}
    p = {}
    for wfield, val in weights_dict.items():
        p[wfield.lower()] = int(round(val))
    doc["deck_slug"] = deck_slug
    doc["params"] = p
    doc["saved_at"] = datetime.now(timezone.utc).isoformat()
    doc["note"] = note
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    invalidate_archetype_cache()
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deck-slug", required=True)
    ap.add_argument("--n-games", type=int, default=300)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--timeout-s", type=int, default=60)
    ap.add_argument("--max-actions", type=int, default=200)
    ap.add_argument("--max-turns", type=int, default=15)
    ap.add_argument("--lr", type=float, default=1.0)
    ap.add_argument("--target-scale", type=float, default=5000.0)
    ap.add_argument("--max-delta", type=float, default=10.0)
    ap.add_argument("--persist-every", type=int, default=20)
    ap.add_argument("--warmup-games", type=int, default=5)
    args = ap.parse_args()

    rng_master = random.Random(args.seed)
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    self_entry, full_pool = load_self_and_full_pool(args.deck_slug)
    self_slug, self_deck, self_ana = self_entry
    leader_name = (self_ana or {}).get("leader_name", "?")

    print(f"deck={args.deck_slug} (leader={leader_name})")
    print(f"  opp_pool={len(full_pool)} decks, n_games={args.n_games}, "
          f"timeout={args.timeout_s}s, lr={args.lr}")

    feature_names = list(FEATURE_TO_WEIGHT_FIELD.keys())
    weights_dict = load_initial_weights()

    out_dir = ROOT / "db" / "ai_params_decks"
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / f"{self_slug}.snapshots.jsonl"
    f_jsonl = log_path.open("a", encoding="utf-8")

    t0 = time.time()
    n_completed = 0
    n_timeout = 0
    win_counts = {name: [0, 0, 0] for name, _, _ in OPP_POOL}
    error_history: list[float] = []
    g = -1
    try:
        for g in range(args.n_games):
            seed = rng_master.randrange(2**31)
            sub_rng = random.Random(seed)
            opp_name, opp_factory = select_opponent(sub_rng)
            opp_idx = sub_rng.randrange(len(full_pool))
            opp_slug, opp_deck, opp_ana = full_pool[opp_idx]
            game_t0 = time.time()
            try:
                snaps, winner, completed = play_one_game_with_timeout(
                    self_deck, self_ana, opp_deck, opp_ana,
                    opp_factory, overlay, sub_rng,
                    timeout_s=args.timeout_s,
                    max_actions=args.max_actions, max_turns=args.max_turns,
                )
            except Exception as e:
                print(f"  [g{g}] failed: {e}")
                continue
            game_elapsed = time.time() - game_t0

            if not completed:
                n_timeout += 1
                continue

            n_completed += 1
            if winner == 1:
                win_counts[opp_name][0] += 1
            elif winner == -1:
                win_counts[opp_name][1] += 1
            else:
                win_counts[opp_name][2] += 1

            for snap in snaps:
                snap.update({
                    "game_idx": g, "self_deck": self_slug, "opp_deck": opp_slug,
                    "opp_ai": opp_name, "winner": winner,
                })
                f_jsonl.write(json.dumps(snap, ensure_ascii=False, separators=(",", ":")) + "\n")
            f_jsonl.flush()

            if g >= args.warmup_games and snaps:
                updates, error = sgd_update_weights(
                    weights_dict, snaps, winner,
                    feature_names, args.lr, args.target_scale,
                    max_delta=args.max_delta,
                )
                for k, v in updates.items():
                    weights_dict[k] = v
                error_history.append(error)

                if (g + 1) % 25 == 0 or g + 1 == args.n_games:
                    elapsed = time.time() - t0
                    rate = (g + 1) / elapsed
                    eta = (args.n_games - g - 1) / rate if rate else 0
                    avg_err = sum(error_history[-25:]) / max(1, min(25, len(error_history)))
                    print(
                        f"  [g{g+1}/{args.n_games}] err={avg_err:+.2f}, "
                        f"timeouts={n_timeout}, completed={n_completed}, "
                        f"rate={rate:.2f}g/s, ETA {eta/60:.1f}min, "
                        f"w_life={weights_dict['W_LIFE']:.0f}, "
                        f"w_lethal={weights_dict['W_LETHAL']:.0f}, "
                        f"w_blocker={weights_dict['W_BLOCKER']:.0f}"
                    )

            if (g + 1) % args.persist_every == 0 and g >= args.warmup_games:
                path = persist_deck_weights(
                    weights_dict, self_slug,
                    note=f"g{g+1}/{args.n_games} SGD lr={args.lr}",
                )
    finally:
        f_jsonl.close()
        if g >= args.warmup_games:
            persist_deck_weights(
                weights_dict, self_slug,
                note=f"final g{g+1}/{args.n_games} SGD lr={args.lr}",
            )
        elapsed = time.time() - t0
        print(
            f"\nDONE [{self_slug}]: {n_completed} completed / {n_timeout} timeouts "
            f"in {elapsed/60:.1f}min ({elapsed/3600:.2f}h)"
        )
        for k, (w, l, d) in win_counts.items():
            tot = w + l + d
            wr = w / tot if tot else 0
            print(f"  vs {k}: {w}W-{l}L-{d}D ({wr:.1%})")


if __name__ == "__main__":
    main()
