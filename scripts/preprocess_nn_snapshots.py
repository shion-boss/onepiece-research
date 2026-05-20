#!/usr/bin/env python3
"""Phase H-3 Step 2: NN 学習 data preprocessing。

cross matchup snapshot jsonl (= collect_cross_snapshots_for_nn.py の 出力) を
state-value pair (.npz) に 変換。

各 snapshot の state_encoded を input X、 game_winner を target Y で.
GD = player 0 視点 で reward 計算 (= P0 勝=+1、 P1 勝=-1、 draw=0)。

# 使い方

```bash
.venv/bin/python scripts/preprocess_nn_snapshots.py \\
  --snapshot-dir /tmp/nn_snapshots_phase_h3 \\
  --output db/nn_h3_train.npz
```
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np


def load_snapshots(snapshot_dir: Path) -> tuple[np.ndarray, np.ndarray, dict]:
    """全 jsonl file を 読み込み、 X (= state_encoded)、 y (= reward) を numpy array で返す。

    各 snapshot で actor_idx 視点 の state_encoded + reward (= actor_idx 勝なら +1、 負なら -1) を 取る。
    """
    paths = sorted(snapshot_dir.glob("*.jsonl"))
    print(f"found {len(paths)} jsonl files", flush=True)

    X_list = []
    y_list = []
    meta = {"n_files": len(paths), "n_snapshots": 0, "n_skipped": 0, "deck_a_counts": {}, "winner_dist": {0: 0, 1: 0, -1: 0}}

    for path in paths:
        with open(path) as f:
            for line in f:
                try:
                    s = json.loads(line)
                except Exception:
                    meta["n_skipped"] += 1
                    continue
                # 必須 field 確認
                if "state_encoded_p0" not in s or "game_winner" not in s:
                    meta["n_skipped"] += 1
                    continue
                # actor_idx 視点 で 学習 (= actor_idx の encoded + actor_idx 視点 reward)
                actor_idx = s.get("actor_idx", 0)
                state_enc = s["state_encoded_p0"] if actor_idx == 0 else s["state_encoded_p1"]
                winner = s["game_winner"]
                if winner == -1:
                    reward = 0.0
                elif winner == actor_idx:
                    reward = 1.0
                else:
                    reward = -1.0
                X_list.append(state_enc)
                y_list.append(reward)
                meta["n_snapshots"] += 1
                # deck_a count
                deck_a = s.get("deck_a", "unknown")
                meta["deck_a_counts"][deck_a] = meta["deck_a_counts"].get(deck_a, 0) + 1
                meta["winner_dist"][winner] = meta["winner_dist"].get(winner, 0) + 1

    X = np.array(X_list, dtype=np.float32)
    y = np.array(y_list, dtype=np.float32)
    return X, y, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot-dir", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--val-ratio", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    snapshot_dir = Path(args.snapshot_dir)
    X, y, meta = load_snapshots(snapshot_dir)

    print(f"\n=== 集計 ===")
    print(f"  total snapshots: {meta['n_snapshots']}")
    print(f"  skipped: {meta['n_skipped']}")
    print(f"  X shape: {X.shape}, dtype={X.dtype}")
    print(f"  y shape: {y.shape}, dtype={y.dtype}, mean={y.mean():.3f}, std={y.std():.3f}")
    print(f"  winner dist: {meta['winner_dist']}")
    print(f"  deck_a counts: {dict(list(meta['deck_a_counts'].items())[:5])}... ({len(meta['deck_a_counts'])} decks total)")

    # train/val split
    rng = np.random.RandomState(args.seed)
    n = X.shape[0]
    indices = rng.permutation(n)
    n_val = int(n * args.val_ratio)
    val_idx = indices[:n_val]
    train_idx = indices[n_val:]

    X_train, y_train = X[train_idx], y[train_idx]
    X_val, y_val = X[val_idx], y[val_idx]

    print(f"\n=== train/val split ===")
    print(f"  train: {X_train.shape[0]} samples")
    print(f"  val: {X_val.shape[0]} samples")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output, X_train=X_train, y_train=y_train, X_val=X_val, y_val=y_val, meta=json.dumps(meta))
    print(f"\nsaved to {output} (size: {output.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
