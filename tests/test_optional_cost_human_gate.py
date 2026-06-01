# -*- coding: utf-8 -*-
"""optional_cost_then の 人間 pay/skip gate の test。

公式「〜することができる：効果」 は 任意コスト = 人間が「払う/見送る」 を 選べる べき。
旧実装は can_pay なら 自動 fire しており、 人間プレイ時に コスト払いの是非を本人に問わず
自動化していた (= [[project_card_effect_100_plan_kickoff]] の human-controllability gap)。

修正: _should_human_pick(state) のとき pending_choice(kind=optional_cost_confirm) を立て、
picks[0]==1 で pay (= _cost_confirmed 付き再実行)、 それ以外で見送り。
AI 操作 (= human_player_idx 不一致) は 従来通り自動 fire (= matrix/AI戦 不変)。
"""
from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import execute_effect, resolve_pending_choice, load_effect_overlay

ROOT = Path(__file__).resolve().parent.parent
FILLER = "OP01-013"
SRC = "OP01-016"  # ナミ (source キャラ)

SPEC_DRAW = {
    "optional_cost_then": {
        "cost": [{"mill_self_life_to_trash": 1}],
        "effect": [{"draw": 1}],
    }
}
SPEC_KO = {
    "optional_cost_then": {
        "cost": [{"mill_self_life_to_trash": 1}],
        "effect": [{"ko": "one_opponent_character_any"}],
    }
}


def _repo():
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _setup(repo, overlay, human, opp_charas=0):
    p1 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p2 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1.deck = [repo.get(FILLER)] * 10
    p2.deck = [repo.get(FILLER)] * 10
    p1.life = [repo.get(FILLER) for _ in range(3)]
    p1.hand = []
    src = InPlay.of(repo.get(SRC), sickness=False)
    p1.characters = [src]
    p2.characters = [InPlay.of(repo.get(FILLER), sickness=False) for _ in range(opp_charas)]
    st = GameState(players=[p1, p2], phase=Phase.MAIN, rng=random.Random(3),
                   effects_overlay=overlay)
    p1.don_active = 5
    if human:
        st.human_player_idx = 0
        st.turn_player_idx = 0
    return st, p1, p2, src


def test_human_gate_fires_before_paying():
    repo, overlay = _repo(), load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p1, p2, src = _setup(repo, overlay, human=True)
    life0, hand0 = len(p1.life), len(p1.hand)
    execute_effect(SPEC_DRAW, st, p1, p2, src)
    assert st.pending_choice is not None
    assert st.pending_choice["kind"] == "optional_cost_confirm"
    # 確認前は コストも効果も走らない
    assert len(p1.life) == life0 and len(p1.hand) == hand0


def test_human_accept_pays_and_resolves():
    repo, overlay = _repo(), load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p1, p2, src = _setup(repo, overlay, human=True)
    life0, hand0 = len(p1.life), len(p1.hand)
    execute_effect(SPEC_DRAW, st, p1, p2, src)
    resolve_pending_choice(st, [1])  # accept
    assert st.pending_choice is None
    assert len(p1.life) == life0 - 1, "コスト(ライフ1trash)が払われる"
    assert len(p1.hand) == hand0 + 1, "効果(draw)が実行される"


def test_human_decline_does_nothing():
    repo, overlay = _repo(), load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p1, p2, src = _setup(repo, overlay, human=True)
    life0, hand0 = len(p1.life), len(p1.hand)
    execute_effect(SPEC_DRAW, st, p1, p2, src)
    resolve_pending_choice(st, [0])  # decline
    assert st.pending_choice is None
    assert len(p1.life) == life0 and len(p1.hand) == hand0, "見送りでコスト/効果なし"


def test_ai_auto_fires_without_gate():
    """AI 操作 (= human_player_idx 不一致) は 従来通り 自動 fire (= 回帰なし)。"""
    repo, overlay = _repo(), load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p1, p2, src = _setup(repo, overlay, human=False)
    life0, hand0 = len(p1.life), len(p1.hand)
    execute_effect(SPEC_DRAW, st, p1, p2, src)
    assert st.pending_choice is None
    assert len(p1.life) == life0 - 1 and len(p1.hand) == hand0 + 1


def test_human_accept_then_target_pick_chains():
    """accept → コスト払い → 効果内の target 選択 が さらに pending_choice で連鎖する。
    72 枚の cost踏み倒し修正カード (KO/コスト-N 等) の 主要フロー。"""
    repo, overlay = _repo(), load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p1, p2, src = _setup(repo, overlay, human=True, opp_charas=2)
    life0, opp0 = len(p1.life), len(p2.characters)
    execute_effect(SPEC_KO, st, p1, p2, src)
    assert st.pending_choice["kind"] == "optional_cost_confirm"
    resolve_pending_choice(st, [1])  # accept pay
    assert len(p1.life) == life0 - 1, "コスト払い"
    assert st.pending_choice is not None
    assert st.pending_choice["kind"] == "target_pick", "効果のtarget選択が連鎖"
    resolve_pending_choice(st, [0])  # 1体KO
    assert st.pending_choice is None
    assert len(p2.characters) == opp0 - 1, "選んだ相手キャラがKO"
