# -*- coding: utf-8 -*-
"""敗因タグ判定の純関数テスト + replay → 集計の通し動作。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.replay_recorder import save_replay
from engine.loss_classifier import (
    TAG_TO_PARAMS,
    _is_activate_main_overused,
    _is_attack_dispersed,
    _is_counter_starved,
    _is_defense_overreact,
    _is_finisher_starved,
    _is_life_burst_lost,
    _loser_idx_from_meta,
    aggregate_loss_tags,
    classify_loss,
    params_to_tune,
)
from engine.log_analyzer import GameStats


def _fake_stats(**kwargs) -> GameStats:
    """GameStats の defaults を埋めるヘルパ。"""
    defaults = dict(turns=15, won=False)
    defaults.update(kwargs)
    return GameStats(**defaults)


def test_loser_idx_from_meta_basic():
    # deck_a が勝ち (winner_for_deck_a=0), first_player=0
    # → deck_a 視点 P0, deck_b 視点 P1 → 敗者 = P1
    assert _loser_idx_from_meta({"winner_for_deck_a": 0, "first_player": 0}) == 1
    # deck_a が勝ち, first_player=1 (= deck_b 先攻)
    # → 敗者 deck_b は P0
    assert _loser_idx_from_meta({"winner_for_deck_a": 0, "first_player": 1}) == 0
    # 引き分け
    assert _loser_idx_from_meta({"winner_for_deck_a": -1}) is None


def test_activate_main_overused_detected():
    log = []
    # 10 ターン中 6 回起動メイン (= 60%) かつ 攻撃 5 回
    for t in range(1, 11):
        log.append(f"T{t} P1: end main")
        if t <= 6:
            log.append(f"T{t} P1:   起動メインコスト: ドン-2")
    stats = _fake_stats(turns=10, attacks_total=5)
    triggered, ev = _is_activate_main_overused(log, loser_idx=1, turns=10, stats=stats)
    assert triggered
    assert ev["am_cost_count"] == 6
    assert ev["am_rate"] >= 0.5


def test_activate_main_overused_not_triggered_when_attacks_high():
    # 起動メイン 6 回 + 攻撃 15 回 (= 攻撃も多くしてる = 浪費じゃない)
    log = []
    for t in range(1, 11):
        if t <= 6:
            log.append(f"T{t} P1:   起動メインコスト: ドン-1")
    stats = _fake_stats(turns=10, attacks_total=15)
    triggered, _ = _is_activate_main_overused(log, loser_idx=1, turns=10, stats=stats)
    assert not triggered


def test_life_burst_lost_detected():
    stats = _fake_stats(turns=8, first_hit_taken_turn=2)
    triggered, ev = _is_life_burst_lost(stats)
    assert triggered
    assert ev["first_hit_taken_turn"] == 2


def test_life_burst_lost_not_triggered_long_game():
    stats = _fake_stats(turns=15, first_hit_taken_turn=2)
    triggered, _ = _is_life_burst_lost(stats)
    assert not triggered


def test_counter_starved_detected():
    snapshots = [{"players": [{"hand": ["c1", "c2", "c3"]}, {"hand": ["c1"]}]}]
    stats = _fake_stats(
        turns=12, defense_counter_uses=5, defense_counter_amount=9000,
    )
    triggered, ev = _is_counter_starved(stats, snapshots, loser_idx=1)
    assert triggered
    assert ev["hand_left"] == 1


def test_attack_dispersed_detected():
    stats = _fake_stats(
        turns=10,
        attacks_total=10, attacks_blocked=7, attacks_life_hit=2,
    )
    triggered, ev = _is_attack_dispersed(stats)
    assert triggered
    assert ev["block_rate"] >= 0.5


def test_defense_overreact_detected():
    stats = _fake_stats(
        turns=10,
        opp_attacks_total=10, defense_counter_uses=9, attacks_total=5,
    )
    triggered, _ = _is_defense_overreact(stats)
    assert triggered


def test_finisher_starved_detected():
    stats = _fake_stats(turns=14, attacks_total=8)
    triggered, ev = _is_finisher_starved(stats, [], {})
    assert triggered
    assert ev["attack_per_turn"] < 1.0


def test_tag_to_params_mapping_complete():
    """全タグが TAG_TO_PARAMS に登録されていて、 valid AIParams フィールドを指す。"""
    from engine.ai_params import AIParams
    valid_fields = {f for f in AIParams.__dataclass_fields__.keys()}
    expected_tags = {
        "activate_main_overused",
        "finisher_starved",
        "life_burst_lost",
        "counter_starved",
        "attack_dispersed",
        "defense_overreact",
    }
    assert set(TAG_TO_PARAMS.keys()) == expected_tags
    for tag, params in TAG_TO_PARAMS.items():
        for p in params:
            assert p in valid_fields, f"{tag} -> {p} is not a valid AIParams field"


def test_params_to_tune_picks_top_tags():
    aggregate = {
        "tag_counts": {
            "activate_main_overused": 20,
            "counter_starved": 5,
            "attack_dispersed": 2,
        },
    }
    out = params_to_tune(aggregate, top_k=2)
    # top 2 タグ (activate_main_overused, counter_starved) の params がマージされる
    assert "activate_main_min_payoff_global" in out
    assert "defense_threshold_life_eq_2" in out
    # 3 番目以下は含まれない
    assert "attack_gap_tolerance_default" not in out


def _save_fake_replay(db_path: Path, log: list[str], meta: dict, snapshots: list = None) -> int:
    """テスト用の minimal replay を SQLite に保存し、 row id を返す。"""
    return save_replay(
        deck_a=meta.get("deck_a", "deck_a"),
        deck_b=meta.get("deck_b", "deck_b"),
        game_idx=meta.get("game_idx", 0),
        winner_for_deck_a=meta.get("winner_for_deck_a", 0),
        first_player=meta.get("first_player", 0),
        turns=meta.get("turns", 0),
        log=log,
        snapshots=snapshots or [],
        seed=meta.get("seed", 0),
        db_path=db_path,
    )


def test_classify_loss_integrates(tmp_path):
    """fake replay を classify_loss にかけて タグが付与される。"""
    log = [
        "T1 P0: マリガン: deck_a 手札を引き直し",
        "T2 P1:   起動メインコスト: ドン-2",
        "T3 P1:   起動メインコスト: ドン-2",
        "T4 P1:   起動メインコスト: ドン-2",
        "T5 P1:   起動メインコスト: ドン-2",
        "T6 P1:   起動メインコスト: ドン-2",
        "T7 P0: atk: leader(P=5000) -> leader(P=5000)",
        "T7 P0:   hit: P1",
    ]
    meta = {
        "deck_a": "winner_deck",
        "deck_b": "loser_deck",
        "winner_for_deck_a": 0,
        "first_player": 0,
        "turns": 7,
    }
    db = tmp_path / "replays.sqlite"
    rid = _save_fake_replay(db, log, meta)
    result = classify_loss(rid, db_path=db)
    assert result.loser_deck == "loser_deck"
    assert "activate_main_overused" in result.tags


def test_aggregate_loss_tags(tmp_path):
    """複数 replay を集計してタグ rate が返る。"""
    db = tmp_path / "replays.sqlite"
    rids: list[int] = []
    # 3 試合: 全部起動メイン乱用パターン
    for i in range(3):
        log = []
        for t in range(1, 8):
            if t <= 5:
                log.append(f"T{t} P1:   起動メインコスト: ドン-2")
        meta = {
            "deck_a": "winner",
            "deck_b": "loser",
            "winner_for_deck_a": 0,
            "first_player": 0,
            "turns": 7,
        }
        rids.append(_save_fake_replay(db, log, meta))

    aggregate = aggregate_loss_tags(rids, db_path=db)
    assert aggregate["total_losses"] == 3
    assert aggregate["tag_counts"].get("activate_main_overused", 0) >= 1
    assert "loser" in aggregate["loser_decks"]
