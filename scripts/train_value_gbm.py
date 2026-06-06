#!/usr/bin/env python3
"""beam-vs-greedy の (盤面features, 勝敗) を集めて GBM value を学習 (= 2026-06-04, 70% 探索)。

beam は board_eval (= 線形 winrate-tune) で 62.5% 飽和。 非線形 GBM を beam-vs-greedy の
盤面→勝敗で学習し、 beam の leaf eval に使えば線形の天井を破れるか試す。
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import pickle
import random
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import numpy as np

from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import Phase, setup_game, play_until_main
from engine.ai import GreedyAI, DeepPlanningAI, play_one_action
from engine.gbm_value import features

_REPO = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(REPO_ROOT / "db" / "card_effects.json")

_W: dict = {}


def _load(slug: str):
    return make_deck_from_dict(
        __import__("json").loads((REPO_ROOT / "decks" / f"{slug}.json").read_text(encoding="utf-8")),
        _REPO)


def _winit(slug: str) -> None:
    _W["slug"] = slug


def _make_beam(seed: int):
    # policy iteration: ONEPIECE_GBM_COLLECT_POLICY=exploitbeam で強いAI自身でデータ生成。
    if os.environ.get("ONEPIECE_GBM_COLLECT_POLICY") == "exploitbeam":
        from engine.exploit_beam_ai import ExploitBeamAI
        return ExploitBeamAI(rng=random.Random(seed * 5 + 1), beam_width=16, max_depth=10)
    ai = DeepPlanningAI(rng=random.Random(seed * 5 + 1), beam_width=8, max_depth=8,
                        adaptive=False, max_turns=1)
    ai.set_ai_opp(GreedyAI(rng=random.Random(seed * 7 + 3)))
    return ai


def _collect_game(seed: int) -> list:
    slug = _W["slug"]
    fp = seed % 2
    state = setup_game(_load(slug), _load(slug), rng=random.Random(seed),
                       first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    test_idx = 0 if fp == 0 else 1
    selfplay = os.environ.get("ONEPIECE_GBM_SELFPLAY") == "1"
    record_all = os.environ.get("ONEPIECE_GBM_RECORD_ALL") == "1"
    ais = [None, None]
    ais[test_idx] = _make_beam(seed)        # = value を使う側
    # self-play: 相手も同じ強いAI (= ExploitBeam)。 さもなくば greedy。
    if selfplay:
        ais[1 - test_idx] = _make_beam(seed * 3 + 99)
    else:
        ais[1 - test_idx] = GreedyAI(rng=random.Random(seed * 5 + 2))
    feats: list = []
    seen_turns: set = set()
    n = 0
    while not state.game_over and state.turn_number < 50 and n < 1500:
        cur = state.turn_player_idx
        # record_all: 自ターン中の全盤面 (= beam の葉分布をカバー)。 さもなくば MAIN 開始のみ。
        if cur == test_idx and state.phase == Phase.MAIN:
            if record_all or state.turn_number not in seen_turns:
                seen_turns.add(state.turn_number)
                try:
                    feats.append(features(state, test_idx))
                except Exception:
                    pass
        try:
            play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    if not state.game_over:
        return []
    won = 1 if getattr(state, "winner", -1) == test_idx else 0
    return [(f, won) for f in feats]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="cardrush_1342")
    ap.add_argument("--games", type=int, default=500)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "db" / "value_gbm_cardrush_1342.pkl")
    ap.add_argument("--rich", action=argparse.BooleanOptionalAction, default=True,
                    help="rich(v2=21特徴: lethal+counter)で学習 (既定)。 --no-rich で v1(17特徴)")
    args = ap.parse_args()

    # rich を worker spawn 前に env で伝播 (= fork 継承、 gbm_value.features が読む)。
    os.environ["ONEPIECE_GBM_RICH"] = "1" if args.rich else "0"

    print(f"=== collect beam-vs-greedy ({args.deck}, {args.games} games, "
          f"{'rich-v2' if args.rich else 'v1'}) ===", flush=True)
    t0 = time.perf_counter()
    seeds = list(range(800000, 800000 + args.games))
    rows: list = []
    with mp.Pool(args.workers, initializer=_winit, initargs=(args.deck,)) as pool:
        for i, out in enumerate(pool.imap_unordered(_collect_game, seeds, chunksize=1)):
            rows.extend(out)
            if (i + 1) % 50 == 0:
                print(f"  {i+1}/{args.games} games, {len(rows)} samples", flush=True)
    print(f"collected {len(rows)} samples in {time.perf_counter()-t0:.0f}s", flush=True)
    if len(rows) < 200:
        print("ERROR: too few samples", flush=True)
        return

    X = np.array([r[0] for r in rows], dtype=float)
    y = np.array([r[1] for r in rows], dtype=int)
    print(f"X shape {X.shape}, win rate {y.mean():.1%}", flush=True)

    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.model_selection import cross_val_score
    clf = GradientBoostingClassifier(n_estimators=200, max_depth=3, learning_rate=0.05,
                                     subsample=0.8, random_state=0)
    # quick CV (= 学習が信号を捉えているか)
    cv = cross_val_score(clf, X, y, cv=4, scoring="roc_auc")
    print(f"CV ROC-AUC: {cv.mean():.3f} +/- {cv.std():.3f}", flush=True)
    clf.fit(X, y)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "wb") as f:
        pickle.dump(clf, f)
    print(f"saved GBM -> {args.out}", flush=True)


if __name__ == "__main__":
    main()
