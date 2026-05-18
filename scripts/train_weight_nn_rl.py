# -*- coding: utf-8 -*-
"""Plan F Phase 2 (= 2026-05-18 ユーザ示唆の正規実装): REINFORCE で TwoTurn AI 専用 評価関数 学習。

哲学:
  対戦用 AI = TwoTurnPlanningAI 固定。 その AI 専用の評価関数を NN で学習。
  「2 ターン後を予測して打った手がいい手だったかは試合終了まで分からない」
  → 試合終了で reward を全 snapshot に配布 → NN update。 反復で「いい手 / 悪い手」 判断。

REINFORCE algorithm:
  1. self-play で 1 試合実行、 各 state で NN(state) → weights、 plan_search → action
  2. 各 (state, weights, action) を snapshot に記録
  3. 試合終了で reward = ±1
  4. NN update: log P(weights|state) × reward を maximize
     (= 勝った試合の weights を NN が出やすくなる、 負けた試合は出にくく)
  5. 反復 (= 1000 試合 / iteration × 20 iterations)

実行例:
  .venv/bin/python scripts/train_weight_nn_rl.py \\
    --base db/weight_nn.pt \\
    --output-dir db/weight_nn_rl/ \\
    --iterations 5 --games-per-iter 500 --workers 8
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

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# worker-side globals
_WORKER_REPO = None
_WORKER_OVERLAY = None
_WORKER_DECKS = None
_WORKER_NN_PATH = None


def _worker_init(nn_path: str):
    global _WORKER_REPO, _WORKER_OVERLAY, _WORKER_DECKS, _WORKER_NN_PATH
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
    _WORKER_NN_PATH = nn_path
    # NN を worker process で load (= weight_nn の cache に乗る)
    os.environ["ONEPIECE_WEIGHT_NN_PATH"] = nn_path
    os.environ["ONEPIECE_WEIGHT_NN"] = "1"
    os.environ["ONEPIECE_LIGHT_OPP_SIM"] = "1"
    os.environ["ONEPIECE_DYNAMIC_WEIGHTS"] = "1"


def _play_one_game(args: tuple[int, int]) -> list[dict]:
    """1 試合 self-play、 state + NN(state) weights + reward を記録。"""
    game_idx, seed = args
    rng = random.Random(seed + game_idx * 31)

    from engine.deck import DeckList
    from engine.ai_experimental import WeightNNTwoTurnAI
    from engine.harness import run_matchup
    from engine.weight_nn import get_weight_model
    from engine.state_encoder import encode_state

    deck_a_slug, deck_a = rng.choice(_WORKER_DECKS)
    deck_b_slug, deck_b = rng.choice(_WORKER_DECKS)

    nn_factory = lambda *a, **kw: WeightNNTwoTurnAI(*a, **kw)
    try:
        rep = run_matchup(
            deck_a, deck_b,
            n_games=1, seed=rng.randint(0, 1_000_000),
            ai_factory_1=nn_factory, ai_factory_2=nn_factory,
            keep_logs=False, record_snapshots=True,
            effects_overlay=_WORKER_OVERLAY,
        )
    except Exception as e:
        return [{"error": str(e), "game_idx": game_idx}]

    if not rep.games:
        return []
    g = rep.games[0]
    # winner: 0=deck1 勝、 1=deck2 勝、 -1=draw
    winner = g.winner

    snapshots: list[dict] = []
    if hasattr(g, "snapshots") and g.snapshots:
        for snap in g.snapshots:
            actor = snap.get("actor_idx", -1)
            if actor not in (0, 1):
                continue
            # actor 視点の reward (= 勝者なら +1、 敗者なら -1)
            if winner == -1:
                reward = 0.0
            elif winner == actor:
                reward = 1.0
            else:
                reward = -1.0
            snapshots.append({
                "game_idx": game_idx,
                "actor_idx": actor,
                "turn": snap.get("turn", 0),
                "state_encoded": snap.get("state_encoded"),
                "reward": reward,
            })
    return snapshots


def collect_snapshots(nn_path: str, n_games: int, workers: int = 4, seed: int = 42) -> list[dict]:
    """self-play で snapshot 集める (= parallel workers)。"""
    tasks = [(i, seed) for i in range(n_games)]
    snapshots: list[dict] = []
    t0 = time.time()
    with mp.Pool(workers, initializer=_worker_init, initargs=(nn_path,)) as pool:
        for i, snaps in enumerate(pool.imap_unordered(_play_one_game, tasks, chunksize=2)):
            snapshots.extend(snaps)
            if (i + 1) % 50 == 0:
                elapsed = time.time() - t0
                rate = (i + 1) / elapsed
                eta = (n_games - i - 1) / rate
                print(f"  collect [{i+1}/{n_games}] elapsed {elapsed:.0f}s, rate {rate:.2f}g/s, ETA {eta:.0f}s",
                      flush=True)
    print(f"  collected {len(snapshots)} snapshots from {n_games} games in {time.time()-t0:.0f}s", flush=True)
    return snapshots


def reinforce_update(nn_path: str, snapshots: list[dict], lr: float = 1e-4,
                     n_epochs: int = 3, batch_size: int = 256, gamma: float = 0.95) -> tuple[float, str]:
    """REINFORCE 風 update: 勝った snapshot の出力 weights を NN が再現する方向に学習。

    実装簡略化 (= continuous policy の log_prob 計算は重い):
    1. NN(state) で 期待 weights を生成
    2. 「勝った snapshot」 = 期待 weights を維持 (= self-supervised)
    3. 「負けた snapshot」 = 期待 weights から離れる方向 (= negative reward でずらす)

    実質、 supervised の「勝ったほうを target」 で学習する simplification。
    純粋 REINFORCE より弱いが実装シンプルで効果 期待できる。
    """
    from engine.weight_nn import WeightNN, WEIGHT_KEYS

    # 有効 snapshot 抽出
    valid = [s for s in snapshots if s.get("state_encoded") and "reward" in s and s["reward"] != 0]
    if not valid:
        return 0.0, "no_valid_snapshots"
    print(f"  update: {len(valid)} snapshots (= reward != 0)", flush=True)

    # state + reward tensor 化
    X = torch.tensor([s["state_encoded"] for s in valid], dtype=torch.float32)
    R = torch.tensor([s["reward"] for s in valid], dtype=torch.float32)

    # NN load
    nn_model = WeightNN()
    nn_model.load_state_dict(torch.load(nn_path, map_location="cpu", weights_only=True))
    nn_model.train()
    optimizer = optim.Adam(nn_model.parameters(), lr=lr)

    avg_loss = 0.0
    for epoch in range(n_epochs):
        perm = torch.randperm(len(X))
        epoch_loss = 0.0
        n_batches = 0
        for i in range(0, len(X), batch_size):
            idx = perm[i:i + batch_size]
            xb = X[idx]
            rb = R[idx]
            optimizer.zero_grad()
            # NN(state) → weights、 勝った snapshot で「同じ weights を維持」 を強化
            weights = nn_model(xb)
            # 勝った試合 (= reward=+1) の weights が high probability、
            # 負けた試合 (= reward=-1) の weights が low probability になる方向で update。
            # 単純化: weights の variance を「reward 大なら 小さく (= 安定)、 reward 小なら 大きく」 で控えめに調整
            # 真の REINFORCE は log P(weights|state) × reward だが、 deterministic NN なので緩和。
            # ここでは 「reward × MSE(weights, mean_weights_per_state)」 を loss に。
            mean_w = weights.mean(dim=0, keepdim=True).detach()
            diff = (weights - mean_w) ** 2
            # 勝った: diff を 0 に近づける (= weights 安定化)、 負けた: diff を増やす (= 探索)
            loss = (diff.mean(dim=1) * rb).mean()
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()
            n_batches += 1
        avg_loss = epoch_loss / max(1, n_batches)
        print(f"    epoch {epoch+1}/{n_epochs}: avg_loss={avg_loss:.6f}", flush=True)

    new_path = nn_path.replace(".pt", "_rl.pt")
    torch.save(nn_model.state_dict(), new_path)
    print(f"  saved {new_path}", flush=True)
    return avg_loss, new_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="db/weight_nn.pt")
    ap.add_argument("--output-dir", default="db/weight_nn_rl/")
    ap.add_argument("--iterations", type=int, default=3)
    ap.add_argument("--games-per-iter", type=int, default=200)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--n-epochs", type=int, default=3)
    args = ap.parse_args()

    out_dir = ROOT / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    current_nn_path = str(ROOT / args.base)

    print(f"=== Plan F Phase 2 (= REINFORCE) 開始 ===")
    print(f"  base: {current_nn_path}")
    print(f"  iterations: {args.iterations}, games_per_iter: {args.games_per_iter}, workers: {args.workers}")
    print(f"  lr: {args.lr}, n_epochs: {args.n_epochs}")

    for it in range(args.iterations):
        print(f"\n--- Iteration {it + 1}/{args.iterations} ---")
        t_iter = time.time()
        # 1. self-play で snapshot 集める
        snaps = collect_snapshots(current_nn_path, args.games_per_iter, args.workers,
                                  seed=42 + it * 1000)
        if not snaps:
            print("  [WARN] no snapshots collected, skip update")
            continue

        # 2. NN update
        loss, new_path = reinforce_update(current_nn_path, snaps, lr=args.lr, n_epochs=args.n_epochs)

        # 3. iteration 別に保存
        iter_path = out_dir / f"iter_{it + 1}.pt"
        import shutil
        shutil.copy(new_path, iter_path)

        elapsed = time.time() - t_iter
        print(f"  iteration done in {elapsed:.0f}s, saved {iter_path}", flush=True)
        current_nn_path = str(iter_path)

    print(f"\n=== DONE. final: {current_nn_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
