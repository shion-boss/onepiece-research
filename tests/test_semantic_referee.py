# -*- coding: utf-8 -*-
"""SemanticReferee の CI ゲート (= 実対戦のカード保存則監視 + 非空振り証明)。

SemanticReferee は RuleReferee に「メインデッキ札の保存則」 を足した強化レフェリー。
保存則は数学的に常に真 → 誤検出ゼロ。 毎 pytest で:

1. 実 AI 対戦で保存則違反 0 (= 効果がカードを複製/消失させていない、 退行検出)。
2. 複製/消失を注入すると検出する (= 非空振り証明、 「0 件」 が空振りでない担保)。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.game import setup_game
from engine.semantic_referee import SemanticReferee, main_card_count

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def repo():
    return CardRepository.from_json(ROOT / "db" / "cards.json")


@pytest.fixture(scope="module")
def overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, overlay):
    import random
    da = DeckList.from_json(ROOT / "decks" / "cardrush_1392.json", repo)
    db = DeckList.from_json(ROOT / "decks" / "cardrush_1342.json", repo)
    return setup_game(da, db, rng=random.Random(0), effects_overlay=overlay)


def test_referee_catches_duplication(repo, overlay):
    """カードを複製 (= 手札に1枚追加) すると保存則違反を検出する。"""
    state = _state(repo, overlay)
    ref = SemanticReferee(strict=False)
    ref._capture_baseline(state)
    assert not ref.violations  # baseline 時点は当然 0
    # 複製を注入: deck の 1 枚を hand にも積む (= 総数 +1)
    state.players[0].hand.append(state.players[0].deck[0])
    ref._check_card_conservation(state)
    assert ref.violations, "カード複製を検出できていない (= 空振り)"
    assert "メインデッキ札" in ref.violations[-1]


def test_referee_catches_card_loss(repo, overlay):
    """カードを消失 (= デッキから1枚抜く) すると保存則違反を検出する。"""
    state = _state(repo, overlay)
    ref = SemanticReferee(strict=False)
    ref._capture_baseline(state)
    state.players[1].deck.pop()  # 1 枚消失
    ref._check_card_conservation(state)
    assert ref.violations, "カード消失を検出できていない (= 空振り)"


def test_referee_clean_when_cards_move(repo, overlay):
    """ゾーン間移動 (= deck → hand) は保存則を破らない (= 誤検出しない)。"""
    state = _state(repo, overlay)
    ref = SemanticReferee(strict=False)
    ref._capture_baseline(state)
    # deck top を hand へ「移動」 (= pop して append、 総数不変)
    state.players[0].hand.append(state.players[0].deck.pop())
    ref._check_card_conservation(state)
    assert not ref.violations, "正当なゾーン移動を誤検出した (= false positive)"


def test_baseline_is_50(repo, overlay):
    """標準デッキの メインデッキ札 baseline は 50 (= 保存則の前提確認)。"""
    state = _state(repo, overlay)
    for p in state.players:
        assert main_card_count(p) == 50, f"{p.name}: メイン札 {main_card_count(p)} != 50"


def test_real_ai_games_conserve_cards():
    """実 AI 対戦 (= 2 pair × 3 戦) で カード保存則違反 0。"""
    import scripts.run_semantic_referee as runner
    pairs = [("cardrush_1392", "cardrush_1342"),
             ("cardrush_1385", "cardrush_1455")]
    total, violations = runner.run(pairs, n_games=3)
    assert total > 0, "試合が走っていない"
    assert not violations, (
        f"実対戦でカード保存則違反 {len(violations)} 件: {violations[:5]}"
    )
