# -*- coding: utf-8 -*-
"""層1 列挙器の健全性テスト (= [[project_superhuman_ai_distillation]] 塊プラン)。

- 列挙したプランは全て合法 (= concrete_template が turn 開始 state から再生可能)。
- multiset dedup が効いている (= 重複 multiset key なし)。
- 列挙は決定的 (= 同一 state で同一プラン数)。
- T1-5 のプラン数が想定レンジ (= 爆発しない)。
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import Phase, setup_game, play_until_main
from engine.ai import GreedyAI, play_one_action
from engine.plan_search import fast_clone, _apply_with_defense
from engine.game import EndPhase
from engine.turn_plan_enumerator import (
    enumerate_turn_plans,
    frozenset_count,
    board_signature,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
_REPO = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(REPO_ROOT / "db" / "card_effects.json")


def _load(slug: str):
    return make_deck_from_dict(
        json.loads((REPO_ROOT / "decks" / f"{slug}.json").read_text(encoding="utf-8")), _REPO
    )


def _game_at_turn(slug: str, target_turn: int, seed: int = 7):
    """slug の mirror を target_turn の手番 MAIN まで GreedyAI で進めた state を返す。"""
    deck = _load(slug)
    rng = random.Random(seed)
    state = setup_game(deck, _load(slug), rng=rng, first_player=0, effects_overlay=_OVERLAY)
    play_until_main(state)
    ais = [GreedyAI(random.Random(seed + 1)), GreedyAI(random.Random(seed + 2))]
    n = 0
    while not state.game_over and n < 400:
        if state.phase == Phase.MAIN and state.turn_number == target_turn:
            return state
        me = state.turn_player_idx
        play_one_action(state, ais[me], ais[1 - me])
        n += 1
    pytest.skip(f"{slug} が turn {target_turn} に到達しなかった (game終了)")


def test_enumerate_returns_legal_plans():
    """各プランの concrete_template が turn 開始 state から例外なく再生でき、
    到達盤面が enumerate の board_sig と一致する (= 合法・再現可能)。"""
    state = _game_at_turn("cardrush_1342", 4)
    me = state.turn_player_idx
    plans, stats = enumerate_turn_plans(state, me, node_cap=20000)
    assert plans, "プランが 1 つも列挙されなかった"
    assert not stats["capped"], "T4 で cap に当たった (= 爆発、 想定外)"

    defender = GreedyAI(random.Random(99))
    # 全プラン (= 多くて数百) を再生して合法性 + board_sig 一致を確認
    for p in plans:
        replay = fast_clone(state)
        for action in p.concrete_template:
            _apply_with_defense(replay, action, defender)
        assert replay.phase == Phase.MAIN
        assert replay.turn_player_idx == me
        # 再生後の board_sig が列挙時の board_sig と一致 (= concrete_template が忠実)
        assert board_signature(replay, me) == p.board_sig


def test_multiset_dedup_no_duplicates():
    """列挙プランの multiset key は一意 (= multiset dedup が効いている)。"""
    state = _game_at_turn("cardrush_1342", 5)
    me = state.turn_player_idx
    plans, _ = enumerate_turn_plans(state, me, node_cap=20000)
    keys = [frozenset_count(p.signature) for p in plans]
    assert len(keys) == len(set(keys)), "multiset key の重複あり (= dedup 漏れ)"


def test_enumeration_deterministic():
    """同一 state からの列挙は決定的 (= プラン数が一致)。"""
    state = _game_at_turn("cardrush_1342", 4)
    me = state.turn_player_idx
    p1, _ = enumerate_turn_plans(state, me, node_cap=20000)
    p2, _ = enumerate_turn_plans(state, me, node_cap=20000)
    assert len(p1) == len(p2)
    assert {frozenset_count(p.signature) for p in p1} == {
        frozenset_count(p.signature) for p in p2
    }


def test_early_turn_counts_bounded():
    """T1-3 は少数 (= DON 制約で爆発しない)。"""
    for turn, ub in [(1, 10), (2, 40), (3, 120)]:
        state = _game_at_turn("cardrush_1342", turn)
        me = state.turn_player_idx
        plans, stats = enumerate_turn_plans(state, me, node_cap=20000)
        assert not stats["capped"]
        assert len(plans) <= ub, f"T{turn}: {len(plans)} plans > 想定上限 {ub}"


def test_endphase_excluded_from_signature():
    """EndPhase はプランに含まれない (= 各プランは EndPhase で停止する前提)。"""
    state = _game_at_turn("cardrush_1342", 4)
    me = state.turn_player_idx
    plans, _ = enumerate_turn_plans(state, me, node_cap=20000)
    for p in plans:
        assert all(not isinstance(a, EndPhase) for a in p.concrete_template)
        assert all(tok[0] != "EndPhase" for tok in p.signature)
