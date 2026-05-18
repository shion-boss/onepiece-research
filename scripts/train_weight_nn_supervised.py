# -*- coding: utf-8 -*-
"""Plan F Step 1 (= 2026-05-18): 重み NN の supervised warm start。

教師: engine.eval.compute_dynamic_weights_v2 (= 人間 hand-tuned 動的重み関数)
学習: snapshot から state_encoded を集めて、 各 state で教師 weights を計算 → NN を MSE で fit

これで「人間 hand-tuned 関数」 を NN が模倣できる状態にする (= warm start)。
次の Step 2 で self-play reinforcement で 真の最適 weights を発見させる。

実行例:
  .venv/bin/python scripts/train_weight_nn_supervised.py \\
    --snapshot db/self_play_snapshots_v2.jsonl \\
    --epochs 30 --batch-size 1024 \\
    --output db/weight_nn.pt
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

from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.eval import compute_dynamic_weights_v2  # noqa: E402
from engine.weight_nn import WEIGHT_KEYS, WeightNN  # noqa: E402


def _build_teacher_weights_from_snapshots(snapshot_path: Path, max_samples: int = 50000):
    """snapshot を読んで、 state_encoded と教師 weights のペアを返す。

    snapshot の各 entry は state_encoded を持つ (= v2 format)。
    教師 weights は engine.eval.compute_dynamic_weights_v2 で計算するが、
    state_encoded から GameState 復元は重い。 代わりに snapshot 内の 情報から
    特徴を直接抽出して 教師 weights を概算する。

    state_encoder.encode_state の正確な dim mapping (= 172 dim):
      [0-77]:    compute_breakdown features (= tanh 正規化、 ±1 range)
      [78-93]:   self_leader one-hot (= 16 dim)
      [94-109]:  opp_leader one-hot
      [110-113]: self_archetype one-hot
      [114-117]: opp_archetype one-hot
      [118-137]: self_board (= 5 chara × 4 dim)
      [138-157]: opp_board (= 5 chara × 4 dim)
      [158]:     my_life / 5
      [159]:     opp_life / 5
      [160]:     my_hand / 10
      [161]:     opp_hand / 10
      [162]:     my_total_don / 10
      [163]:     opp_total_don / 10
      [164]:     my_trash / 30
      [165]:     opp_trash / 30
      [166-170]: phase one-hot (= 5 dim)
      [171]:     turn / 15
    """
    print(f"loading {snapshot_path} (= max_samples={max_samples})", flush=True)
    X = []
    Y = []
    n = 0
    with open(snapshot_path, encoding="utf-8") as f:
        for line in f:
            if n >= max_samples:
                break
            try:
                snap = json.loads(line)
            except json.JSONDecodeError:
                continue
            se = snap.get("state_encoded")
            if not se or len(se) < 172:
                continue
            # state_encoder の正確な dim mapping から features 抽出 (= resource 部 158-165, turn 171)
            my_life_n = max(0, int(round(se[158] * 5)))
            opp_life_n = max(0, int(round(se[159] * 5)))
            my_hand_n = max(0, int(round(se[160] * 10)))
            opp_hand_n = max(0, int(round(se[161] * 10)))
            turn = max(1, int(round(se[171] * 15)))
            # opp_field_power は board encode [138-157] の power_norm × 10000 sum
            # 各 chara block 4 dim、 1 番目 dim が power_norm
            opp_field_power = max(
                0,
                sum(float(se[138 + i * 4]) * 10000 for i in range(5)),
            )

            # 教師 weights を概算で計算 (= compute_dynamic_weights_v2 の式を inline で)
            from engine.eval import select_weights_for_player
            from engine.core import Player, InPlay

            # 暫定 base (= 単純に DEFAULT_WEIGHTS 相当)
            from engine.eval import DEFAULT_WEIGHTS
            base = DEFAULT_WEIGHTS

            turn_factor = 1.0 + max(0, turn - 5) * 0.15
            if my_life_n >= 4:
                w_life_self_mult = 0.5 * turn_factor
            elif my_life_n >= 2:
                w_life_self_mult = 1.0 * turn_factor
            else:
                w_life_self_mult = 2.5 * turn_factor
            if opp_life_n >= 4:
                w_life_opp_mult = 0.7 * turn_factor
            elif opp_life_n >= 2:
                w_life_opp_mult = 1.2 * turn_factor
            else:
                w_life_opp_mult = 2.5 * turn_factor
            w_life = base.W_LIFE * (w_life_self_mult + w_life_opp_mult) / 2

            if my_hand_n <= 2:
                w_hand_self_mult = 2.5
            elif my_hand_n <= 5:
                w_hand_self_mult = 1.0
            else:
                w_hand_self_mult = 0.4
            if opp_hand_n <= 2:
                w_hand_opp_mult = 1.5
            elif opp_hand_n <= 5:
                w_hand_opp_mult = 1.0
            else:
                w_hand_opp_mult = 0.6
            w_hand = base.W_HAND * (w_hand_self_mult + w_hand_opp_mult) / 2

            w_don = base.W_DON * 0.4

            opp_field_strength = 1.0
            if opp_field_power >= 15000:
                opp_field_strength = 1.5
            elif opp_field_power >= 8000:
                opp_field_strength = 1.2
            w_blocker = base.W_BLOCKER * opp_field_strength

            teacher = [
                float(w_life),                       # W_LIFE
                float(w_hand),                       # W_HAND
                float(base.W_FIELD_COUNT),           # W_FIELD_COUNT
                float(base.W_FIELD_POWER),           # W_FIELD_POWER
                float(w_don),                        # W_DON
                float(w_blocker),                    # W_BLOCKER
                float(base.W_ATTACHED_DON),          # W_ATTACHED_DON
                float(base.W_ACTIVE_CHARA),          # W_ACTIVE_CHARA
                float(base.W_LETHAL),                # W_LETHAL
            ]

            X.append(se)
            Y.append(teacher)
            n += 1

    print(f"loaded {n} samples", flush=True)
    return np.array(X, dtype=np.float32), np.array(Y, dtype=np.float32)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default="db/self_play_snapshots_v2.jsonl")
    ap.add_argument("--max-samples", type=int, default=50000)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch-size", type=int, default=1024)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--output", default="db/weight_nn.pt")
    args = ap.parse_args()

    X_np, Y_np = _build_teacher_weights_from_snapshots(Path(args.snapshot), args.max_samples)
    print(f"X shape: {X_np.shape}, Y shape: {Y_np.shape}", flush=True)
    print(f"Y stats: mean={Y_np.mean(0)}, std={Y_np.std(0)}", flush=True)

    X = torch.from_numpy(X_np)
    Y = torch.from_numpy(Y_np)

    n = len(X)
    split = int(n * 0.85)
    X_train, X_val = X[:split], X[split:]
    Y_train, Y_val = Y[:split], Y[split:]
    print(f"train: {len(X_train)}, val: {len(X_val)}", flush=True)

    model = WeightNN(input_dim=X.shape[1])
    optimizer = optim.Adam(model.parameters(), lr=args.lr)
    criterion = nn.MSELoss()

    train_ds = TensorDataset(X_train, Y_train)
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)

    best_val_loss = float("inf")
    for epoch in range(args.epochs):
        model.train()
        train_loss = 0.0
        n_batches = 0
        t0 = time.time()
        for xb, yb in train_loader:
            optimizer.zero_grad()
            pred = model(xb)
            # Y は physical scale なので、 NN 出力も physical scale で比較
            loss = criterion(pred, yb)
            loss.backward()
            optimizer.step()
            train_loss += loss.item()
            n_batches += 1
        avg_train_loss = train_loss / n_batches

        model.eval()
        with torch.no_grad():
            val_pred = model(X_val)
            val_loss = criterion(val_pred, Y_val).item()

        elapsed = time.time() - t0
        print(
            f"  epoch {epoch+1}/{args.epochs}: "
            f"train_loss={avg_train_loss:.0f}, val_loss={val_loss:.0f}, {elapsed:.1f}s",
            flush=True,
        )

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            torch.save(model.state_dict(), args.output)
            print(f"    ✔ saved {args.output} (best val_loss={val_loss:.0f})", flush=True)

    print(f"\n=== DONE. best val_loss = {best_val_loss:.0f} ===", flush=True)
    print(f"output: {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
