# -*- coding: utf-8 -*-
"""Plan F (= 2026-05-18): 重み NN — state を見て 9 dim weights を動的計算。

input:  state_encoded (= 172 dim、 既存 state_encoder.encode_state)
output: 9 dim weights [W_LIFE, W_HAND, W_FIELD_COUNT, W_FIELD_POWER,
                       W_DON, W_BLOCKER, W_ATTACHED_DON, W_ACTIVE_CHARA, W_LETHAL]

学習方式 (= 段階的):
  Step 1 (= 案 a): supervised warm start — dynamic_weights v2 を教師に NN を fit
  Step 2 (= 案 b): self-play reinforcement — NN weights で対戦 → 勝率最大化

設計: docs は memory/project_plan_f_weight_nn.md。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import torch
import torch.nn as nn


# 出力する weights の名前 (= 順序固定)
WEIGHT_KEYS = [
    "W_LIFE", "W_HAND", "W_FIELD_COUNT", "W_FIELD_POWER",
    "W_DON", "W_BLOCKER", "W_ATTACHED_DON", "W_ACTIVE_CHARA",
    "W_LETHAL",
]
N_WEIGHTS = len(WEIGHT_KEYS)

# weights の base scale (= softplus 出力をこのスケールに乗せる)
# 既存 DEFAULT_WEIGHTS とほぼ同オーダーになるよう設定
# (= NN は 0-3 range を出して、 × base_scale で 0-3x の倍率を表現)
BASE_SCALES = {
    "W_LIFE":         3000,
    "W_HAND":          800,
    "W_FIELD_COUNT":  1500,
    "W_FIELD_POWER":     1,  # power 自体が thousands
    "W_DON":           500,
    "W_BLOCKER":      1200,
    "W_ATTACHED_DON": 1000,
    "W_ACTIVE_CHARA":  600,
    "W_LETHAL":     30000,
}


class WeightNN(nn.Module):
    """state → 9 dim positive weights mapping。

    softplus で positive 保証、 BASE_SCALES で各 weight の物理 scale に合わせる。
    output weights[k] = softplus(linear(...)) × BASE_SCALES[k]

    hidden_dim 引数で大型化対応 (= 2026-05-18):
      256 (= default、 ~80K params): 朝の supervised 学習用
      512 (= big、 ~300K params): Phase 2 RL で 大量データ + 大型 model
    """

    def __init__(self, input_dim: int = 172, hidden_dim: int = 256, dropout: float = 0.1):
        super().__init__()
        self.shared = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim // 2, hidden_dim // 4),
            nn.ReLU(),
        )
        # 9 dim positive output via softplus
        self.weight_head = nn.Linear(hidden_dim // 4, N_WEIGHTS)
        # softplus は positive 保証、 ただし学習開始時は ~ log(2) ≈ 0.69 で BASE_SCALES の ~70% スタート
        self.softplus = nn.Softplus()

        # base scale tensor (= 各 weight の物理スケール調整)
        self.register_buffer(
            "base_scales",
            torch.tensor([BASE_SCALES[k] for k in WEIGHT_KEYS], dtype=torch.float32),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """state → 9 dim weights (= positive、 base scale 適用後)。"""
        h = self.shared(x)
        raw = self.weight_head(h)  # (B, 9) any real
        positive = self.softplus(raw)  # (B, 9) positive
        weights = positive * self.base_scales  # (B, 9) physical scale
        return weights

    def predict_weights(self, state_encoded: list[float]) -> dict[str, float]:
        """1 sample 推論 → dict 形式の weights を返す (= eval.py から呼ぶ用)。"""
        with torch.no_grad():
            x = torch.tensor(state_encoded, dtype=torch.float32).unsqueeze(0)
            w = self.forward(x).squeeze(0).tolist()
            return {k: w[i] for i, k in enumerate(WEIGHT_KEYS)}


class WeightNNBig(WeightNN):
    """大型版: hidden=512 (= ~300K params)。 forward / predict_weights は親クラスから継承。"""

    def __init__(self, input_dim: int = 172, dropout: float = 0.1):
        super().__init__(input_dim=input_dim, hidden_dim=512, dropout=dropout)


# global model cache (= 1 度 load して使い回す)
_MODEL_CACHE: Optional[WeightNN] = None
_MODEL_PATH: Optional[Path] = None


def _default_model_path() -> Path:
    return Path(__file__).resolve().parent.parent / "db" / "weight_nn.pt"


def get_weight_model() -> Optional[WeightNN]:
    """db/weight_nn.pt から model を load (= 1 度のみ、 cache)。 不在 / disable で None。"""
    global _MODEL_CACHE, _MODEL_PATH
    if os.environ.get("ONEPIECE_WEIGHT_NN_DISABLE"):
        return None
    if _MODEL_CACHE is not None:
        return _MODEL_CACHE
    env_path = os.environ.get("ONEPIECE_WEIGHT_NN_PATH")
    path = Path(env_path) if env_path else _default_model_path()
    if not path.exists():
        return None
    try:
        state_dict = torch.load(path, map_location="cpu", weights_only=True)
        model = WeightNN()
        model.load_state_dict(state_dict)
        model.eval()
        _MODEL_CACHE = model
        _MODEL_PATH = path
        return model
    except Exception as e:
        print(f"[weight_nn] load failed: {e}")
        return None


def reload_weight_model() -> Optional[WeightNN]:
    """学習後に cache reset。"""
    global _MODEL_CACHE, _MODEL_PATH
    _MODEL_CACHE = None
    _MODEL_PATH = None
    return get_weight_model()


def compute_weights_nn(state, me_idx: int) -> Optional[dict[str, float]]:
    """NN で state-dependent weights を計算。 model 不在で None (= 線形 fallback)。"""
    model = get_weight_model()
    if model is None:
        return None
    try:
        from .state_encoder import encode_state
        x = encode_state(state, me_idx)
        return model.predict_weights(x)
    except Exception as e:
        print(f"[weight_nn] compute_weights_nn failed: {e}")
        return None
