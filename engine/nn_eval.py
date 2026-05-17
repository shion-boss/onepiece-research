# -*- coding: utf-8 -*-
"""PyTorch MLP NN evaluator (= Plan Step 3、 軽量 dual-head)。

input: 172 dim (= engine.state_encoder.encode_state)
hidden: 128 → 64
output: dual-head
  - value: scalar (= score、 既存 compute_score 互換)
  - policy: 9 dim (= action category 確率分布、 plan_search beam pruning 用)

学習:
- value loss = MSE (= snapshot の outcome ±1 を target)
- policy loss = CrossEntropy (= 実際に AI が選んだ action category を target)
- dual loss = value_loss + 0.5 * policy_loss

推論:
- 1 forward = ~数 ms (= CPU)
- plan_search の各 leaf で呼ぶ場合 全体 +20-30% overhead 想定

env var ONEPIECE_NN_MODEL_PATH or 既定 path (= db/nn_eval.pt) に model file 存在で 自動有効化。
無ければ ridge fallback (= eval.py の compute_score 線形 path)。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import json

import torch
import torch.nn as nn

from .core import GameState
from .state_encoder import encode_state, encoded_dim


# action category 数 (= policy head の output dim)
N_ACTION_CATEGORIES = 9
ACTION_CATEGORIES = [
    "PlayCharacter", "PlayEvent", "PlayStage",
    "AttachDonToLeader", "AttachDonToCharacter",
    "AttackLeader", "AttackCharacter",
    "ActivateMain", "EndPhase",
]
ACTION_CATEGORY_TO_IDX = {a: i for i, a in enumerate(ACTION_CATEGORIES)}


class NNEvaluator(nn.Module):
    """軽量 MLP dual-head (= value + policy)、 CPU で 1 forward ~ms。

    parameter 数 ≈ 172*128 + 128*64 + 64*1 + 64*9 ≈ 30K (= 軽量)。
    """

    def __init__(self, input_dim: int = 172, hidden_dim: int = 128):
        super().__init__()
        self.shared = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
        )
        self.value_head = nn.Linear(hidden_dim // 2, 1)
        self.policy_head = nn.Linear(hidden_dim // 2, N_ACTION_CATEGORIES)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """returns (value, policy_logits)。 value は (B, 1) スカラ、 policy は (B, K) logits。"""
        h = self.shared(x)
        value = self.value_head(h)
        policy_logits = self.policy_head(h)
        return value, policy_logits


class SimpleEvaluator(nn.Module):
    """78 dim features (= compute_breakdown.diff) を入力にする 軽量 MLP。

    Plan Step 3 暫定: 既存 snapshot (= features dict 78 dim) で学習可能。
    state_encoder 整備までの fallback 経路。
    parameter 数 ≈ 78*64 + 64*32 + 32*1 + 32*9 ≈ 8K。
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


class StateEncoderEvaluator(nn.Module):
    """Phase G (= v4): 172 dim state_encoded を直接入力。 dropout 付き 3 層 hidden。

    plan「順に全部」 v4 notebook (= colab_train_nn_eval_v4.ipynb) の StateEncoderEvaluator
    と完全同一構造。 v4 .pt の state_dict をそのまま load 可能。

    parameter 数 ≈ 172*256 + 256*128 + 128*64 + 64*1 + 64*9 ≈ 80K。
    """

    def __init__(self, input_dim: int = 172, dropout: float = 0.2):
        super().__init__()
        self.shared = nn.Sequential(
            nn.Linear(input_dim, 256),  # shared.0
            nn.ReLU(),                  # shared.1
            nn.Dropout(dropout),        # shared.2
            nn.Linear(256, 128),        # shared.3
            nn.ReLU(),                  # shared.4
            nn.Dropout(dropout),        # shared.5
            nn.Linear(128, 64),         # shared.6
            nn.ReLU(),                  # shared.7
            nn.Dropout(dropout),        # shared.8
        )
        self.value_head = nn.Linear(64, 1)
        self.policy_head = nn.Linear(64, N_ACTION_CATEGORIES)

    def forward(self, x):
        h = self.shared(x)
        return self.value_head(h), self.policy_head(h)


def _detect_model_from_state_dict(state_dict: dict) -> Optional[nn.Module]:
    """state_dict の key + shape から適切な model class を auto-detect。

    判別ロジック:
    - "shared.6.weight" 存在 → StateEncoderEvaluator (= v4、 3 hidden + dropout)
    - "shared.2.weight" のみ → SimpleEvaluator (= v1/v2/v3 系、 2 hidden、 dropout なし)
    - "shared.0.weight" の shape[1] (= input_dim) を SimpleEvaluator に渡す

    Returns: 構築済 model (state_dict load 前)、 判別不可なら None。
    """
    if "shared.0.weight" not in state_dict:
        return None
    input_dim = state_dict["shared.0.weight"].shape[1]

    # v4 系 (= StateEncoderEvaluator): shared.0 / shared.3 / shared.6 の 3 層
    if "shared.6.weight" in state_dict:
        return StateEncoderEvaluator(input_dim=input_dim)

    # v1/v2/v3 系 (= SimpleEvaluator): shared.0 / shared.2 の 2 層、 hidden=64 想定
    return SimpleEvaluator(input_dim=input_dim)


