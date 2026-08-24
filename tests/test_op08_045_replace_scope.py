# -*- coding: utf-8 -*-
"""OP08-045 サッチ の置換範囲。

公式テキスト: 「このキャラが **KO される場合** か、 **相手の効果で** 場を離れる場合、
代わりにこのキャラをトラッシュに置き、 カード1枚を引く。」

⚠ 2026-08-24 是正: overlay は `when: replace_leave` / `if: {target: self}` の **1 本** だけで、
  engine の `replace_leave` は 「あらゆる離脱種別」 で発火する (effects.py の docstring)。
  = **自分の効果で手札に戻した時にも置換が成立** し、 戻るはずのキャラがトラッシュへ行って
  1 ドローしていた。 「相手の効果で」 の限定が落ちていた型。
  → `replace_ko` (原因不問) と `replace_leave` (`by_opp_effect: true`) の 2 本に分解。

検出は `scripts/audit_human_choice_coverage.py` の 「A か B」 択一 flag。
"""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import load_effect_overlay, try_replace_ko

ROOT = Path(__file__).resolve().parent.parent
FILLER = "OP01-013"
SATCH = "OP08-045"


def _setup():
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-002"), sickness=False))
    for p in (p0, p1):
        p.deck = [repo.get(FILLER)] * 10
        p.life = [repo.get(FILLER)] * 3
        p.life_face_up = [False] * 3
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(5),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    victim = InPlay.of(repo.get(SATCH), sickness=False)
    p0.characters.append(victim)
    return overlay, st, p0, p1, victim


def test_op08_045_overlay_has_both_branches():
    """overlay が 「KO (原因不問)」 と 「相手の効果での離脱」 の 2 本を持つ。"""
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    effs = overlay.get(SATCH).effects
    whens = {e.get("when") for e in effs}
    assert whens == {"replace_ko", "replace_leave"}, (
        f"置換が 2 本に分解されていない: {whens}。 replace_leave 1 本だと "
        "**自分の効果での離脱でも発火** する (公式は 「相手の効果で」 限定)"
    )
    leave = next(e for e in effs if e.get("when") == "replace_leave")
    assert leave.get("if", {}).get("by_opp_effect") is True, (
        "replace_leave 側に by_opp_effect の限定が無い"
    )
    ko = next(e for e in effs if e.get("when") == "replace_ko")
    assert "by_opp_effect" not in ko.get("if", {}), (
        "KO 側は原因不問 (バトル KO でも発動する) なので by_opp_effect を付けてはいけない"
    )


@pytest.mark.parametrize(
    "leave_kind,by_opp_effect,expect_replaced",
    [
        ("ko", False, True),               # バトル KO → 置換する
        ("ko", True, True),                # 相手の効果で KO → 置換する
        ("return_to_hand", True, True),    # 相手の効果で手札へ → 置換する
        ("return_to_hand", False, False),  # ⭐ **自分の効果**で手札へ → 置換しない
        ("return_to_deck_bottom", False, False),  # 同上 (デッキ下)
    ],
)
def test_op08_045_replace_scope(leave_kind, by_opp_effect, expect_replaced):
    overlay, st, me, opp, victim = _setup()
    hand_before = len(me.hand)
    replaced = try_replace_ko(st, me, opp, victim, overlay,
                              by_opp_effect=by_opp_effect, leave_kind=leave_kind)
    assert replaced is expect_replaced, (
        f"leave_kind={leave_kind} by_opp_effect={by_opp_effect}: "
        f"置換 {replaced} (期待 {expect_replaced})"
    )
    if expect_replaced:
        assert len(me.hand) == hand_before + 1, "置換したのに 1 ドローしていない"
    else:
        assert len(me.hand) == hand_before, (
            "置換していないのにドローしている (= 自分の効果での離脱で発火した)"
        )
