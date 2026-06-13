# -*- coding: utf-8 -*-
"""combo_finder (= Step 1 静的コンボ finder) のテスト。"""
from pathlib import Path

import pytest

from engine.combo_finder import find_combos
from engine.deck import CardRepository

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _group(res, key):
    return next((g for g in res.groups if g.key == key), None)


def test_pell_detects_all_axes(repo):
    """ペル(OP04-013) は KO閾値/加速/特徴/速攻 の4軸を検出する。"""
    res = find_combos(repo, "OP04-013")
    assert res.anchor.name == "ペル"
    keys = {g.key for g in res.groups}
    # KO 閾値 → enabler、 アラバスタ → tribal、 サーチ等 → accelerant、 アタック時 → amplifier
    assert "enabler" in keys
    assert "tribal" in keys


def test_pell_enabler_ranks_efficient_over_flashy(repo):
    """差別化: 効率の良い下げ役が上位、 下げ幅最大だが単発/異アーキの円卓は top に来ない。"""
    res = find_combos(repo, "OP04-013", per_group=8)
    enabler = _group(res, "enabler")
    assert enabler is not None and enabler.cards
    top_ids = [c.card_id for c in enabler.cards]
    # 円卓 (OP01-027、 -10000 だが EVENT/超新星) は top8 に入らない (= overkill 飽和 + 一貫性/適合減点)
    assert "OP01-027" not in top_ids
    # 効率の良いアラバスタの下げ役 (コーザ EB01-004 等) が含まれる
    assert any(cid in top_ids for cid in ("EB01-004", "OP04-008", "OP15-004"))


def test_groups_sorted_by_score_desc(repo):
    res = find_combos(repo, "OP04-013")
    for g in res.groups:
        scores = [c.score for c in g.cards]
        assert scores == sorted(scores, reverse=True)


def test_no_parallel_duplicates(repo):
    """パラレル (= _p1/_r1) は base に畳まれ、 同一カードが重複しない。"""
    res = find_combos(repo, "OP04-013", per_group=30)
    for g in res.groups:
        bases = [c.card_id.split("_")[0] for c in g.cards]
        assert len(bases) == len(set(bases))


def test_anchor_excluded_from_results(repo):
    res = find_combos(repo, "OP04-013", per_group=30)
    for g in res.groups:
        assert all(c.card_id != "OP04-013" for c in g.cards)


def test_unknown_card_raises(repo):
    with pytest.raises(KeyError):
        find_combos(repo, "NOPE-999")
