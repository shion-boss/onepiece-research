# -*- coding: utf-8 -*-
"""
MCTSAI (ISMCTS + PUCT) のスモークテスト
======================================

Phase 2 で書き換えた MCTSAI が:
- determinize_state (ISMCTS) で opp.hand を直視しない
- PUCT 選択 / EvalGreedyAI ロールアウトで動作する
- 後方互換 (旧 n_simulations / c_uct パラメータ) で従来通り使える
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.ai import EvalGreedyAI, GreedyAI, MCTSAI
from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.harness import run_matchup

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _make_state(repo) -> GameState:
    """シンプルな対戦状態 (両者リーダーのみ)。"""
    p1 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p2 = Player(name="P1", leader=InPlay.of(repo.get("OP01-002"), sickness=False))
    p1.hand = [repo.get("OP01-013")] * 5
    p2.hand = [repo.get("OP01-013")] * 5
    p1.deck = [repo.get("OP01-013")] * 40
    p2.deck = [repo.get("OP01-013")] * 40
    return GameState(
        players=[p1, p2],
        phase=Phase.MAIN,
        rng=random.Random(0),
        effects_overlay={},
    )


def test_mcts_choose_action_returns_legal_action():
    """MCTSAI.choose_action がクラッシュせず合法手を返す。"""
    from engine.game import legal_actions

    repo = _repo()
    state = _make_state(repo)
    ai = MCTSAI(
        rng=random.Random(42),
        n_simulations_critical=20,
        n_simulations_default=10,
        rollout_depth=10,
    )
    action = ai.choose_action(state)
    legal = legal_actions(state)
    assert action in legal, f"返された手が合法手に含まれていない: {action}"


def test_mcts_backward_compat_old_params():
    """旧 n_simulations / c_uct パラメータで後方互換動作する。"""
    repo = _repo()
    state = _make_state(repo)
    ai = MCTSAI(
        rng=random.Random(0),
        n_simulations=15,
        c_uct=1.41,
        rollout_depth=10,
    )
    # 旧 n_simulations が critical/default 両方に適用される
    assert ai.n_simulations_critical == 15
    assert ai.n_simulations_default == 15
    assert ai.c_puct == 1.41
    # 動作確認
    action = ai.choose_action(state)
    assert action is not None


def test_mcts_adaptive_n_simulations():
    """n_simulations_critical と n_simulations_default が個別設定可能。"""
    ai = MCTSAI(
        n_simulations_critical=100,
        n_simulations_default=20,
    )
    assert ai.n_simulations_critical == 100
    assert ai.n_simulations_default == 20


def test_mcts_priors_normalized():
    """_compute_priors が合計 1.0 に正規化された prior を返す。"""
    repo = _repo()
    state = _make_state(repo)
    ai = MCTSAI(rng=random.Random(0))
    from engine.game import legal_actions
    actions = list(legal_actions(state))
    if len(actions) > 1:
        priors = ai._compute_priors(state, actions)
        assert len(priors) == len(actions)
        assert abs(sum(priors) - 1.0) < 1e-6
        assert all(0.0 <= p <= 1.0 for p in priors)


def test_mcts_runs_full_game():
    """MCTSAI vs GreedyAI で 1 試合完走 (= 終局に到達)。"""
    repo = _repo()
    from engine.deck import DeckList

    deck_a = DeckList(
        name="MCTS test A",
        leader=repo.get("OP01-001"),
        main=[repo.get("OP01-013")] * 50,
        slug="mcts_test_a",
    )
    deck_b = DeckList(
        name="MCTS test B",
        leader=repo.get("OP01-002"),
        main=[repo.get("OP01-013")] * 50,
        slug="mcts_test_b",
    )

    # 低い simulation 数で早く終わるように (factory は ai 単体のコンストラクタ)
    class _FastMCTS(MCTSAI):
        def __init__(self, rng=None, deck_analysis=None):
            super().__init__(
                rng=rng,
                n_simulations_critical=10,
                n_simulations_default=5,
                rollout_depth=8,
                deck_analysis=deck_analysis,
            )

    report = run_matchup(
        deck_a,
        deck_b,
        n_games=1,
        seed=42,
        ai_factory_1=_FastMCTS,
        ai_factory_2=GreedyAI,
        max_actions_per_game=500,
    )
    # 1 試合完走 (勝敗どちらでもよい、 引き分けも許容)
    total = report.deck1_wins + report.deck2_wins + report.draws
    assert total == 1, f"1 試合完走しなかった: wins={report.deck1_wins}/{report.deck2_wins}, draws={report.draws}"
