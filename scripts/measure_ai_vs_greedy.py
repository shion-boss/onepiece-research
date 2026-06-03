#!/usr/bin/env python3
"""較正: 各 AI が GreedyAI に対して何 % 勝つか (= 達成可能な天井の目安)。

ohtsuki「greedy には負ける気がしない = 90% いけるはず」 を data で確認する。
PlanLibraryAI が greedy-anchor で ~54% に頭打ち = greedy 天井。 beam (= 既存の強 AI) が
何 % 取れるかで「この engine/deck で強 AI が greedy をどこまで割れるか」 を測る。
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from engine.ai import GreedyAI, PlanningAI, RandomAI
from scripts.plan_value_iteration import play_game, _load

_W: dict = {}


def _winit(slug: str) -> None:
    _W["slug"] = slug


def _make_ai(kind: str, seed: int):
    rng = random.Random(seed * 5 + 1)
    if kind == "beam":
        return PlanningAI(rng=rng, beam_width=4, max_depth=6, adaptive=False, max_turns=1)
    if kind == "beam_adaptive":
        return PlanningAI(rng=rng, adaptive=True)
    if kind == "greedy":
        return GreedyAI(rng=rng)
    if kind == "random":
        return RandomAI(rng=rng)
    raise ValueError(kind)


def _wgame(task: tuple) -> str:
    kind, seed = task
    ai = _make_ai(kind, seed)
    opp = GreedyAI(random.Random(seed * 5 + 2))
    res = play_game(_load(_W["slug"]), _load(_W["slug"]), ai, opp, seed)
    if res["error"]:
        return "error"
    w = res["winner"]
    if w < 0:
        return "draw"
    return "win" if w == res["test_idx"] else "loss"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="cardrush_1342")
    ap.add_argument("--ai", default="beam", choices=["beam", "beam_adaptive", "greedy", "random"])
    ap.add_argument("--games", type=int, default=120)
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    seeds = [(args.ai, 500000 + g) for g in range(args.games)]
    print(f"=== {args.ai} vs GreedyAI on {args.deck} (mirror, n={args.games}) ===", flush=True)
    with mp.Pool(args.workers, initializer=_winit, initargs=(args.deck,)) as pool:
        out = list(pool.imap_unordered(_wgame, seeds, chunksize=1))
    win = out.count("win")
    loss = out.count("loss")
    draw = out.count("draw")
    err = out.count("error")
    total = win + loss
    wr = win / total if total else 0.0
    print(f"  winrate={wr:.1%}  W{win}-L{loss}  D{draw} err{err}", flush=True)


if __name__ == "__main__":
    main()
