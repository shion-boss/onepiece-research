# -*- coding: utf-8 -*-
"""OP02-095 オニグモ の overlay 条件バグ修正の回帰テスト。

クラウド backfill (wave 033) が検出した実バグ: overlay の条件が
`opp_or_self_chara_cost_eq_0_exists` (= 印刷コスト c.card.cost==0 を見る) を使っていたが、
cards.json にコスト0の CHARACTER は 1 枚も存在しない。 公式の「コスト0のキャラがいる場合」は
効果で実効コストが0になったキャラを指すので、 印刷コスト版では効果が永久に発火しなかった。
→ `exists_chara_cost_le: 0` (= base_cost 実効コストを見る、 OP02-093/101/102/113 と同型) に修正。
"""
from __future__ import annotations

import random

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import eval_all_conditions, load_effect_overlay


def _setup():
    repo = CardRepository.from_json("db/cards.json")
    overlay = load_effect_overlay("db/card_effects.json")
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3
    return repo, overlay, st, p0, p1


def test_op02_095_fires_with_effective_cost_0_character():
    """実効コスト0のキャラが場にいれば条件成立 (= バニッシュ付与が発火する)。"""
    repo, overlay, st, p0, p1 = _setup()
    onigumo = InPlay.of(repo.get("OP02-095"), sickness=False)
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # 印刷 cost2
    victim.cost_minus_until_turn_end = victim.card.cost        # 実効コスト0に
    assert victim.base_cost == 0
    p0.characters = [onigumo, victim]
    ent = overlay.get("OP02-095").effects[0]
    assert eval_all_conditions(ent, st, p0, onigumo) is True, \
        "実効コスト0のキャラがいるのに条件が成立しない (印刷コスト版のバグが残っている)"


def test_op02_095_no_fire_without_cost_0_character():
    """コスト0キャラがいなければ条件不成立 (= バニッシュを得ない)。"""
    repo, overlay, st, p0, p1 = _setup()
    onigumo = InPlay.of(repo.get("OP02-095"), sickness=False)
    p0.characters = [onigumo]  # 他にキャラなし (オニグモ自身は cost>0)
    ent = overlay.get("OP02-095").effects[0]
    assert eval_all_conditions(ent, st, p0, onigumo) is False


def test_op02_095_overlay_uses_effective_cost_condition():
    """overlay が実効コスト条件 exists_chara_cost_le を使っている (印刷コスト版でない)。"""
    overlay = load_effect_overlay("db/card_effects.json")
    ent = overlay.get("OP02-095").effects[0]
    assert "exists_chara_cost_le" in ent.get("if", {}), \
        "OP02-095 が実効コスト条件を使っていない"
    assert "opp_or_self_chara_cost_eq_0_exists" not in ent.get("if", {}), \
        "印刷コスト版の壊れた条件が残っている"
