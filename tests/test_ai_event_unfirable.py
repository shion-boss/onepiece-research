# -*- coding: utf-8 -*-
"""Phase 1.1: AI が effect 不発 event を play しない 修正 のテスト (= 2026-05-26)。

背景:
- 神避 (= OP13-076、 cost=0、 effect cost=rest_self_don:5、 if=self_attached_don_ge:1) で
  AI が active_don=2 (= rest 不能) + attached_don=0 (= if 失敗) の状態 で play する bug 観測。
- engine は cost / if で 正しく skip するが、 AI は 1 枚 hand → trash 送り の 無駄打ち。

修正対象:
- engine/ai.py: _can_pay_effect_cost / _is_event_main_effect_unfirable helper 追加
- prune_mechanical_waste / GreedyAI / EvalGreedyAI で unfirable event を 除外
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.ai import (
    _can_pay_effect_cost,
    _is_event_main_effect_unfirable,
    prune_mechanical_waste,
)
from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import CardEffectBundle, load_effect_overlay
from engine.game import PlayEvent

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _make_state(repo, my_don_active=2, my_don_rested=0):
    """me 側の DON / hand を 自由に いじれる minimal state。"""
    me = Player(name="me", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    opp = Player(name="opp", leader=InPlay.of(repo.get("OP15-058"), sickness=False))
    me.life = [repo.get("OP01-013")] * 3
    opp.life = [repo.get("OP01-013")] * 3
    me.deck = [repo.get("OP01-013")] * 30
    opp.deck = [repo.get("OP01-013")] * 30
    me.don_active = my_don_active
    me.don_rested = my_don_rested
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    state = GameState(
        players=[me, opp],
        phase=Phase.MAIN,
        rng=random.Random(1),
        effects_overlay=overlay,
    )
    state.turn_player_idx = 0
    return state


# ─────────────────────────────────────────────────────
# _can_pay_effect_cost: 個別 cost 種別の支払い可否
# ─────────────────────────────────────────────────────


def test_can_pay_effect_cost_no_cost_returns_true():
    """cost={} / None / 非 dict は 常に True (= 制約なし)。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    assert _can_pay_effect_cost(me, {}) is True
    assert _can_pay_effect_cost(me, None) is True  # type: ignore[arg-type]
    assert _can_pay_effect_cost(me, "discard") is True  # type: ignore[arg-type]


def test_can_pay_effect_cost_rest_self_don_insufficient():
    """rest_self_don: 5、 active=2 → False (= 神避 シナリオ)。"""
    repo = _repo()
    state = _make_state(repo, my_don_active=2)
    me = state.players[0]
    assert _can_pay_effect_cost(me, {"rest_self_don": 5}) is False


def test_can_pay_effect_cost_rest_self_don_sufficient():
    """rest_self_don: 5、 active=5 → True。"""
    repo = _repo()
    state = _make_state(repo, my_don_active=5)
    me = state.players[0]
    assert _can_pay_effect_cost(me, {"rest_self_don": 5}) is True


def test_can_pay_effect_cost_pay_don_counts_rested():
    """pay_don: 3、 active=1 + rested=2 → True (= active+rested で 評価)。"""
    repo = _repo()
    state = _make_state(repo, my_don_active=1, my_don_rested=2)
    me = state.players[0]
    assert _can_pay_effect_cost(me, {"pay_don": 3}) is True
    assert _can_pay_effect_cost(me, {"pay_don": 4}) is False


