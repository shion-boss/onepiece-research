# -*- coding: utf-8 -*-
"""デッキ自動生成 (engine/deck_generator) のテスト。 sim を伴わない combo-only mode で高速検証。"""
import random
from pathlib import Path

import pytest

from engine.deck import CardRepository
from engine.deck_generator import generate_deck

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def test_generate_fixes_cards_and_assembles_combos(repo):
    """固定カードを必ず含み、 コンボ相棒を引き込んで combo_strength を上げる (= 共有コア活用)。"""
    cands = generate_deck(
        repo, "OP15-058", ["OP15-075", "OP15-061"], n_candidates=5, rng=random.Random(1)
    )
    assert cands
    best = cands[0]
    # 合法な 50 枚 + 固定カードが入っている
    assert len(best.deck.main) == 50
    ids = {c.card_id for c in best.deck.main}
    assert "OP15-075" in ids and "OP15-061" in ids
    # コンボ相棒を assemble して combo_strength が素の固定ペア (約9) を大きく超える
    assert best.combo_strength > 20.0
    # score 降順
    assert [c.score for c in cands] == sorted((c.score for c in cands), reverse=True)


def test_must_include_capped_to_five(repo):
    """使いたいカードは重複除去・最大5枚。 超過しても build は壊れない。"""
    six = ["OP15-075", "OP15-061", "OP15-076", "OP13-076", "OP15-061", "OP05-077"]
    cands = generate_deck(repo, "OP15-058", six, n_candidates=2, rng=random.Random(1))
    assert cands and len(cands[0].deck.main) == 50


def test_generated_decks_are_standard_legal(repo):
    """生成デッキはスタンダード合法 (= block②+)。 build_with_core が block①のみのカードで
    埋めて非合法デッキを作っていたバグの回帰ガード (= 固定カードが合法なら validate 空)。"""
    cands = generate_deck(repo, "OP15-058", ["OP15-075", "OP15-061"], n_candidates=4, rng=random.Random(2))
    for c in cands:
        assert c.deck.validate() == [], f"非合法デッキ: {c.deck.validate()[:2]}"


def test_combo_only_ranks_by_combo_strength(repo):
    """opponents 未指定 (combo-only) は combo_strength 主体でランクされ、 全候補 50 枚。"""
    cands = generate_deck(repo, "OP15-058", ["OP15-075"], n_candidates=6, rng=random.Random(7))
    assert all(len(c.deck.main) == 50 for c in cands)
    assert all(c.win_rate is None for c in cands)  # sim なし
    assert cands[0].combo_strength == max(c.combo_strength for c in cands)