# global model cache (= 1 度 load して使い回す)
_MODEL_CACHE: Optional[nn.Module] = None
_MODEL_LOADED_PATH: Optional[Path] = None
_FEATURE_KEYS_CACHE: Optional[list[str]] = None


def _default_model_path() -> Path:
    return Path(__file__).resolve().parent.parent / "db" / "nn_eval.pt"


def _default_feature_keys_path() -> Path:
    return Path(__file__).resolve().parent.parent / "db" / "_nn_feature_keys.json"


def get_feature_keys() -> Optional[list[str]]:
    """train_nn_eval.py が保存した feature keys を load。"""
    global _FEATURE_KEYS_CACHE
    if _FEATURE_KEYS_CACHE is not None:
        return _FEATURE_KEYS_CACHE
    path = _default_feature_keys_path()
    if not path.exists():
        return None
    try:
        _FEATURE_KEYS_CACHE = json.loads(path.read_text(encoding="utf-8"))
        return _FEATURE_KEYS_CACHE
    except Exception:
        return None


def get_model() -> Optional[nn.Module]:
    """env or 既定 path から model を load (= 1 度のみ、 cache)。
    無ければ None (= 線形 fallback)。

    state_dict の構造から SimpleEvaluator / StateEncoderEvaluator を auto-detect。
    """
    global _MODEL_CACHE, _MODEL_LOADED_PATH
    if _MODEL_CACHE is not None:
        return _MODEL_CACHE
    env_path = os.environ.get("ONEPIECE_NN_MODEL_PATH")
    path = Path(env_path) if env_path else _default_model_path()
    if not path.exists():
        return None
    try:
        state_dict = torch.load(path, map_location="cpu", weights_only=True)
        model = _detect_model_from_state_dict(state_dict)
        if model is None:
            print(f"[nn_eval] could not detect model class from state_dict keys: {list(state_dict.keys())[:5]}")
            return None
        model.load_state_dict(state_dict)
        model.eval()
        _MODEL_CACHE = model
        _MODEL_LOADED_PATH = path
        return model
    except Exception as e:
        print(f"[nn_eval] model load failed: {e}")
        return None


def reload_model(path: Optional[Path] = None) -> Optional[NNEvaluator]:
    """学習で model 更新後に cache を reset。"""
    global _MODEL_CACHE, _MODEL_LOADED_PATH
    _MODEL_CACHE = None
    _MODEL_LOADED_PATH = None
    if path is not None:
        os.environ["ONEPIECE_NN_MODEL_PATH"] = str(path)
    return get_model()


def _build_input_features(model: nn.Module, state: GameState, me_idx: int) -> list[float]:
    """model 種別に応じて入力 features を構築。

    - SimpleEvaluator (= 78 dim): compute_breakdown の diff 値を feature_keys 順に並べる
    - StateEncoderEvaluator / NNEvaluator (= 172 dim): state_encoder.encode_state
    """
    if isinstance(model, SimpleEvaluator):
        feature_keys = get_feature_keys()
        if feature_keys is None:
            # fallback (= keys file 不在、 sorted で代用)
            from .eval import compute_breakdown
            bd = compute_breakdown(state, me_idx)
            return [float(v.get("diff", 0)) for _, v in sorted(bd.items())]
        from .eval import compute_breakdown
        bd = compute_breakdown(state, me_idx)
        return [float(bd.get(k, {}).get("diff", 0)) for k in feature_keys]
    # StateEncoderEvaluator / NNEvaluator
    return encode_state(state, me_idx)


def compute_score_nn(state: GameState, me_idx: int) -> Optional[float]:
    """NN value head の出力を score として返す。 model 不在なら None (= 線形 fallback)。"""
    model = get_model()
    if model is None:
        return None
    try:
        with torch.no_grad():
            features = _build_input_features(model, state, me_idx)
            x = torch.tensor(features, dtype=torch.float32).unsqueeze(0)
            value, _ = model(x)
            return float(value.item()) * 5000.0
    except Exception as e:
        print(f"[nn_eval] compute_score_nn failed: {e}")
        return None


def compute_policy_nn(state: GameState, me_idx: int) -> Optional[dict[str, float]]:
    """NN policy head の category 別 確率分布を返す。 model 不在なら None。

    SimpleEvaluator でも動作する (= ただし v1-v3 では policy head 学習されてないので
    実用的な分布は出ない、 v4 で初めて意味を持つ)。
    """
    model = get_model()
    if model is None:
        return None
    try:
        with torch.no_grad():
            features = _build_input_features(model, state, me_idx)
            x = torch.tensor(features, dtype=torch.float32).unsqueeze(0)
            _, policy_logits = model(x)
            probs = torch.softmax(policy_logits, dim=-1).squeeze(0)
            return {ACTION_CATEGORIES[i]: float(probs[i].item()) for i in range(N_ACTION_CATEGORIES)}
    except Exception as e:
        print(f"[nn_eval] compute_policy_nn failed: {e}")
        return None
