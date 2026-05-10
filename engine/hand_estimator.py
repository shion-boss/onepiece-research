# -*- coding: utf-8 -*-
"""
ハンド推定 (隠匿情報モデル) — 最小実装
======================================

公式ルール上、 相手の手札は非公開 (= 自プレイヤーには見えない)。
現実装の AI は state.opponent.hand を直接読めるため「ズル」している。

このモジュールは、 相手手札を確率分布として扱う最小実装を提供。

API:
- `EstimatedHand(card_count, deck_remaining)`: 推定 hand データ
- `sample_opponent_hand(state, opp_idx, rng) -> list[CardDef]`:
    opp の hand_count 枚を opp.deck + opp.hand から (= 残り 50-場 枚から) ランダムにサンプル
- `estimate_counter_total(state, opp_idx) -> int`: 期待 counter 総量 (公開済情報の確率分布から)

使い方 (将来 MCTSAI で):
- choose_action 前に sample_opponent_hand(state, opp_idx, rng) で仮の手札を生成
- deepcopy state でその仮 hand を opp.hand に代入
- ロールアウト実行 → 仮想結果

現実装は AI に組込まず、 ヘルパとして提供。 `engine.eval.compute_breakdown` の
hand 評価で使うことも可能 (= opp.hand の内容を使わず hand_count だけで評価)。
"""

from __future__ import annotations

import random
from typing import Optional

from .core import CardDef, GameState


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
    """opp の hand に期待される counter 総量を、 deck + hand プールの平均値で推定。

    AI が「相手は何 counter 持ってるか」を予測するのに使う簡易関数。
    使い方 (将来):
      gap_safety = estimate_counter_total(state, opp_idx) // opp.hand_count + 500
      → 1 枚あたり期待 counter + 500 のマージンで防御の見積
    """
    opp = state.players[opp_idx]
    pool = list(opp.deck) + list(opp.hand)
    if not pool:
        return 0
    total = sum(c.counter for c in pool)
    avg_per_card = total / len(pool)
    return int(avg_per_card * len(opp.hand))


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
