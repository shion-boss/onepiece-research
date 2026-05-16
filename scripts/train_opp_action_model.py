#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step 5: Opp action model 学習 (= 関数 11 NN backend、 2026-05-16)。

inverse reasoning (= B.5b) の likelihood source として `P(action | hand, state)` を学習。
完全情報 self-play log から (state, opp_hand, opp_action) ペアを抽出。

# 学習データ
- db/self_play_snapshots.jsonl (= Step 2 出力、 各 snapshot に features + action_category)
- ※ opp_hand は現状の snapshot に明示記録されてない (= Step 2 では skip)。
  暫定: action_category を target に、 state features (= 公開部分) のみから学習する
  「分布近似」 として運用。 真の P(action | hand, state) は将来 snapshot に hand 含めた後で。

# Architecture
- Input: state features (= 78 dim) + opp side board encoding (= TBD)
- Output: action category probability (= 10 dim softmax)
- 軽量 MLP: 78 → 64 → 32 → 10

# 出力
- db/opp_action_model.pt (= state_dict)
- db/_opp_action_feature_keys.json (= feature keys)

Usage:
  .venv/bin/python scripts/train_opp_action_model.py
  .venv/bin/python scripts/train_opp_action_model.py --epochs 30 --batch-size 256
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.opponent_action_model import ACTION_CATEGORIES

DEFAULT_OUTPUT = ROOT / "db" / "opp_action_model.pt"
DEFAULT_KEYS_PATH = ROOT / "db" / "_opp_action_feature_keys.json"
N_ACTION_CATEGORIES = len(ACTION_CATEGORIES)


class OppActionDataset(Dataset):
    """各 snapshot を (state_features, action_category) に変換。"""

    def __init__(self, snapshots: list[dict], feature_keys: list[str]):
        self.feature_keys = feature_keys
        self.X: list[list[float]] = []
        self.y: list[int] = []
        cat_to_idx = {c: i for i, c in enumerate(ACTION_CATEGORIES)}
        for snap in snapshots:
            feats = snap.get("features", {})
            row = [float(feats.get(k, 0.0)) for k in feature_keys]
            cat_name = snap.get("action_category", "Other")
            if cat_name is None:
                continue
            self.X.append(row)
            self.y.append(cat_to_idx.get(cat_name, N_ACTION_CATEGORIES - 1))
        self.X_t = torch.tensor(self.X, dtype=torch.float32)
        self.y_t = torch.tensor(self.y, dtype=torch.long)

    def __len__(self) -> int:
        return len(self.X)

    def __getitem__(self, idx: int):
        return self.X_t[idx], self.y_t[idx]


class OppActionModel(nn.Module):
    """軽量 MLP: state features → action category 分布。"""

    def __init__(self, input_dim: int = 78, hidden_dim: int = 64):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Linear(hidden_dim // 2, N_ACTION_CATEGORIES),
        )

    def forward(self, x):
        return self.net(x)

    def predict_policy(self, x) -> list[float]:
        """1 sample 推論 (= engine/opponent_action_model.action_likelihood NN path 用)。"""
        if not isinstance(x, torch.Tensor):
            x = torch.tensor(x, dtype=torch.float32)
        if x.dim() == 1:
            x = x.unsqueeze(0)
        with torch.no_grad():
            logits = self.net(x)
            probs = torch.softmax(logits, dim=-1)
            return probs.squeeze(0).tolist()


def load_snapshots(input_paths: list[Path]) -> tuple[list[dict], list[str]]:
    all_snaps: list[dict] = []
    feature_keys: list[str] = []
    for path in input_paths:
        if not path.exists():
            print(f"  [skip] {path} not found")
            continue
        with path.open("r", encoding="utf-8") as fp:
            for line in fp:
                try:
                    snap = json.loads(line)
                    all_snaps.append(snap)
                    if not feature_keys:
                        keys = list(snap.get("features", {}).keys())
                        if keys:
                            feature_keys = sorted(keys)
                except json.JSONDecodeError:
                    continue
        print(f"  loaded {path.name}: total {len(all_snaps)} so far")
    return all_snaps, feature_keys


