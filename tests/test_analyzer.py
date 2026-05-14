# -*- coding: utf-8 -*-
"""engine/analyzer.py のユニットテスト。"""

from __future__ import annotations

import random
from pathlib import Path

from engine.ai import GreedyAI
from engine.analyzer import analyze_game
from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.harness import run_matchup

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def test_analyze_game_returns_eval_series():
    """1 試合走らせて analyze_game が eval_series を生成できる"""
    repo = _repo()
    overlay = _overlay()
    d1 = DeckList.from_json(ROOT / "decks" / "cardrush_1424.json", repo)  # 紫エネル
    d2 = DeckList.from_json(ROOT / "decks" / "cardrush_1437.json", repo)  # 緑ミホーク
    rep = run_matchup(
        d1, d2, n_games=1, seed=42, effects_overlay=overlay,
        record_snapshots=True, enforce_rules=False,
        ai_factory_1=GreedyAI, ai_factory_2=GreedyAI,  # smoke なので fast を明示
    )
    snaps = rep.games[0].snapshots
    assert len(snaps) > 5, f"snapshot 数が極端に少ない ({len(snaps)})"

    analysis = analyze_game(
        snaps,
        me_idx=0,
        me_name=d1.name,
        opp_name=d2.name,
    )
    assert len(analysis.eval_series) == len(snaps)
    # 最後の snapshot は game_over → 極端値 (W_GAME_OVER 1_000_000)
    last = analysis.eval_series[-1]
    assert abs(last.score) == 1_000_000 or abs(last.score) < 500_000
    # 平均スコアは finite 値のみで計算される
    assert analysis.summary is not None
    assert abs(analysis.summary.avg_score) < 500_000


def test_analyze_game_turning_points():
    """ターニングポイント検出: 大きな delta が抽出される"""
    repo = _repo()
    overlay = _overlay()
    d1 = DeckList.from_json(ROOT / "decks" / "cardrush_1439.json", repo)  # 青黄ナミ
    d2 = DeckList.from_json(ROOT / "decks" / "cardrush_1424.json", repo)  # 紫エネル
    rep = run_matchup(
        d1, d2, n_games=1, seed=10, effects_overlay=overlay,
        record_snapshots=True, enforce_rules=False,
        ai_factory_1=GreedyAI, ai_factory_2=GreedyAI,
    )
    snaps = rep.games[0].snapshots
    analysis = analyze_game(
        snaps, me_idx=0, me_name=d1.name, opp_name=d2.name,
        turning_threshold=2000,
    )
    # turning points が存在し、 順序が snap_idx 昇順
    assert isinstance(analysis.turning_points, list)
    indices = [tp.snap_idx for tp in analysis.turning_points]
    assert indices == sorted(indices), "turning_points は snap_idx 昇順"
    # delta の絶対値が threshold 以上
    for tp in analysis.turning_points:
        assert abs(tp.delta) >= 2000


def test_analyze_game_empty_snapshots():
    """snapshot 空でも安全に空 GameAnalysis を返す"""
    analysis = analyze_game([], me_idx=0, me_name="A", opp_name="B")
    assert analysis.eval_series == []
    assert analysis.turning_points == []
    assert analysis.summary is None


def test_analyze_game_comeback_detection():
    """劣勢 (normalized <= -0.5) → 勝利 で comeback=True が立つ"""
    # 人工的なミニ snapshot 列
    fake_snap = lambda turn, my_life, op_life, my_chars, op_chars, game_over=False, winner=None: {
        "turn": turn, "turn_player_idx": 0, "phase": "MAIN", "log": f"T{turn}",
        "game_over": game_over, "winner": winner, "event": None,
        "players": [
            {
                "name": "A",
                "leader": {"instance_id": 1, "card_id": "OP01-001", "name": "L",
                           "rested": False, "attached_dons": 0,
                           "summoning_sickness": False, "power": 5000,
                           "base_power": 5000, "keywords": []},
                "characters": [
                    {"instance_id": 100 + i, "card_id": "OP01-013", "name": "C",
                     "rested": False, "attached_dons": 0,
                     "summoning_sickness": False, "power": 4000,
                     "base_power": 4000, "keywords": []}
                    for i in range(my_chars)
                ],
                "stages": [], "hand": [], "hand_count": 5,
                "life_count": my_life, "trash": [], "trash_count": 0,
                "deck_count": 30, "don_active": 5, "don_rested": 0,
                "don_total": 5, "don_remaining_in_deck": 5,
            },
            {
                "name": "B",
                "leader": {"instance_id": 2, "card_id": "OP01-001", "name": "L",
                           "rested": False, "attached_dons": 0,
                           "summoning_sickness": False, "power": 5000,
                           "base_power": 5000, "keywords": []},
                "characters": [
                    {"instance_id": 200 + i, "card_id": "OP01-013", "name": "C",
                     "rested": False, "attached_dons": 0,
                     "summoning_sickness": False, "power": 4000,
                     "base_power": 4000, "keywords": []}
                    for i in range(op_chars)
                ],
                "stages": [], "hand": [], "hand_count": 5,
                "life_count": op_life, "trash": [], "trash_count": 0,
                "deck_count": 30, "don_active": 5, "don_rested": 0,
                "don_total": 5, "don_remaining_in_deck": 5,
            },
        ],
    }
    snaps = [
        fake_snap(1, 4, 4, 1, 1),  # 互角
        fake_snap(2, 1, 4, 0, 3),  # 自分劣勢 (life 1, 場 0、 相手 3)
        fake_snap(3, 1, 0, 2, 1),  # 巻き返し
        fake_snap(4, 1, 0, 2, 1, game_over=True, winner=0),
    ]
    analysis = analyze_game(snaps, me_idx=0, me_name="A", opp_name="B")
    assert analysis.summary is not None
    assert analysis.summary.comeback is True, \
        f"劣勢→勝利で comeback=True のはず ({analysis.summary})"
