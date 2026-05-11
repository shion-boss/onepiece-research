# -*- coding: utf-8 -*-
"""
盤面評価関数 (9 指標)
=====================

`web/src/lib/boardEval.ts` と公式・重みを同期させた評価関数。

- 5 base 指標: ライフ / 場のキャラ数 / 場のパワー合計 / 手札 / DON 総数
- 4 拡張指標: ブロッカー数 / 付与 DON 合計 / アクティブキャラ数 / リーサル兆候

`compute_score` で me_idx 視点のスコアを返す (差分 = self - opp)。
`compute_breakdown` で内訳辞書 (UI / analyzer 両方で使用)。

LookaheadAI / MCTSAI / EvalGreedyAI は本モジュールを呼んで意思決定する。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import hand_estimator
from .core import GameState, Player


@dataclass
class BoardEvalWeights:
    """評価指標の重み。 default は LookaheadAI と boardEval.ts 由来の経験的値。"""

    W_LIFE: int = 1500
    W_FIELD_COUNT: int = 1200
    W_FIELD_POWER: int = 1
    W_HAND: int = 250
    W_DON: int = 200
    # 拡張指標
    W_BLOCKER: int = 800
    W_ATTACHED_DON: int = 400
    W_ACTIVE_CHARA: int = 600
    W_LETHAL: int = 5000
    # ゲーム終了 (decisive)
    W_GAME_OVER: int = 1_000_000


_AI_PARAMS_PATH = Path(__file__).resolve().parent.parent / "db" / "ai_params.json"


def _load_weights_from_ai_params() -> BoardEvalWeights:
    """db/ai_params.json から重みをロード。

    ai_params.py には依存しない (循環 import 回避のため直接 json 読み)。
    ファイル不在 / 形式不正なら dataclass デフォルトに fallback。
    """
    if not _AI_PARAMS_PATH.exists():
        return BoardEvalWeights()
    try:
        data = json.loads(_AI_PARAMS_PATH.read_text(encoding="utf-8"))
        p = data.get("params", {})
        return BoardEvalWeights(
            W_LIFE=int(p.get("w_life", 1500)),
            W_FIELD_COUNT=int(p.get("w_field_count", 1200)),
            W_FIELD_POWER=int(p.get("w_field_power", 1)),
            W_HAND=int(p.get("w_hand", 250)),
            W_DON=int(p.get("w_don", 200)),
            W_BLOCKER=int(p.get("w_blocker", 800)),
            W_ATTACHED_DON=int(p.get("w_attached_don", 400)),
            W_ACTIVE_CHARA=int(p.get("w_active_chara", 600)),
            W_LETHAL=int(p.get("w_lethal", 5000)),
        )
    except Exception:
        return BoardEvalWeights()


DEFAULT_WEIGHTS = _load_weights_from_ai_params()


def reload_default_weights() -> BoardEvalWeights:
    """学習で db/ai_params.json が更新された後、 メモリ上の DEFAULT_WEIGHTS を再ロード。"""
    global DEFAULT_WEIGHTS
    DEFAULT_WEIGHTS = _load_weights_from_ai_params()
    return DEFAULT_WEIGHTS


def _player_metrics(p: Player) -> dict:
    """Player から 8 種の生指標を抽出 (lethal を除く)。"""
    blocker = sum(
        1 for c in p.characters if c.has_keyword_active("ブロッカー")
    )
    attached = (
        p.leader.attached_dons
        + sum(c.attached_dons for c in p.characters)
        + sum(s.attached_dons for s in p.stages)
    )
    active_chara = sum(
        1
        for c in p.characters
        if not c.rested and not c.summoning_sickness
    )
    return {
        "life": len(p.life),
        "field_count": len(p.characters),
        "field_power": sum(c.power for c in p.characters),
        "hand": len(p.hand),
        "don": p.total_don,
        "blocker": blocker,
        "attached_don": attached,
        "active_chara": active_chara,
    }


def lethal_estimate(state: GameState, me_idx: int) -> float:
    """リーサル可能性を 0.0〜1.0 で返す。 boardEval.ts と同公式。

    me の「次ターン総打点」(active leader + active chars) と opp の防御力
    (life × 5000 + 期待カウンター総量) を比較し、 sigmoid でスケール。

    期待カウンター総量は `hand_estimator.expected_counter_total` で算出:
    opp.deck + opp.hand プール上の平均カウンター値 × 手札枚数。
    トラッシュ済カウンター持ちは自動的に除外される。
    """
    self_p = state.players[me_idx]
    opp_p = state.players[1 - me_idx]
    attackers: list[int] = []
    if not self_p.leader.rested:
        attackers.append(self_p.leader.power)
    for c in self_p.characters:
        if not c.rested and not c.summoning_sickness:
            attackers.append(c.power)
    if not attackers:
        return 0.0
    opp_leader_p = opp_p.leader.power
    excesses = [max(0, p - opp_leader_p) for p in attackers]
    total_excess = sum(excesses)
    opp_counter_total = hand_estimator.expected_counter_total(state, 1 - me_idx)
    opp_defense = len(opp_p.life) * 5000 + opp_counter_total
    if opp_defense == 0:
        return 1.0
    ratio = total_excess / opp_defense
    return 1.0 / (1.0 + math.exp(-2 * (ratio - 1)))


def compute_breakdown(
    state: GameState,
    me_idx: int,
    weights: Optional[BoardEvalWeights] = None,
) -> dict:
    """各指標の内訳を返す。

    返り値構造:
      {
        "life": {"self": int, "opp": int, "diff": int, "contribution": int},
        "field_count": {...}, "field_power": {...}, "hand": {...},
        "don": {...}, "blocker": {...}, "attached_don": {...},
        "active_chara": {...}, "lethal": {...}
      }
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS
    me = state.players[me_idx]
    opp = state.players[1 - me_idx]
    sm = _player_metrics(me)
    om = _player_metrics(opp)

    self_lethal = lethal_estimate(state, me_idx)
    opp_lethal = lethal_estimate(state, 1 - me_idx)

    metrics = [
        ("life", sm["life"], om["life"], weights.W_LIFE),
        ("field_count", sm["field_count"], om["field_count"], weights.W_FIELD_COUNT),
        ("field_power", sm["field_power"], om["field_power"], weights.W_FIELD_POWER),
        ("hand", sm["hand"], om["hand"], weights.W_HAND),
        ("don", sm["don"], om["don"], weights.W_DON),
        ("blocker", sm["blocker"], om["blocker"], weights.W_BLOCKER),
        ("attached_don", sm["attached_don"], om["attached_don"], weights.W_ATTACHED_DON),
        ("active_chara", sm["active_chara"], om["active_chara"], weights.W_ACTIVE_CHARA),
        ("lethal", self_lethal, opp_lethal, weights.W_LETHAL),
    ]
    out = {}
    for name, sv, ov, w in metrics:
        diff = sv - ov
        out[name] = {
            "self": sv,
            "opp": ov,
            "diff": diff,
            "contribution": diff * w,
        }
    return out


