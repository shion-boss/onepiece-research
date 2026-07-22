"""EIV1 の card identity 表現 (grounded per-card vector) — 2026-07-24。

ohtsuki 要求「ラベルも必要だが、 カードそのものも認識してほしい」の identity 側。

- **grounded ラベル/timing 集計 (= gbm_value v15)** は GBM value が今すぐ使う (固定長ベクトルに集計)。
  色跨ぎで共有・data 効率良いが、 **同カテゴリ内の強弱の微差 (強いサーチ vs 弱いサーチ) は潰れる**。
- その微差 = 「カードそのもの」を捉えるには **学習カード埋め込み (embedding)** が要る。 GBM は埋め込みを
  学習できないので、 これは value を小 NN 化したときの成長ピース (data-hungry = corpus を貯めてから)。

このモジュールはその **土台となる per-card grounded ベクトル** を提供する:
  card_vector(cid) = multi-hot(効果ラベル) ++ multi-hot(timing) ++ 正規化 stats [power,cost,counter,blocker]
  ＝ 各カードの「素性」を固定次元で表す。 未知カードも素性で埋まる (= cold-start しない)。
  将来の NN embedding はこのベクトルを **初期値/入力** にして学習で微差を上に乗せる (grounded init)。

＝ EIV1 の①表現の「カード identity」レーン。 GBM 経路 (v15 集計) とは独立。 EIV1 corpus は
per-card id も記録するので (eiv1_collect)、 corpus が育てば **再収集なしで** identity NN を学習できる。
"""
from __future__ import annotations
from typing import Any, List, Optional

from . import card_labels

# 固定順の語彙 (embedding 次元の順序を安定させる)
_EFFECT = card_labels.EFFECT_LABELS
_TIMING = card_labels.TIMING_LABELS
# stats 正規化スケール (概ね [0,1] に収める素朴な定数)
_PW_SCALE, _COST_SCALE, _CTR_SCALE = 12000.0, 10.0, 2000.0

# grounded ベクトルの次元 = |効果ラベル| + |timing| + 4 (power,cost,counter,blocker)
CARD_VEC_DIM = len(_EFFECT) + len(_TIMING) + 4


def card_vector(cid: Optional[str]) -> List[float]:
    """cid → grounded per-card ベクトル (固定次元 CARD_VEC_DIM)。 未知/None は 0 ベクトル。"""
    vec = [0.0] * CARD_VEC_DIM
    if not cid:
        return vec
    rec = card_labels.build_all().get(cid)
    if not rec:
        return vec
    L = set(rec.get("labels", ()))
    T = set(rec.get("timings", ()))
    i = 0
    for lab in _EFFECT:
        if lab in L:
            vec[i] = 1.0
        i += 1
    for tm in _TIMING:
        if tm in T:
            vec[i] = 1.0
        i += 1
    vec[i] = float(rec.get("power", 0) or 0) / _PW_SCALE
    vec[i + 1] = float(rec.get("cost", 0) or 0) / _COST_SCALE
    vec[i + 2] = float(rec.get("counter", 0) or 0) / _CTR_SCALE
    vec[i + 3] = 1.0 if rec.get("is_blocker") else 0.0
    return vec


def _cid(c) -> Optional[str]:
    cid = getattr(c, "card_id", None)
    if cid is None:
        cid = getattr(getattr(c, "card", None), "card_id", None)
    return cid


def board_card_ids(state: Any, player_idx: int) -> List[str]:
    """player の場のキャラ card_id 列 (leader は別枠)。 identity NN の主入力。"""
    p = state.players[player_idx]
    out = []
    for c in getattr(p, "characters", []):
        cid = _cid(c)
        if cid:
            out.append(cid)
    return out


def hand_card_ids(state: Any, player_idx: int) -> List[str]:
    """player の手札 card_id 列 (自分側のみ既知情報として記録する用途)。"""
    p = state.players[player_idx]
    out = []
    for c in getattr(p, "hand", []):
        cid = _cid(c)
        if cid:
            out.append(cid)
    return out


def leader_id(state: Any, player_idx: int) -> Optional[str]:
    lead = getattr(state.players[player_idx], "leader", None)
    return _cid(lead) if lead is not None else None


def per_card_snapshot(state: Any, me_idx: int) -> dict:
    """EIV1 corpus に足す per-card 生スナップショット (= identity NN 用の raw データ)。
    GBM(v15 集計)とは別に、 どのカードがどこに居たかを保存 → corpus が育てば再収集なしで identity 学習。"""
    opp = 1 - me_idx
    return {
        "me_lead": leader_id(state, me_idx),
        "opp_lead": leader_id(state, opp),
        "me_board": board_card_ids(state, me_idx),
        "opp_board": board_card_ids(state, opp),
        "me_hand": hand_card_ids(state, me_idx),
    }
