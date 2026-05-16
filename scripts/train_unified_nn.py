#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step 4: Unified NN 学習 (= 採用案 C、 oracle + partial を 1 NN に統合、 2026-05-16)。

既存 `scripts/train_nn_eval.py` のリネーム + 拡張版。 distill 不要 (= mask 機構で同 NN
を oracle/partial 両モード対応)。

# 学習データ
- db/self_play_snapshots.jsonl (= Step 2 出力、 各 snapshot に features 78 dim + action_category + final_winner)
- db/ai_params_decks/*.snapshots.jsonl (= 既存 fine-tune snapshot、 互換性 source)

# 学習方式 (= 採用案 C)
- 各 mini-batch で 50% oracle / 50% partial の random masking
- partial mask = OPP_HAND_MASK_KEYS の dim を 0 化
- mode_flag (1 dim) を input に concat → NN が自動分岐を学習
- 最終 fine_tune_epochs では partial 100% で fine-tune (= 推論時精度確保)

# 出力
- db/unified_nn.pt (= state_dict)
- db/_unified_feature_keys.json (= feature keys + mask 対象 dim index)

Usage:
  .venv/bin/python scripts/train_unified_nn.py
  .venv/bin/python scripts/train_unified_nn.py --epochs 60 --fine-tune-epochs 15
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Optional

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.state_encoder import OPP_HAND_MASK_KEYS

DEFAULT_OUTPUT = ROOT / "db" / "unified_nn.pt"
DEFAULT_KEYS_PATH = ROOT / "db" / "_unified_feature_keys.json"
N_ACTION_CATEGORIES = 10  # 関数 11 ACTION_CATEGORIES と一致


class UnifiedSnapshotDataset(Dataset):
    """各 snapshot を (features, winner, action_category_idx) に変換。

    mask_indices は mask 機構で 0 化される dim の index list。
    """

    def __init__(
        self,
        snapshots: list[dict],
        feature_keys: list[str],
        mask_indices: list[int],
    ):
        self.feature_keys = feature_keys
        self.mask_indices = mask_indices

        self.X: list[list[float]] = []
        self.y: list[float] = []
        self.action_idx: list[int] = []

        # action category 名 → idx
        from engine.opponent_action_model import ACTION_CATEGORIES
        cat_to_idx = {c: i for i, c in enumerate(ACTION_CATEGORIES)}

        for snap in snapshots:
            feats = snap.get("features", {})
            row = [float(feats.get(k, 0.0)) for k in feature_keys]
            self.X.append(row)
            w = snap.get("final_winner", snap.get("winner", 0))
            self.y.append(float(w))
            cat_name = snap.get("action_category", "Other")
            self.action_idx.append(cat_to_idx.get(cat_name, len(ACTION_CATEGORIES) - 1))

        self.X_t = torch.tensor(self.X, dtype=torch.float32)
        self.y_t = torch.tensor(self.y, dtype=torch.float32).unsqueeze(1)
        self.a_t = torch.tensor(self.action_idx, dtype=torch.long)

    def __len__(self) -> int:
        return len(self.X)

    def __getitem__(self, idx: int):
        return self.X_t[idx], self.y_t[idx], self.a_t[idx]


def apply_partial_mask(
    x: torch.Tensor,
    mask_indices: list[int],
    partial_ratio: float,
    rng: Optional[torch.Generator] = None,
) -> tuple[torch.Tensor, torch.Tensor]:
    """batch x の各 sample に対し partial_ratio 確率で mask 適用 + mode_flag concat。

    Args:
        x: (batch, dim) tensor
        mask_indices: 0 化対象 dim の index list (= OPP_HAND_MASK_KEYS)
        partial_ratio: partial mode で学習する batch 比率 (= 0.5 で 50/50、 1.0 で 100% partial)
        rng: 乱数 (= None なら torch default)

    Returns:
        (x_with_flag, mode_mask) — x_with_flag は (batch, dim+1)、 末尾に mode_flag (0=oracle, 1=partial)。
        mode_mask は (batch,) bool で partial の sample index。
    """
    batch_size = x.size(0)
    if rng is None:
        partial_mask = torch.rand(batch_size) < partial_ratio
    else:
        partial_mask = torch.rand(batch_size, generator=rng) < partial_ratio
    # partial sample で mask_indices を 0 化
    x_modified = x.clone()
    if mask_indices:
        idx_tensor = torch.tensor(mask_indices, dtype=torch.long)
        x_modified[partial_mask][:, idx_tensor] = 0.0  # noqa: 部分代入は in-place
        # better: 明示的 batch loop で確実に
        for i, is_partial in enumerate(partial_mask):
            if is_partial.item():
                x_modified[i, idx_tensor] = 0.0
    # mode_flag concat
    mode_flag = partial_mask.float().unsqueeze(1)
    x_with_flag = torch.cat([x_modified, mode_flag], dim=1)
    return x_with_flag, partial_mask


class UnifiedNN(nn.Module):
    """Unified NN (= 採用案 C、 oracle/partial 共通)。

    入力: 78 dim features + 1 dim mode_flag = 79 dim
    出力: value (1 dim, tanh) + policy (10 dim, softmax 前 logits)
    """

    def __init__(self, input_dim: int = 79, hidden_dim: int = 128):
        super().__init__()
        self.shared = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(hidden_dim // 2, hidden_dim // 4),
            nn.ReLU(),
        )
        self.value_head = nn.Linear(hidden_dim // 4, 1)
        self.policy_head = nn.Linear(hidden_dim // 4, N_ACTION_CATEGORIES)

    def forward(self, x):
        h = self.shared(x)
        return torch.tanh(self.value_head(h)), self.policy_head(h)


def load_snapshots(input_paths: list[Path]) -> tuple[list[dict], list[str]]:
    """jsonl 群を ロード → snapshots + feature_keys。"""
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
        print(f"  loaded {path.name}: total {len(all_snaps)} snapshots so far")
    return all_snaps, feature_keys


def train(args) -> None:
    print("=== Loading snapshots ===")
    input_paths = [Path(p) for p in args.input]
    snapshots, feature_keys = load_snapshots(input_paths)
    if not snapshots:
        print("[ERROR] no snapshots found")
        sys.exit(1)

    print(f"  N = {len(snapshots)} snapshots, D = {len(feature_keys)} features")
    pos = sum(1 for s in snapshots if s.get("final_winner", s.get("winner", 0)) > 0)
    neg = sum(1 for s in snapshots if s.get("final_winner", s.get("winner", 0)) < 0)
    print(f"  outcome dist: win={pos}, lose={neg}, draw={len(snapshots) - pos - neg}")

    # mask 対象 dim 特定
    mask_indices: list[int] = [
        i for i, k in enumerate(feature_keys) if k in OPP_HAND_MASK_KEYS
    ]
    print(f"  mask_indices: {len(mask_indices)} dims (= {[feature_keys[i] for i in mask_indices]})")

    # shuffle + split (= 80/20)
    rng = random.Random(args.seed)
    rng.shuffle(snapshots)
    n = len(snapshots)
    split = int(n * 0.8)
    train_snaps = snapshots[:split]
    val_snaps = snapshots[split:]

    train_ds = UnifiedSnapshotDataset(train_snaps, feature_keys, mask_indices)
    val_ds = UnifiedSnapshotDataset(val_snaps, feature_keys, mask_indices)
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)
    print(f"  train = {len(train_ds)}, val = {len(val_ds)}")

    # NN
    input_dim = len(feature_keys) + 1  # +1 for mode_flag
    model = UnifiedNN(input_dim=input_dim, hidden_dim=args.hidden_dim)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"  model = UnifiedNN(input={input_dim}, hidden={args.hidden_dim}), params={n_params}")

    optimizer = optim.Adam(model.parameters(), lr=args.lr, weight_decay=1e-5)
    value_criterion = nn.MSELoss()
    policy_criterion = nn.CrossEntropyLoss()

    print(f"\n=== Training: {args.epochs} mixed epochs + {args.fine_tune_epochs} partial-only epochs ===")
    best_val_acc = 0.0
    for epoch in range(args.epochs + args.fine_tune_epochs):
        is_fine_tune = epoch >= args.epochs
        # mixed epoch は 50% partial、 fine_tune epoch は 100% partial
        partial_ratio = 1.0 if is_fine_tune else args.partial_ratio
        phase_label = "fine-tune (partial 100%)" if is_fine_tune else f"mixed (partial {partial_ratio:.0%})"

        model.train()
        train_loss = 0.0
        n_batches = 0
        for X, y, a in train_loader:
            optimizer.zero_grad()
            X_with_flag, _ = apply_partial_mask(X, mask_indices, partial_ratio)
            value_pred, policy_pred = model(X_with_flag)
            loss_v = value_criterion(value_pred, y)
            loss_p = policy_criterion(policy_pred, a)
            loss = loss_v + 0.5 * loss_p
            loss.backward()
            optimizer.step()
            train_loss += loss.item()
            n_batches += 1

        # val sign acc on partial mode (= 推論時想定)
        model.eval()
        with torch.no_grad():
            val_x = val_ds.X_t
            val_y = val_ds.y_t
            val_x_with_flag, _ = apply_partial_mask(val_x, mask_indices, partial_ratio=1.0)
            val_v_pred, _ = model(val_x_with_flag)
            sign_acc_partial = float((torch.sign(val_v_pred) == torch.sign(val_y)).float().mean().item())
            # oracle mode の val acc も併記 (= 学習量検証)
            val_x_oracle, _ = apply_partial_mask(val_x, mask_indices, partial_ratio=0.0)
            val_v_oracle, _ = model(val_x_oracle)
            sign_acc_oracle = float((torch.sign(val_v_oracle) == torch.sign(val_y)).float().mean().item())

        avg_train_loss = train_loss / max(1, n_batches)
        print(
            f"  epoch {epoch+1}/{args.epochs + args.fine_tune_epochs} [{phase_label}]: "
            f"train_loss={avg_train_loss:.4f}, "
            f"val_acc(partial)={sign_acc_partial:.3f}, val_acc(oracle)={sign_acc_oracle:.3f}"
        )

        # best snapshot 保存 (= partial mode の精度を最優先)
        if sign_acc_partial > best_val_acc:
            best_val_acc = sign_acc_partial
            args.output.parent.mkdir(parents=True, exist_ok=True)
            torch.save(model.state_dict(), args.output)
            DEFAULT_KEYS_PATH.write_text(
                json.dumps({
                    "feature_keys": feature_keys,
                    "mask_indices": mask_indices,
                    "input_dim": input_dim,
                    "hidden_dim": args.hidden_dim,
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"    ✔ saved {args.output.name} (best val_acc partial={sign_acc_partial:.3f})")

    print(f"\n=== DONE. best val_acc (partial) = {best_val_acc:.3f} ===")


def main() -> None:
    # description は短く (= docstring の % が argparse format 処理と衝突するため)
    ap = argparse.ArgumentParser(
        description="Step 4: Unified NN training (= mask + mode_flag, oracle/partial unified)."
    )
    ap.add_argument(
        "--input",
        nargs="+",
        default=[str(ROOT / "db" / "self_play_snapshots.jsonl")],
        help="入力 jsonl path 群 (= 複数指定可)",
    )
    ap.add_argument("--epochs", type=int, default=60, help="mixed 学習 epoch 数")
    ap.add_argument("--fine-tune-epochs", type=int, default=15, help="partial-only fine-tune epoch 数")
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--hidden-dim", type=int, default=128)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--partial-ratio", type=float, default=0.5, help="mixed epoch の partial 比率 0-1")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args()
    train(args)


if __name__ == "__main__":
    main()
