# -*- coding: utf-8 -*-
"""
MatchupProfile dynamic update Phase 7D テスト (= 2026-05-14)
============================================================

- infer_opponent_archetype が deck_classifier 経由で動作
- infer_opponent_archetype_with_confidence が信頼度を返す
- GreedyAI._ensure_matchup_overrides がターン毎に再評価
- base values が turn 変更時に保持される
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.ai import GreedyAI
from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.matchup_model import (
    _reset_caches_for_testing,
    infer_opponent_archetype,
    infer_opponent_archetype_with_confidence,
)

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _make_state(repo, opp_leader_id="OP15-058", turn=1):
    me = Player(name="me", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    opp = Player(name="opp", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    me.deck = [repo.get("OP01-013")] * 30
    opp.deck = [repo.get("OP01-013")] * 30
    state = GameState(
        players=[me, opp],
        phase=Phase.MAIN,
        rng=random.Random(1),
        turn_number=turn,
    )
    return state


# ─────────────────────────────────────────────────────
# infer_opponent_archetype with classifier
# ─────────────────────────────────────────────────────


def test_infer_archetype_uses_classifier_path():
    """classifier 経由で archetype 推定 (= 紫エネル → ミッドレンジ)。"""
    repo = _repo()
    _reset_caches_for_testing()
    state = _make_state(repo, opp_leader_id="OP15-058")
    arche = infer_opponent_archetype(state, opp_idx=1, use_classifier=True)
    assert arche == "ミッドレンジ", f"紫エネル は ミッドレンジ のはず ({arche})"


def test_infer_archetype_classifier_fallback_to_static():
    """classifier 学習データ外の leader でも fallback で archetype を返す。"""
    repo = _repo()
    _reset_caches_for_testing()
    # OP01-001 (= ロロノアゾロ、 active pool 外)
    state = _make_state(repo, opp_leader_id="OP01-001")
    arche = infer_opponent_archetype(state, opp_idx=1, use_classifier=True)
    # fallback で何らかの archetype を返す (= ARCHETYPES 内)
    assert arche in ("アグロ", "ミッドレンジ", "コントロール", "ランプ")


def test_infer_archetype_use_classifier_false_uses_static():
    """use_classifier=False で旧経路 (= static map のみ)。"""
    repo = _repo()
    _reset_caches_for_testing()
    state = _make_state(repo, opp_leader_id="OP15-058")
    arche = infer_opponent_archetype(state, opp_idx=1, use_classifier=False)
    assert arche == "ミッドレンジ"


# ─────────────────────────────────────────────────────
# infer_opponent_archetype_with_confidence
# ─────────────────────────────────────────────────────


def test_archetype_with_confidence_high_for_known_leader():
    """既知 leader での信頼度は 高い (= 0.9+)。"""
    repo = _repo()
    _reset_caches_for_testing()
    state = _make_state(repo, opp_leader_id="OP15-058")
    arche, conf = infer_opponent_archetype_with_confidence(state, opp_idx=1)
    assert arche == "ミッドレンジ"
    assert conf > 0.9, f"既知 leader での信頼度は ≥ 0.9 のはず ({conf})"


def test_archetype_with_confidence_lower_for_unknown_leader():
    """未学習 leader では (= active pool 外) 信頼度が低くなる。"""
    repo = _repo()
    _reset_caches_for_testing()
    state = _make_state(repo, opp_leader_id="OP01-001")
    arche, conf = infer_opponent_archetype_with_confidence(state, opp_idx=1)
    # 確定的でないが、 既知 leader よりは低いはず
    assert conf < 0.95


# ─────────────────────────────────────────────────────
# GreedyAI._ensure_matchup_overrides ターン毎再評価
# ─────────────────────────────────────────────────────


def test_greedy_ai_reevaluates_each_turn():
    """ターンが変わると _last_matchup_eval_turn が更新される。"""
    repo = _repo()
    _reset_caches_for_testing()
    ai = GreedyAI(rng=random.Random(0))

    # ターン 1 で評価
    state = _make_state(repo, opp_leader_id="OP15-058", turn=1)
    state.turn_player_idx = 0  # 自分のターン
    ai._ensure_matchup_overrides(state, me_idx=0)
    assert ai._last_matchup_eval_turn == 1
    profile_turn1 = ai._matchup_profile

    # 同ターン再呼出 → skip
    ai._ensure_matchup_overrides(state, me_idx=0)
    assert ai._last_matchup_eval_turn == 1  # 変わらず

    # ターン 3 に進めて再呼出 → 再評価
    state.turn_number = 3
    ai._ensure_matchup_overrides(state, me_idx=0)
    assert ai._last_matchup_eval_turn == 3
    # profile は archetype が同じなので等価値だが、 再評価したことは last_eval_turn で確認可能


def test_greedy_ai_base_values_preserved():
    """ターン毎再評価で base 値 (= deck_analysis 適用後) が保たれる。"""
    repo = _repo()
    _reset_caches_for_testing()
    # コントロール archetype の deck_analysis を渡す
    deck_analysis = {
        "archetype": "コントロール",
        "ai_hint_signals": [],
        "key_cards": [],
    }
    ai = GreedyAI(rng=random.Random(0), deck_analysis=deck_analysis)

    # コントロール の base defense_thresholds: life 4 → (5000, 2)
    base_life4 = ai._base_defense_thresholds.get(4)
    assert base_life4 == (5000, 2), f"コントロール base life=4 = (5000, 2), got {base_life4}"

    # 評価実行 (override 適用)
    state = _make_state(repo, opp_leader_id="OP15-058", turn=1)
    state.turn_player_idx = 0
    ai._ensure_matchup_overrides(state, me_idx=0)
    after_eval_life4 = ai.defense_thresholds.get(4)
    # base から override 後でも base value は維持
    assert ai._base_defense_thresholds.get(4) == (5000, 2)
    # 実 defense_thresholds は override で変わる可能性 (= db/matchup_strategies.json による)


def test_greedy_ai_per_turn_reset_to_base():
    """各ターン頭で defense_thresholds が base にリセットされてから override される。"""
    repo = _repo()
    _reset_caches_for_testing()
    deck_analysis = {
        "archetype": "コントロール",
        "ai_hint_signals": [],
        "key_cards": [],
    }
    ai = GreedyAI(rng=random.Random(0), deck_analysis=deck_analysis)

    # T1
    state = _make_state(repo, opp_leader_id="OP15-058", turn=1)
    state.turn_player_idx = 0
    ai._ensure_matchup_overrides(state, me_idx=0)
    t1_thresholds = dict(ai.defense_thresholds)

    # 人為的に defense_thresholds を破壊
    ai.defense_thresholds[1] = (99999, 99)
    ai.defense_thresholds[2] = (1, 1)

    # T3 で再評価 → base から再適用、 破壊した値は消える
    state.turn_number = 3
    ai._ensure_matchup_overrides(state, me_idx=0)
    t3_thresholds = dict(ai.defense_thresholds)

    # 同じ archetype + 同じ opp なら overrides も同じ → t1 と一致
    assert t1_thresholds == t3_thresholds, \
        f"再評価で base + override 適用、 破壊された値はリセットされるはず: t1={t1_thresholds}, t3={t3_thresholds}"