def test_can_pay_effect_cost_discard_hand_requires_extra_for_event_trash():
    """discard_hand: 1 → event 自身 trash の 分 + 1 枚 必要 = hand >= 2。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    me.hand = [repo.get("OP01-013")]
    assert _can_pay_effect_cost(me, {"discard_hand": 1}) is False
    me.hand = [repo.get("OP01-013"), repo.get("OP01-013")]
    assert _can_pay_effect_cost(me, {"discard_hand": 1}) is True


def test_can_pay_effect_cost_subtracts_event_play_cost():
    """event_play_cost が active から 引かれる (= rest_self_don 評価)。"""
    repo = _repo()
    state = _make_state(repo, my_don_active=5)
    me = state.players[0]
    # active=5 で event_play_cost=3 → 残 active=2 → rest_self_don:3 失敗
    assert _can_pay_effect_cost(me, {"rest_self_don": 3}, event_play_cost=3) is False
    assert _can_pay_effect_cost(me, {"rest_self_don": 2}, event_play_cost=3) is True


# ─────────────────────────────────────────────────────
# _is_event_main_effect_unfirable: 神避 シナリオ
# ─────────────────────────────────────────────────────


def test_kami_yoke_unfirable_when_cost_insufficient():
    """神避 (OP13-076)、 active=2 → rest_self_don:5 不能 → unfirable=True。"""
    repo = _repo()
    state = _make_state(repo, my_don_active=2)
    me = state.players[0]
    opp = state.players[1]
    kami_yoke = repo.get("OP13-076")
    me.hand = [kami_yoke, repo.get("OP01-013")]
    assert _is_event_main_effect_unfirable(
        state, me, opp, kami_yoke, state.effects_overlay
    ) is True


def test_kami_yoke_unfirable_when_no_attached_don():
    """active=5 で rest_self_don 払えても attached_don=0 → if 失敗 → unfirable=True。"""
    repo = _repo()
    state = _make_state(repo, my_don_active=5)
    me = state.players[0]
    opp = state.players[1]
    kami_yoke = repo.get("OP13-076")
    me.hand = [kami_yoke, repo.get("OP01-013")]
    # me.leader.attached_dons = 0、 me.characters 空 → self_attached_don_ge:1 不成立
    assert _is_event_main_effect_unfirable(
        state, me, opp, kami_yoke, state.effects_overlay
    ) is True


def test_kami_yoke_firable_when_active_and_attached_don_ok():
    """active=5 + leader に attached_don=1 → cost + if 共に満たす → unfirable=False。"""
    repo = _repo()
    state = _make_state(repo, my_don_active=5)
    me = state.players[0]
    opp = state.players[1]
    kami_yoke = repo.get("OP13-076")
    me.hand = [kami_yoke, repo.get("OP01-013")]
    me.leader.attached_dons = 1
    # opp に 1 体 chara を 置いて target 確保
    opp.characters = [InPlay.of(repo.get("OP07-021"), sickness=False)]
    assert _is_event_main_effect_unfirable(
        state, me, opp, kami_yoke, state.effects_overlay
    ) is False


def test_unfirable_returns_false_when_no_overlay():
    """overlay 不在 (= 判定不能) なら False (= 撃つに任せる)。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    kami_yoke = repo.get("OP13-076")
    assert _is_event_main_effect_unfirable(state, me, opp, kami_yoke, {}) is False
    assert _is_event_main_effect_unfirable(state, me, opp, kami_yoke, None) is False  # type: ignore[arg-type]


