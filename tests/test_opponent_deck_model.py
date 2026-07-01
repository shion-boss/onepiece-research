"""相手デッキ belief モデル (engine/opponent_deck_model.py) のテスト。"""

from __future__ import annotations

import random

import pytest

from engine.opponent_deck_model import OpponentDeckModel, get_default_model


def _synthetic() -> OpponentDeckModel:
    """leader "L" に 3 レシピ、"S" に 1 レシピの合成 belief モデル。

    L: A は全 3 デッキ (4,4,4)、B は 1 デッキ (2)、C は 2 デッキ (4,3)。
    """
    decklists_L = [
        {"slug": "d1", "date": "", "main": [["A", 4], ["C", 4]]},
        {"slug": "d2", "date": "", "main": [["A", 4], ["B", 2]]},
        {"slug": "d3", "date": "", "main": [["A", 4], ["C", 3]]},
    ]

    def marg(dlist):
        from collections import defaultdict

        n = len(dlist)
        present, total = defaultdict(int), defaultdict(int)
        for d in dlist:
            for cid, cnt in d["main"]:
                present[cid] += 1
                total[cid] += cnt
        return {
            cid: {
                "prob": present[cid] / n,
                "exp_count": total[cid] / n,
                "mean_present": total[cid] / present[cid],
                "n": present[cid],
            }
            for cid in present
        }

    data = {
        "meta": {},
        "leaders": {
            "L": {
                "leader_name": "Leader L",
                "n_decks": 3,
                "decklists": decklists_L,
                "marginals": marg(decklists_L),
            },
            "S": {
                "leader_name": "Solo",
                "n_decks": 1,
                "decklists": [{"slug": "s1", "date": "", "main": [["X", 4]]}],
                "marginals": marg([{"main": [["X", 4]]}]),
            },
        },
    }
    return OpponentDeckModel(data)


def test_prior_marginals():
    m = _synthetic()
    b = m.belief_for_leader("L")
    assert b["A"]["prob"] == pytest.approx(1.0)
    assert b["A"]["exp_count"] == pytest.approx(4.0)
    # B は 3 デッキ中 1 デッキ、2 枚
    assert b["B"]["prob"] == pytest.approx(1 / 3)
    assert b["B"]["exp_count"] == pytest.approx(2 / 3)
    # C は 3 デッキ中 2 デッキ、平均 3.5 枚
    assert b["C"]["prob"] == pytest.approx(2 / 3)
    assert b["C"]["mean_present"] == pytest.approx(3.5)


def test_unknown_leader_is_empty():
    m = _synthetic()
    assert m.belief_for_leader("UNKNOWN") == {}
    assert m.has_leader("UNKNOWN") is False
    assert m.prob("UNKNOWN", "A") == 0.0
    assert m.sample_main("UNKNOWN") is None


def test_posterior_conditioning_sharpens():
    """相手が B を見せたら、B を積む唯一のレシピ (d2) に絞られる。"""
    m = _synthetic()
    post = m.belief_for_leader("L", seen={"B": 1})
    # d2 のみ整合 → A,B は必ず、C は消える
    assert post["A"]["prob"] == pytest.approx(1.0)
    assert post["B"]["prob"] == pytest.approx(1.0)
    assert "C" not in post


def test_posterior_no_consistent_degrades_to_prior():
    """整合レシピが無い seen は prior に degrade (空にしない)。"""
    m = _synthetic()
    post = m.belief_for_leader("L", seen={"Z": 1})  # Z はどのレシピにも無い
    prior = m.belief_for_leader("L")
    assert post == prior


def test_sample_main_respects_seen():
    m = _synthetic()
    rng = random.Random(0)
    for _ in range(20):
        sampled = m.sample_main("L", rng=rng, seen={"B": 1})
        assert sampled is not None
        cards = {cid for cid, _ in sampled}
        assert "B" in cards  # B を見せた以上、B を含むレシピしか引かない


def test_sample_main_is_coherent_real_recipe():
    """サンプルは実レシピそのもの (独立サンプリングでないので coherent)。"""
    m = _synthetic()
    rng = random.Random(1)
    sampled = m.sample_main("L", rng=rng)
    assert sampled is not None
    # d1/d2/d3 のいずれかと一致するはず
    known = [
        [("A", 4), ("C", 4)],
        [("A", 4), ("B", 2)],
        [("A", 4), ("C", 3)],
    ]
    assert sampled in known


def test_top_cards_ranked_by_exp_count():
    m = _synthetic()
    top = m.top_cards("L", n=2)
    assert top[0][0] == "A"  # exp_count 最大
    assert len(top) == 2


def test_default_model_loads():
    """ビルド済 artifact があればロードでき、既知 leader を含む。無ければ空でも壊れない。"""
    m = get_default_model()
    # artifact 未ビルドでも例外を出さないこと
    assert isinstance(m.leaders, list)
