# -*- coding: utf-8 -*-
"""EB03-062 トラファルガー・ロー 起動メイン (trash_self + discard_hand 併用) の
人間 discard pick resume bug の回帰テスト。

bug (2026-06-11 corazon mirror campaign 中に発見):
  cost = {trash_self, discard_hand:1}、 do = [put_top_to_life, play_from_hand(≤7c ロー)]。
  初回 fire で trash_self が source を場→トラッシュへ移すが、 discard_hand は人間 pick の
  ため pending_choice で halt。 resume 時 activate_main_discard_pick が source_iid で場を
  引けず (= 既にトラッシュ) inplay=None → 早期 return し、 discard も do も丸ごと unfire。
  → 自身 trash だけ済んで「ライフ増加なし・無料ロー登場なし・手札も減らない」 状態に。

fix: resume 時 source 不在なら source_card_id でトラッシュの CardDef から ghost InPlay を
  再構成して continuation を完遂する。 trash_self+discard_hand を持つ全 7 枚に効く。
"""
from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    fire_activate_main,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent
EB = "EB03-062"          # 速攻 ロー、 起動メイン lifegain engine
ROW_LE7 = "OP09-069"     # トラファルガー・ロー cost1 (= 無料登場対象)
FILLER = "OP01-013"      # 非ロー (= discard 対象)


def _eff(overlay):
    return [e for e in overlay[EB].effects if e.get("when") == "activate_main"][0]


def test_eb03062_human_activate_completes_discard_life_and_free_play():
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")

    p1 = Player(name="P0", leader=InPlay.of(repo.get("OP12-061"), sickness=False))
    p2 = Player(name="P1", leader=InPlay.of(repo.get("OP12-061"), sickness=False))
    eb = InPlay.of(repo.get(EB), sickness=False)
    p1.characters = [eb]
    p1.hand = [repo.get(FILLER), repo.get(ROW_LE7)]
    p1.deck = [repo.get(FILLER)] * 10
    p1.life = [repo.get(FILLER), repo.get(FILLER)]  # 2 枚
    p2.deck = [repo.get(FILLER)] * 10

    st = GameState(players=[p1, p2], phase=Phase.MAIN, rng=random.Random(7),
                   effects_overlay=overlay)
    st.human_player_idx = 0
    st.turn_player_idx = 0
    p1.don_active = 0  # cost に DON 不要

    life_before = len(p1.life)

    fire_activate_main(st, p1, p2, eb, _eff(overlay))
    # 人間 discard pick で halt しているはず
    assert st.pending_choice is not None
    assert st.pending_choice.get("kind") == "activate_main_discard_pick"

    # candidate 0 = FILLER を捨てる (ロー は free-play 用に温存)
    resolve_pending_choice(st, [0])
    # play_from_hand が 二次 pending を出す実装なら解決 (候補 1 枚なので通常 auto)
    guard = 0
    while st.pending_choice is not None and guard < 4:
        resolve_pending_choice(st, [0])
        guard += 1

    names_chars = [c.card.card_id for c in p1.characters]
    names_trash = [c.card_id for c in p1.trash]

    # source は trash 済
    assert EB in names_trash, "EB03-062 が trash されていない"
    assert EB not in names_chars, "EB03-062 が場に残っている"
    # discard cost が適用された (FILLER が 1 枚 trash、 手札から消えた)
    assert FILLER in names_trash, "discard cost (FILLER) が適用されていない (bug)"
    # lifegain (+1)
    assert len(p1.life) == life_before + 1, f"ライフが増えていない: {len(p1.life)} (bug)"
    # 無料 ≤7c ロー が登場
    assert ROW_LE7 in names_chars, "無料ロー (OP09-069) が登場していない (bug)"
    # ロー は手札から出たので手札に残っていない
    assert ROW_LE7 not in [c.card_id for c in p1.hand]
