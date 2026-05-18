# -*- coding: utf-8 -*-
"""相手 action model (= 関数 11 / 16、 Phase 8 / Step 1 / 2026-05-16)。

inverse reasoning (= B.5b) の likelihood source として使う `P(action | hand, state)` を推定。
学習は完全情報 self-play (= Step 5) で行う。 Step 1 では:
- `bucket_state` (= 関数 16): state を discrete bucket に離散化
- `action_likelihood` (= 関数 11): table fallback で uniform 確率を返す骨組み

NN backend は Step 5 で `_OPP_ACTION_MODEL_NN` に load される。 NN load 済なら NN path、
未 load なら bucket_state ベースの統計テーブル fallback で動作。

# 公開 API
- `bucket_state(state, opp_idx) -> tuple`
- `action_likelihood(state, opp_idx, candidate_action, candidate_hand) -> float`
- `set_action_table(table)`: 統計テーブル設定 (= test / 学習スクリプトから)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .core import CardDef, GameState


# bucket 数:
# - life:       0-1 / 2-3 / 4-5 の 3 段階
# - don_active: 0 / 1-3 / 4-6 / 7+ の 4 段階
# - hand_size:  0-2 / 3-5 / 6+ の 3 段階
# - phase:      "main" / "battle" / "end" / その他 の 4 段階 (= 文字列で）
# - trash_size: 0-5 / 6-15 / 16+ の 3 段階
# 合計 bucket 数: 3 × 4 × 3 × 4 × 3 = 432


def _bucket_life(n: int) -> int:
    if n <= 1:
        return 0
    if n <= 3:
        return 1
    return 2


def _bucket_don(n: int) -> int:
    if n == 0:
        return 0
    if n <= 3:
        return 1
    if n <= 6:
        return 2
    return 3


def _bucket_hand(n: int) -> int:
    if n <= 2:
        return 0
    if n <= 5:
        return 1
    return 2


def _bucket_trash(n: int) -> int:
    if n <= 5:
        return 0
    if n <= 15:
        return 1
    return 2


def _bucket_phase(phase) -> str:
    name = phase.name if hasattr(phase, "name") else str(phase)
    if "MAIN" in name:
        return "main"
    if "BATTLE" in name or "ATTACK" in name:
        return "battle"
    if "END" in name:
        return "end"
    return "other"


def bucket_state(state: "GameState", opp_idx: int) -> tuple:
    """state を discrete bucket に離散化 (= 関数 16)。

    Returns: (life_b, don_b, hand_b, phase_b, trash_b) tuple、 432 種に分類。
    NN 未学習時の `action_likelihood` の table-based fallback で使用。
    """
    opp = state.players[opp_idx]
    return (
        _bucket_life(len(opp.life)),
        _bucket_don(getattr(opp, "don_active", getattr(opp, "total_don", 0))),
        _bucket_hand(len(opp.hand)),
        _bucket_phase(state.phase),
        _bucket_trash(len(opp.trash)),
    )


# action カテゴリ (~10 種)。 学習スクリプトでも同じカテゴリを使う。
ACTION_CATEGORIES = [
    "PlayCharacter",
    "PlayEvent",
    "PlayStage",
    "ActivateMain",
    "AttackLeader",
    "AttackCharacter",
    "AttachDon",
    "PassMain",
    "EndPhase",
    "Other",
]
N_ACTION_CATEGORIES = len(ACTION_CATEGORIES)


def _action_category_key(candidate_action: Any) -> str:
    """Action オブジェクトをカテゴリキーに分類。 既存 Action 階層に依存しない簡易判定。"""
    if candidate_action is None:
        return "Other"
    cls_name = type(candidate_action).__name__
    if cls_name in ACTION_CATEGORIES:
        return cls_name
    # 既存 engine の Action 命名規則に基づくマッピング
    name_upper = cls_name.upper()
    if "PLAY" in name_upper and "CHAR" in name_upper:
        return "PlayCharacter"
    if "PLAY" in name_upper and "EVENT" in name_upper:
        return "PlayEvent"
    if "PLAY" in name_upper and "STAGE" in name_upper:
        return "PlayStage"
    if "ACTIVATE" in name_upper or "MAIN" in name_upper:
        return "ActivateMain"
    if "ATTACK" in name_upper:
        # leader / chara 区別を試みる
        target = getattr(candidate_action, "target", None)
        if target is not None and hasattr(target, "card"):
            cat = getattr(target.card, "category", "")
            if "LEADER" in str(cat):
                return "AttackLeader"
            return "AttackCharacter"
        return "AttackCharacter"
    if "DON" in name_upper or "ATTACH" in name_upper:
        return "AttachDon"
    if "PASS" in name_upper:
        return "PassMain"
    if "END" in name_upper:
        return "EndPhase"
    return "Other"


# 統計テーブル (= 学習スクリプトから set される、 default は空 = uniform)
_OPP_ACTION_TABLE: dict[tuple, dict[str, float]] = {}

# NN backend (= Step 5 で load される)
_OPP_ACTION_MODEL_NN: Optional[Any] = None


def set_action_table(table: dict[tuple, dict[str, float]]) -> None:
    """統計テーブル (= bucket_key → action_category → prob) を設定。"""
    global _OPP_ACTION_TABLE
    _OPP_ACTION_TABLE = dict(table)


def set_nn_model(model) -> None:
    """NN backend を設定 (= Step 5 で load された opp_action_model.pt)。"""
    global _OPP_ACTION_MODEL_NN
    _OPP_ACTION_MODEL_NN = model


def _try_auto_load_nn() -> None:
    """db/opp_action_model.pt が存在すれば auto-load (= 1 度だけ)。"""
    global _OPP_ACTION_MODEL_NN
    if _OPP_ACTION_MODEL_NN is not None:
        return
    import os
    if os.environ.get("ONEPIECE_OPP_ACTION_DISABLE"):
        return
    from pathlib import Path
    import json
    pt_path = Path(__file__).resolve().parent.parent / "db" / "opp_action_model.pt"
    if not pt_path.exists():
        return
    try:
        import torch
        import torch.nn as nn
        # train_opp_action_model.py が出力する meta は db/_opp_action_feature_keys.json
        meta_path = pt_path.parent / "_opp_action_feature_keys.json"
        if not meta_path.exists():
            return
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        input_dim = int(meta.get("input_dim", 78))
        hidden_dim = int(meta.get("hidden_dim", 64))
        feature_keys = meta.get("feature_keys")

        class _OppModel(nn.Module):
            def __init__(self):
                super().__init__()
                self.net = nn.Sequential(
                    nn.Linear(input_dim, hidden_dim),
                    nn.ReLU(),
                    nn.Dropout(0.2),
                    nn.Linear(hidden_dim, hidden_dim // 2),
                    nn.ReLU(),
                    nn.Linear(hidden_dim // 2, N_ACTION_CATEGORIES),
                )

            def predict_policy(self, x):
                if not isinstance(x, torch.Tensor):
                    x = torch.tensor(x, dtype=torch.float32)
                if x.dim() == 1:
                    x = x.unsqueeze(0)
                with torch.no_grad():
                    logits = self.net(x)
                    probs = torch.softmax(logits, dim=-1)
                    return probs.squeeze(0).tolist()

        m = _OppModel()
        sd = torch.load(pt_path, map_location="cpu", weights_only=True)
        m.load_state_dict(sd)
        m.eval()
        m._input_dim = input_dim  # action_likelihood が input dim 識別に使う
        m._feature_keys = feature_keys
        _OPP_ACTION_MODEL_NN = m
    except Exception as e:
        print(f"[opp_action_model] auto-load failed: {e}")
        _OPP_ACTION_MODEL_NN = None


def reset_for_testing() -> None:
    """テスト用に table と NN をリセット。"""
    global _OPP_ACTION_TABLE, _OPP_ACTION_MODEL_NN
    _OPP_ACTION_TABLE = {}
    _OPP_ACTION_MODEL_NN = None


def action_likelihood(
    state: "GameState",
    opp_idx: int,
    candidate_action: Any,
    candidate_hand: list,
) -> float:
    """関数 11: P(action | hand, state) を推定。

    NN backend (= _OPP_ACTION_MODEL_NN) がロード済なら NN path、
    未ロードなら統計テーブル fallback、 さらに table も空なら uniform。
    """
    _try_auto_load_nn()  # 初回呼び出しで auto-load (= 既に load 済ならスキップ)
    # path A: NN backend
    # 注: 2026-05-17 時点の学習 model (= train_opp_action_model.py 出力) は 78 dim 入力
    # (= compute_breakdown features)。 真の P(action | hand, state) ではなく marginal
    # P(action | state) を返す partial 実装。 hand-aware NN は Plan H で再学習する。
    if _OPP_ACTION_MODEL_NN is not None:
        try:
            input_dim = getattr(_OPP_ACTION_MODEL_NN, "_input_dim", None)
            if input_dim == 78 or input_dim is None:
                # 旧 78 dim model: compute_breakdown 由来 features を使う
                from .eval import compute_breakdown
                feature_keys = getattr(_OPP_ACTION_MODEL_NN, "_feature_keys", None)
                bd = compute_breakdown(state, opp_idx)
                if feature_keys:
                    x = [float(bd.get(k, {}).get("diff", 0)) for k in feature_keys]
                else:
                    x = [float(v.get("diff", 0)) for _, v in sorted(bd.items())]
            else:
                # 202 dim model (= 将来の hand-aware 版)
                from .state_encoder import encode_state_with_hand
                x = encode_state_with_hand(state, opp_idx, candidate_hand)
            policy = _OPP_ACTION_MODEL_NN.predict_policy(x)
            action_key = _action_category_key(candidate_action)
            idx = ACTION_CATEGORIES.index(action_key) if action_key in ACTION_CATEGORIES else N_ACTION_CATEGORIES - 1
            return float(policy[idx])
        except Exception:
            pass  # NN 失敗時は table fallback

    # path B: 統計テーブル fallback
    bucket = bucket_state(state, opp_idx)
    action_key = _action_category_key(candidate_action)

    if bucket in _OPP_ACTION_TABLE:
        probs = _OPP_ACTION_TABLE[bucket]
        return float(probs.get(action_key, 1.0 / N_ACTION_CATEGORIES))

    # path C: uniform fallback (= 学習データ全く無し)
    return 1.0 / N_ACTION_CATEGORIES
