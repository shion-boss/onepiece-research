# -*- coding: utf-8 -*-
"""Plan F Phase 2 ローカル CPU 版: REINFORCE で weight NN を fine-tune。

WeightNN は ~80K params の小型 NN、 CPU で十分 (= 数分で完走)。
Colab 不要、 ohtsuki さん手動操作なし。 全自動 cycle 用。

実行例:
  .venv/bin/python scripts/train_weight_nn_rl_local.py \\
    --snapshot db/twoturn_snapshots.jsonl \\
    --base db/weight_nn.pt \\
    --output db/weight_nn_rl.pt \\
    --epochs 30
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.weight_nn import WeightNN  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch-size", type=int, default=512)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--gamma", type=float, default=0.95, help="reward discount")
    ap.add_argument("--noise-std", type=float, default=0.3, help="Gaussian policy noise std")
    args = ap.parse_args()

    print(f"=== Plan F Phase 2 ローカル CPU REINFORCE ===", flush=True)
    print(f"  snapshot: {args.snapshot}", flush=True)
    print(f"  base: {args.base} → output: {args.output}", flush=True)

    # snapshot 読み込み
    t0 = time.time()
    snapshots = []
    with open(args.snapshot, encoding="utf-8") as f:
        for line in f:
            try:
                s = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "state_encoded" not in s or "reward" not in s:
                continue
            snapshots.append(s)
    print(f"  loaded {len(snapshots)} snapshots in {time.time()-t0:.1f}s", flush=True)

    if not snapshots:
        print("[ERROR] no snapshots", flush=True)
        return 1

    # reward 分布
    from collections import Counter
    r_dist = Counter(s["reward"] for s in snapshots)
    print(f"  reward dist: {dict(r_dist)}", flush=True)

    # discount reward
    for s in snapshots:
        delta = max(0, s.get("max_turn", s.get("turn", 0)) - s.get("turn", 0))
        s["discounted_reward"] = s["reward"] * (args.gamma ** delta)

    # tensor 化
    STATE_DIM = 172
    X_np = np.zeros((len(snapshots), STATE_DIM), dtype=np.float32)
    R_np = np.zeros((len(snapshots),), dtype=np.float32)
    for i, s in enumerate(snapshots):
        se = s["state_encoded"]
        if len(se) >= STATE_DIM:
            X_np[i, :] = se[:STATE_DIM]
        else:
            X_np[i, :len(se)] = se
        R_np[i] = s["discounted_reward"]

    X = torch.from_numpy(X_np)
    R = torch.from_numpy(R_np)
    print(f"  X shape: {X.shape}, R range: [{R.min():.2f}, {R.max():.2f}], mean: {R.mean():.3f}", flush=True)

    # baseline = mean reward で advantage 算出
    baseline = R.mean()
    advantage = R - baseline
    print(f"  baseline: {baseline:.3f}, advantage std: {advantage.std():.3f}", flush=True)

    # model load
    model = WeightNN()
    model.load_state_dict(torch.load(args.base, map_location="cpu", weights_only=True))
    model.train()
    n_params = sum(p.numel() for p in model.parameters())
    print(f"  model loaded, params: {n_params}", flush=True)

    optimizer = optim.Adam(model.parameters(), lr=args.lr)

    train_ds = TensorDataset(X, advantage)
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)

    print(f"\n=== Training (epochs={args.epochs}, batch={args.batch_size}, lr={args.lr}) ===", flush=True)
    for epoch in range(args.epochs):
        model.train()
        epoch_loss = 0.0
        n_batches = 0
        t_epoch = time.time()
        for xb, advb in train_loader:
            optimizer.zero_grad()
            mu = model(xb)
            # Gaussian policy: sampled weights = mu + noise
            eps = torch.randn_like(mu) * args.noise_std * mu.abs().mean(dim=1, keepdim=True)
            sampled = mu + eps
            std = args.noise_std * mu.abs().mean(dim=1, keepdim=True).clamp(min=1.0)
            log_prob = -0.5 * ((sampled - mu) / std) ** 2
            log_prob = log_prob.sum(dim=1)
            loss = -(log_prob * advb).mean()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
            epoch_loss += loss.item()
            n_batches += 1
        avg = epoch_loss / max(1, n_batches)
        print(f"  epoch {epoch+1}/{args.epochs}: avg_loss={avg:.4f}, {time.time()-t_epoch:.1f}s", flush=True)

    # save
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), args.output)
    print(f"\nsaved: {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
