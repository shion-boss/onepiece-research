# -*- coding: utf-8 -*-
"""Plan D per-deck value NN 学習 (= ローカル CPU 版、 ohtsuki さん Colab 不要)。

入力: db/mcts_rollout_by_deck/<slug>.jsonl × 16
出力: db/value_nn_per_deck/<slug>.pt × 16 + _summary.json

CPU で ~5-10 min 完走 (= 各 deck ~20-30 sec × 16 deck)。

実行例:
  .venv/bin/python scripts/train_value_nn_per_deck_local.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import TensorDataset, DataLoader

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.value_nn_alphazero import ValueNNAlphaZero  # noqa: E402

STATE_DIM = 172


def train_one_deck(snaps: list, epochs: int = 50, batch: int = 128, lr: float = 1e-3,
                   device: str = "cpu", dropout: float = 0.15,
                   weight_decay: float = 0.0,
                   hidden_dim: int = 256) -> tuple[ValueNNAlphaZero, dict]:
    """1 deck の snaps で value NN を 学習。"""
    X = np.zeros((len(snaps), STATE_DIM), dtype=np.float32)
    Y = np.zeros((len(snaps),), dtype=np.float32)
    for i, s in enumerate(snaps):
        se = s["state_encoded"]
        if len(se) >= STATE_DIM:
            X[i, :] = se[:STATE_DIM]
        else:
            X[i, :len(se)] = se
        Y[i] = float(s["p_win"])
    Xt = torch.from_numpy(X).to(device)
    Yt = torch.from_numpy(Y).to(device)

    model = ValueNNAlphaZero(hidden_dim=hidden_dim, dropout=dropout).to(device)
    model.train()
    optimizer = optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=1e-5)
    criterion = nn.MSELoss()

    train_ds = TensorDataset(Xt, Yt)
    train_loader = DataLoader(train_ds, batch_size=batch, shuffle=True)

    final_loss = None
    for epoch in range(epochs):
        ep_loss = 0.0
        nb = 0
        for xb, yb in train_loader:
            optimizer.zero_grad()
            pred = model(xb)
            loss = criterion(pred, yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
            ep_loss += loss.item()
            nb += 1
        scheduler.step()
        final_loss = ep_loss / nb if nb else None

    return model, {"final_loss": final_loss, "mean_p_win": float(np.mean(Y))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snap-dir", default="db/mcts_rollout_by_deck")
    ap.add_argument("--out-dir", default="db/value_nn_per_deck")
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--dropout", type=float, default=0.15)
    ap.add_argument("--weight-decay", type=float, default=0.0)
    ap.add_argument("--hidden-dim", type=int, default=256)
    ap.add_argument("--min-snaps", type=int, default=50)
    args = ap.parse_args()

    snap_dir = ROOT / args.snap_dir
    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    snap_files = sorted([p for p in snap_dir.glob("*.jsonl")])
    print(f"=== Plan D per-deck value NN 学習 (= ローカル CPU) ===", flush=True)
    print(f"  snap_dir: {snap_dir} ({len(snap_files)} files)", flush=True)
    print(f"  out_dir:  {out_dir}", flush=True)
    print(f"  epochs: {args.epochs}, batch: {args.batch}, lr: {args.lr}", flush=True)

    summary = {}
    t_global = time.time()

    for path in snap_files:
        slug = path.stem
        snaps = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                    if "state_encoded" in d and "p_win" in d:
                        snaps.append(d)
                except Exception:
                    pass

        if len(snaps) < args.min_snaps:
            print(f"  [SKIP] {slug}: {len(snaps)} snaps < {args.min_snaps}", flush=True)
            continue

        t_deck = time.time()
        model, stats = train_one_deck(
            snaps, epochs=args.epochs, batch=args.batch, lr=args.lr,
            dropout=args.dropout, weight_decay=args.weight_decay,
        )
        out_path = out_dir / f"{slug}.pt"
        torch.save(model.state_dict(), out_path)
        elapsed = time.time() - t_deck
        summary[slug] = {
            "snaps": len(snaps),
            "elapsed_s": elapsed,
            **stats,
        }
        print(
            f"  {slug:30s}: {len(snaps):5d} snaps, mean_p_win={stats['mean_p_win']:.3f}, "
            f"final_loss={stats['final_loss']:.4f}, {elapsed:.1f}s → {out_path.name}",
            flush=True,
        )

    print(f"\n=== TOTAL {time.time()-t_global:.0f}s ===", flush=True)
    summary_path = out_dir / "_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"summary: {summary_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
