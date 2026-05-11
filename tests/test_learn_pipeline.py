# -*- coding: utf-8 -*-
"""学習パイプラインの helper 関数 + replay 永続化 (SQLite) の通し動作テスト。

実 matchup を回すと時間がかかるので、 重い部分 (= 全 N×N) はテストせず、
- replay_recorder の save/load/list/prune (SQLite)
- learn_ai_params の helper (_winrate_to_tier / _prediction_accuracy)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.replay_recorder import (
    DEFAULT_MAX_PER_PAIR,
    clear_all,
    count_replays,
    list_replays,
    load_replay,
    save_replay,
)


def test_save_and_load_replay(tmp_path):
    """1 試合保存 → 読み込み round trip。"""
    db = tmp_path / "replays.sqlite"
    rid = save_replay(
        deck_a="deck_a",
        deck_b="deck_b",
        game_idx=0,
        winner_for_deck_a=1,
        first_player=0,
        turns=8,
        log=["T1 P0: マリガン"],
        snapshots=[{"turn": 1}],
        seed=42,
        db_path=db,
    )
    assert isinstance(rid, int)
    loaded = load_replay(rid, db_path=db)
    assert loaded["meta"]["deck_a"] == "deck_a"
    assert loaded["meta"]["winner_for_deck_a"] == 1
    assert loaded["meta"]["id"] == rid
    assert loaded["log"] == ["T1 P0: マリガン"]
    assert loaded["snapshots"] == [{"turn": 1}]


def test_list_replays_filters_by_pair(tmp_path):
    """deck_a/deck_b を指定すると該当ペアのみ返す。"""
    db = tmp_path / "replays.sqlite"
    for i in range(2):
        save_replay("deck_x", "deck_y", i, 0, 0, 5, [], [], 0, db_path=db)
    for i in range(3):
        save_replay("deck_x", "deck_z", i, 1, 0, 5, [], [], 0, db_path=db)
    xy = list_replays("deck_x", "deck_y", db_path=db)
    assert len(xy) == 2
    xz = list_replays("deck_x", "deck_z", db_path=db)
    assert len(xz) == 3
    # deck_a だけ指定 → x を含むペア全て
    all_x = list_replays("deck_x", db_path=db)
    assert len(all_x) == 5


def test_list_replays_only_losses_for(tmp_path):
    """only_losses_for で特定デッキの敗北だけ返す。"""
    db = tmp_path / "replays.sqlite"
    # deck_a "alpha" が勝つ (winner_for_deck_a=0) → beta 敗北
    save_replay("alpha", "beta", 0, 0, 0, 5, [], [], 0, db_path=db)
    save_replay("alpha", "beta", 1, 0, 0, 5, [], [], 0, db_path=db)
    # deck_a "alpha" が負ける (winner_for_deck_a=1) → alpha 敗北
    save_replay("alpha", "beta", 2, 1, 0, 5, [], [], 0, db_path=db)
    losses_alpha = list_replays(only_losses_for="alpha", db_path=db)
    assert len(losses_alpha) == 1
    losses_beta = list_replays(only_losses_for="beta", db_path=db)
    assert len(losses_beta) == 2


def test_prune_keeps_only_max(tmp_path):
    """max_per_pair を超えたら古いものから削除される。"""
    db = tmp_path / "replays.sqlite"
    for i in range(7):
        save_replay("a", "b", i, 0, 0, 5, [], [], 0,
                    db_path=db, max_per_pair=5)
    files = list_replays("a", "b", db_path=db)
    assert len(files) == 5


def test_count_and_clear(tmp_path):
    db = tmp_path / "replays.sqlite"
    for i in range(4):
        save_replay("a", "b", i, 0, 0, 5, [], [], 0, db_path=db)
    assert count_replays(db_path=db) == 4
    clear_all(db_path=db)
    assert count_replays(db_path=db) == 0


# ---- learn_ai_params helper unit tests ----


def test_winrate_to_tier():
    from scripts.learn_ai_params import _winrate_to_tier
    thresholds = {"S": 0.85, "A": 0.75, "B": 0.50, "C": 0.25, "D": 0.0}
    assert _winrate_to_tier(0.9, thresholds) == "S"
    assert _winrate_to_tier(0.8, thresholds) == "A"
    assert _winrate_to_tier(0.6, thresholds) == "B"
    assert _winrate_to_tier(0.3, thresholds) == "C"
    assert _winrate_to_tier(0.1, thresholds) == "D"


def test_prediction_accuracy():
    from scripts.learn_ai_params import _prediction_accuracy
    matrix = {
        "avg_winrates": {
            "deck1": 0.80,  # A 予測
            "deck2": 0.20,  # D 予測
        },
    }
    tier_truth = {
        "tier_thresholds": {"S": 0.85, "A": 0.75, "B": 0.50, "C": 0.25, "D": 0.0},
        "tiers": {
            "deck1": {"tier": "A"},
            "deck2": {"tier": "D"},
        },
    }
    assert _prediction_accuracy(matrix, tier_truth) == 1.0
    # 1 件外れたら 0.5
    matrix["avg_winrates"]["deck1"] = 0.30  # C 予測 ≠ A truth
    assert _prediction_accuracy(matrix, tier_truth) == 0.5


def test_winrate_variance_penalty():
    from scripts.learn_ai_params import _winrate_variance_penalty
    matrix = {"avg_winrates": {"d1": 0.50, "d2": 0.50}}
    tier_truth = {
        "tiers": {
            "d1": {"expected_winrate": 0.50},
            "d2": {"expected_winrate": 0.50},
        },
    }
    assert _winrate_variance_penalty(matrix, tier_truth) == 0.0
    # 差があるとペナルティ > 0
    matrix["avg_winrates"]["d1"] = 0.80
    pen = _winrate_variance_penalty(matrix, tier_truth)
    assert pen > 0


def test_apply_param_values_creates_copy():
    from scripts.learn_ai_params import _apply_param_values
    from engine.ai_params import AIParams
    base = AIParams()
    new = _apply_param_values(base, {
        "activate_main_min_payoff_global": 1000,
        "w_life": 2000,
        "non_existent_field": 999,  # 無視される
    })
    assert new.activate_main_min_payoff_global == 1000
    assert new.w_life == 2000
    # base は不変
    assert base.activate_main_min_payoff_global == 0
    assert base.w_life == 1500
