# -*- coding: utf-8 -*-
"""回帰テスト: 多属性カード (「斬/打」 等) が 「属性(X)を持つ」 filter / target に
正しくマッチすることを確認する。

バグ (2026-06-10 発見, cardrush_1453 緑ミホーク プレイ中):
  _matches_filter の attribute 判定が 完全一致 (card.attribute != filt["attribute"])
  だったため、 ロー&ベポ「斬/打」 や キッド&キラー「斬/特」 が ペローナ OP12-034 の
  search「属性(斬)を持つカード」 から 取りこぼされていた。 公式「属性(X)を持つ」 =
  X が card の (「/」区切り) 属性に含まれれば真。 substring `in` 方式に統一して修正。
"""

from __future__ import annotations

from pathlib import Path

from engine.deck import CardRepository
from engine.effects import _matches_filter

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def test_multi_attribute_matches_single_attribute_filter():
    repo = _repo()
    # ST24-004 ロー&ベポ = 「斬/打」、 ST24-002 キッド&キラー = 「斬/特」 → どちらも 斬 を持つ
    assert _matches_filter(repo.get("ST24-004"), {"attribute": "斬"}) is True
    assert _matches_filter(repo.get("ST24-002"), {"attribute": "斬"}) is True
    # 単一属性 斬 も当然マッチ
    assert _matches_filter(repo.get("OP13-031"), {"attribute": "斬"}) is True
    # 斬 を持たないカードは除外 (OP12-034 ペローナ = 属性なし扱い)
    assert _matches_filter(repo.get("OP12-034"), {"attribute": "斬"}) is False
    # 打 側もマッチ (ロー&ベポ「斬/打」)
    assert _matches_filter(repo.get("ST24-004"), {"attribute": "打"}) is True
    # 「斬/打」 は 知 を持たない
    assert _matches_filter(repo.get("ST24-004"), {"attribute": "知"}) is False


def test_perona_op12_034_search_or_clauses_includes_multi_attr():
    """ペローナ OP12-034 の search filter (属性(斬) OR 緑イベント) が
    多属性 斬 キャラを拾えること。"""
    repo = _repo()
    filt = {"or_clauses": [{"attribute": "斬"}, {"category": "EVENT", "color": "緑"}]}
    assert _matches_filter(repo.get("ST24-004"), filt) is True  # 斬/打 → 斬 節で通る
    assert _matches_filter(repo.get("ST24-002"), filt) is True  # 斬/特 → 斬 節で通る