def train(args) -> None:
    print("=== Loading snapshots ===")
    input_paths = [Path(p) for p in args.input]
    snapshots, feature_keys = load_snapshots(input_paths)
    if not snapshots:
        print("[ERROR] no snapshots found")
        sys.exit(1)

    # action_category がない snapshot を除外
    snapshots = [s for s in snapshots if s.get("action_category")]
    print(f"  N = {len(snapshots)} valid snapshots (with action_category)")

    # category 分布表示
    from collections import Counter
    cat_dist = Counter(s.get("action_category") for s in snapshots)
    print(f"  Action category distribution:")
    for cat in ACTION_CATEGORIES:
        cnt = cat_dist.get(cat, 0)
        pct = cnt / max(len(snapshots), 1) * 100
        print(f"    {cat:20s}: {cnt:6d} ({pct:.1f} pct)")

    rng = random.Random(args.seed)
    rng.shuffle(snapshots)
    n = len(snapshots)
    split = int(n * 0.8)
    train_ds = OppActionDataset(snapshots[:split], feature_keys)
    val_ds = OppActionDataset(snapshots[split:], feature_keys)
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)
    print(f"  train = {len(train_ds)}, val = {len(val_ds)}")

    model = OppActionModel(input_dim=len(feature_keys), hidden_dim=args.hidden_dim)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"  model = OppActionModel(input={len(feature_keys)}, hidden={args.hidden_dim}), params={n_params}")

    optimizer = optim.Adam(model.parameters(), lr=args.lr, weight_decay=1e-5)
    criterion = nn.CrossEntropyLoss()

    print(f"\n=== Training (epochs={args.epochs}) ===")
    best_top3 = 0.0
    for epoch in range(args.epochs):
        model.train()
        train_loss = 0.0
        n_batches = 0
        for X, y in train_loader:
            optimizer.zero_grad()
            logits = model(X)
            loss = criterion(logits, y)
            loss.backward()
            optimizer.step()
            train_loss += loss.item()
            n_batches += 1

        # val: top-1 / top-3 accuracy
        model.eval()
        with torch.no_grad():
            val_logits = model(val_ds.X_t)
            pred_top3 = torch.topk(val_logits, k=min(3, N_ACTION_CATEGORIES), dim=-1).indices
            correct_top1 = (pred_top3[:, 0] == val_ds.y_t).float().mean().item()
            in_top3 = (pred_top3 == val_ds.y_t.unsqueeze(1)).any(dim=1).float().mean().item()
        avg_train_loss = train_loss / max(1, n_batches)
        print(
            f"  epoch {epoch+1}/{args.epochs}: train_loss={avg_train_loss:.4f}, "
            f"val_top1={correct_top1:.3f}, val_top3={in_top3:.3f}"
        )

        if in_top3 > best_top3:
            best_top3 = in_top3
            args.output.parent.mkdir(parents=True, exist_ok=True)
            torch.save(model.state_dict(), args.output)
            DEFAULT_KEYS_PATH.write_text(
                json.dumps({
                    "feature_keys": feature_keys,
                    "input_dim": len(feature_keys),
                    "hidden_dim": args.hidden_dim,
                    "action_categories": ACTION_CATEGORIES,
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"    ✔ saved {args.output.name} (best val_top3={in_top3:.3f})")

    print(f"\n=== DONE. best val_top3 = {best_top3:.3f} ===")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Step 5: Opp action model training (= P(action | state) for inverse reasoning)."
    )
    ap.add_argument(
        "--input",
        nargs="+",
        default=[str(ROOT / "db" / "self_play_snapshots.jsonl")],
    )
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--hidden-dim", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args()
    train(args)


if __name__ == "__main__":
    main()
