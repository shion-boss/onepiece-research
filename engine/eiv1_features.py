"""EIV1 の特徴表現 (card-aware・grounded・growable) — 2026-07-23。

EIV1 = 天井なしコツコツ強化の self-play Expert Iteration AI ([[project_eiv1_expert_iteration]])。
その "表現" レバー。 EBV2 の 21 匿名スカラー(盲目)を、 overlay 由来の駒種ラベルで grounding した
card-aware な起点にする。

現状の起点 = gbm_value v15 (= 43dim)。 3 層の card-aware grounded 表現:
  1. v2 board 21 = 匿名スカラー盤面(EBV2 相当)
  2. v14 駒種ラベル 8 = on-board を removal/blocker/effect/activatable で分解 (機能ラベル)
  3. v15 機能×timing 14 = search_engine(起動メインサーチ) vs search_body(登場時サーチ) 等を別列
     (= ohtsuki 要求「ラベル + timing 区別」)。 draw_engine/ramp/recovery/negate/aggression も per player。

⚠ growable の設計: ここに列を APPEND して次元を伸ばす (= 容量をデータと共に伸ばす③の"表現"側)。
gbm_score は model 次元で feature 版を自動判別するので、 新次元は gbm_value.features + _feat_for_dim に
版を足せば inference も追随 (v16, v17... と増やせる)。

成長ロードマップ (ohtsuki 要求「カードそのものも認識」):
  - grounded ラベル+timing = ここまで実装済 (色跨ぎ共有・data 効率良・学習不要)
  - card identity (= 同カテゴリ内の強弱の微差、 例: 強いサーチ vs 弱いサーチ) = **学習埋め込み**が要る。
    GBM は埋め込みを学習できない → 次段は value を小 NN 化 (embedding テーブル + MLP)。 これが
    「カードそのもの」を捉える成長ピースで、 data-hungry (= EIV1 の corpus を貯めてから)。 grounded を
    起点にすれば cold-start しない (未知カードもラベル+timing で汎化、 学習でその上に微差を乗せる)。
"""
from __future__ import annotations
from typing import Any

from . import gbm_value

# EIV1 起点の feature 版 (= v15, card-aware grounded + timing)。 成長時はここを差し替え/拡張。
FEATURE_VER = "v15"


def eiv1_features(state: Any, me_idx: int) -> list:
    """EIV1 の feature ベクトル (現状 = v15 = 21 board + 8 駒種ラベル + 14 機能×timing カテゴリ)。"""
    return gbm_value.features(state, me_idx, v15=True)


def eiv1_dim() -> int:
    return len(gbm_value.FEATURE_KEYS_V15)
