# -*- coding: utf-8 -*-
"""Plan D (= 2026-05-18): AlphaZero 風 value NN。 MCTS rollout で計算した P(win|state) を target。

v1-v5 NN (= 最終勝者 ±1 を全 snapshot 一律 target) との違い:
  v1-v5: 序盤 snapshot も「最終勝者」 が target = noise 大、 critical state で 鈍い
  Plan D: 各 state で MCTS rollout → P(win|state) を計算済 → critical state でも正確

input:  state_encoded (= 172 dim)
hidden: 256 → 256 → 128 (= 中型、 v5 比 1.5x)
output: P(win) ∈ [0, 1] (= sigmoid)
loss:   BCE or MSE

推論時: plan_search の leaf eval で 「(2 × P(win) - 1) × magnify」 を score として使う
       (= P(win)=0.5 で 0、 1.0 で +magnify、 0.0 で -magnify)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import torch
import torch.nn as nn


class ValueNNAlphaZero(nn.Module):
    """AlphaZero 風 value NN: state → P(win) ∈ [0,1]。

    parameter 数 ~150K (= v5 の 1.8x)。 表現力アップで critical state の精度向上を狙う。
    """

    def __init__(self, input_dim: int = 172, hidden_dim: int = 256, dropout: float = 0.15):
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
        self.value_head = nn.Linear(hidden_dim // 2, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """returns P(win) ∈ [0,1] (= sigmoid 適用後)。"""
        h = self.body(x)
        return torch.sigmoid(self.value_head(h)).squeeze(-1)


# global cache
_MODEL: Optional[ValueNNAlphaZero] = None
_MODEL_PATH: Optional[Path] = None


def _default_path() -> Path:
    return Path(__file__).resolve().parent.parent / "db" / "value_nn_alphazero.pt"


def get_value_model() -> Optional[ValueNNAlphaZero]:
    """db/value_nn_alphazero.pt から load (= 1 度のみ cache)。"""
    global _MODEL, _MODEL_PATH
    if os.environ.get("ONEPIECE_AZ_VALUE_DISABLE"):
        return None
    if _MODEL is not None:
        return _MODEL
    env_path = os.environ.get("ONEPIECE_AZ_VALUE_NN_PATH")
    path = Path(env_path) if env_path else _default_path()
    if not path.exists():
        return None
    try:
        sd = torch.load(path, map_location="cpu", weights_only=True)
        m = ValueNNAlphaZero()
        m.load_state_dict(sd)
        m.eval()
        _MODEL = m
        _MODEL_PATH = path
        return m
    except Exception as e:
        print(f"[value_nn_alphazero] load failed: {e}")
        return None


def reload_value_model() -> Optional[ValueNNAlphaZero]:
    global _MODEL, _MODEL_PATH
    _MODEL = None
    _MODEL_PATH = None
    return get_value_model()


def compute_value_az(state, me_idx: int) -> Optional[float]:
    """state → P(win) → magnify でスコア化。 model 不在で None。

    plan_search の leaf eval として呼ぶ:
      score = (2 × P(win) - 1) × magnify
      P(win)=0.5 (= 五分) で score=0
      P(win)=1.0 (= 確定勝利) で score=+magnify
      P(win)=0.0 (= 確定敗北) で score=-magnify
    """
    model = get_value_model()
    if model is None:
        return None
    try:
        from .state_encoder import encode_state
        x = torch.tensor(encode_state(state, me_idx), dtype=torch.float32).unsqueeze(0)
        with torch.no_grad():
            p_win = float(model(x).item())
        magnify = float(os.environ.get("ONEPIECE_AZ_MAGNIFY", "30000"))
        return (2.0 * p_win - 1.0) * magnify
    except Exception as e:
        print(f"[value_nn_alphazero] compute_value_az failed: {e}")
        return None
