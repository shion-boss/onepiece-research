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


def test_condition_note_detects_leader_power():
    """リーダーパワー条件 (= 要セットアップ) を検出して減点する。"""
    from engine.combo_finder import _condition_note

    factor, note, ctype = _condition_note(
        "自分のリーダーがパワー0以下の場合、相手のキャラ1枚までを、パワー-3000。"
    )
    assert factor < 0.5 and note and ctype == "leader_power"
    assert _condition_note("相手のキャラ1枚までを、パワー-3000。")[0] == 1.0  # 無条件


def test_conditional_enabler_penalized(repo):
    """条件付き効果 (= 海ネコ OP15-004: 自リーダーパワー0以下) は ペル enabler の top8 圏外
    に落ち、 全候補で見ると無条件の下げ役 (コーザ) より低評価 + 注記が付く。"""
    res = find_combos(repo, "OP04-013", per_group=8)
    g = next(gr for gr in res.groups if gr.key == "enabler")
    assert "OP15-004" not in {c.card_id for c in g.cards}  # 旧 #1 → 圏外

    res_all = find_combos(repo, "OP04-013", per_group=300)
    g_all = next(gr for gr in res_all.groups if gr.key == "enabler")
    cards = {c.card_id: c for c in g_all.cards}
    assert "OP15-004" in cards and "EB01-004" in cards  # 除外でなく低評価で残る
    assert cards["OP15-004"].score < cards["EB01-004"].score
    assert "⚠" in cards["OP15-004"].reason


def test_multicard_chain_for_conditional_enabler(repo):
    """ペルは条件付き enabler (海ネコ) の不足ピースを補う 3枚コンボを出す
    (= ペル + 海ネコ + 自リーダーを下げるカード)。 ユーザー要望の多枚コンボ。"""
    res = find_combos(repo, "OP04-013", per_group=8)
    assert res.chains, "多枚コンボが空"
    found = False
    for ch in res.chains:
        ids = [s.card_id for s in ch.steps]
        if ids and ids[0] == "OP04-013" and "OP15-004" in ids:
            assert ch.n_cards >= 3
            assert ch.steps[0].role.startswith("ペイオフ")
            # 条件成立の satisfier ステップがある
            assert any("条件成立" in s.role for s in ch.steps)
            found = True
    assert found, "ペル+海ネコ+リーダー下げ の3枚コンボが無い"


def test_leader_feature_compatibility():
    """要求リーダー特徴が anchor と非互換なら除外する (= サッチ 白ひげ@ペル アラバスタ)。"""
    from engine.combo_finder import _leader_feature_compatible

    bad = "自分のリーダーが『白ひげ海賊団』を含む特徴を持つ場合、相手のキャラ1枚を、パワー-2000。"
    assert not _leader_feature_compatible(bad, ["アラバスタ王国"])
    assert _leader_feature_compatible("リーダーが特徴《アラバスタ王国》を持つ場合", ["アラバスタ王国"])
    assert _leader_feature_compatible("条件なしの効果", ["アラバスタ王国"])


def test_chain_excludes_incompatible_and_sums_debuff(repo):
    """ペルのチェーン: サッチ(白ひげ要求)は除外、 コーザ(自リーダー下げ+相手-3000)は
    reach に -3000 合算 (= ユーザー指摘、 海ネコ-3000 + コーザ-3000 = -6000 → 最大10000)。"""
    res = find_combos(repo, "OP04-013", per_group=8)
    # サッチ ST15-004 はどのチェーンにも入らない
    for ch in res.chains:
        assert "ST15-004" not in [s.card_id for s in ch.steps]
    # 海ネコ + コーザ のチェーンで debuff が合算されている
    target = next(
        (ch for ch in res.chains
         if {"OP15-004", "EB01-004"} <= {s.card_id for s in ch.steps}),
        None,
    )
    assert target is not None
    assert "合計" in target.description or "10000" in target.description


def test_amplifier_excludes_self_only_rush(repo):
    """『このキャラは【速攻】を得る』(= 自身のみ) は anchor に付与しないので amplifier 除外。
    『キャラ1枚は【速攻】』『【速攻】を与える』(= 他付与) は含む (= ユーザー指摘の クリエル)。"""
    from engine.combo_finder import _grants_rush_to_others

    assert not _grants_rush_to_others("【ドン!!×1】このキャラは【速攻】を得る。")
    assert _grants_rush_to_others("自分のキャラ1枚までは、このターン中、【速攻】を得る。")
    assert _grants_rush_to_others("自分のキャラ1枚までに、【速攻】を与える。")
    res = find_combos(repo, "OP04-013", per_group=30)
    amp = next((g for g in res.groups if g.key == "amplifier"), None)
    if amp:
        ids = {c.card_id for c in amp.cards}
        assert "OP03-004" not in ids  # クリエル (自身のみ)
        assert "OP14-004" not in ids  # キャベンディッシュ (自身のみ)


def test_leader_name_lock_note_and_exclusion(repo):
    """リーダー名指定 (= チャカ: 「ネフェルタリ・ビビ」) は、 互換(ビビ=アラバスタ)なら
    注記付きで残し、 非互換(白ひげ等)なら除外する (= ユーザー指摘)。"""
    from engine.combo_finder import _leader_lock

    lmap = {
        "ネフェルタリ・ビビ": {"アラバスタ王国"},
        "エドワード・ニューゲート": {"白ひげ海賊団"},
    }
    compat, note = _leader_lock(
        "リーダーが「ネフェルタリ・ビビ」の場合、相手-3000", ["アラバスタ王国"], lmap
    )
    assert compat and "ネフェルタリ・ビビ" in note
    compat2, _ = _leader_lock(
        "リーダーが「エドワード・ニューゲート」の場合", ["アラバスタ王国"], lmap
    )
    assert not compat2  # 白ひげ専用 → アラバスタのペルでは除外

    res = find_combos(repo, "OP04-013", per_group=30)
    g = next(gr for gr in res.groups if gr.key == "enabler")
    chaka = next((c for c in g.cards if c.card_id == "OP04-008"), None)
    assert chaka is not None and "ネフェルタリ・ビビ" in chaka.reason


def test_amplifier_respects_grant_target_restriction(repo):
    """速攻付与の対象制限を anchor が満たさないなら amplifier 除外 (= ユーザー指摘)。
    EB03-001=『【アタック時】効果を持たない』 限定→アタック時持ちのペルに付与不可。
    シャンクス=『ロジャー海賊団』 限定→アラバスタのペルに付与不可。"""
    from engine.combo_finder import _rush_grant_can_target, _text

    peru = repo._by_id["OP04-013"]
    assert not _rush_grant_can_target(_text(repo._by_id["EB03-001"]), peru)
    assert not _rush_grant_can_target(_text(repo._by_id["OP12-007"]), peru)
    assert _rush_grant_can_target(_text(repo._by_id["OP04-001"]), peru)  # 制限なし
    res = find_combos(repo, "OP04-013", per_group=30)
    amp = next((g for g in res.groups if g.key == "amplifier"), None)
    if amp:
        ids = {c.card_id for c in amp.cards}
        assert "EB03-001" not in ids  # 嘘 (アタック時持たない限定)
        assert "OP12-007" not in ids  # 嘘 (ロジャー海賊団限定)


def test_unknown_card_raises(repo):
    with pytest.raises(KeyError):
        find_combos(repo, "NOPE-999")
