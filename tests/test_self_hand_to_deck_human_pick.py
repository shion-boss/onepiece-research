# -*- coding: utf-8 -*-
"""self_hand_to_deck_bottom の 人間 pick gate の test。

ナミュール OP08-050 【登場時】「カード2枚を引き、自分の手札2枚を…デッキの上か下に置く」
で、 旧実装は コスト最高 を auto 選択 → 人間 の cost9 finisher (ボア・ハンコック OP14-112)
を デッキ底 へ 葬っていた (= 人間が選べない bug)。

修正: 人間 acting + 候補 > N なら modal halt (kind=self_hand_to_deck_pick) → 人間 が
どのカードを戻すか選ぶ。 AI / 候補<=N は 従来 ヒューリスティック (コスト最高) を 維持。
"""
from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import execute_effect, resolve_pending_choice

ROOT = Path(__file__).resolve().parent.parent
FINISHER = "OP14-112"  # ボア・ハンコック (cost9/10000)
CHEAP = "OP14-103"     # グロリオーサ (cost2)
FILLER = "OP14-113"    # マーガレット (cost3)


def _repo():
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _state(repo, hand_ids, human=False):
    p1 = Player(name="P0", leader=InPlay.of(repo.get("OP14-041"), sickness=False))
    p2 = Player(name="P1", leader=InPlay.of(repo.get("OP14-041"), sickness=False))
    p1.deck = [repo.get(FILLER) for _ in range(10)]
    p2.deck = [repo.get(FILLER) for _ in range(10)]
    p1.hand = [repo.get(c) for c in hand_ids]
    st = GameState(players=[p1, p2], phase=Phase.MAIN, rng=random.Random(7))
    p1.don_active = 5
    if human:
        st.human_player_idx = 0
    st.turn_player_idx = 0
    return st, p1, p2


def test_human_halts_for_pick_instead_of_burying_finisher():
    repo = _repo()
    # 手札 = finisher(cost9) ×2 + cheap(cost2) ×2。 2 枚 戻す。
    st, p1, _ = _state(repo, [FINISHER, FINISHER, CHEAP, CHEAP], human=True)
    halted = execute_effect({"self_hand_to_deck_bottom": 2}, st, p1, st.players[1], None)
    # 人間 acting + 候補(4) > N(2) → halt
    assert halted is True
    assert st.pending_choice is not None
    assert st.pending_choice["kind"] == "self_hand_to_deck_pick"
    assert st.pending_choice["limit"] == 2
    # まだ 何も デッキに 落ちていない (= auto-bury していない)
    assert len(p1.hand) == 4
    assert FINISHER not in [c.card_id for c in p1.deck]

    # 人間が cheap 2 枚 (candidate idx 2,3) を デッキ底 へ
    resolve_pending_choice(st, [2, 3])
    hand_ids = [c.card_id for c in p1.hand]
    # finisher は 手札に 残る (= 埋められない)
    assert hand_ids.count(FINISHER) == 2
    assert len(p1.hand) == 2
    # cheap 2 枚 が デッキ底
    assert p1.deck[-1].card_id == CHEAP
    assert p1.deck[-2].card_id == CHEAP


def test_ai_keeps_highest_cost_heuristic():
    repo = _repo()
    st, p1, _ = _state(repo, [FINISHER, CHEAP], human=False)  # AI (human_player_idx None)
    halted = execute_effect({"self_hand_to_deck_bottom": 1}, st, p1, st.players[1], None)
    assert not halted
    assert st.pending_choice is None
    # AI は コスト最高 (finisher) を デッキ底 へ (= 従来挙動 維持)
    assert p1.deck[-1].card_id == FINISHER
    assert [c.card_id for c in p1.hand] == [CHEAP]


def test_human_empty_pick_falls_back_to_required_count():
    repo = _repo()
    st, p1, _ = _state(repo, [FINISHER, CHEAP, CHEAP], human=True)
    execute_effect({"self_hand_to_deck_bottom": 2}, st, p1, st.players[1], None)
    assert st.pending_choice["kind"] == "self_hand_to_deck_pick"
    # 人間が 0 枚 選択 (skip) → 強制 N=2 を ヒューリスティックで補完
    resolve_pending_choice(st, [])
    assert st.pending_choice is None
    assert len(p1.hand) == 1  # 3 - 2 = 1
