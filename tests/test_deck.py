# -*- coding: utf-8 -*-
"""デッキ構築ルールのテスト。"""

from __future__ import annotations

from pathlib import Path

from engine.deck import CardRepository, DeckList, _base_id, make_deck_from_dict

ROOT = Path(__file__).resolve().parent.parent


def test_base_id_strip_variant():
    assert _base_id("OP01-013") == "OP01-013"
    assert _base_id("OP06-049_p1") == "OP06-049"
    assert _base_id("ST12-005_p1") == "ST12-005"


def test_validate_4copy_via_base_id():
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    # OP06-049 (青センゴク) と OP06-049_p1 はパラレル違いだが同名
    fake = {
        "name": "test base_id 4枚",
        "leader": "OP01-060",  # 青ドフラ
        "main": (
            [{"card_id": "OP06-049", "count": 3}]
            + [{"card_id": "OP06-049_p1", "count": 2}]   # 合計5枚 → 違反
            + [{"card_id": "EB02-001", "count": 4}] * 11
            + [{"card_id": "EB01-005", "count": 1}]      # 合計 50
        ),
    }
    deck = make_deck_from_dict(fake, repo)
    issues = deck.validate()
    assert any("OP06-049" in i and "x 5" in i for i in issues), issues


def test_validate_existing_decks_pass():
    """decks/*.json (cardrush 産メタ含む) は基本的に validate() が空であるべき。
    レシピが古く現禁止リストに違反するもの (黒黄モリア / 青黄ハンコック等) は別途 archive 済。"""
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    # *.analysis.json は分析メタデータなのでデッキ本体から除外
    deck_paths = sorted(
        p
        for p in (ROOT / "decks").glob("*.json")
        if not p.name.endswith(".analysis.json")
    )
    assert deck_paths, "decks/ にデッキファイルが無い"
    failures = []
    for p in deck_paths:
        try:
            deck = DeckList.from_json(p, repo)
        except Exception as e:
            failures.append(f"{p.name}: load failed: {e}")
            continue
        issues = deck.validate()
        if issues:
            failures.append(f"{p.name}: {issues}")
    assert not failures, "\n".join(failures)


def test_validate_forbidden_card_detected():
    """禁止カードが入っていたら違反として検出。"""
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    # OP03-040 ナミ は現行 banlist の禁止カード
    fake = {
        "name": "禁止カード採用テスト",
        "leader": "OP01-001",  # 赤ゾロ
        "main": (
            [{"card_id": "OP03-040", "count": 1}]   # 禁止
            + [{"card_id": "EB01-005", "count": 4}] * 12
            + [{"card_id": "OP01-013", "count": 1}]
        ),
    }
    deck = make_deck_from_dict(fake, repo)
    issues = deck.validate()
    assert any("禁止カード採用" in i and "OP03-040" in i for i in issues), issues


def test_validate_forbidden_pair_detected():
    """禁止ペア (OP07-115 と EB04-058) を両方入れたら違反。"""
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    # 黄リーダーが必要 (OP07-115/EB04-058 とも黄)
    # OP07-001 を仮で使う (黄リーダー存在チェック)
    try:
        repo.get("OP07-001")  # 黄リーダー
        leader = "OP07-001"
    except KeyError:
        # 別の黄リーダーで代用
        leader = "OP02-001"  # 赤白ひげ - ペア検証だけなら色チェック違反は別問題

    fake = {
        "name": "禁止ペアテスト",
        "leader": leader,
        "main": (
            [{"card_id": "OP07-115", "count": 1}]
            + [{"card_id": "EB04-058", "count": 1}]
            + [{"card_id": "EB02-001", "count": 4}] * 12
        ),
    }
    deck = make_deck_from_dict(fake, repo)
    issues = deck.validate()
    assert any("禁止ペア違反" in i and "OP07-115" in i and "EB04-058" in i for i in issues), issues


def test_validate_skip_banlist_when_empty():
    """banlist={} を渡せば banlist 検証はスキップされる。"""
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    fake = {
        "name": "禁止カード採用 (banlist スキップ)",
        "leader": "OP01-001",
        "main": (
            [{"card_id": "OP03-040", "count": 1}]
            + [{"card_id": "EB01-005", "count": 4}] * 12
            + [{"card_id": "OP01-013", "count": 1}]
        ),
    }
    deck = make_deck_from_dict(fake, repo)
    issues = deck.validate(banlist={})
    # 禁止カード違反は出ないはず (banlist 空)
    assert not any("禁止カード採用" in i for i in issues), issues