def compute_score(
    state: GameState,
    me_idx: int,
    weights: Optional[BoardEvalWeights] = None,
) -> float:
    """me_idx 視点の盤面スコア (= self_score - opp_score)。

    ゲーム終了時は ±W_GAME_OVER で確定値。 それ以外は 9 指標の重み付き差分合計。
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS
    if state.game_over:
        if state.winner == me_idx:
            return float(weights.W_GAME_OVER)
        elif state.winner is not None:
            return float(-weights.W_GAME_OVER)
        return 0.0  # 引き分け

    breakdown = compute_breakdown(state, me_idx, weights)
    return sum(m["contribution"] for m in breakdown.values())


def compute_self_opp_scores(
    state: GameState,
    me_idx: int,
    weights: Optional[BoardEvalWeights] = None,
) -> tuple[float, float]:
    """self_score, opp_score を別個に返す (UI / analyzer の表示用)。"""
    if weights is None:
        weights = DEFAULT_WEIGHTS
    me = state.players[me_idx]
    opp = state.players[1 - me_idx]
    sm = _player_metrics(me)
    om = _player_metrics(opp)
    self_lethal = lethal_estimate(state, me_idx)
    opp_lethal = lethal_estimate(state, 1 - me_idx)
    w = weights

    def sum_side(m: dict, lethal: float) -> float:
        return (
            m["life"] * w.W_LIFE
            + m["field_count"] * w.W_FIELD_COUNT
            + m["field_power"] * w.W_FIELD_POWER
            + m["hand"] * w.W_HAND
            + m["don"] * w.W_DON
            + m["blocker"] * w.W_BLOCKER
            + m["attached_don"] * w.W_ATTACHED_DON
            + m["active_chara"] * w.W_ACTIVE_CHARA
            + lethal * w.W_LETHAL
        )

    return sum_side(sm, self_lethal), sum_side(om, opp_lethal)


def normalized_score(score: float, scale: float = 5000.0) -> float:
    """生スコアを -1.0 〜 +1.0 に正規化。 boardEval.ts と同 (tanh)。"""
    return math.tanh(score / scale)
