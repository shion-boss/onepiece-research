# -*- coding: utf-8 -*-
"""Plan G (= 2026-05-18 夜): turn-plan-directed planning。

人間プレイヤーは デッキ構築時 「T1: 2 コスト展開」「T4: 中堅展開」「T6: フィニッシャー」
という ターン毎の 理想盤面プラン を 持つ。 現状 AI は 評価関数 argmax (= reactive)
だが、 ターン目標 (= proactive goal) を 持たない。

decks/<slug>.analysis.json の ideal_moves を 読んで、 現 turn の candidate_cards を
play する action に bonus を 加算する。

ideal_moves format:
  [{"turn": 1, "description": "...", "candidate_cards": ["OP13-016", ...]},
   {"turn": 4, "description": "...", "candidate_cards": ["OP10-045", ...]}]

W_TURN_PLAN 重みは ONEPIECE_TURN_PLAN_W env で 制御 (= default 0 で 無効)。
"""

from __future__ import annotations

from typing import Optional


def get_turn_plan_candidates(
    deck_analysis: Optional[dict], turn_number: int
) -> set[str]:
    """deck_analysis から 現 turn (= 近傍含む) の candidate cards を 取得。

    厳密一致だけだと turn 数 sparse (= 1, 4, 6 等) で 大半 turn で 空。
    なので 「直近 ideal_moves の candidate」 を 適用 (= turn 3 → turn 1 の plan を 適用)。
    """
    if not deck_analysis or not isinstance(deck_analysis, dict):
        return set()
    ideal = deck_analysis.get("ideal_moves", [])
    if not ideal:
        return set()

    # 現 turn 以下の 最新 plan を 採用 (= 「該当 turn から 進行中」 として)
    best_plan = None
    for m in ideal:
        m_turn = m.get("turn", 0)
        if m_turn <= turn_number:
            if best_plan is None or m_turn > best_plan.get("turn", 0):
                best_plan = m
    if best_plan is None:
        # まだ 最初の plan turn より 前 → 最も 早い plan を 適用
        best_plan = min(ideal, key=lambda m: m.get("turn", 99))

    cards = best_plan.get("candidate_cards", [])
    return set(c for c in cards if c)
