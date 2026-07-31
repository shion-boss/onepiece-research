"""Rust ネイティブ方策の head-to-head A/B (席・デッキ均等化 + checkpoint 再開) — 2026-07-31。

`eng.eval_policies` で **左右に別方策** (greedy / beam / rollout / rollout_beam) を置いて対戦させ、
hero (mode0) の勝率を測る。 EI ループの「教師は本当に配備方策より強いのか」を確かめる物差し。

均等化 (重要、 [[feedback_ab_harness_balance_player_index]]): 同一 seed で
  (a) hero=p0 / (b) hero=p1  の 2 game を必ず打つ。 seed が決めるのは デッキ組・先攻・シャッフルなので、
  この 2 本で **席バイアス と デッキ配分バイアス が同時に相殺** される。

  .venv/bin/python scripts/rust_policy_ab.py --mode0 rollout --mode1 beam --pairs 200
  .venv/bin/python scripts/rust_policy_ab.py --mode0 rollout --mode1 beam --pairs 200 --resume

進捗は 10 秒毎 (既定) に stdout、 結果は --out (既定 db/rust_selfplay/policy_ab_<m0>_vs_<m1>.json) に
逐次 checkpoint。 中断しても --resume で続きから。
"""
from __future__ import annotations
import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import optcg_engine as eng  # noqa: E402
import scripts.rust_parity_check as P  # noqa: E402
from engine.state_snapshot import _ser_full  # noqa: E402

OUT_DIR = ROOT / "db" / "rust_selfplay"

# rust_selfplay_ei.DECK_POOL と同一 (生成と評価で同じ分布を見る為)
DECK_POOL = [
    "cardrush_1385", "cardrush_1478", "cardrush_1342", "cardrush_1491",
    "pros02_zoro_g", "tcgportal_op13_luffy",
]

_deck_cache: dict[str, str] = {}


def deck_value(slug: str) -> str:
    """マリガン判定材料込みの deck Value (rust_parity_check.deck_value に集約)。"""
    return P.deck_value(slug)


def rng_state(seed: int) -> str:
    return json.dumps(list(random.Random(seed).getstate()[1]))


def pair_of(seed: int) -> tuple[str, str]:
    a = DECK_POOL[seed % len(DECK_POOL)]
    b = DECK_POOL[(seed // len(DECK_POOL) + 1) % len(DECK_POOL)]
    if a == b:
        b = DECK_POOL[(seed + 1) % len(DECK_POOL)]
    return a, b


def wilson(wins: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """勝率の Wilson 信頼区間 (下限, 上限)。 n 小でも破綻しない。"""
    if n == 0:
        return (0.0, 1.0)
    p = wins / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def run(args: argparse.Namespace) -> dict:
    out_path = Path(args.out) if args.out else OUT_DIR / f"policy_ab_{args.mode0}_vs_{args.mode1}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    state = {"mode0": args.mode0, "mode1": args.mode1, "beam": args.beam, "depth": args.depth,
             "rollout_plies": args.rollout_plies, "seed0": args.seed0, "pairs_target": args.pairs,
             "done_pairs": 0, "hero_wins": 0.0, "games": 0, "draws": 0,
             "per_deck": {}, "sec": 0.0, "results": []}
    if args.resume and out_path.exists():
        try:
            prev = json.loads(out_path.read_text(encoding="utf-8"))
            if (prev.get("mode0"), prev.get("mode1"), prev.get("seed0")) == (args.mode0, args.mode1, args.seed0):
                state = prev
                state["pairs_target"] = args.pairs
                print(f"[resume] {state['done_pairs']} pair 済から再開", flush=True)
        except Exception as e:
            print(f"[resume] 読めず新規開始: {e}", flush=True)

    w0 = args.weights0 or None
    w1 = args.weights1 or None
    t0 = time.time()
    last_report = t0
    base_sec = state["sec"]

    for k in range(state["done_pairs"], args.pairs):
        seed = args.seed0 + k
        a, b = pair_of(seed)
        first = seed % 2
        # (a) hero = p0 (deck a)、 (b) hero = p1 (deck b) — 席とデッキを同時に均等化
        for hero_side in (0, 1):
            m0, m1 = (args.mode0, args.mode1) if hero_side == 0 else (args.mode1, args.mode0)
            ww0, ww1 = (w0, w1) if hero_side == 0 else (w1, w0)
            r = json.loads(eng.eval_policies(deck_value(a), deck_value(b), rng_state(seed), first,
                                             m0, m1, ww0, ww1, args.beam, args.depth,
                                             args.max_turns, args.rollout_plies))
            winner = r.get("winner")
            state["games"] += 1
            hero_deck = a if hero_side == 0 else b
            pd = state["per_deck"].setdefault(hero_deck, [0, 0.0])
            pd[0] += 1
            if winner is None:
                state["draws"] += 1
                state["hero_wins"] += 0.5
                pd[1] += 0.5
            elif winner == hero_side:
                state["hero_wins"] += 1.0
                pd[1] += 1.0
        state["done_pairs"] = k + 1

        now = time.time()
        if now - last_report >= args.report_sec or state["done_pairs"] == args.pairs:
            state["sec"] = base_sec + (now - t0)
            n, w = state["games"], state["hero_wins"]
            lo, hi = wilson(w, n)
            out_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"[{state['done_pairs']}/{args.pairs} pair | {n} game | {state['sec']:.0f}s] "
                  f"{args.mode0} win {w/n:.3f} (95%CI {lo:.3f}-{hi:.3f}) draw {state['draws']}",
                  flush=True)
            last_report = now

    state["sec"] = base_sec + (time.time() - t0)
    n, w = state["games"], state["hero_wins"]
    lo, hi = wilson(w, n)
    state["hero_winrate"] = round(w / n, 4) if n else None
    state["ci95"] = [round(lo, 4), round(hi, 4)]
    state["sec_per_game"] = round(state["sec"] / n, 3) if n else None
    out_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n=== 結果 ===", flush=True)
    print(f"{args.mode0} vs {args.mode1}: {w:.1f}/{n} = {w/n:.3f} (95%CI {lo:.3f}-{hi:.3f}), "
          f"draw {state['draws']}, {state['sec']:.0f}s ({state['sec']/n:.2f} s/game)", flush=True)
    for dk, (dn, dw) in sorted(state["per_deck"].items(), key=lambda kv: -kv[1][0]):
        print(f"  {dk:24s} n={dn:4d} hero win {dw/dn:.3f}", flush=True)
    print(f"→ {out_path}", flush=True)
    return state


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode0", default="rollout", help="hero 方策 (greedy/beam/rollout/rollout_beam)")
    ap.add_argument("--mode1", default="beam", help="相手方策")
    ap.add_argument("--pairs", type=int, default=200, help="seed 数 (1 seed = 2 game)")
    ap.add_argument("--seed0", type=int, default=20000)
    ap.add_argument("--beam", type=int, default=8)
    ap.add_argument("--depth", type=int, default=12)
    ap.add_argument("--rollout-plies", type=int, default=80)
    ap.add_argument("--max-turns", type=int, default=40)
    ap.add_argument("--weights0", default=None, help="hero value 重み JSON 文字列 (省略=heuristic)")
    ap.add_argument("--weights1", default=None)
    ap.add_argument("--report-sec", type=float, default=10.0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--resume", action="store_true")
    run(ap.parse_args())


if __name__ == "__main__":
    main()
