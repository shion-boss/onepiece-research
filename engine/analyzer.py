# -*- coding: utf-8 -*-
"""
試合後分析 (post-game analyzer)
================================

snapshot 履歴から各時点の盤面評価を計算し、 「ターニングポイント」(eval が大きく動いた瞬間)
を抽出する。 戦い方の振り返り・ミス箇所特定・デッキ理解の補助として使う。

分析は read-only。 既存 snapshot から派生するだけで再対戦は不要。

入力: snapshot dict のリスト (= state._build_snapshot 由来)。
   各 snapshot は { turn, turn_player_idx, phase, log, game_over, winner, event, players[2] }。
   players[i] は { life_count, hand_count, characters[], stages[], ...,
                   leader: { ..., attached_dons, power, keywords[] } }。

出力: GameAnalysis dataclass。
   - eval_series: 各 snapshot の me_idx 視点 score (正規化前 + tanh 正規化値)
   - turning_points: |eval delta| が threshold 以上の snapshot リスト
   - summary: 平均 eval / 最大リード / 最大劣勢 / 逆転勝ちか
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .eval import BoardEvalWeights, DEFAULT_WEIGHTS


@dataclass
class EvalPoint:
    snap_idx: int
    turn: int
    phase: str
    score: float           # 生スコア (重み付き合計)
    normalized: float      # tanh(score / 5000)
    log: str = ""


@dataclass
class TurningPoint:
    snap_idx: int
    turn: int
    delta: float           # 直前 snapshot からの score 変化
    side: str              # "self_gain" (=self視点で+) | "self_loss" (=self視点で-)
    log: str
    score_before: float
    score_after: float


@dataclass
class GameSummary:
    avg_score: float
    max_lead: float        # eval が最も高かった瞬間
    max_deficit: float     # eval が最も低かった瞬間
    final_score: float     # 終局時の score
    comeback: bool         # 一度劣勢 (norm <= -0.5) から逆転勝ち


@dataclass
class GameAnalysis:
    me_idx: int
    me_name: str
    opp_name: str
    winner: Optional[int]  # snap.players index
    eval_series: list[EvalPoint] = field(default_factory=list)
    turning_points: list[TurningPoint] = field(default_factory=list)
    summary: Optional[GameSummary] = None


# ----------------------------------------------------------------------------- #
# snapshot dict から evaluate (engine.eval は state object 用なので別ロジック)
# ----------------------------------------------------------------------------- #
def _player_metrics_from_snap(p: dict) -> dict:
    """snapshot dict 形式の players[i] から 8 種の生指標を抽出。"""
    chars = p.get("characters", [])
    stages = p.get("stages", [])
    leader = p["leader"]
    blocker = sum(1 for c in chars if "ブロッカー" in (c.get("keywords") or []))
    attached = (
        leader.get("attached_dons", 0)
        + sum(c.get("attached_dons", 0) for c in chars)
        + sum(s.get("attached_dons", 0) for s in stages)
    )
    active_chara = sum(
        1 for c in chars
        if not c.get("rested", False) and not c.get("summoning_sickness", False)
    )
    return {
        "life": p.get("life_count", 0),
        "field_count": len(chars),
        "field_power": sum(c.get("power", 0) for c in chars),
        "hand": p.get("hand_count", 0),
        "don": p.get("don_total", 0),
        "blocker": blocker,
        "attached_don": attached,
        "active_chara": active_chara,
    }


def _lethal_estimate_from_snap(self_p: dict, opp_p: dict) -> float:
    self_chars = self_p.get("characters", [])
    self_leader = self_p["leader"]
    opp_leader = opp_p["leader"]
    attackers: list[int] = []
    if not self_leader.get("rested", False):
        attackers.append(self_leader.get("power", 0))
    for c in self_chars:
        if not c.get("rested", False) and not c.get("summoning_sickness", False):
            attackers.append(c.get("power", 0))
    if not attackers:
        return 0.0
    opp_leader_p = opp_leader.get("power", 0)
    excesses = [max(0, p - opp_leader_p) for p in attackers]
    total_excess = sum(excesses)
    opp_defense = opp_p.get("life_count", 0) * 5000 + opp_p.get("hand_count", 0) * 1500
    if opp_defense == 0:
        return 1.0
    ratio = total_excess / opp_defense
    return 1.0 / (1.0 + math.exp(-2 * (ratio - 1)))


def _score_from_snap(
    snap: dict,
    me_idx: int,
    weights: BoardEvalWeights = DEFAULT_WEIGHTS,
) -> float:
    """snapshot dict から me_idx 視点のスコアを計算。"""
    if snap.get("game_over"):
        winner = snap.get("winner")
        if winner == me_idx:
            return float(weights.W_GAME_OVER)
        elif winner is not None:
            return float(-weights.W_GAME_OVER)
        return 0.0
    me = snap["players"][me_idx]
    opp = snap["players"][1 - me_idx]
    sm = _player_metrics_from_snap(me)
    om = _player_metrics_from_snap(opp)
    self_lethal = _lethal_estimate_from_snap(me, opp)
    opp_lethal = _lethal_estimate_from_snap(opp, me)
    w = weights
    return (
        (sm["life"] - om["life"]) * w.W_LIFE
        + (sm["field_count"] - om["field_count"]) * w.W_FIELD_COUNT
        + (sm["field_power"] - om["field_power"]) * w.W_FIELD_POWER
        + (sm["hand"] - om["hand"]) * w.W_HAND
        + (sm["don"] - om["don"]) * w.W_DON
        + (sm["blocker"] - om["blocker"]) * w.W_BLOCKER
        + (sm["attached_don"] - om["attached_don"]) * w.W_ATTACHED_DON
        + (sm["active_chara"] - om["active_chara"]) * w.W_ACTIVE_CHARA
        + (self_lethal - opp_lethal) * w.W_LETHAL
    )


# ----------------------------------------------------------------------------- #
# メイン分析関数
# ----------------------------------------------------------------------------- #
def analyze_game(
    snapshots: list[dict],
    me_idx: int,
    me_name: str,
    opp_name: str,
    turning_threshold: float = 3000.0,
    top_n_turning: int = 12,
    weights: BoardEvalWeights = DEFAULT_WEIGHTS,
) -> GameAnalysis:
    """snapshot 配列から GameAnalysis を生成。

    me_idx: 評価視点となるプレイヤー (= 自分。 通常 deck_a 側)
    me_name / opp_name: 表示用
    turning_threshold: |delta| がこれ以上なら turning point 候補
    top_n_turning: 結果に含める turning point 上位件数 (delta 絶対値の大きい順)
    """
    if not snapshots:
        return GameAnalysis(
            me_idx=me_idx, me_name=me_name, opp_name=opp_name, winner=None,
        )

    # eval_series 計算
    eval_series: list[EvalPoint] = []
    for i, snap in enumerate(snapshots):
        score = _score_from_snap(snap, me_idx, weights)
        norm = math.tanh(score / 5000.0)
        eval_series.append(
            EvalPoint(
                snap_idx=i,
                turn=snap.get("turn", 0),
                phase=snap.get("phase", "?"),
                score=score,
                normalized=norm,
                log=snap.get("log", ""),
            )
        )

    # turning points (隣接 snapshot の score 差を計算 → 大きい順)
    candidates: list[TurningPoint] = []
    for i in range(1, len(eval_series)):
        prev = eval_series[i - 1]
        cur = eval_series[i]
        # 終局直後の極端値 (±W_GAME_OVER) はノイズなので除外
        if abs(cur.score) >= 500_000 or abs(prev.score) >= 500_000:
            continue
        delta = cur.score - prev.score
        if abs(delta) >= turning_threshold:
            candidates.append(
                TurningPoint(
                    snap_idx=cur.snap_idx,
                    turn=cur.turn,
                    delta=delta,
                    side="self_gain" if delta > 0 else "self_loss",
                    log=cur.log,
                    score_before=prev.score,
                    score_after=cur.score,
                )
            )
    # 絶対値の大きい順、 同点なら snap_idx 早い順
    candidates.sort(key=lambda t: (-abs(t.delta), t.snap_idx))
    turning_points = candidates[:top_n_turning]
    # snap_idx 順に戻す (UI でリスト表示しやすいように時系列)
    turning_points.sort(key=lambda t: t.snap_idx)

    # summary
    finite_scores = [
        e.score for e in eval_series if abs(e.score) < 500_000
    ]
    if finite_scores:
        avg_score = sum(finite_scores) / len(finite_scores)
        max_lead = max(finite_scores)
        max_deficit = min(finite_scores)
    else:
        avg_score = max_lead = max_deficit = 0.0
    final_score = eval_series[-1].score if eval_series else 0.0

    # 逆転勝ち判定: 一度 normalized <= -0.5 (= -tanh ≈ score≦-2746) になり、 最終的に勝利
    comeback = False
    last_winner = snapshots[-1].get("winner")
    if last_winner == me_idx:
        for e in eval_series:
            if abs(e.score) < 500_000 and e.normalized <= -0.5:
                comeback = True
                break

    summary = GameSummary(
        avg_score=avg_score,
        max_lead=max_lead,
        max_deficit=max_deficit,
        final_score=final_score,
        comeback=comeback,
    )

    return GameAnalysis(
        me_idx=me_idx,
        me_name=me_name,
        opp_name=opp_name,
        winner=last_winner,
        eval_series=eval_series,
        turning_points=turning_points,
        summary=summary,
    )
