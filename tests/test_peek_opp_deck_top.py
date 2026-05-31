# -*- coding: utf-8 -*-
"""peek_opp_deck_top primitive (= OP11-070 プリン 「相手のデッキの上から1枚を見る」) の test。

[[project_card_effect_100_plan_kickoff]] 順2 prototype で 未実装 (_missing_effect) と判明した
OP11-070 起動メイン効果を 新 primitive として実装した分の検証。
"""
from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import execute_effect, fire_activate_main, load_effect_overlay, resolve_triggers

ROOT = Path(__file__).resolve().parent.parent


def _repo():
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def test_peek_opp_deck_top_records_private_info_no_mutation():
    """相手デッキ上を見る: 状態変化なし、 private 情報を記録、 public log に名前を出さない。"""
    repo = _repo()
    p1 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p2 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    top = repo.get("OP01-016")
    p2.deck = [top, repo.get("OP01-013"), repo.get("OP01-013")]
    state = GameState(players=[p1, p2], phase=Phase.MAIN, rng=random.Random(1),
                      effects_overlay={})
    deck_before = list(p2.deck)
    execute_effect({"peek_opp_deck_top": 1}, state, p1, p2, None)
    # 状態変化なし
    assert p2.deck == deck_before, "相手デッキは変化しない (見るだけ)"
    # private 記録 (= viewer = p1)
    assert state.last_peeked_opp_deck_top == {"viewer_idx": 0, "card_ids": ["OP01-016"]}
    # public log に カード名 を出さない (= 隠ぺい情報保護)
    assert all("OP01-016" not in line and top.name not in line for line in state.log), \
        "相手デッキ上の カード名 が public log に漏洩している"


def test_peek_opp_deck_top_empty_deck_safe():
    """相手デッキ空でも例外なく不発ログ。"""
    repo = _repo()
    p1 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p2 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p2.deck = []
    state = GameState(players=[p1, p2], phase=Phase.MAIN, rng=random.Random(1),
                      effects_overlay={})
    execute_effect({"peek_opp_deck_top": 1}, state, p1, p2, None)
    assert state.last_peeked_opp_deck_top["card_ids"] == []


def test_op11_070_activate_main_charges_once_and_peeks():
    """OP11-070 起動メイン: ドン‼-1 を 1 回だけ請求し (旧 bug: 2 回)、 相手デッキ上を見る。"""
    repo = _repo()
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    src = InPlay.of(repo.get("OP11-070"), sickness=False)
    p1 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p2 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1.characters = [src]
    p1.deck = [repo.get("OP01-013")] * 5
    p2.deck = [repo.get("OP01-016")] + [repo.get("OP01-013")] * 5
    state = GameState(players=[p1, p2], phase=Phase.MAIN, rng=random.Random(1),
                      effects_overlay=overlay)
    p1.don_active = 5
    p1.don_rested = 0
    p1.don_remaining_in_deck = 0
    am = [e for e in overlay["OP11-070"].effects if e.get("when") == "activate_main"][0]
    fire_activate_main(state, p1, p2, src, am)
    resolve_triggers(state)
    # ドン‼-1 (= pay_don:1) が 1 回 → don_active 5→4、 deck へ 1 戻る
    assert p1.don_active == 4, f"ドン‼-1 が 1 回のはず, got don_active={p1.don_active}"
    assert state.last_peeked_opp_deck_top["card_ids"] == ["OP01-016"]
