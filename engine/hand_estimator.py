# -*- coding: utf-8 -*-
"""
ハンド推定 (隠匿情報モデル)
=============================

公式ルール上、 相手の手札は非公開 (= 自プレイヤーには見えない)。
現実装の AI は state.opponent.hand を直接読めるため「ズル」している。

このモジュールは、 相手手札を確率分布として扱う API を提供。

公開 API:
- `EstimatedHand`: 期待カウンター/ブロッカー残存確率を集約した推定結果
- `expected_counter_per_card(state, opp_idx)`: 1 枚あたり期待カウンター値
- `expected_counter_total(state, opp_idx)`: 期待カウンター総量
- `probability_of_blocker_in_hand(state, opp_idx)`: 手札に 1 枚以上ブロッカーが
  ある確率 (ハイパージオメトリック)
- `estimate_hand(state, opp_idx) -> EstimatedHand`: 上記をまとめて取得
- `sample_opponent_hand(state, opp_idx, rng)`: hand_count 枚を deck+hand プールから
  無作為サンプル (MCTS 決定論化用)
- `determinize_state(state, opp_idx, rng)`: state を完全情報化 (MCTS rollout 用)

「プール」の定義: opp.deck + opp.hand (= trash/play 以外の残カード全部)。
公開情報 (trash / play 済カード) は自動的に除外される。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

from .core import CardDef, GameState


@dataclass
class EstimatedHand:
    """相手手札の確率的推定値。

    - hand_count: 公開情報 (= 相手手札枚数、公式ルール上常に確認可能)
    - counter_per_card: deck+hand プール上の 1 枚あたり期待カウンター
    - counter_total: counter_per_card × hand_count
    - blocker_prob: 手札に 1 枚以上ブロッカーがある確率 (0.0〜1.0)
    """

    hand_count: int
    counter_per_card: float
    counter_total: int
    blocker_prob: float


def _opponent_pool(state: GameState, opp_idx: int) -> list[CardDef]:
    """opp の手札候補プール: deck + hand (= trash/play 以外の残カード全部)。

    公開済 (trash, play, life) は含まれない。
    """
    opp = state.players[opp_idx]
    return list(opp.deck) + list(opp.hand)


def expected_counter_per_card(state: GameState, opp_idx: int) -> float:
    """opp の deck+hand プール上での 1 枚あたり期待カウンター値。

    例: プールに [2000, 1000, 0, 0, 1000] のカウンター値なら平均 800。
    既にトラッシュに行ったカウンター持ちカードは自動的に除外される。
    """
    pool = _opponent_pool(state, opp_idx)
    if not pool:
        return 0.0
    return sum(c.counter for c in pool) / len(pool)


def expected_counter_total(state: GameState, opp_idx: int) -> int:
    """opp の手札に期待されるカウンター総量。"""
    opp = state.players[opp_idx]
    return int(expected_counter_per_card(state, opp_idx) * len(opp.hand))


def probability_of_blocker_in_hand(state: GameState, opp_idx: int) -> float:
    """opp の手札に少なくとも 1 枚ブロッカーがある確率 (ハイパージオメトリック)。

    プール N 枚中ブロッカー K 枚、手札 h 枚として、
    P(>=1 blocker) = 1 - C(N-K, h) / C(N, h)
                   = 1 - Π_{i=0}^{h-1} (N-K-i) / (N-i)
    """
    opp = state.players[opp_idx]
    pool = _opponent_pool(state, opp_idx)
    h = len(opp.hand)
    n_pool = len(pool)
    if h == 0 or n_pool == 0:
        return 0.0
    n_blocker = sum(1 for c in pool if c.is_blocker)
    if n_blocker == 0:
        return 0.0
    if n_blocker >= n_pool:
        return 1.0
    if h >= n_pool:
        return 1.0
    p_zero = 1.0
    for i in range(h):
        denom = n_pool - i
        if denom <= 0:
            return 1.0
        p_zero *= (n_pool - n_blocker - i) / denom
        if p_zero <= 0.0:
            return 1.0
    return 1.0 - p_zero


def estimate_hand(state: GameState, opp_idx: int) -> EstimatedHand:
    """opp.hand を直視せず、 公開情報のみから期待値推定。"""
    opp = state.players[opp_idx]
    per_card = expected_counter_per_card(state, opp_idx)
    return EstimatedHand(
        hand_count=len(opp.hand),
        counter_per_card=per_card,
        counter_total=int(per_card * len(opp.hand)),
        blocker_prob=probability_of_blocker_in_hand(state, opp_idx),
    )


def sample_opponent_hand(
    state: GameState,
    opp_idx: int,
    rng: Optional[random.Random] = None,
) -> list[CardDef]:
    """opp の hand_count 枚を deck + hand プールから無作為にサンプル。

    決定論的 AI の評価では opp.hand を見ずに、 残カードから推定したいケースで使う。
    プール = opp.deck (山札) + opp.hand (= 既に手札にあるが非公開と仮定して plundered)
    実際には deck だけでなく現 hand も対象に含めたい (= 50枚デッキ完成形のうち場/トラッシュ以外)。
    """
    if rng is None:
        rng = state.rng or random.Random()
    opp = state.players[opp_idx]
    pool = list(opp.deck) + list(opp.hand)
    n = min(len(opp.hand), len(pool))
    if n == 0:
        return []
    return rng.sample(pool, n)


def estimate_counter_total(state: GameState, opp_idx: int) -> int:
    """期待カウンター総量 (旧 API、 `expected_counter_total` へのエイリアス)。"""
    return expected_counter_total(state, opp_idx)


def determinize_state(
    state: GameState,
    opp_idx: int,
    rng: Optional[random.Random] = None,
) -> None:
    """state を「完全情報化」: opp.hand を deck からのランダムサンプルで置換。

    MCTSAI の rollout / Lookahead の評価で、 opp.hand を見ない (= 公正な) 探索に使う。
    呼出し前に state を deepcopy しておくこと (本物を壊さないため)。
    """
    if rng is None:
        rng = state.rng or random.Random()
    opp = state.players[opp_idx]
    pool = list(opp.deck) + list(opp.hand)
    n = len(opp.hand)
    if n == 0 or not pool:
        return
    sampled = rng.sample(pool, n)
    # 残りはデッキ
    remaining = [c for c in pool if c not in sampled]
    # rng.sample は順序ランダム、 remaining はデッキ底順 (= 元順序維持)
    opp.hand = sampled
    opp.deck = remaining
