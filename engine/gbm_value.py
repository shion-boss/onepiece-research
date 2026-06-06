# -*- coding: utf-8 -*-
"""学習盤面value (= GBM) を beam の leaf eval に使う (= 2026-06-04 自律、 70% 探索)。

board_eval (= hand-tuned linear) は winrate-tune 済でも beam が 62.5% で飽和 (= 線形の天井)。
GBM (= 非線形、 特徴の交互作用) を beam-vs-greedy の (盤面, 勝敗) で学習し、 leaf で P(win) を
返せば、 線形 eval が捉えられない交互作用 (例: low-life × no-blocker) を value 化できる。

統合: compute_score の冒頭で ONEPIECE_GBM_VALUE_PATH が set されていれば、 game_over は
±W_GAME_OVER、 非終端は (P(win)-0.5)*SCALE を返す (= 既存 leaf eval を置換)。
"""
from __future__ import annotations

import os
from typing import Any, Optional

# feature 名 (= 学習/推論で厳密一致させる)。 v1 = 17 (基本盤面量、 2026-06-04)。
FEATURE_KEYS = (
    "d_life", "d_field_count", "d_field_power", "d_hand", "d_don",
    "d_blocker", "d_attached_don", "d_active_chara",
    "my_life", "opp_life", "my_hand", "opp_hand",
    "my_field_count", "opp_field_count", "my_field_power", "opp_field_power",
    "turn",
)
# v2 = 21 (2026-06-05): v1 が ROC0.755 で飽和 (= 37k sample でも不変 → データでなく特徴が天井)。
# race圏 (lethal) と 手札 counter 総量 (= 防御資源、 線形 eval が捉えぬ交互作用) を追加。
FEATURE_KEYS_V2 = FEATURE_KEYS + ("my_lethal", "opp_lethal", "my_counter", "opp_counter")

_MODEL = None
_MODEL_PATH: Optional[str] = None
SCALE = 1_000_000.0


def features(state: Any, me_idx: int, rich: Optional[bool] = None) -> list:
    """GameState + me_idx → feature vector。 rich=True で v2 (21)、 既定は env
    ONEPIECE_GBM_RICH (= 学習時に set)。 推論は gbm_score が model 次元で自動判別。"""
    from .eval import _player_metrics
    me = _player_metrics(state.players[me_idx])
    opp = _player_metrics(state.players[1 - me_idx])
    base = [
        me["life"] - opp["life"],
        me["field_count"] - opp["field_count"],
        me["field_power"] - opp["field_power"],
        me["hand"] - opp["hand"],
        me["don"] - opp["don"],
        me["blocker"] - opp["blocker"],
        me["attached_don"] - opp["attached_don"],
        me["active_chara"] - opp["active_chara"],
        me["life"], opp["life"], me["hand"], opp["hand"],
        me["field_count"], opp["field_count"], me["field_power"], opp["field_power"],
        int(getattr(state, "turn_number", 0)),
    ]
    if rich is None:
        rich = os.environ.get("ONEPIECE_GBM_RICH") == "1"
    if not rich:
        return base
    from .eval import lethal_estimate
    me_p, opp_p = state.players[me_idx], state.players[1 - me_idx]
    my_counter = sum(int(getattr(c, "counter", 0) or 0) for c in me_p.hand)
    opp_counter = sum(int(getattr(c, "counter", 0) or 0) for c in opp_p.hand)
    return base + [
        float(lethal_estimate(state, me_idx)),
        float(lethal_estimate(state, 1 - me_idx)),
        my_counter, opp_counter,
    ]


def _load(path: str):
    global _MODEL, _MODEL_PATH
    if _MODEL is not None and _MODEL_PATH == path:
        return _MODEL
    import pickle
    with open(path, "rb") as f:
        _MODEL = pickle.load(f)
    _MODEL_PATH = path
    return _MODEL


def gbm_score(state: Any, me_idx: int) -> Optional[float]:
    """ONEPIECE_GBM_VALUE_PATH の GBM で leaf value を返す (= 未設定なら None)。

    game_over は ±W_GAME_OVER、 非終端は (P(win)-0.5)*SCALE。
    """
    path = os.environ.get("ONEPIECE_GBM_VALUE_PATH")
    if not path:
        return None
    if getattr(state, "game_over", False):
        from .eval import DEFAULT_WEIGHTS
        w = getattr(state, "winner", -1)
        if w == me_idx:
            return float(DEFAULT_WEIGHTS.W_GAME_OVER)
        if w == 1 - me_idx:
            return -float(DEFAULT_WEIGHTS.W_GAME_OVER)
        return 0.0
    try:
        model = _load(path)
        # model の次元で v1(17)/v2(21) を自動判別 (= deployed 17特徴 GBM を壊さず後方互換)。
        n_feat = int(getattr(model, "n_features_in_", len(FEATURE_KEYS)))
        x = [features(state, me_idx, rich=(n_feat == len(FEATURE_KEYS_V2)))]
        p = float(model.predict_proba(x)[0][1])
        return (p - 0.5) * SCALE
    except Exception:
        return None
