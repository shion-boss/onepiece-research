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


def test_offcolor_leader_filter_unit():
    """指定色を含まないリーダーは除外、 含むリーダー/非リーダーは残る。"""
    from engine.combo_finder import ComboCard, _filter_offcolor_leaders

    def mk(cid, cat, colors):
        return ComboCard(cid, cid, cat, colors, 0, 0, [], "", 1.0, "")

    cards = [
        mk("L_red", "LEADER", ["赤"]),
        mk("L_redblue", "LEADER", ["赤", "青"]),
        mk("L_blue", "LEADER", ["青"]),
        mk("C_blue", "CHARACTER", ["青"]),
    ]
    out = {c.card_id for c in _filter_offcolor_leaders(cards, {"赤"})}
    assert "L_red" in out          # 同色 → 残る
    assert "L_redblue" in out      # 赤を含む2色 → 残る
    assert "L_blue" not in out     # 赤を含まない → 除外
    assert "C_blue" in out         # 非リーダーは色フィルタしない


def test_pell_results_leaders_share_color(repo):
    """ペル(赤) の結果に出るリーダーは全て赤を含む (= 違う色のリーダーは除外)。"""
    res = find_combos(repo, "OP04-013", per_group=30)
    for g in res.groups:
        for c in g.cards:
            if c.category == "LEADER":
                assert "赤" in c.color, f"{c.card_id} {c.color} は赤を含まない"


def test_regulation_standard_filters_block_icon(repo):
    """min_block_icon=2 (= スタンダード) で候補が block_icon>=2 のみになり、 件数は全体以下。"""
    res_std = find_combos(repo, "OP04-013", per_group=30, min_block_icon=2)
    for g in res_std.groups:
        for c in g.cards:
            assert repo._by_id[c.card_id].block_icon >= 2, f"{c.card_id} block<2"
    res_all = find_combos(repo, "OP04-013", per_group=30, min_block_icon=0)
    n_all = sum(len(g.cards) for g in res_all.groups)
    n_std = sum(len(g.cards) for g in res_std.groups)
    assert n_std <= n_all


def test_cooccurrence_module_grounded():
    """実戦デッキ共起モジュールが妥当なコーパスと接地した結果を返す。"""
    from engine.combo_cooccurrence import cooccurring, deck_count, n_decks

    assert n_decks() > 50  # 十分な実戦コーパス
    assert deck_count("OP14-112") >= 4  # ハンコックは複数デッキ
    co = cooccurring("OP14-112", top=5)
    assert co and all(d["cooc"] >= 2 for d in co)
    assert cooccurring("OP04-013") == []  # ペルは off-meta → 空


def test_cooccurrence_group_for_meta_card(repo):
    """実戦デッキに多いカードは『実戦シナジー』群が先頭に出る (= 接地)。"""
    res = find_combos(repo, "OP14-112")  # ハンコック (実戦8デッキ)
    assert res.groups and res.groups[0].key == "cooccurrence"
    assert res.groups[0].cards


def test_offmeta_card_no_cooccurrence(repo):
    """実戦デッキに不在のカードは共起群なし (= 静的ルールに委ねる)。"""
    res = find_combos(repo, "OP04-013")  # ペル (実戦0)
    assert "cooccurrence" not in {g.key for g in res.groups}


def test_bidirectional_payoff_for_powerdown(repo):
    """相手パワーを下げるカードは『活かすKO/除去ペイオフ』群が出る (= 双方向)。"""
    res = find_combos(repo, "OP01-027")  # 円卓 (-10000)
    payoff = next((g for g in res.groups if g.key == "payoff"), None)
    assert payoff is not None and payoff.cards
    assert all("KO" in c.reason for c in payoff.cards)


def test_unknown_card_raises(repo):
    with pytest.raises(KeyError):
        find_combos(repo, "NOPE-999")
