# -*- coding: utf-8 -*-
"""set_ko_per_turn_immune primitive + REFRESH 補充 (= OP10-118 等)。

公式: 「このキャラはターンに1回、 相手の効果で KO されない」 を 表現 する 新 primitive。
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import execute_effect, load_effect_overlay

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _make_state(repo, overlay=None):
    p1 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p2 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1.deck = [repo.get("OP01-013")] * 30
    p2.deck = [repo.get("OP01-013")] * 30
    return GameState(
        players=[p1, p2],
        phase=Phase.MAIN,
        rng=random.Random(1),
        effects_overlay=overlay or {},
    )


def test_set_ko_per_turn_immune_blocks_first_ko():
    """1 ターン に 1 回 だけ KO 効果 を 無効化 する。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    target = InPlay.of(repo.get("OP01-013"), sickness=False)
    target.ko_per_turn_immune_max = 1
    target.ko_per_turn_immune_remaining = 1
    opp.characters = [target]

    # 1 回目 ko: counter で 防御 → 生存
    execute_effect({"ko": "all_opponent_characters"}, state, me, opp, None)
    assert target in opp.characters, "1 回目 ko は per-turn immune で 防御"
    assert target.ko_per_turn_immune_remaining == 0, "counter 1 消費"

    # 2 回目 ko: counter 切れ → KO
    execute_effect({"ko": "all_opponent_characters"}, state, me, opp, None)
    assert target not in opp.characters, "2 回目 ko は 通常 KO される"


def test_set_ko_per_turn_immune_primitive_resolves():
    """primitive 自体 が 動作 する: set_ko_per_turn_immune で max/remaining が 設定 される。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    inplay = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [inplay]

    execute_effect({"set_ko_per_turn_immune": {"target": "self", "count": 1}},
                   state, me, opp, inplay)
    assert inplay.ko_per_turn_immune_max == 1
    assert inplay.ko_per_turn_immune_remaining == 1


def test_op10_118_overlay_marked():
    """OP10-118 / _p1 overlay に set_ko_per_turn_immune 追加 済 確認。"""
    import json
    overlay = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    for cid in ("OP10-118", "OP10-118_p1"):
        entries = overlay.get(cid, [])
        found = False
        for e in entries:
            if not isinstance(e, dict):
                continue
            for prim in e.get("do", []) or []:
                if isinstance(prim, dict) and "set_ko_per_turn_immune" in prim:
                    found = True
                    break
            if found:
                break
        assert found, f"{cid} に set_ko_per_turn_immune entry が ない"


def test_refresh_replenishes_per_turn_counter():
    """REFRESH phase で 自ターン 開始 時 に counter を max に 復活。"""
    from engine.game import advance_phase
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    inplay = InPlay.of(repo.get("OP01-013"), sickness=False)
    inplay.ko_per_turn_immune_max = 1
    inplay.ko_per_turn_immune_remaining = 0  # 既 消費 済
    me.characters = [inplay]

    # REFRESH へ 到達 (= 自ターン 開始)
    state.turn_player_idx = 0
    state.turn_number = 3  # > 1 で REFRESH 有効
    state.phase = Phase.REFRESH
    advance_phase(state)  # REFRESH 内 logic 実行

    assert inplay.ko_per_turn_immune_remaining == 1, "REFRESH で remaining が max に 復活"
