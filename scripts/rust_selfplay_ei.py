"""Rust ネイティブ self-play による Expert Iteration ループ (データフライホイール) — 2026-07-31。

Rust engine を作った本来の目的 = self-play 学習ループを単一 PC で回す。 その最小実装:

  ① 生成: 現在の value でネイティブ self-play (eng.self_play collect_traj) → (特徴, 勝敗ラベル)
  ② 学習: logistic regression で value 重み (16 次元) を学習 → db/rust_value_weights.json
  ③ 評価: 新 value greedy vs 旧 value greedy を head-to-head (eng.eval_ab、 先後均等) で勝率測定
  ④ 反復: 勝率 > gate なら新 value を採用して ①へ

value は features() の線形結合 (logistic) = Rust の eval_with に weights を渡すだけで完結
(GBM/NN より弱いが Rust 移植が自明でループが閉じる = capability 優先。 強い value は次段)。

  .venv/bin/python scripts/rust_selfplay_ei.py --rounds 4 --games 200 --eval-games 120
  .venv/bin/python scripts/rust_selfplay_ei.py --resume   # 既存 weights から再開

⚠ v1 の限界 (self-play 品質): 方策=greedy (beam でなく、 生成速度優先) / 防御未実装 (アタック貫通) /
  value=線形。 = 「フライホイールが閉じて value が greedy を強くする」を実証する最小系。
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

import numpy as np  # noqa: E402
import optcg_engine as eng  # noqa: E402
import scripts.rust_parity_check as P  # noqa: E402
from engine.state_snapshot import _ser_full  # noqa: E402

WEIGHTS_PATH = ROOT / "db" / "rust_value_weights.json"
N_FEATURES = 16

# 生成/評価に使うデッキ pool (メタ 16 の一部。 多様性のため異なるアーキタイプ)。
DECK_POOL = [
    "cardrush_1385", "cardrush_1478", "cardrush_1342", "cardrush_1491",
    "pros02_zoro_g", "tcgportal_op13_luffy",
]

_deck_cache: dict[str, str] = {}


def deck_value(slug: str) -> str:
    if slug not in _deck_cache:
        d = P._dl(slug)
        _deck_cache[slug] = json.dumps({"leader": _ser_full(d.leader),
                                        "main": [_ser_full(c) for c in d.main]})
    return _deck_cache[slug]


def rng_state(seed: int) -> str:
    return json.dumps(list(random.Random(seed).getstate()[1]))


def generate(weights: list[float] | None, n_games: int, seed0: int) -> tuple[np.ndarray, np.ndarray]:
    """現在の value で n_games 生成し (特徴 X, ラベル y) を返す。"""
    wj = json.dumps(weights) if weights is not None else None
    X, Y = [], []
    for g in range(n_games):
        seed = seed0 + g
        a = DECK_POOL[seed % len(DECK_POOL)]
        b = DECK_POOL[(seed // len(DECK_POOL) + 1) % len(DECK_POOL)]
        if a == b:
            b = DECK_POOL[(seed + 1) % len(DECK_POOL)]
        r = json.loads(eng.self_play(deck_value(a), deck_value(b), rng_state(seed),
                                     seed % 2, "greedy", wj, 8, 12, 40, True))
        for row in r.get("trajectory", []):
            X.append(row["f"])
            Y.append(row["y"])
    return np.asarray(X, dtype=np.float64), np.asarray(Y, dtype=np.float64)


def train_logistic(X: np.ndarray, y: np.ndarray, l2: float = 1e-3, iters: int = 400, lr: float = 0.5) -> list[float]:
    """features (bias 込み 16 次元) → P(勝ち) の logistic regression。 numpy full-batch GD。"""
    n, d = X.shape
    w = np.zeros(d)
    for _ in range(iters):
        z = X @ w
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
        grad = X.T @ (p - y) / n + l2 * w
        w -= lr * grad
    return w.tolist()


def eval_ab(w_new: list[float] | None, w_old: list[float] | None, n_games: int, seed0: int,
            mode: str = "beam") -> float:
    """value(w_new) vs value(w_old) を head-to-head。 先後を均等化して w_new の勝率を返す。
    ⚠ mode=beam 推奨: 学習 value は greedy-1-ply では spurious 特徴を exploit されて負ける
    (empty-hand=win 等)、 探索 (beam) の葉評価に使うと heuristic を上回る (memory: value は search に載せる)。"""
    wn = json.dumps(w_new) if w_new is not None else None
    wo = json.dumps(w_old) if w_old is not None else None
    wins = 0
    played = 0
    for g in range(n_games):
        seed = seed0 + g
        a = DECK_POOL[seed % len(DECK_POOL)]
        b = DECK_POOL[(seed // len(DECK_POOL) + 1) % len(DECK_POOL)]
        if a == b:
            b = DECK_POOL[(seed + 1) % len(DECK_POOL)]
        # 前半: new=player0 / 後半: new=player1 (先後・席均等化)
        new_is_p0 = g % 2 == 0
        w0j, w1j = (wn, wo) if new_is_p0 else (wo, wn)
        r = json.loads(eng.eval_ab(deck_value(a), deck_value(b), rng_state(seed),
                                   seed % 2, mode, w0j, w1j, 8, 10, 40))
        win = r.get("winner")
        if win is None:
            played += 1
            continue  # draw = 0.5 は wins に足さない (played に数える)
        new_won = (win == 0) == new_is_p0
        wins += 1 if new_won else 0
        played += 1
    return wins / played if played else 0.0


def main():
    ap = argparse.ArgumentParser(description="Rust self-play Expert Iteration ループ")
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--games", type=int, default=200, help="1 round の生成ゲーム数")
    ap.add_argument("--eval-games", type=int, default=120, help="A/B 評価ゲーム数")
    ap.add_argument("--gate", type=float, default=0.53, help="採用する勝率下限 (対 前 value)")
    ap.add_argument("--resume", action="store_true", help="既存 weights から再開")
    args = ap.parse_args()

    eng.load_overlay(str(ROOT / "db" / "card_effects.json"))

    weights: list[float] | None = None
    if args.resume and WEIGHTS_PATH.exists():
        weights = json.loads(WEIGHTS_PATH.read_text())["weights"]
        print(f"resume: 既存 value (次元 {len(weights)}) から開始")

    for rnd in range(args.rounds):
        t0 = time.time()
        # ① 生成 (現在の value で self-play)
        X, y = generate(weights, args.games, seed0=1000 * (rnd + 1))
        gen_dt = time.time() - t0
        # ② 学習
        w_new = train_logistic(X, y)
        # ③ 評価 (新 value greedy vs 旧 value greedy)
        wr = eval_ab(w_new, weights, args.eval_games, seed0=50_000 + 1000 * rnd)
        adopt = wr >= args.gate
        tag = "採用" if adopt else "棄却"
        print(f"round {rnd}: gen {args.games}g/{len(y)}rows {gen_dt:.1f}s | "
              f"A/B 新vs旧 = {wr*100:.1f}% (N={args.eval_games}) → {tag}")
        if adopt:
            weights = w_new
            WEIGHTS_PATH.write_text(json.dumps({
                "weights": weights, "n_features": N_FEATURES, "round": rnd,
                "note": "Rust self-play EI logistic value (features 線形, bias 込み 16dim)",
            }, ensure_ascii=False, indent=1), encoding="utf-8")

    if weights is not None:
        print(f"\n最終 value → {WEIGHTS_PATH}")
        print("Rust で使う: eng.self_play(..., weights_json=json.dumps(weights), ...)")


if __name__ == "__main__":
    main()
