# -*- coding: utf-8 -*-
"""
DeepPlanningAI (Phase 1) テスト
==============================

- Step 1A: max_turns=1 で後方互換 (= 旧 _is_terminal 挙動)
- Step 1B: max_turns=2 で opp ターンを sim 経由で完走、 plan が opp turn を跨いで生成される
- Step 1D (= 後で追加): _compute_adaptive_params がターン/信頼度ベースで切替
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from engine.ai import GreedyAI
from engine.deck import CardRepository, DeckList
from engine.game import setup_game, play_until_main
from engine.harness import load_effect_overlay
from engine.plan_search import _is_terminal, search_turn_plan

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


@pytest.fixture(scope="module")
def overlay() -> dict:
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _load_deck(repo: CardRepository, slug: str) -> DeckList:
    p = ROOT / "decks" / f"{slug}.json"
    return DeckList.from_json(p, repo)


@pytest.fixture(scope="module")
def state_at_main(repo, overlay):
    """T1 自分 MAIN 直前まで進めた state を返す (= cardrush 任意ペア)。"""
    deck1 = _load_deck(repo, "cardrush_1342")
    deck2 = _load_deck(repo, "cardrush_1385")
    state = setup_game(
        deck1, deck2, rng=random.Random(42), first_player=0,
        effects_overlay=overlay,
    )
    play_until_main(state)
    return state


# ─────────────────────────────────────────────────────
# Step 1A: max_turns=1 後方互換
# ─────────────────────────────────────────────────────


def test_is_terminal_backward_compat_max_turns_1(state_at_main):
    """max_turns=1 で旧挙動: phase != MAIN または turn_player_idx 切替で terminal。"""
    state = state_at_main
    me_idx = state.turn_player_idx

    # 自分 MAIN 中 → not terminal
    assert _is_terminal(state, me_idx, start_turn_number=state.turn_number, max_turns=1) is False

    # game_over → terminal
    state.game_over = True
    assert _is_terminal(state, me_idx, start_turn_number=state.turn_number, max_turns=1) is True
    state.game_over = False


def test_is_terminal_multi_turn_uses_turn_delta(state_at_main):
    """max_turns=2 で turn_number delta による判定。"""
    state = state_at_main
    me_idx = state.turn_player_idx
    start = state.turn_number

    # delta=0 → not terminal
    assert _is_terminal(state, me_idx, start_turn_number=start, max_turns=2) is False

    # delta=2 まで進めた仮想 state なら terminal
    # (= 直接 turn_number 操作で検証、 実 state は変えない)
    fake_turn = start + 2
    state.turn_number = fake_turn
    assert _is_terminal(state, me_idx, start_turn_number=start, max_turns=2) is True
    # 復元
    state.turn_number = start


def test_search_turn_plan_max_turns_1_backward_compat(state_at_main):
    """max_turns=1 (= default) で旧挙動: 自ターン内で plan を返す。"""
    state = state_at_main
    ai_opp = GreedyAI(rng=random.Random(0))

    plan, score = search_turn_plan(
        state, ai_opp, beam_width=4, max_depth=6, max_turns=1
    )
    # plan は空でなく、 score は finite
    assert plan is not None
    assert score != -float("inf")


# ─────────────────────────────────────────────────────
# Step 1B: max_turns=2 で opp turn 自動 sim
# ─────────────────────────────────────────────────────


def test_search_turn_plan_multi_turn_runs_without_error(state_at_main):
    """max_turns=2 で opp 自動 sim 経由で plan が返る (= エラー無し動作確認)。"""
    state = state_at_main
    ai_opp = GreedyAI(rng=random.Random(0))
    ai_self = GreedyAI(rng=random.Random(0))

    plan, score = search_turn_plan(
        state, ai_opp, beam_width=3, max_depth=8,
        max_turns=2, ai_self=ai_self,
    )
    # plan は空でなく、 score は finite
    assert plan is not None
    assert score != -float("inf")


# ─────────────────────────────────────────────────────
# Step 1D: _compute_adaptive_params
# ─────────────────────────────────────────────────────


def test_adaptive_params_early_turn(state_at_main):
    """T1-2 で旧挙動 (4, 1, 6) を返す。"""
    from engine.ai import PlanningAI

    ai = PlanningAI(rng=random.Random(0))
    state = state_at_main

    state.turn_number = 1
    beam, max_turns, per_turn_depth = ai._compute_adaptive_params(state)
    assert (beam, max_turns, per_turn_depth) == (4, 1, 6), \
        f"T1: 期待 (4,1,6), 実 {(beam, max_turns, per_turn_depth)}"

    state.turn_number = 2
    assert ai._compute_adaptive_params(state) == (4, 1, 6)


def test_adaptive_params_mid_turn(state_at_main):
    """T3-5 で 2 ターン読み (4, 2, 5)。"""
    from engine.ai import PlanningAI

    ai = PlanningAI(rng=random.Random(0))
    state = state_at_main

    for t in (3, 4, 5):
        state.turn_number = t
        beam, max_turns, per_turn_depth = ai._compute_adaptive_params(state)
        assert (beam, max_turns, per_turn_depth) == (4, 2, 5), \
            f"T{t}: 期待 (4,2,5), 実 {(beam, max_turns, per_turn_depth)}"


def test_adaptive_params_late_turn_high_confidence(state_at_main, monkeypatch):
    """T6+ AND classifier conf >= 0.95 で plan-to-end (3, 8, 4)。"""
    from engine.ai import PlanningAI, MAX_TURNS_HARD_CAP
    from engine import matchup_model

    ai = PlanningAI(rng=random.Random(0))
    state = state_at_main
    state.turn_number = 6

    # classifier 信頼度を強制的に 0.99 に
    monkeypatch.setattr(
        matchup_model, "infer_opponent_archetype_with_confidence",
        lambda s, idx: ("ミッドレンジ", 0.99),
    )
    beam, max_turns, per_turn_depth = ai._compute_adaptive_params(state)
    assert (beam, max_turns, per_turn_depth) == (3, MAX_TURNS_HARD_CAP, 4), \
        f"T6 conf=0.99: 期待 (3,{MAX_TURNS_HARD_CAP},4), 実 {(beam, max_turns, per_turn_depth)}"


def test_adaptive_params_late_turn_low_confidence(state_at_main, monkeypatch):
    """T6+ AND classifier conf < 0.95 で downgrade (3, 3, 4)。"""
    from engine.ai import PlanningAI
    from engine import matchup_model

    ai = PlanningAI(rng=random.Random(0))
    state = state_at_main
    state.turn_number = 7

    monkeypatch.setattr(
        matchup_model, "infer_opponent_archetype_with_confidence",
        lambda s, idx: ("コントロール", 0.50),
    )
    beam, max_turns, per_turn_depth = ai._compute_adaptive_params(state)
    assert (beam, max_turns, per_turn_depth) == (3, 3, 4), \
        f"T7 conf=0.50: 期待 (3,3,4), 実 {(beam, max_turns, per_turn_depth)}"


def test_adaptive_params_classifier_exception_fallback(state_at_main, monkeypatch):
    """classifier 例外時は conf=0.5 扱いで downgrade (3, 3, 4)。"""
    from engine.ai import PlanningAI
    from engine import matchup_model

    def raising(*a, **kw):
        raise RuntimeError("classifier error")

    ai = PlanningAI(rng=random.Random(0))
    state = state_at_main
    state.turn_number = 8

    monkeypatch.setattr(
        matchup_model, "infer_opponent_archetype_with_confidence", raising,
    )
    beam, max_turns, per_turn_depth = ai._compute_adaptive_params(state)
    assert (beam, max_turns, per_turn_depth) == (3, 3, 4)


def test_adaptive_disabled_uses_legacy(state_at_main):
    """adaptive=False で旧挙動 (固定 beam_width / max_depth, max_turns=1)。"""
    from engine.ai import PlanningAI

    ai = PlanningAI(rng=random.Random(0), beam_width=4, max_depth=6, adaptive=False)
    # adaptive=False で choose_action が実行できる (= 固定値で plan_search 呼ぶ)
    action = ai.choose_action(state_at_main)
    assert action is not None


def test_simulate_opp_turn_advances_state(state_at_main, repo, overlay):
    """_simulate_opp_turn が opp turn を完走し state.turn_player_idx を me に戻す。"""
    from engine.plan_search import _simulate_opp_turn, _apply_with_defense, fast_clone
    from engine.game import EndPhase, apply_action

    state = state_at_main
    me_idx = state.turn_player_idx
    opp_idx = 1 - me_idx
    ai_self = GreedyAI(rng=random.Random(0))

    # 自分 EndPhase で opp 側 MAIN まで進める
    cloned = fast_clone(state)
    cloned.record_action_evals = False
    apply_action(cloned, EndPhase())

    # この時点で turn_player_idx == opp_idx, phase = MAIN のはず
    assert cloned.turn_player_idx == opp_idx
    pre_turn = cloned.turn_number

    # opp ターンを完走
    opp_sim = GreedyAI(rng=random.Random(0))
    _simulate_opp_turn(cloned, opp_idx, opp_sim, ai_self)

    # opp ターン完了で turn_player_idx == me_idx に戻る (or game_over)
    assert cloned.game_over or cloned.turn_player_idx == me_idx
    # turn_number が進む (= 1 以上)
    assert cloned.turn_number > pre_turn
