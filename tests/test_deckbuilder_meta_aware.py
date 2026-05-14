# -*- coding: utf-8 -*-
"""
deckbuilder meta-aware mode テスト (2026-05-14)
================================================

Phase 7 メタ分析 (db/meta_deck_analysis.json) を活用した自動構築の検証。
- _load_meta_hints が JSON から target 値を取得
- _meta_aware_curve_target が target_avg_cost で curve をシフト
- auto_build_deck(meta_aware=True) で role 優先採用
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.deck import CardRepository
from engine.deckbuilder import (
    _load_meta_hints,
    _meta_aware_curve_target,
    auto_build_deck,
)

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


# ─────────────────────────────────────────────────────
# _load_meta_hints
# ─────────────────────────────────────────────────────


def test_load_meta_hints_returns_targets():
    """meta hints が 期待する target を含む。"""
    hints = _load_meta_hints()
    # meta_deck_analysis.json が存在する場合のみ意味のあるテスト
    if not hints:
        return  # 分析未実行、 skip
    assert "target_avg_cost" in hints
    assert hints["target_avg_cost"] > 2.0  # 妥当な範囲
    assert hints["target_avg_cost"] < 6.0
    assert "target_blocker_count" in hints
    assert "positive_roles" in hints
    assert "negative_roles" in hints
    # 上位デッキ分析で得た 「役立つ役割」 が含まれてるか確認
    # (= recovery / draw / disruption いずれか)
    assert isinstance(hints["positive_roles"], list)
    assert isinstance(hints["negative_roles"], list)


# ─────────────────────────────────────────────────────
# _meta_aware_curve_target
# ─────────────────────────────────────────────────────


def test_curve_target_default_when_close_to_baseline():
    """target_avg_cost が baseline (= ~3.36) 近くなら baseline curve そのまま。"""
    curve = _meta_aware_curve_target(target_avg_cost=3.4)
    base = {1: 8, 2: 10, 3: 10, 4: 8, 5: 6, 6: 4, 7: 4}
    assert curve == base


def test_curve_target_higher_avg_shifts_to_high_cost():
    """target が高ければ 5-7 cost を増やす。"""
    curve = _meta_aware_curve_target(target_avg_cost=4.0)
    # 高コスト寄せ → 5-7 cost 計の枚数が baseline (= 14) より多い
    high_cost_sum = curve[5] + curve[6] + curve[7]
    base_high = 6 + 4 + 4  # 14
    assert high_cost_sum >= base_high


def test_curve_target_lower_avg_shifts_to_low_cost():
    """target が低ければ 1-2 cost を増やす。"""
    curve = _meta_aware_curve_target(target_avg_cost=2.5)
    # 低コスト寄せ → 1-2 cost 計の枚数が baseline (= 18) より多い
    low_cost_sum = curve[1] + curve[2]
    base_low = 8 + 10  # 18
    assert low_cost_sum >= base_low


def test_curve_target_totals_50():
    """curve_target の合計は常に 50。"""
    for target_avg in [2.5, 3.0, 3.5, 4.0, 4.5]:
        curve = _meta_aware_curve_target(target_avg)
        assert sum(curve.values()) == 50, \
            f"target_avg={target_avg} で curve total != 50: {curve}"


# ─────────────────────────────────────────────────────
# auto_build_deck meta_aware
# ─────────────────────────────────────────────────────


def test_auto_build_deck_meta_aware_smoke():
    """meta_aware=True で 50 枚 deck を生成、 エラーなし。"""
    repo = _repo()
    # 紫エネル leader で生成
    deck = auto_build_deck(
        leader_id="OP15-058",
        repo=repo,
        meta_aware=True,
        rng=random.Random(42),
    )
    assert len(deck.main) == 50
    # validate
    deck.validate()


def test_auto_build_deck_meta_aware_avg_cost_close_to_target():
    """meta_aware で生成された deck の avg_cost が target に近い。"""
    repo = _repo()
    deck = auto_build_deck(
        leader_id="OP15-058",
        repo=repo,
        meta_aware=True,
        rng=random.Random(42),
    )
    avg = sum(c.cost for c in deck.main) / 50
    hints = _load_meta_hints()
    if hints:
        target = hints["target_avg_cost"]
        # 厳密一致は無理 (= curve baseline 既定なら baseline 平均)、 緩い範囲チェック
        assert abs(avg - target) < 1.5, f"avg={avg}, target={target}"


def test_auto_build_deck_default_mode_unchanged():
    """meta_aware=False (default) で旧挙動を維持。"""
    repo = _repo()
    deck = auto_build_deck(
        leader_id="OP15-058",
        repo=repo,
        meta_aware=False,
        rng=random.Random(42),
    )
    assert len(deck.main) == 50


def test_auto_build_deck_no_meta_data_falls_back():
    """meta_aware=True でも meta data 不在なら baseline で動作 (= fallback)。"""
    # 既存 meta data はあるはずだが、 fallback コード経路の確認
    # → 実際には _load_meta_hints が空辞書を返すケース
    # ここでは smoke test のみ
    repo = _repo()
    deck = auto_build_deck(
        leader_id="OP15-058",
        repo=repo,
        meta_aware=True,
    )
    assert len(deck.main) == 50


# ─────────────────────────────────────────────────────
# Phase 7L 戦略制約
# ─────────────────────────────────────────────────────


def test_meta_aware_enforces_min_characters():
    """meta_aware=True で キャラ最低 38 枚保証。"""
    from engine.core import Category
    repo = _repo()
    deck = auto_build_deck(
        leader_id="OP15-058",
        repo=repo,
        meta_aware=True,
        rng=random.Random(42),
    )
    n_chars = sum(1 for c in deck.main if c.category == Category.CHARACTER)
    assert n_chars >= 38, f"キャラ {n_chars} < 38 (= 上級者最低 推奨)"


def test_meta_aware_enforces_min_counter_cards():
    """meta_aware=True で counter 持ち最低 30 枚保証。"""
    repo = _repo()
    deck = auto_build_deck(
        leader_id="OP15-058",
        repo=repo,
        meta_aware=True,
        rng=random.Random(42),
    )
    n_counter = sum(1 for c in deck.main if c.counter > 0)
    assert n_counter >= 30, f"counter 持ち {n_counter} < 30 (= 推奨)"


def test_meta_aware_excludes_banned_cards():
    """meta_aware=True で 禁止カード が含まれない。"""
    from engine.deckbuilder import _load_banlist_ids
    from engine.deck import _base_id
    repo = _repo()
    banned = _load_banlist_ids()
    deck = auto_build_deck(
        leader_id="OP15-058",
        repo=repo,
        meta_aware=True,
    )
    for c in deck.main:
        bid = _base_id(c.card_id)
        assert bid not in banned and c.card_id not in banned, \
            f"禁止カード {c.card_id} が含まれてる"


def test_validate_deck_consistency_smoke():
    """validate_deck_consistency が正常 deck で warnings 空 (or 小限)。"""
    from engine.deckbuilder import validate_deck_consistency
    repo = _repo()
    deck = auto_build_deck(
        leader_id="OP15-058",
        repo=repo,
        meta_aware=True,
    )
    warnings = validate_deck_consistency(deck)
    # 制約満たすなら 重大警告無し (= 「禁止」「枚数」 等)
    critical = [w for w in warnings if "禁止" in w or "枚数" in w or "上限超過" in w]
    assert not critical, f"重大警告: {critical}"


def test_validate_detects_low_character_count():
    """validate_deck_consistency が キャラ < 38 を検出。"""
    from engine.deckbuilder import validate_deck_consistency
    from engine.deck import DeckList
    repo = _repo()
    # 全部 イベント のデッキを偽造 (= キャラ 0)
    leader = repo.get("OP15-058")
    event_card = repo.get("OP01-090")  # 何らかの event
    fake = DeckList(
        name="EventOnly",
        leader=leader,
        main=[event_card] * 50,
    )
    warnings = validate_deck_consistency(fake)
    assert any("キャラ" in w for w in warnings), f"キャラ不足 警告がない: {warnings}"
