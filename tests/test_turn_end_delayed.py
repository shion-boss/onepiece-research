# -*- coding: utf-8 -*-
"""ターン終了時 delayed 処理の test。

[[project_card_effect_100_plan_kickoff]] 順2 構造検出器で発見した 2 件:
  - schedule_at_self_turn_end が append のみで 一度も flush されない dead 状態 (= OP15-025)。
  - OP11-092 ヘルメッポ の 「ターン終了時 登場キャラ を デッキ下」 が _unimplemented。
両者を trigger_end_of_turn の turn-end 処理で 実装した分の検証。
"""
from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    fire_activate_main,
    load_effect_overlay,
    resolve_triggers,
    trigger_end_of_turn,
    trigger_on_play,
)

ROOT = Path(__file__).resolve().parent.parent
SWORD = "EB04-044"  # SWORD キャラ (cost<=8)


def _repo():
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _state(repo, overlay):
    p1 = Player(name="P0", leader=InPlay.of(repo.get("OP11-001"), sickness=False))
    p2 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1.deck = [repo.get("OP01-013")] * 10
    p2.deck = [repo.get("OP01-013")] * 10
    st = GameState(players=[p1, p2], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    return st, p1, p2


def test_schedule_at_self_turn_end_now_flushes():
    """schedule_at_self_turn_end が trigger_end_of_turn で 実行され、 list が drain される。"""
    repo = _repo()
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p1, p2 = _state(repo, overlay)
    deck0 = len(p1.deck)
    p1.scheduled_at_self_turn_end = [{"do": [{"draw": 1}]}]
    trigger_end_of_turn(st, overlay)
    resolve_triggers(st)
    assert p1.scheduled_at_self_turn_end == [], "scheduled が drain される"
    assert len(p1.deck) == deck0 - 1, "予約された draw が実行された (= 旧 dead bug 修復)"


def test_op11_092_temp_summon_returns_to_deck_bottom_at_turn_end():
    """OP11-092: trash から SWORD キャラ 一時登場 → ターン終了時 デッキ下へ戻る。"""
    repo = _repo()
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p1, p2 = _state(repo, overlay)
    p1.hand = [repo.get("OP01-013")]          # discard cost 用
    p1.trash = [repo.get(SWORD)]              # 登場元
    src = InPlay.of(repo.get("OP11-092"), sickness=True)
    p1.characters = [src]
    deck0 = len(p1.deck)
    trigger_on_play(st, p1, p2, src, overlay)
    resolve_triggers(st)
    # 一時登場: SWORD キャラが場に出ている (src + 登場キャラ)
    summoned = [c for c in p1.characters if c.card.card_id == SWORD]
    assert summoned, "SWORD キャラが trash から登場した"
    assert summoned[0].return_to_deck_bottom_at_turn_end is True
    # ターン終了処理
    trigger_end_of_turn(st, overlay)
    resolve_triggers(st)
    assert not [c for c in p1.characters if c.card.card_id == SWORD], \
        "一時登場キャラが場から消えた"
    assert p1.deck[-1].card_id == SWORD, "デッキの一番下に戻った"
    # deck: -1 (登場時 draw) +1 (一時登場キャラ 返却) = deck0
    assert len(p1.deck) == deck0


def test_normal_summon_not_returned():
    """return フラグなしの通常登場キャラは ターン終了で 戻らない (= 回帰防止)。"""
    repo = _repo()
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p1, p2 = _state(repo, overlay)
    normal = InPlay.of(repo.get(SWORD), sickness=True)
    p1.characters = [normal]
    trigger_end_of_turn(st, overlay)
    resolve_triggers(st)
    assert normal in p1.characters, "通常キャラは場に残る"
