# -*- coding: utf-8 -*-
"""
カード意図 metadata (Phase Intent)
====================================

各カードに「どういう盤面で使うべきか (= play_when)」 と
「使うべきでない盤面 (= play_avoid)」 を JSON で定義し、 AI がそれを参照して
選択判断を強化する。

公開 API:
- load_intents(path=None) -> dict
- compute_intent_score(card_id, state, me, opp, intents=None) -> int
- evaluate_condition(cond, me, opp, state) -> bool

データソース: db/card_intents.json (= 重要カードのみ手動 annotate、 4,518 全
カード必須ではない)。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .core import GameState, Player


_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "db" / "card_intents.json"

_intents_cache: Optional[dict] = None


def load_intents(
    path: str | Path | None = None, *, force_reload: bool = False,
) -> dict:
    """db/card_intents.json をロード (cache 付き)。"""
    global _intents_cache
    if _intents_cache is not None and not force_reload and path is None:
        return _intents_cache
    p = Path(path) if path else _DEFAULT_PATH
    if not p.exists():
        out: dict = {}
    else:
        raw = json.loads(p.read_text(encoding="utf-8"))
        out = {k: v for k, v in raw.items() if not k.startswith("_") and isinstance(v, dict)}
    if path is None:
        _intents_cache = out
    return out


# ============================================================================ #
# Condition 評価 vocabulary
# ============================================================================ #

def _eval_int_cond(actual: int, key: str, value: int) -> bool:
    """key suffix (_le/_ge/_eq) で int 比較。"""
    if key.endswith("_le"):
        return actual <= value
    if key.endswith("_ge"):
        return actual >= value
    if key.endswith("_eq"):
        return actual == value
    return False


def evaluate_condition(
    cond: dict,
    me: Player,
    opp: Player,
    state: GameState,
) -> bool:
    """1 つの condition dict を評価。 全 key が AND 条件。

    対応 key 一覧:
    - opp_chara_count_le/ge/eq    : 相手キャラ数
    - opp_chara_cost_ge           : 相手場に cost ≥ N のキャラが居るか
    - opp_chara_with_cost_ge_count: 相手場の cost ≥ N キャラ数 ≥ M (= dict {cost, count})
    - self_chara_count_le/ge/eq   : 自キャラ数
    - self_don_le/ge/eq           : 自分の合計ドン (active + rested + attached)
    - self_don_active_le/ge/eq    : アクティブ ドンのみ
    - self_life_le/ge/eq          : 自ライフ枚数
    - opp_life_le/ge/eq           : 相手ライフ枚数
    - self_hand_le/ge/eq          : 自手札数
    - opp_hand_le/ge/eq           : 相手手札数
    - turn_le/ge/eq               : ターン数
    - self_chara_with_feature     : 自場に特定特徴を持つキャラがいる ("特徴名")
    - leader_feature_contains     : 自リーダーが特定特徴を持つ ("特徴名")
    - self_first_player           : 自分が先攻 (bool)
    """
    for key, value in cond.items():
        if key in ("boost", "penalty", "_note"):
            continue
        try:
            if not _eval_one_key(key, value, me, opp, state):
                return False
        except (AttributeError, TypeError, KeyError, ValueError):
            return False
    return True


def _eval_one_key(
    key: str, value, me: Player, opp: Player, state: GameState,
) -> bool:
    # opp_chara_*
    if key.startswith("opp_chara_count_"):
        return _eval_int_cond(len(opp.characters), key, int(value))
    if key == "opp_chara_cost_ge":
        return any(c.card.cost >= int(value) for c in opp.characters)
    if key == "opp_chara_with_cost_ge_count":
        cost = int(value.get("cost", 0))
        n = int(value.get("count", 1))
        return sum(1 for c in opp.characters if c.card.cost >= cost) >= n
    # self_chara_*
    if key.startswith("self_chara_count_"):
        return _eval_int_cond(len(me.characters), key, int(value))
    if key == "self_chara_with_feature":
        feat = str(value)
        return any(feat in c.card.features for c in me.characters)
    # don
    if key.startswith("self_don_active_"):
        return _eval_int_cond(me.don_active, key, int(value))
    if key.startswith("self_don_"):
        total = (me.don_active + me.don_rested
                 + me.leader.attached_dons
                 + sum(c.attached_dons for c in me.characters))
        return _eval_int_cond(total, key, int(value))
    # life
    if key.startswith("self_life_"):
        return _eval_int_cond(len(me.life), key, int(value))
    if key.startswith("opp_life_"):
        return _eval_int_cond(len(opp.life), key, int(value))
    # hand
    if key.startswith("self_hand_"):
        return _eval_int_cond(len(me.hand), key, int(value))
    if key.startswith("opp_hand_"):
        return _eval_int_cond(len(opp.hand), key, int(value))
    # turn
    if key.startswith("turn_"):
        return _eval_int_cond(state.turn_number, key, int(value))
    # leader
    if key == "leader_feature_contains":
        return str(value) in me.leader.card.features
    if key == "self_first_player":
        # state.players[0] は first_player なので state.turn_player_idx == 0 が常に先攻
        # ただし mid-game で is_first_player を判定するには別の state 管理が必要
        # 簡易: turn_number 奇数 / 偶数 で判定 (= 1, 3, 5... が自分のターンなら先攻)
        is_first = (state.turn_number % 2 == 1) if state.turn_player_idx == 0 else (state.turn_number % 2 == 0)
        return bool(value) == is_first
    return False


# ============================================================================ #
# Intent score 計算
# ============================================================================ #

def compute_intent_score(
    card_id: str,
    state: GameState,
    me: Player,
    opp: Player,
    *,
    intents: Optional[dict] = None,
) -> int:
    """カード ID + 現状から intent score を返す (= 合計 boost - penalty)。

    Returns:
        int (= 通常 -100..+100、 metadata 無いカードは 0)
    """
    if intents is None:
        intents = load_intents()
    entry = intents.get(card_id)
    if not entry:
        # base_id でリトライ (= variant 共有)
        from .deck import _base_id
        entry = intents.get(_base_id(card_id))
    if not entry:
        return 0

    score = 0
    for cond in entry.get("play_when", []):
        if evaluate_condition(cond, me, opp, state):
            score += int(cond.get("boost", 10))
    for cond in entry.get("play_avoid", []):
        if evaluate_condition(cond, me, opp, state):
            score -= int(cond.get("penalty", 10))
    return score


def get_intent_summary(card_id: str, *, intents: Optional[dict] = None) -> Optional[dict]:
    """カードの intent metadata を取得 (= UI 表示等用)。"""
    if intents is None:
        intents = load_intents()
    entry = intents.get(card_id)
    if entry is None:
        from .deck import _base_id
        entry = intents.get(_base_id(card_id))
    return entry
