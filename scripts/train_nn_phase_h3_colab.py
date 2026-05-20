"""Phase H-3 NN 学習 - Colab T4 GPU 用 (= 2026-05-20)。

このファイルの内容を Colab notebook の cell に copy-paste して 実行 する。
既存 engine/value_nn_alphazero.py の ValueNNAlphaZero (= 256-256-128 sigmoid) と 互換構造。

# 事前準備 (Colab 環境)

1. .npz ファイル (= preprocess_nn_snapshots.py の 出力) を Colab 環境 に upload
   - Google Drive 経由 or 直接 upload
2. 以下 の セル を 順次 実行

# 期待結果

- 学習済 model = `value_nn_phase_h3.pt` (= ~600 KB)
- val_loss < 0.65 + val_sign_accuracy > 0.6 が target
"""

# ============================================================
# Cell 1: Setup + import
# ============================================================
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader, TensorDataset
import numpy as np
import json
from pathlib import Path

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"device: {device}")

# ============================================================
# Cell 2: data load (.npz upload した path を指定)
# ============================================================
NPZ_PATH = "nn_h3_train.npz"  # Colab に upload した file の path
data = np.load(NPZ_PATH, allow_pickle=True)
X_train = torch.tensor(data["X_train"], dtype=torch.float32)
y_train_raw = torch.tensor(data["y_train"], dtype=torch.float32)
X_val = torch.tensor(data["X_val"], dtype=torch.float32)
y_val_raw = torch.tensor(data["y_val"], dtype=torch.float32)

# 既存 ValueNNAlphaZero と互換: y は [-1, +1] → [0, 1] に 変換 (= sigmoid target)
# y=+1 (= 勝) → 1.0、 y=-1 (= 負) → 0.0、 y=0 (= draw) → 0.5
y_train = (y_train_raw + 1.0) / 2.0
y_val = (y_val_raw + 1.0) / 2.0

meta = json.loads(str(data["meta"]))

print(f"X_train: {X_train.shape} (= {X_train.shape[0]} snapshots)")
print(f"y_train (sigmoid space [0,1]): mean={y_train.mean():.3f} std={y_train.std():.3f}")
print(f"X_val: {X_val.shape}")
print(f"meta winner dist: {meta.get('winner_dist')}")
print(f"input dim: {X_train.shape[1]} (= 172 想定)")

# ============================================================
# Cell 3: model definition (= 既存 ValueNNAlphaZero 完全互換)
# ============================================================
class ValueNNAlphaZero(nn.Module):
    """既存 engine/value_nn_alphazero.py の class と 完全互換。

    architecture: 172 → 256 → 256 → 128 → 1, sigmoid
    parameter 数: ~150K
    """
    def __init__(self, input_dim=172, hidden_dim=256, dropout=0.15):
        super().__init__()
        self.body = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Dropout(dropout),
        )
        self.head = nn.Linear(hidden_dim // 2, 1)

    def forward(self, x):
        h = self.body(x)
        return torch.sigmoid(self.head(h)).squeeze(-1)


model = ValueNNAlphaZero(input_dim=X_train.shape[1]).to(device)
n_params = sum(p.numel() for p in model.parameters())
print(f"model: {n_params} parameters (= ~150K 想定)")

# ============================================================
# Cell 4: training setup
# ============================================================
BATCH_SIZE = 256
LR = 1e-3
EPOCHS = 100
PATIENCE = 10  # early stopping

train_ds = TensorDataset(X_train, y_train)
val_ds = TensorDataset(X_val, y_val)
train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True)
val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE)

optimizer = optim.Adam(model.parameters(), lr=LR, weight_decay=1e-5)
loss_fn = nn.BCELoss()  # binary cross entropy for sigmoid target
scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="min", factor=0.5, patience=5)

# ============================================================
# Cell 5: training loop
# ============================================================
best_val_loss = float("inf")
best_epoch = 0
patience_counter = 0

for epoch in range(EPOCHS):
    # train
    model.train()
    train_loss = 0.0
    for X_batch, y_batch in train_loader:
        X_batch, y_batch = X_batch.to(device), y_batch.to(device)
        optimizer.zero_grad()
        pred = model(X_batch)
        loss = loss_fn(pred, y_batch)
        loss.backward()
        optimizer.step()
        train_loss += loss.item() * X_batch.size(0)
    train_loss /= len(train_ds)

    # val
    model.eval()
    val_loss = 0.0
    sign_correct = 0
    n_val = 0
    with torch.no_grad():
        for X_batch, y_batch in val_loader:
            X_batch, y_batch = X_batch.to(device), y_batch.to(device)
            pred = model(X_batch)
            loss = loss_fn(pred, y_batch)
            val_loss += loss.item() * X_batch.size(0)
            # sign accuracy (= win prediction の 一致率)、 P(win) > 0.5 → predict win
            pred_class = (pred > 0.5).float()
            true_class = (y_batch > 0.5).float()
            # draw (y=0.5) は除外
            mask = y_batch != 0.5
            sign_correct += ((pred_class == true_class) & mask).sum().item()
            n_val += mask.sum().item()
    val_loss /= len(val_ds)
    sign_acc = sign_correct / max(1, n_val)

    scheduler.step(val_loss)
    print(f"  Epoch {epoch+1:3d}: train_loss={train_loss:.4f} val_loss={val_loss:.4f} val_sign_acc={sign_acc:.3f} lr={optimizer.param_groups[0]['lr']:.2e}")

    if val_loss < best_val_loss:
        best_val_loss = val_loss
        best_epoch = epoch
        torch.save(model.state_dict(), "value_nn_phase_h3_best.pt")
        patience_counter = 0
    else:
        patience_counter += 1
        if patience_counter >= PATIENCE:
            print(f"  Early stopping at epoch {epoch+1} (best epoch={best_epoch+1}, best val_loss={best_val_loss:.4f})")
            break

print(f"\n=== Training Done ===")
print(f"best epoch: {best_epoch+1}, best val_loss: {best_val_loss:.4f}")

# ============================================================
# Cell 6: save final model
# ============================================================
model.load_state_dict(torch.load("value_nn_phase_h3_best.pt"))
torch.save(model.state_dict(), "value_nn_phase_h3.pt")
print(f"saved: value_nn_phase_h3.pt ({Path('value_nn_phase_h3.pt').stat().st_size} bytes)")
print("\n=== ohtsuki さん: この .pt ファイルを ローカル に download し、 db/value_nn_phase_h3.pt として 保存 ===")
print("=== inference は engine.value_nn_alphazero と 完全互換、 ONEPIECE_AZ_VALUE_NN_PATH 環境変数 で 切替可能 ===")