def test_unfirable_returns_false_when_no_main_effect():
    """when=main 効果が 1 つも ない bundle (= counter 専用 等) は False (= 判定対象外)。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    fake_event = repo.get("OP13-076")
    counter_only_overlay = {
        fake_event.card_id: CardEffectBundle(
            card_id=fake_event.card_id,
            effects=[
                {"when": "counter", "cost": {"discard_hand": 1}, "do": []},
            ],
        ),
    }
    assert _is_event_main_effect_unfirable(
        state, me, opp, fake_event, counter_only_overlay
    ) is False


# ─────────────────────────────────────────────────────
# prune_mechanical_waste: PlayEvent が 削除 される か
# ─────────────────────────────────────────────────────


def test_prune_removes_unfirable_play_event():
    """神避 を 撃てない 状態 で PlayEvent が prune される (= safety: 元 list 返さない)。"""
    repo = _repo()
    state = _make_state(repo, my_don_active=2)
    me = state.players[0]
    me.hand = [repo.get("OP13-076"), repo.get("OP01-013")]
    # PlayEvent + 他に 1 つ (= EndPhase 代替) で 2 候補
    from engine.game import EndPhase
    actions = [PlayEvent(hand_idx=0), EndPhase()]
    pruned = prune_mechanical_waste(state, actions)
    # 神避 は 削除 → EndPhase のみ 残る
    assert not any(isinstance(a, PlayEvent) for a in pruned)
    assert any(isinstance(a, EndPhase) for a in pruned)


def test_prune_keeps_firable_play_event():
    """active=5 + attached_don=1 (= 撃てる 状態) では PlayEvent が 残る。"""
    repo = _repo()
    state = _make_state(repo, my_don_active=5)
    me = state.players[0]
    opp = state.players[1]
    me.hand = [repo.get("OP13-076"), repo.get("OP01-013")]
    me.leader.attached_dons = 1
    opp.characters = [InPlay.of(repo.get("OP07-021"), sickness=False)]
    from engine.game import EndPhase
    actions = [PlayEvent(hand_idx=0), EndPhase()]
    pruned = prune_mechanical_waste(state, actions)
    assert any(isinstance(a, PlayEvent) for a in pruned)


def test_prune_safety_fallback_returns_original():
    """全 action が prune される 場合 は 元リスト を 返す (= AI 破綻 防止)。"""
    repo = _repo()
    state = _make_state(repo, my_don_active=2)
    me = state.players[0]
    me.hand = [repo.get("OP13-076")]
    # PlayEvent 単独 → prune で 0 → 元 list 返却
    actions = [PlayEvent(hand_idx=0)]
    pruned = prune_mechanical_waste(state, actions)
    assert pruned == actions  # 元 list そのもの


# ─────────────────────────────────────────────────────
# prune_mechanical_waste: EndPhase 早期 end 抑制 (= 2026-05-27)
# bad_moves 1342 mirror で 全 bad move が EndPhase = DON 余・ 攻撃可能 で 終了 と 判明
# ─────────────────────────────────────────────────────


def test_prune_removes_endphase_when_play_character_legal():
    """PlayCharacter が legal なら EndPhase は 排除 (= 早期 end 抑制)。"""
    from engine.game import EndPhase, PlayCharacter
    repo = _repo()
    state = _make_state(repo, my_don_active=2)
    me = state.players[0]
    me.hand = [repo.get("OP01-013")]
    actions = [PlayCharacter(hand_idx=0), EndPhase()]
    pruned = prune_mechanical_waste(state, actions)
    assert any(isinstance(a, PlayCharacter) for a in pruned)
    assert not any(isinstance(a, EndPhase) for a in pruned)


def test_prune_keeps_endphase_when_only_action():
    """legal_actions が EndPhase のみ なら そのまま 残す (= safety)。"""
    from engine.game import EndPhase
    repo = _repo()
    state = _make_state(repo)
    actions = [EndPhase()]
    pruned = prune_mechanical_waste(state, actions)
    assert any(isinstance(a, EndPhase) for a in pruned)


def test_prune_keeps_endphase_when_all_others_wasteful():
    """PlayEvent unfirable + EndPhase なら EndPhase 残る (= 既存 test と 同 path safety)。"""
    from engine.game import EndPhase
    repo = _repo()
    state = _make_state(repo, my_don_active=2)
    me = state.players[0]
    me.hand = [repo.get("OP13-076")]
    actions = [PlayEvent(hand_idx=0), EndPhase()]
    pruned = prune_mechanical_waste(state, actions)
    assert any(isinstance(a, EndPhase) for a in pruned)
    assert not any(isinstance(a, PlayEvent) for a in pruned)
