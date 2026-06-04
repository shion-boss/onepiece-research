#!/usr/bin/env python3
"""GreedyAI 70%+ への探索: 各 AI config を vs GreedyAI で並列ベンチ (= 2026-06-04, 自律)。

opponent が GreedyAI なので、 beam が opp_sim=GreedyAI で読めば実相手を正確にモデル化でき
exploit できるはず。 各 config を N 戦して winrate を sort 表示、 best を選ぶ。
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import random
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.plan_value_iteration import play_game, _load

_W: dict = {}


def _build_ai(kind: str, params: dict, seed: int):
    from engine.ai import GreedyAI, MCTSAI, LookaheadAI, DeepPlanningAI
    rng = random.Random(seed * 5 + 1)
    if kind == "greedy":
        return GreedyAI(rng=rng)
    if kind == "lookahead":
        return LookaheadAI(rng=rng)
    if kind == "mcts":
        return MCTSAI(rng=rng, n_simulations=params.get("n", 50),
                      rollout_depth=params.get("depth", 12),
                      c_uct=params.get("c", 1.41))
    if kind == "smart":
        from engine.smart_opponent_ai import SmartOpponentAI
        return SmartOpponentAI(rng=rng, threshold=params.get("threshold", 0.55))
    if kind == "azmcts":
        from engine.az_mcts import AZMctsAI
        vf = None
        if params.get("value_nn"):
            from engine.value_nn_alphazero import compute_value_az
            def vf(state, to_move, _c=compute_value_az):
                p = _c(state, to_move)
                return p if p is not None else 0.5
        return AZMctsAI(rng=rng, n_sim=params.get("n", 120),
                        c_puct=params.get("c", 1.5), value_fn=vf)
    if kind == "exploitbeam":
        from engine.exploit_beam_ai import ExploitBeamAI
        return ExploitBeamAI(rng=rng, beam_width=params.get("w", 16),
                             max_depth=params.get("d", 10))
    if kind == "exploit":
        from engine.exploit_greedy_ai import ExploitGreedyAI
        return ExploitGreedyAI(rng=rng, node_cap=params.get("node_cap", 1500),
                               top_k=params.get("top_k", 10),
                               rollouts=params.get("rollouts", 4))
    if kind == "beam":
        ai = DeepPlanningAI(
            rng=rng, beam_width=params.get("w", 4), max_depth=params.get("d", 6),
            adaptive=params.get("adaptive", False), max_turns=params.get("mt", 1))
        # opponent は GreedyAI なので defense/opp sim を greedy に固定 (= 実相手を正確 model 化)
        ai.set_ai_opp(GreedyAI(rng=random.Random(seed * 7 + 3)))
        return ai
    raise ValueError(kind)


def _winit(slug: str, cfg: dict, opp_kind: str = "greedy") -> None:
    _W["slug"] = slug
    _W["cfg"] = cfg
    _W["opp"] = opp_kind
    for k, v in cfg.get("env", {}).items():
        os.environ[k] = v


def _make_opp(seed: int):
    from engine.ai import GreedyAI
    if _W.get("opp") == "exploitbeam":
        from engine.exploit_beam_ai import ExploitBeamAI
        return ExploitBeamAI(rng=random.Random(seed * 5 + 2))
    return GreedyAI(random.Random(seed * 5 + 2))


def _wgame(seed: int) -> str:
    cfg = _W["cfg"]
    ai = _build_ai(cfg["kind"], cfg.get("params", {}), seed)
    opp = _make_opp(seed)
    res = play_game(_load(_W["slug"]), _load(_W["slug"]), ai, opp, seed)
    if res["error"]:
        return "error"
    w = res["winner"]
    if w < 0:
        return "draw"
    return "win" if w == res["test_idx"] else "loss"


def run_cfg(slug: str, cfg: dict, n: int, workers: int, opp_kind: str = "greedy") -> dict:
    seeds = list(range(700000, 700000 + n))
    t0 = time.perf_counter()
    with mp.Pool(workers, initializer=_winit, initargs=(slug, cfg, opp_kind)) as pool:
        out = list(pool.imap_unordered(_wgame, seeds, chunksize=1))
    win = out.count("win")
    loss = out.count("loss")
    total = win + loss
    return {"name": cfg["name"], "winrate": (win / total) if total else 0.0,
            "wins": win, "losses": loss, "draws": out.count("draw"),
            "errors": out.count("error"), "sec": time.perf_counter() - t0}


# 探索する config 群
CONFIGS = [
    {"name": "greedy", "kind": "greedy"},
    {"name": "exploitbeam", "kind": "exploitbeam", "params": {"w": 16, "d": 10}},
    {"name": "lookahead", "kind": "lookahead"},
    {"name": "beam_4_6_1", "kind": "beam", "params": {"w": 4, "d": 6, "mt": 1}},
    {"name": "beam_8_8_1", "kind": "beam", "params": {"w": 8, "d": 8, "mt": 1}},
    {"name": "beam_8_8_1_dyn", "kind": "beam", "params": {"w": 8, "d": 8, "mt": 1},
     "env": {"ONEPIECE_DYNAMIC_WEIGHTS": "1"}},
    {"name": "beam_8_8_1_az", "kind": "beam", "params": {"w": 8, "d": 8, "mt": 1},
     "env": {"ONEPIECE_AZ_VALUE_NN": "1"}},
    {"name": "beam_8_8_1_gbm", "kind": "beam", "params": {"w": 8, "d": 8, "mt": 1},
     "env": {"ONEPIECE_GBM_VALUE_PATH": "db/value_gbm_cardrush_1342.pkl"}},
    {"name": "beam_8_8_1_postopp", "kind": "beam", "params": {"w": 8, "d": 8, "mt": 1},
     "env": {"ONEPIECE_POSTOPP_EVAL": "1"}},
    {"name": "beam_16_10_1_postopp", "kind": "beam", "params": {"w": 16, "d": 10, "mt": 1},
     "env": {"ONEPIECE_POSTOPP_EVAL": "1"}},
    {"name": "beam_32_12_1_postopp", "kind": "beam", "params": {"w": 32, "d": 12, "mt": 1},
     "env": {"ONEPIECE_POSTOPP_EVAL": "1"}},
    {"name": "beam_16_10_1_postopp_gbm", "kind": "beam", "params": {"w": 16, "d": 10, "mt": 1},
     "env": {"ONEPIECE_POSTOPP_EVAL": "1",
             "ONEPIECE_GBM_VALUE_PATH": "db/value_gbm_cardrush_1342.pkl"}},
    {"name": "beam_32_12_1_postopp_gbm", "kind": "beam", "params": {"w": 32, "d": 12, "mt": 1},
     "env": {"ONEPIECE_POSTOPP_EVAL": "1",
             "ONEPIECE_GBM_VALUE_PATH": "db/value_gbm_cardrush_1342.pkl"}},
    {"name": "beam_16_10_1_postopp_gbmv2", "kind": "beam", "params": {"w": 16, "d": 10, "mt": 1},
     "env": {"ONEPIECE_POSTOPP_EVAL": "1",
             "ONEPIECE_GBM_VALUE_PATH": "db/value_gbm_cardrush_1342_v2.pkl"}},
    # self-play value (= V_sp) を beam の葉で直接使う (post-opp 無し、 AlphaZero型)
    {"name": "beam_8_8_1_vsp", "kind": "beam", "params": {"w": 8, "d": 8, "mt": 1},
     "env": {"ONEPIECE_GBM_VALUE_PATH": "db/value_gbm_cardrush_1342_sp.pkl"}},
    {"name": "beam_16_10_1_vsp", "kind": "beam", "params": {"w": 16, "d": 10, "mt": 1},
     "env": {"ONEPIECE_GBM_VALUE_PATH": "db/value_gbm_cardrush_1342_sp.pkl"}},
    # ExploitBeam (= v1, 72.7%) を相手にする汎化テスト用にも使える config
    {"name": "exploitbeam_t", "kind": "exploitbeam", "params": {"w": 16, "d": 10}},
    {"name": "smart", "kind": "smart", "params": {"threshold": 0.55}},
    {"name": "azmcts_120", "kind": "azmcts", "params": {"n": 120}},
    {"name": "azmcts_240", "kind": "azmcts", "params": {"n": 240}},
    {"name": "beam_12_8_1_gbm", "kind": "beam", "params": {"w": 12, "d": 8, "mt": 1},
     "env": {"ONEPIECE_GBM_VALUE_PATH": "db/value_gbm_cardrush_1342.pkl"}},
    {"name": "beam_12_10_1", "kind": "beam", "params": {"w": 12, "d": 10, "mt": 1}},
    {"name": "beam_16_12_1", "kind": "beam", "params": {"w": 16, "d": 12, "mt": 1}},
    {"name": "beam_24_14_1", "kind": "beam", "params": {"w": 24, "d": 14, "mt": 1}},
    {"name": "beam_adaptive", "kind": "beam", "params": {"adaptive": True}},
    {"name": "beam_8_14_2", "kind": "beam", "params": {"w": 8, "d": 14, "mt": 2}},
    {"name": "beam_10_18_2_gd", "kind": "beam", "params": {"w": 10, "d": 18, "mt": 2},
     "env": {"ONEPIECE_GOAL_MIRROR_OPP": "0"}},
    {"name": "mcts_30", "kind": "mcts", "params": {"n": 30, "depth": 18}},
    {"name": "beam_6_10_2_greedyopp", "kind": "beam", "params": {"w": 6, "d": 10, "mt": 2},
     "env": {"ONEPIECE_LIGHT_OPP_SIM": "1"}},
    {"name": "beam_8_12_3_greedyopp", "kind": "beam", "params": {"w": 8, "d": 12, "mt": 3},
     "env": {"ONEPIECE_LIGHT_OPP_SIM": "1"}},
    {"name": "exploit_k10_r4", "kind": "exploit",
     "params": {"top_k": 10, "rollouts": 4, "node_cap": 1500}},
    {"name": "exploit_k8_r8", "kind": "exploit",
     "params": {"top_k": 8, "rollouts": 8, "node_cap": 1500}},
    {"name": "mcts_50", "kind": "mcts", "params": {"n": 50}},
    {"name": "mcts_150", "kind": "mcts", "params": {"n": 150}},
    {"name": "mcts_400", "kind": "mcts", "params": {"n": 400}},
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="cardrush_1342")
    ap.add_argument("--n", type=int, default=80)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--only", nargs="*", default=None, help="config 名で絞る")
    ap.add_argument("--opp", default="greedy", choices=["greedy", "exploitbeam"],
                    help="対戦相手 (= 汎化テストは exploitbeam)")
    args = ap.parse_args()

    cfgs = CONFIGS if not args.only else [c for c in CONFIGS if c["name"] in args.only]
    print(f"=== bench vs {args.opp} on {args.deck} (N={args.n}/config) ===", flush=True)
    results = []
    for cfg in cfgs:
        r = run_cfg(args.deck, cfg, args.n, args.workers, args.opp)
        results.append(r)
        print(f"  {r['name']:26s} winrate={r['winrate']:5.1%}  "
              f"W{r['wins']:3d}-L{r['losses']:3d} D{r['draws']} err{r['errors']}  "
              f"({r['sec']:.0f}s, {r['sec']/max(args.n,1):.2f}s/g)", flush=True)

    print("\n=== sorted ===", flush=True)
    for r in sorted(results, key=lambda x: -x["winrate"]):
        flag = "  <<< 70%+" if r["winrate"] >= 0.70 else ""
        print(f"  {r['name']:26s} {r['winrate']:5.1%}{flag}", flush=True)


if __name__ == "__main__":
    main()
