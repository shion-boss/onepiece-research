# -*- coding: utf-8 -*-
"""engine/deck_improver.py のユニットテスト (= log 解析 + 提案生成)。"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from engine.deck import CardRepository, DeckList
from engine.deck_improver import (
    CardChange,
    CardStat,
    Proposal,
    _extract_played_cards,
    compute_card_stats,
    generate_proposals,
)

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


@pytest.fixture(scope="module")
def deck(repo) -> DeckList:
    return DeckList.from_json(ROOT / "decks" / "cardrush_1454.json", repo)


# ============================================================================ #
# log 解析
# ============================================================================ #

def test_extract_played_cards_basic():
    """play / event / stage 行を P0 視点で抽出。"""
    log = [
        "T1 P0: start: 〜",
        "T1 P0: play: シュラ (cost 1 pay 1)",
        "T1 P0: event: 雷獣 (cost 0 pay 0)",
        "T1 P0:   効果: ドロー 1 → ['万雷']",
        "T2 P1: play: しらほし (cost 5 pay 5)",  # 相手プレイ
    ]
    counter = _extract_played_cards(log, player_idx=0)
    assert counter["シュラ"] == 1
    assert counter["雷獣"] == 1
    assert "しらほし" not in counter


def test_extract_played_cards_multiple_same_card():
    log = [
        "T1 P0: play: シュラ (cost 1 pay 1)",
        "T2 P0: play: シュラ (cost 1 pay 1)",
        "T3 P0: play: シュラ (cost 1 pay 1)",
    ]
    counter = _extract_played_cards(log, player_idx=0)
    assert counter["シュラ"] == 3


def test_extract_played_cards_p1_view():
    log = [
        "T1 P0: play: シュラ (cost 1 pay 1)",
        "T2 P1: play: しらほし (cost 5 pay 5)",
        "T2 P1: event: 海王類の力 (cost 0 pay 0)",
    ]
    counter = _extract_played_cards(log, player_idx=1)
    assert "シュラ" not in counter
    assert counter["しらほし"] == 1
    assert counter["海王類の力"] == 1


# ============================================================================ #
# 統計計算
# ============================================================================ #

def test_compute_card_stats_returns_data(deck):
    """対戦データがある場合、 stats が返る (= cardrush_1454 は履歴あり)。

    V2 (2026-05-14) 注: deck pool 移行直後は新 slug の replay 履歴が薄いため、
    n_matches == 0 なら skip (= matrix 走行で蓄積後に再有効化)。
    """
    import pytest
    stats, n_matches, baseline = compute_card_stats("cardrush_1454", deck)
    if n_matches == 0:
        pytest.skip("replay 履歴が無い (= deck pool 移行直後、 matrix 走行で蓄積後に有効)")
    assert 0.0 <= baseline <= 1.0
    assert len(stats) > 0
    # 各 stat の整合
    for s in stats:
        assert s.n_in_deck >= 1
        assert s.n_appearances >= 0
        assert 0.0 <= s.winrate_when_played <= 1.0


def test_compute_card_stats_empty_for_unknown_deck(deck):
    """対戦データ無しのデッキでは empty が返る。"""
    stats, n_matches, baseline = compute_card_stats("nonexistent_slug", deck)
    assert n_matches == 0
    assert baseline == 0.0
    assert stats == []


# ============================================================================ #
# 提案生成
# ============================================================================ #

def test_generate_proposals_empty_for_no_stats(deck, repo):
    """stats が空なら proposals も空。"""
    proposals = generate_proposals([], deck, repo)
    assert proposals == []


def _synthetic_stats(deck, repo) -> list:
    """提案生成を **決定的** にするための合成 stats。

    ⚠ 従来は `compute_card_stats("cardrush_1454", deck)` の実対戦データに依存しており、
      「弱いカードが無い」 環境では `pytest.skip` = **assertion が 1 つも走らなかった**。
      デッキ内の実カードに対して 「明らかに弱い 1 枚 / 明らかに強い 1 枚」 を人工的に作り、
      提案ロジック自体を常に検証する (2026-08-10)。
    """
    counts = Counter(c.card_id for c in deck.main)
    ids = [cid for cid, _ in counts.most_common()]
    assert len(ids) >= 2, "デッキに 2 種類以上のカードが必要 (前提崩れ)"
    weak, strong = ids[0], ids[1]
    out = []
    for cid in (weak, strong):
        card = repo.get(cid)
        out.append(CardStat(
            card_id=cid, base_id=cid, name=card.name,
            n_in_deck=counts[cid],
            n_appearances=20, n_total_plays=30, n_matches=40,
            # weak = ベースラインを大きく下回る / strong = 大きく上回る
            winrate_when_played=0.20 if cid == weak else 0.85,
            deck_winrate_baseline=0.50,
        ))
    return out


def test_generate_proposals_returns_swap_or_count(deck, repo):
    """合成 stats (明確に弱い1枚 + 強い1枚) で提案が必ず生成され、 net delta が 0 になる。"""
    proposals = generate_proposals(_synthetic_stats(deck, repo), deck, repo)
    assert proposals, (
        "明確に弱いカード (勝率 20% vs baseline 50%) を与えても提案が 0 件 = "
        "提案ロジックが機能していない"
    )
    for p in proposals:
        assert p.proposal_type in ("swap", "count_decrease", "count_increase")
        # changes の delta 合計 = 0 (= 50 枚維持)
        assert sum(c.delta for c in p.changes) == 0


def test_proposal_changes_are_card_changes(deck, repo):
    """提案の changes が CardChange 型で、 delta が 0 でないこと (合成 stats で決定的に)。"""
    proposals = generate_proposals(_synthetic_stats(deck, repo), deck, repo)
    assert proposals, "合成 stats で提案が 0 件 (前提崩れ)"
    p = proposals[0]
    for c in p.changes:
        assert isinstance(c, CardChange)
        assert isinstance(c.card_id, str)
        assert isinstance(c.delta, int)
        assert c.delta != 0
