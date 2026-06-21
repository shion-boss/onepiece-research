# -*- coding: utf-8 -*-
"""value 関数 A/B: 同一デッキ mirror で ExploitBeam(value X) vs ExploitBeam(value Y) (= 2026-06-18)。

「検証ハーネス(rollout)で学習した value」 が現行 (board_eval / 既存GBM) より強く打つかを直接対決で測る。
先攻後攻を均等に入替え、 X 側の勝率を返す (>50% = X が強い)。

usage: PYTHONPATH=. .venv/bin/python scripts/ab_value_gbm.py \
    --deck cardrush_1478 --gbm-x db/value_gbm_cardrush_1478_rollout.pkl --gbm-y none --n-games 24
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.game import Phase, advance_phase, setup_game, play_until_main
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI


def _mk(slug, gbm, rng):
    gbm_path = None if (gbm is None or gbm == "none") else gbm
    return ExploitBeamAI(rng=rng, deck_analysis={"deck_slug": slug}, gbm_path=gbm_path)


def run(deck, gbm_x, gbm_y, n_games, seed):
    repo = CardRepository.from_json("db/cards.json")
    overlay = load_effect_overlay("db/card_effects.json")
    dl = DeckList.from_json(f"decks/{deck}.json", repo)
    x_wins = y_wins = draws = 0
    for g in range(n_games):
        rng = random.Random(seed + g)
        # 先攻後攻を交互: x_idx = X が座るプレイヤー index
        x_idx = g % 2
        st = setup_game(dl, dl, rng=rng, first_player=0, effects_overlay=overlay,
                        do_mulligan_and_finalize=True)
        play_until_main(st)
        ais = {x_idx: _mk(deck, gbm_x, rng),
               1 - x_idx: _mk(deck, gbm_y, random.Random(seed + g + 9999))}
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
            x_wins += 1
        elif st.game_over and w == 1 - x_idx:
            y_wins += 1
        else:
            draws += 1
        if (g + 1) % 6 == 0:
            print(f"  {g+1}/{n_games}: X={x_wins} Y={y_wins} draw={draws}", flush=True)
    total = x_wins + y_wins
    wr = x_wins / total if total else 0.5
    print(f"\n=== {deck} mirror | X={gbm_x} vs Y={gbm_y} | {n_games}戦 ===")
    print(f"X 勝={x_wins} Y 勝={y_wins} draw={draws}  →  X 勝率(draw除く)={wr:.1%}")
    return wr


_PAR: dict = {}


def _ab_init(deck):
    """worker 初期化: repo/overlay/decklist を 1 度だけロード (= プロセス毎)。"""
    repo = CardRepository.from_json("db/cards.json")
    _PAR["overlay"] = load_effect_overlay("db/card_effects.json")
    _PAR["dl"] = DeckList.from_json(f"decks/{deck}.json", repo)
    _PAR["deck"] = deck


def _ab_one(task):
    """1 ゲームを play して 'x'/'y'/'draw' を返す。 seed 派生は run() と完全一致 (= 並列でも同一結果)。"""
    g, gbm_x, gbm_y, seed = task
    overlay = _PAR["overlay"]
    dl = _PAR["dl"]
    deck = _PAR["deck"]
    rng = random.Random(seed + g)
    x_idx = g % 2
    st = setup_game(dl, dl, rng=rng, first_player=0, effects_overlay=overlay,
                    do_mulligan_and_finalize=True)
    play_until_main(st)
    ais = {x_idx: _mk(deck, gbm_x, rng),
           1 - x_idx: _mk(deck, gbm_y, random.Random(seed + g + 9999))}
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


def run_parallel(deck, gbm_x, gbm_y, n_games, seed, workers=12):
    """run() の並列版 (= ExploitBeam mirror は 1 ゲーム ~10s なので high-N は並列必須)。
    各ゲームは独立 + seed 派生が run() と同一なので 集計結果は逐次版と一致する。"""
    tasks = [(g, gbm_x, gbm_y, seed) for g in range(n_games)]
    x_wins = y_wins = draws = 0
    with mp.Pool(workers, initializer=_ab_init, initargs=(deck,)) as pool:
        for i, r in enumerate(pool.imap_unordered(_ab_one, tasks, chunksize=1)):
            if r == "x":
                x_wins += 1
            elif r == "y":
                y_wins += 1
            else:
                draws += 1
            if (i + 1) % 10 == 0:
                print(f"  {i+1}/{n_games}: X={x_wins} Y={y_wins} draw={draws}", flush=True)
    total = x_wins + y_wins
    wr = x_wins / total if total else 0.5
    print(f"\n=== {deck} mirror(par x{workers}) | X={gbm_x} vs Y={gbm_y} | {n_games}戦 ===")
    print(f"X 勝={x_wins} Y 勝={y_wins} draw={draws}  →  X 勝率(draw除く)={wr:.1%}")
    return wr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="cardrush_1478")
    ap.add_argument("--gbm-x", default="db/value_gbm_cardrush_1478_rollout.pkl")
    ap.add_argument("--gbm-y", default="none")
    ap.add_argument("--n-games", type=int, default=24)
    ap.add_argument("--seed", type=int, default=100)
    ap.add_argument("--workers", type=int, default=1,
                    help="1=逐次 (run)、 >1=並列 (run_parallel)")
    args = ap.parse_args()
    if args.workers > 1:
        run_parallel(args.deck, args.gbm_x, args.gbm_y, args.n_games, args.seed, args.workers)
    else:
        run(args.deck, args.gbm_x, args.gbm_y, args.n_games, args.seed)


if __name__ == "__main__":
    main()
