# -*- coding: utf-8 -*-
"""NN value の pickle 可能 wrapper (2026-07-28、 Plan B PoC)。
importable module に置くことで、 学習側(train_nn_value)と評価側(arena/ValuePolicyAI)で
同一 class 参照 → unpickle 可能(__main__ 問題回避)。 sklearn 互換 predict を提供。
"""
import numpy as np
import torch
import torch.nn as nn


class MLP(nn.Module):
    def __init__(self, dim, hidden):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(dim, hidden), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(hidden, hidden), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(hidden, hidden // 2), nn.ReLU(),
            nn.Linear(hidden // 2, 1),
        )

    def forward(self, x):
        return torch.sigmoid(self.net(x)).squeeze(-1)


class NNWrapper:
    """sklearn 互換 predict(2D np → 1D value ∈ [0,1])。 標準化 + torch MLP を内包、 pickle 可。"""
    def __init__(self, state_dict, dim, hidden, mean, std):
        self.state_dict = state_dict
        self.dim = dim
        self.hidden = hidden
        self.mean = mean
        self.std = std
        self._m = None

    def _model(self):
        if self._m is None:
            torch.set_num_threads(1)
            m = MLP(self.dim, self.hidden)
            m.load_state_dict(self.state_dict)
            m.eval()
            self._m = m
        return self._m

    def predict(self, X):
        m = self._model()
        x = (np.asarray(X, dtype=np.float32) - self.mean) / self.std
        with torch.no_grad():
            return m(torch.from_numpy(x)).numpy()
