# -*- coding: utf-8 -*-
"""value 駆動 防御 A/B: 同一デッキ mirror で ExploitBeam(value-defense ON) vs (OFF) (= 2026-06-21)。

両側とも同一の offense value (per-deck pkl / agnostic-gate / board_eval を deck から自動解決)
を使い、 **唯一の差 = choose_defense が value 駆動 (X) か検証済ヒューリスティック (Y) か**。
= 防御レバーだけを isolate して mirror A/B (= [[project_play_timing_prior]] と同じ手法)。

先攻後攻を交互に入替え、 X (= value-defense) 側の勝率を返す (>50% = value-defense が強い)。
[[feedback_ab_statistical_power]]: 判定は N>=80 で。

usage:
  PYTHONPATH=. .venv/bin/python scripts/eval_value_defense.py --deck cardrush_1478 --n-games 80 --workers 12
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.game import Phase, advance_phase, setup_game, play_until_main
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI


def _mk(slug, value_defense, rng):
    ai = ExploitBeamAI(rng=rng, deck_analysis={"deck_slug": slug})
    ai._value_defense = bool(value_defense)
    return ai


def _play_one(deck, overlay, dl, g, seed):
    """1 ゲーム play して 'x'/'y'/'draw'。 x_idx = value-defense 側 player index。"""
    rng = random.Random(seed + g)
    x_idx = g % 2  # 先攻後攻を交互
    st = setup_game(dl, dl, rng=rng, first_player=0, effects_overlay=overlay,
                    do_mulligan_and_finalize=True)
    play_until_main(st)
    ais = {x_idx: _mk(deck, True, rng),
           1 - x_idx: _mk(deck, False, random.Random(seed + g + 9999))}
    guard = 0
    while not st.game_over and guard < 4000:
        guard += 1
        if st.turn_number > 60:
            break
        tp = st.turn_player_idx
        if st.phase == Phase.MAIN:
            try:
                play_one_action(st, ais[tp], ais[1 - tp])
            except Exception:
                break
        else:
            advance_phase(st)
    w = getattr(st, "winner", -1)
    if st.game_over and w == x_idx:
        return "x"
    if st.game_over and w == 1 - x_idx:
        return "y"
    return "draw"


def run(deck, n_games, seed):
    repo = CardRepository.from_json("db/cards.json")
    overlay = load_effect_overlay("db/card_effects.json")
    dl = DeckList.from_json(f"decks/{deck}.json", repo)
    x = y = d = 0
    t0 = time.time()
    for g in range(n_games):
        r = _play_one(deck, overlay, dl, g, seed)
        x += (r == "x"); y += (r == "y"); d += (r == "draw")
        if (g + 1) % 6 == 0:
            print(f"  {g+1}/{n_games}: X={x} Y={y} draw={d} ({time.time()-t0:.0f}s)", flush=True)
    return _report(deck, x, y, d, n_games)


_PAR: dict = {}


def _init(deck):
    repo = CardRepository.from_json("db/cards.json")
    _PAR["overlay"] = load_effect_overlay("db/card_effects.json")
    _PAR["dl"] = DeckList.from_json(f"decks/{deck}.json", repo)
    _PAR["deck"] = deck


def _one(task):
    g, seed = task
    return _play_one(_PAR["deck"], _PAR["overlay"], _PAR["dl"], g, seed)


def run_parallel(deck, n_games, seed, workers=12):
    tasks = [(g, seed) for g in range(n_games)]
    x = y = d = 0
    t0 = time.time()
    with mp.Pool(workers, initializer=_init, initargs=(deck,)) as pool:
        for i, r in enumerate(pool.imap_unordered(_one, tasks, chunksize=1)):
            x += (r == "x"); y += (r == "y"); d += (r == "draw")
            if (i + 1) % 10 == 0:
                print(f"  {i+1}/{n_games}: X={x} Y={y} draw={d} ({time.time()-t0:.0f}s)", flush=True)
    return _report(deck, x, y, d, n_games)


def _report(deck, x, y, d, n_games):
    total = x + y
    wr = x / total if total else 0.5
    print(f"\n=== {deck} value-defense mirror | {n_games}戦 ===")
    print(f"X(value-defense)勝={x}  Y(heuristic)勝={y}  draw={d}  →  X 勝率(draw除く)={wr:.1%}")
    return wr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="cardrush_1478")
    ap.add_argument("--n-games", type=int, default=80)
    ap.add_argument("--seed", type=int, default=100)
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args()
    if args.workers > 1:
        run_parallel(args.deck, args.n_games, args.seed, args.workers)
    else:
        run(args.deck, args.n_games, args.seed)


if __name__ == "__main__":
    main()
