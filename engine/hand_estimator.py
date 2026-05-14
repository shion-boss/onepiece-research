# -*- coding: utf-8 -*-
"""
ハンド推定 (隠匿情報モデル)
=============================

公式ルール上、 相手の手札は非公開 (= 自プレイヤーには見えない)。
現実装の AI は state.opponent.hand を直接読めるため「ズル」している。

このモジュールは、 相手手札を確率分布として扱う API を提供。

公開 API:
- `EstimatedHand`: 期待カウンター/ブロッカー残存確率 + 分布を集約
- `expected_counter_per_card(state, opp_idx)`: 1 枚あたり期待カウンター値
- `expected_counter_total(state, opp_idx)`: 期待カウンター総量
- `counter_total_pmf(state, opp_idx)`: 手札 counter 合計の確率分布 (Phase 7B 追加)
- `probability_counter_total_at_least(state, opp_idx, threshold)`: 合計 ≥ threshold の確率 (Phase 7B 追加)
- `counter_total_quantile(state, opp_idx, q)`: 合計の q-分位点 (Phase 7B 追加)
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
from collections import Counter as _Counter
from dataclasses import dataclass, field
from math import comb
from typing import Optional

from .core import CardDef, GameState


@dataclass
class EstimatedHand:
    """相手手札の確率的推定値。

    - hand_count: 公開情報 (= 相手手札枚数、公式ルール上常に確認可能)
    - counter_per_card: deck+hand プール上の 1 枚あたり期待カウンター
    - counter_total: counter_per_card × hand_count (= 期待値)
    - counter_pmf: 手札 counter 合計の確率分布 {total: prob} (Phase 7B 追加)
    - counter_q50: counter 合計の中央値 (= P(<=q50) >= 0.5)
    - counter_q90: counter 合計の 90% 分位点 (= 「ほぼ確実にこれ以下」)
    - blocker_prob: 手札に 1 枚以上ブロッカーがある確率 (0.0〜1.0)
    """

    hand_count: int
    counter_per_card: float
    counter_total: int
    blocker_prob: float
    counter_pmf: dict[int, float] = field(default_factory=dict)
    counter_q50: int = 0
    counter_q90: int = 0


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


def counter_total_pmf(state: GameState, opp_idx: int) -> dict[int, float]:
    """opp 手札の counter 合計の確率分布 (pmf、 Phase 7B 追加)。

    Returns: `{counter_total: probability}` 辞書。 確率の総和 = 1.0。

    ## 計算原理 (= ハイパージオメトリック分布)

    プールが N 枚 (= deck + hand) で、 各 counter 値の枚数を K_v、 手札 h 枚を抽出する時、
    手札の counter 合計 S が特定値を取る確率を 多変量超幾何分布から計算:

    P(composition = (n_v1, n_v2, ...)) = Π C(K_vi, n_vi) / C(N, h)
    S = Σ v_i × n_vi

    通常 OPTCG では counter 値が 3-4 種類 (0, 1000, 2000) なので、
    全 composition を列挙しても O(N^2) 程度で済む = 高速。

    例: pool=[0×30, 1000×15, 2000×5] (total 50), hand=5
    → 6×4×6=144 通りの composition (多くは確率 0)、 実効計算量 ~50 ops。

    プール空 / 手札空: `{0: 1.0}` を返す。
    """
    opp = state.players[opp_idx]
    hand_size = len(opp.hand)
    if hand_size == 0:
        return {0: 1.0}
    pool = _opponent_pool(state, opp_idx)
    if len(pool) < hand_size:
        return {0: 1.0}

    # counter 値別の枚数 グループ
    groups = _Counter(c.counter for c in pool)
    n_total = len(pool)
    norm = comb(n_total, hand_size)
    if norm == 0:
        return {0: 1.0}

    pmf: dict[int, float] = {}
    # 各 counter 値について「手札に n 枚採用」 を再帰的に列挙
    items = list(groups.items())

    def _enumerate(idx: int, remaining: int, total: int, numerator: int) -> None:
        if idx == len(items):
            if remaining == 0:
                pmf[total] = pmf.get(total, 0.0) + numerator / norm
            return
        val, count = items[idx]
        max_take = min(count, remaining)
        for n in range(max_take + 1):
            new_num = numerator * comb(count, n)
            _enumerate(idx + 1, remaining - n, total + val * n, new_num)

    _enumerate(0, hand_size, 0, 1)
    return pmf


def probability_counter_total_at_least(
    state: GameState, opp_idx: int, threshold: int,
) -> float:
    """opp 手札の counter 合計が threshold 以上である確率 (Phase 7B 追加)。

    リーサル判定で「相手がこのダメージを止められる確率」 として使う:
        P_block = P(counter_total >= damage)
        P_lethal = 1 - P_block

    threshold ≤ 0 なら 1.0 (= 常に成立)。
    """
    if threshold <= 0:
        return 1.0
    pmf = counter_total_pmf(state, opp_idx)
    return sum(p for total, p in pmf.items() if total >= threshold)


def counter_total_quantile(
    state: GameState, opp_idx: int, q: float,
) -> int:
    """opp 手札の counter 合計の q-分位点 (Phase 7B 追加)。

    Returns: 「累積確率 q 以上に達する最小の counter 合計値」。
    例: q=0.5 で中央値、 q=0.9 で 「90% の確率でこれ以下」 (= 強気の見積)。

    プール空 / 手札空: 0 を返す。
    """
    q = max(0.0, min(1.0, q))
    pmf = counter_total_pmf(state, opp_idx)
    if not pmf:
        return 0
    sorted_totals = sorted(pmf.keys())
    cumulative = 0.0
    for total in sorted_totals:
        cumulative += pmf[total]
        if cumulative >= q:
            return total
    return sorted_totals[-1]


def estimate_hand(state: GameState, opp_idx: int) -> EstimatedHand:
    """opp.hand を直視せず、 公開情報のみから期待値推定。 分布値込み (Phase 7B)。"""
    opp = state.players[opp_idx]
    per_card = expected_counter_per_card(state, opp_idx)
    pmf = counter_total_pmf(state, opp_idx)
    q50 = counter_total_quantile(state, opp_idx, 0.5)
    q90 = counter_total_quantile(state, opp_idx, 0.9)
    return EstimatedHand(
        hand_count=len(opp.hand),
        counter_per_card=per_card,
        counter_total=int(per_card * len(opp.hand)),
        blocker_prob=probability_of_blocker_in_hand(state, opp_idx),
        counter_pmf=pmf,
        counter_q50=q50,
        counter_q90=q90,
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
