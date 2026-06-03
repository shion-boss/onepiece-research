# -*- coding: utf-8 -*-
"""PlanBonusTable + value fusion のテスト (= 層3/層6)。"""
from __future__ import annotations

from engine.plan_library import PlanBonusTable, fuse_value, multiset_key


def test_fuse_value_cold_equals_prior():
    """学習データ無し (n=0) では value = prior = sigmoid(eval_score/temp)。"""
    # eval_score=0 → prior=0.5
    assert abs(fuse_value(0.0, 0, 0, temp=2000, shrink_k=6) - 0.5) < 1e-9
    # 正の eval_score → prior>0.5、 負→<0.5
    assert fuse_value(4000.0, 0, 0) > 0.5
    assert fuse_value(-4000.0, 0, 0) < 0.5


def test_fuse_value_warm_moves_to_winrate():
    """データが増えると実勝率へ寄る (= prior から離れる)。"""
    # prior≈0.5 (eval 0)、 だが 100 戦 80 勝 → value は 0.5 より 0.8 寄り
    v = fuse_value(0.0, 100, 80, temp=2000, shrink_k=6)
    assert 0.7 < v < 0.8
    # 全敗なら低い
    v2 = fuse_value(0.0, 100, 0, temp=2000, shrink_k=6)
    assert v2 < 0.1


def test_table_update_and_value():
    tbl = PlanBonusTable(temp=2000, shrink_k=6)
    cell = (("turn", 4), ("opp_archetype", "control"))
    mk = multiset_key(((("play", "OP13-016")), ("attack", "leader_face")))
    for _ in range(10):
        tbl.update(cell, mk, won=True)
    for _ in range(2):
        tbl.update(cell, mk, won=False)
    n, w = tbl.get_counts(cell, mk)
    assert (n, w) == (12, 10)
    # 学習後 value は prior(0.5) より高い
    assert tbl.value(cell, mk, 0.0) > 0.6


def test_save_load_roundtrip(tmp_path):
    tbl = PlanBonusTable(temp=1500, shrink_k=4)
    cell = (("turn", 5), ("opp_archetype", "aggro"))
    mk = multiset_key((("play", "OP01-001"), ("attach_don", "leader", 1)))
    tbl.update(cell, mk, True)
    tbl.update(cell, mk, False)
    p = tmp_path / "t.json"
    tbl.save(p)
    tbl2 = PlanBonusTable.load(p)
    assert len(tbl2) == 1
    assert tbl2.get_counts(cell, mk) == (2, 1)
    assert tbl2.temp == 1500 and tbl2.shrink_k == 4


def test_merge():
    a = PlanBonusTable()
    b = PlanBonusTable()
    cell = (("turn", 3),)
    mk = multiset_key((("play", "X"),))
    a.update(cell, mk, True)
    b.update(cell, mk, False)
    b.update(cell, mk, True)
    a.merge_(b)
    assert a.get_counts(cell, mk) == (3, 2)
