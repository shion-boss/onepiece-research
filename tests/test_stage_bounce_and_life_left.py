# -*- coding: utf-8 -*-
"""選択列挙 (探索が選択肢を分岐するモード) の bail 潰しで露見した **カード挙動の実バグ** 2 件。

1. 「ステージ1枚までを、 持ち主の手札に戻す」 (OP15-054 選択肢②) が **silent no-op** だった。
   overlay は `{"return_to_hand": {"type": "any_stage_n_1"}}` と正しいのに、 `any_stage_n_N` を
   解決する実装がどちらのエンジンにも無く、 Python は未知 spec → `[]` (= 何も起きない)。
   ⭐ **AI が選ばない選択肢は実装が無くても誰も気づかない** — 選択を探索に載せて初めて踏まれた。

2. 「相手のライフが**離れている**ターン中」 (P-120 サンジ = コスト-2) が
   **戦闘ダメージでしか成立しなかった**。 公式 (cardqa_op_11 Q903 / cardqa_op_12 Q999) は
   「自分のライフか相手のライフかにかかわらず」 「どちらのライフが離れても」 = 離れ方を問わない。
"""
from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import deal_effect_damage, execute_effect, load_effect_overlay

ROOT = Path(__file__).resolve().parent.parent
FILLER = "OP01-013"
STAGE_A = "OP15-057"  # ドレスローザ王国 (STAGE)


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
    return repo, overlay, st, p0, p1


def test_any_stage_n_1_returns_opponent_stage():
    """「ステージ1枚まで手札に戻す」 は **両陣営** が対象。 AI は相手のステージを選ぶ。"""
    repo, _overlay, st, p0, p1 = _setup()
    p1.stages.append(InPlay.of(repo.get(STAGE_A), sickness=False))
    assert len(p1.stages) == 1

    execute_effect({"return_to_hand": {"type": "any_stage_n_1"}}, st, p0, p1, None)

    assert len(p1.stages) == 0, "相手のステージが手札に戻る (旧実装は silent no-op)"
    assert [c.card_id for c in p1.hand] == [STAGE_A]


def test_effect_damage_sets_life_left_this_turn():
    """効果ダメージでも 「相手のライフが離れている」 は成立する (P-120 の条件)。"""
    _repo, _overlay, st, p0, p1 = _setup()
    assert p1.life_lost_this_turn is False

    deal_effect_damage(st, p0, p1, 1)

    assert len(p1.life) == 2, "効果ダメージでライフが 1 枚離れる"
    assert p1.life_lost_this_turn is True, (
        "「ライフが離れている」 は離れ方を問わない (旧実装は戦闘ダメージ限定だった)"
    )
