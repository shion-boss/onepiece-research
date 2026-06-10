# -*- coding: utf-8 -*-
"""ST22-015「おれァ‘‘白ひげ‘‘だァア!!!!」 overlay 欠落 bug の regression guard。

2026-06-10 (1456 赤青エース campaign g5 中に発見): overlay が leader +2000 の
power_pump だけで、 **メイン効果「手札から『エドワード・ニューゲート』1枚までを
登場させる」 + 「ライフの上か下から1枚を手札に加える」 が丸ごと欠落** していた
(= 8 コスト払って leader +2000 しか起きない簡略実装、 CLAUDE.md 公式テキスト忠実主義 違反)。

修正: do に play_from_hand_named_set (ニューゲ召喚) + life_top_or_bottom_to_hand を追加。
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    TriggerEvent,
    _execute_event,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent


def test_st22015_overlay_has_summon_and_lifegain():
    """overlay が ニューゲ召喚 + ライフ→手札 の primitive を含む (= 簡略でない)。"""
    eff = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    do = eff["ST22-015"][0]["do"]
    keys = {k for d in do if isinstance(d, dict) for k in d}
    assert "play_from_hand_named_set" in keys, "ニューゲ召喚 primitive 欠落"
    assert "life_top_or_bottom_to_hand" in keys, "ライフ→手札 primitive 欠落"


def test_st22015_summons_newgate_from_hand():
    """ST22-015 発動で 手札の エドワード・ニューゲート (OP13-042) が登場し ETB が発火、
    ライフ→手札 + leader +2000 も起きる。"""
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP13-002"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP13-002"), sickness=False))
    p0.deck = [repo.get("OP01-013")] * 20
    p1.deck = [repo.get("OP01-013")] * 20
    p0.life = [repo.get("OP01-013")] * 3
    p0.hand = [repo.get("OP13-042")]  # ニューゲ in hand
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=ov)
    p0.don_active = 10

    _execute_event(st, TriggerEvent(when="main", owner_idx=0, source_card_id="ST22-015"))
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [0])
        guard += 1

    assert any(c.card.card_id == "OP13-042" for c in p0.characters), \
        "ニューゲ が 手札から 登場していない"
    assert len(p0.life) == 2, "ライフ→手札 が 起きていない (life 3→2 のはず)"
    assert p0.leader.power == 8000, "leader +2000 が 起きていない"
    # ニューゲ ETB (draw2/discard1) も発火 → 手札は空でない
    assert len(p0.hand) >= 1, "ニューゲ ETB の draw が 発火していない"
