#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Plan Step 3: NN evaluator 学習 (= PyTorch MLP、 CPU)。

既存 fine-tune snapshot (= db/ai_params_decks/*.snapshots.jsonl) を input。
features dict (= 78 dim) → NN value head + policy head。

学習:
- value loss = MSE (= snapshot.final_winner ±1 を target)
- policy loss = CrossEntropy (= 各 turn の actor 動作 を target、 簡易)
- dual loss = value_loss + 0.5 * policy_loss

出力: db/nn_eval.pt (= state_dict)、 ONEPIECE_NN_MODEL_PATH 経由で eval.py が auto-load。

Usage:
  .venv/bin/python scripts/train_nn_eval.py
  .venv/bin/python scripts/train_nn_eval.py --epochs 20 --batch-size 64
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.nn_eval import NNEvaluator, ACTION_CATEGORY_TO_IDX, N_ACTION_CATEGORIES
from engine.state_encoder import encoded_dim


# Plan Step 3 簡略: 既存 snapshot は 78 dim features dict のみ保有 (= state encode は無)。
# 暫定: features dict 78 dim を直接 input として 78→64→32→1 (= 軽量 NN) で学習。
# 本格 (= 172 dim) は 新 snapshot collect 後 切替。
SNAPSHOT_FEATURE_KEYS_PATH = ROOT / "db" / "_nn_feature_keys.json"


class SnapshotDataset(Dataset):
    """各 jsonl 行 = 1 snapshot、 features (78 dim diff) + winner (±1) を tensor 化。"""

    def __init__(self, snapshots: list[dict], feature_keys: list[str]):
        self.feature_keys = feature_keys
        self.X: list[list[float]] = []
        self.y: list[float] = []
        self.action_idx: list[int] = []
        for snap in snapshots:
            feats = snap.get("features", {})
            row = [float(feats.get(k, 0.0)) for k in feature_keys]
            self.X.append(row)
            # winner (= snap.winner or final_winner) を ±1 / 0 に正規化
            w = snap.get("winner", snap.get("final_winner", 0))
            self.y.append(float(w))
            # action category (= 後で snapshot に actor の action が記録されてる場合)
            # 既存 snapshot は actor_idx のみ、 action category なし → all 0 で fallback
            self.action_idx.append(0)
        self.X_t = torch.tensor(self.X, dtype=torch.float32)
        self.y_t = torch.tensor(self.y, dtype=torch.float32).unsqueeze(1)
        self.a_t = torch.tensor(self.action_idx, dtype=torch.long)

    def __len__(self) -> int:
        return len(self.X)

    def __getitem__(self, idx: int):
        return self.X_t[idx], self.y_t[idx], self.a_t[idx]


def load_all_snapshots() -> tuple[list[dict], list[str]]:
    """db/ai_params_decks/*.snapshots.jsonl を全 deck 読み込み。

    Returns: (snapshots, feature_keys)
    """
    decks_dir = ROOT / "db" / "ai_params_decks"
    all_snaps: list[dict] = []
    feature_keys: list[str] = []
    for f in sorted(decks_dir.glob("*.snapshots.jsonl")):
        with f.open("r", encoding="utf-8") as fp:
            for line in fp:
                try:
                    snap = json.loads(line)
                    all_snaps.append(snap)
                    if not feature_keys:
                        feature_keys = sorted(snap.get("features", {}).keys())
                except json.JSONDecodeError:
                    continue
    return all_snaps, feature_keys


class SimpleEvaluator(nn.Module):
    """既存 78 dim features を入力にする軽量 MLP (= state encode 整備までの暫定)。

    parameter 数 ≈ 78*64 + 64*32 + 32*1 + 32*9 ≈ 8K (= 超軽量)。
    """

    def __init__(self, input_dim: int, hidden_dim: int = 64):
        super().__init__()
        self.shared = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
        )
        self.value_head = nn.Linear(hidden_dim // 2, 1)
        self.policy_head = nn.Linear(hidden_dim // 2, N_ACTION_CATEGORIES)

    def forward(self, x):
        h = self.shared(x)
        return self.value_head(h), self.policy_head(h)


def train(args) -> None:
    print("=== loading snapshots ===")
    snapshots, feature_keys = load_all_snapshots()
    if not snapshots:
        print("[ERROR] no snapshots found in db/ai_params_decks/")
        sys.exit(1)
    print(f"  N = {len(snapshots)} snapshots, D = {len(feature_keys)} features")
    print(f"  outcome dist: win={sum(1 for s in snapshots if s.get('winner', s.get('final_winner', 0)) > 0)}, "
          f"lose={sum(1 for s in snapshots if s.get('winner', s.get('final_winner', 0)) < 0)}, "
          f"draw={sum(1 for s in snapshots if s.get('winner', s.get('final_winner', 0)) == 0)}")

    # train / val split (= 80/20)
    n = len(snapshots)
    split = int(n * 0.8)
    train_snaps = snapshots[:split]
    val_snaps = snapshots[split:]
    train_ds = SnapshotDataset(train_snaps, feature_keys)
    val_ds = SnapshotDataset(val_snaps, feature_keys)
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size)

    print(f"  train = {len(train_ds)}, val = {len(val_ds)}")

    # 簡易版: 78 dim 入力の SimpleEvaluator (= 状態 encode 整備までの暫定)
    model = SimpleEvaluator(input_dim=len(feature_keys))
    n_params = sum(p.numel() for p in model.parameters())
    print(f"  model = SimpleEvaluator(input={len(feature_keys)}, hidden=64), params={n_params}")

    optimizer = optim.Adam(model.parameters(), lr=args.lr)
    value_criterion = nn.MSELoss()
    policy_criterion = nn.CrossEntropyLoss()

    print(f"\n=== training (epochs={args.epochs}) ===")
    best_val_acc = 0.0
    for epoch in range(args.epochs):
        model.train()
        train_loss = 0.0
        n_batches = 0
        for X, y, a in train_loader:
            optimizer.zero_grad()
            value_pred, policy_pred = model(X)
            loss_v = value_criterion(value_pred, y)
            loss_p = policy_criterion(policy_pred, a)
            loss = loss_v + 0.5 * loss_p
            loss.backward()
            optimizer.step()
            train_loss += loss.item()
            n_batches += 1

        # val sign acc (= 既存 ridge と同じ metric)
        model.eval()
        with torch.no_grad():
            val_x, val_y, val_a = val_ds.X_t, val_ds.y_t, val_ds.a_t
            val_v_pred, val_p_pred = model(val_x)
            sign_acc = float((torch.sign(val_v_pred) == torch.sign(val_y)).float().mean().item())
        avg_train_loss = train_loss / max(1, n_batches)
        print(f"  epoch {epoch+1}/{args.epochs}: train_loss={avg_train_loss:.4f}, val_sign_acc={sign_acc:.3f}")
        if sign_acc > best_val_acc:
            best_val_acc = sign_acc
            # save model + feature keys
            args.output.parent.mkdir(parents=True, exist_ok=True)
            torch.save(model.state_dict(), args.output)
            SNAPSHOT_FEATURE_KEYS_PATH.write_text(json.dumps(feature_keys, ensure_ascii=False), encoding="utf-8")
            print(f"    ✔ saved {args.output} (best val_sign_acc={sign_acc:.3f})")

    print(f"\n=== DONE. best val_sign_acc={best_val_acc:.3f} ===")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--output", type=Path, default=ROOT / "db" / "nn_eval.pt")
    args = ap.parse_args()
    train(args)


if __name__ == "__main__":
    main()
