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


def test_anchor_own_parallel_excluded(repo):
    """anchor 自身のパラレル別アート (= _p1/_r1) は候補に出さない。
    ⚠ 2026-06-15 検出: PRB02-012 ナミ の accelerant に PRB02-012_p1 が
    「自分をサーチ」 として混入していた (= 同一カードのコンボは嘘)。"""
    from engine.combo_finder import _base_id

    for anchor_id in ("PRB02-012", "OP05-004", "OP04-013"):
        res = find_combos(repo, anchor_id, per_group=30)
        anchor_base = _base_id(anchor_id)
        for g in res.groups:
            assert all(
                _base_id(c.card_id) != anchor_base for c in g.cards
            ), f"{anchor_id}: self-parallel leaked into [{g.key}]"
        # チェーンは step0 が anchor 本体 (= ペイオフ) なので、 それ以外の step に
        # anchor のパラレルが混ざっていないことだけ確認する。
        for ch in res.chains:
            assert all(_base_id(s.card_id) != anchor_base for s in ch.steps[1:])


def test_feature_target_character_restricted_unit(repo):
    """『《X》を持つキャラカード』 サーチは character 限定、 『《X》を持つカード』 は非限定。"""
    from engine.combo_finder import _feature_target_is_character_restricted as restr

    t_char = "デッキの上から4枚を見て、特徴《超新星》か《麦わらの一味》を持つキャラカード1枚までを公開し、手札に加える。"
    assert restr(t_char, "超新星") is True       # AかB リストでも キャラ を拾う
    assert restr(t_char, "麦わらの一味") is True
    t_any = "「ジンベエ」以外の特徴《王下七武海》を持つカード1枚までを公開し、手札に加える。"
    assert restr(t_any, "王下七武海") is False    # 「カード」 (キャラ無し) は非限定
    # 条件節「リーダーが《X》を持つ場合」 は検索動詞が同文に無いので誤判定しない
    t_cond = "相手のキャラ1枚をKO。自分のリーダーが特徴《海軍》を持つ場合、カード1枚を引く。"
    assert restr(t_cond, "海軍") is False


def test_event_anchor_no_kyara_restricted_search(repo):
    """イベント anchor に『キャラカード限定』 サーチを提案しない (= イベントは拾えない)。"""
    # OP13-038 ゴムゴムの象銃 (EVENT 麦わらの一味) に OP14-019 (キャラカードサーチ) を出さない
    res = find_combos(repo, "OP13-038", per_group=30)
    acc = _group(res, "accelerant")
    ids = [c.card_id for c in (acc.cards if acc else [])]
    assert "OP14-019" not in ids


def test_event_anchor_no_cheat_summon(repo):
    """イベント/ステージ anchor に「踏み倒し登場」 (= 登場させる) は提案しない。
    ⚠ 2026-06-15 検出: EVENT に「《X》を踏み倒し登場」 が 1113 件混入していた
    (= イベントは『登場』 しない)。 同特徴の相棒は tribal 群に出る。"""
    # EB01-009「うるせェ!!!いこう!!!!」 = EVENT, 麦わらの一味
    res = find_combos(repo, "EB01-009", per_group=30)
    for g in res.groups:
        for c in g.cards:
            assert "踏み倒し登場" not in c.reason, f"EVENT に cheat 提案: {c.card_id}"


def test_event_anchor_no_character_cost_reduction(repo):
    """『登場させるキャラの登場コスト軽減』 をイベント anchor に提案しない (= キャラ専用)。"""
    # OP01-055「おれの”侍”になれ‼!」 = EVENT ワノ国 ; OP02-025 錦えもん は ワノ国 キャラの登場コスト減
    res = find_combos(repo, "OP01-055", per_group=30)
    acc = _group(res, "accelerant")
    ids = [c.card_id for c in (acc.cards if acc else [])]
    assert "OP02-025" not in ids


def test_ko_on_own_turn_classifies_event_main_ko():
    """KO の timing を 直近 trigger で判定 (= 【メイン】KO は自ターン、 【カウンター】KO は相手ターン)。"""
    from engine.combo_finder import _ko_on_own_turn

    assert _ko_on_own_turn("【メイン】相手のパワー3000以下のキャラ1枚を、KOする。") is True
    assert _ko_on_own_turn("【アタック時】相手のパワー5000以下のキャラをKO。") is True
    assert _ko_on_own_turn("【カウンター】相手のパワー4000以下のキャラ1枚をKOする。") is False
    assert _ko_on_own_turn("【相手のターン中】相手のパワー6000以下をKO。") is False


def test_event_ko_excludes_opp_turn_only_downer(repo):
    """自ターンに撃つ【メイン】KO (神の裁き) に、 相手ターン限定の下げ役 (クリーク) を
    enabler として混入させない。 ⚠ 2026-06-15 検出: anchor が【アタック時】 以外だと timing
    gate が効かず、 /combos・deckコンボ両方で誤混入していた共有バグ。"""
    res = find_combos(repo, "OP15-075", per_group=30)  # 神の裁き (【メイン】KO)
    enab = _group(res, "enabler")
    ids = [c.card_id for c in (enab.cards if enab else [])]
    assert "OP15-001" not in ids  # クリーク (【相手のターン中】-2000) は噛まない
    # find_deck_combos (= 同じ matcher) でも同様に除外される
    from engine.combo_finder import find_deck_combos
    deck = [repo._by_id[i] for i in ("OP15-075", "OP15-061", "OP15-001")]
    edges = find_deck_combos(deck, repo._by_id["OP15-058"]).edges
    assert not any(
        e.kind in ("enabler", "payoff") and "OP15-001" in (e.a_id, e.b_id) for e in edges
    )


def test_powerdown_own_turn_recognizes_activate_main():
    """【起動メイン】等の自ターン trigger は、 手前に【相手のターン中】 節があっても自ターン扱い。"""
    from engine.combo_finder import _powerdown_on_own_turn

    # EB04-001 風: 【相手のターン中】+2000 の後に【起動メイン】相手-1000 → 自ターンに使える
    t = ("【相手のターン中】自分のライフが1枚以下の場合、このリーダーのパワー+2000。"
         "【起動メイン】【ターン1回】相手のキャラ1枚までを、このターン中、パワー-1000。")
    assert _powerdown_on_own_turn(t) is True
    # 相手ターン限定の下げ (シャンクス OP14-027 風) は自ターン不可
    t2 = "【相手のターン中】このキャラがレストの場合、相手のキャラすべてを、パワー-2000。"
    assert _powerdown_on_own_turn(t2) is False


def test_payoff_not_built_for_opp_turn_only_powerdown(repo):
    """下げが【相手のターン中】 限定 (= 守備) の anchor には payoff 群を作らない。
    ⚠ 2026-06-15 検出: OP15-001/OP14-027/OP07-071/OP03-015 に bogus payoff が出ていた。"""
    for cid in ("OP15-001", "OP14-027", "OP07-071", "OP03-015"):
        res = find_combos(repo, cid, per_group=8)
        assert not any(g.key == "payoff" for g in res.groups), f"{cid} に opp-turn payoff 誤生成"


def test_opp_powerdown_excludes_self_and_cost():
    """相手を下げる量だけを取り、 自己デバフ/コストの -X は採らない。"""
    from engine.combo_finder import _opp_powerdown_amount

    # 自己デバフ (このキャラ/自分のリーダーを下げる) → None
    assert _opp_powerdown_amount("【相手のターン中】このキャラのパワー-2000。") is None
    assert _opp_powerdown_amount("自分のリーダーを、このターン中、パワー-2000できる。") is None
    # 相手対象 → 量
    assert _opp_powerdown_amount("相手のキャラ1枚までを、このターン中、パワー-2000。") == 2000
    # コーザ: コスト側 -5000 (自分のリーダー) でなく 相手側 -3000 を採る
    koza = ("【アタック時】自分のアクティブのリーダー1枚を、このターン中、パワー-5000する"
            "ことができる：相手のキャラ1枚までを、このターン中、パワー-3000。")
    assert _opp_powerdown_amount(koza) == 3000


def test_payoff_not_built_for_self_debuff_anchor(repo):
    """自己デバフ (相手を下げない) カードに payoff 群を作らない。
    ⚠ 2026-06-15 検出: EB02-005 ニセ麦わら (このキャラ-2000) 等に bogus payoff が出ていた。"""
    for cid in ("EB02-005", "P-092", "OP05-001"):
        res = find_combos(repo, cid, per_group=8)
        assert not any(g.key == "payoff" for g in res.groups), f"{cid} に payoff 誤生成"


def test_payoff_timing_gate_consistent_across_entrypoints(repo):
    """payoff の timing gate が find_combos と find_deck_combos で一致する (= gate を matcher に
    集約した de-drift の証跡。 片方の entrypoint だけ直して乖離する事故を pin する)。"""
    from engine.combo_finder import find_deck_combos

    BAKARA = "EB03-007"  # パワー6000以下KO (= payoff の受け手)

    def deck_payoff_anchor_ids(anchor_id):
        deck = [repo._by_id[anchor_id], repo._by_id[BAKARA]]
        edges = find_deck_combos(deck, None).edges
        return {e.a_id for e in edges if e.kind == "payoff"}

    def combos_has_payoff(anchor_id):
        return any(g.key == "payoff" for g in find_combos(repo, anchor_id, per_group=8).groups)

    # 自ターンの下げ (ペル OP05-014 = -2000) → 両 entrypoint で payoff あり
    assert "OP05-014" in deck_payoff_anchor_ids("OP05-014")
    assert combos_has_payoff("OP05-014")
    # 相手ターン限定の下げ (クリーク) → 両 entrypoint で payoff なし
    assert "OP15-001" not in deck_payoff_anchor_ids("OP15-001")
    assert not combos_has_payoff("OP15-001")


def test_target_cost_limit_scoped_to_search_clause():
    """検索の『コストN以下』 は対象の手前 (= 同じ検索句) だけから取る。
    別節の コスト制限を誤適用しない (= PRB02-007 ジンベエ の【アタック時】コスト1以下)。"""
    from engine.combo_finder import _target_cost_limit

    # ST13-019: 「コスト5以下の、「サボ」か…」 → 名前の手前に コスト5以下
    t1 = "自分のデッキの上から5枚を見て、コスト5以下の、「サボ」か「モンキー・D・ルフィ」1枚までを公開し、手札に加える。"
    assert _target_cost_limit(t1, t1.find("「サボ」")) == 5
    assert _target_cost_limit(t1, t1.find("「モンキー・D・ルフィ」")) == 5  # 後ろの名前も同制限
    # PRB02-007: 検索は《王下七武海》(コスト制限なし)、 コスト1以下は別の【アタック時】節
    t2 = ("自分のデッキの上から5枚を見て、「ジンベエ」以外の特徴《王下七武海》を持つカード1枚までを"
          "公開し、手札に加える。【アタック時】コスト1以下のキャラ1枚までを、デッキの下に置く。")
    assert _target_cost_limit(t2, t2.find("《王下七武海》")) is None


def test_accelerant_respects_search_cost_limit(repo):
    """コスト制限付きサーチは、 範囲外の anchor に提案しない / 範囲内・無制限は残す。"""
    # ST13-019 はコスト5以下しか拾えない → cost10 エース(OP07-119) の加速に出さない
    res_ace = find_combos(repo, "OP07-119", per_group=30)
    acc = _group(res_ace, "accelerant")
    ids = [c.card_id for c in (acc.cards if acc else [])]
    assert "ST13-019" not in ids
    # 一方、 PRB02-007 ジンベエ の《王下七武海》 サーチは無制限 → cost9 ミホークに残る
    res_mihawk = find_combos(repo, "OP01-070", per_group=30)
    acc2 = _group(res_mihawk, "accelerant")
    ids2 = [c.card_id for c in (acc2.cards if acc2 else [])]
    assert "PRB02-007" in ids2


def test_find_deck_combos_extracts_intra_deck_edges(repo):
    """デッキ内の実在コンボを edge 抽出する。 ペル(KO≤4000) + コーザ(相手-3000) = enabler。"""
    from engine.combo_finder import find_deck_combos

    ids = ["OP04-013", "EB01-004", "OP04-008", "OP13-012"]  # ペル/コーザ/チャカ/ビビ(search)
    deck = [repo._by_id[i] for i in ids]
    leader = repo._by_id["EB03-001"]  # ネフェルタリ・ビビ (アラバスタ王国)
    m = find_deck_combos(deck, leader)
    # ペル起点の enabler edge にコーザが入る
    enabler = {(e.a_id, e.b_id) for e in m.edges if e.kind == "enabler"}
    assert ("OP04-013", "EB01-004") in enabler
    # 自己 edge は無い
    assert all(e.a_id != e.b_id for e in m.edges)
    # 候補はデッキ内に限る (= プール外は出ない)
    deck_bases = {"OP04-013", "EB01-004", "OP04-008", "OP13-012", "EB03-001"}
    for e in m.edges:
        assert e.a_id in deck_bases and e.b_id in deck_bases


def test_deck_combo_summary_dedups_and_ranks(repo):
    """人間向けサマリは実行型コンボを 無順序ペアで畳み、 強度降順で返す。"""
    from engine.combo_finder import deck_combo_summary

    deck = [repo._by_id[i] for i in ("OP04-013", "EB01-004", "OP04-008")]  # ペル/コーザ/チャカ
    out = deck_combo_summary(deck, repo._by_id["EB03-001"], top_n=12)
    combos = [e for e in out if e.kind != "accelerant"]  # 実行型コンボ部
    assert combos, "実行型コンボが1件も出ていない"
    for e in out:
        assert len(e.card_ids) >= 2
        assert e.description
        assert e.kind in ("enabler", "payoff", "amplifier", "chain", "accelerant")
    # enabler(ペル→コーザ) と payoff(コーザ→ペル) は同一コンボ → 1 件に畳む
    pell_koza = [e for e in combos if set(e.card_ids[:2]) == {"OP04-013", "EB01-004"}]
    assert len(pell_koza) == 1
    # コンボ部は強度降順 (= accelerant は別節として末尾に付くので分けて検証)
    assert [e.score for e in combos] == sorted((e.score for e in combos), reverse=True)


def test_live_deck_combos_only_when_assembled(repo):
    """live_deck_combos は、 ピースが手札/場に揃ったコンボだけ返す (= 対戦中の live 判定)。"""
    import types
    from engine.combo_readiness import live_deck_combos, _SUMMARY_CACHE

    def mk(leader, hand, deck):
        p = types.SimpleNamespace()
        p.leader = leader; p.hand = hand; p.characters = []; p.stages = []
        p.deck = deck; p.trash = []; p.life = []
        return p

    def state(p):
        s = types.SimpleNamespace()
        s.players = [p, mk(leader, [], [])]
        return s

    leader = repo._by_id["OP15-058"]   # エネル
    kard = repo._by_id["OP15-075"]     # 神の裁き (KO閾値)
    oom = repo._by_id["OP15-061"]      # オーム (下げ役)
    pair = {"OP15-075", "OP15-061"}

    _SUMMARY_CACHE.clear()
    live = live_deck_combos(state(mk(leader, [kard, oom], [])), 0)
    assert any({c["card_id"] for c in e["cards"]} == pair for e in live), "揃っているのに live でない"
    _SUMMARY_CACHE.clear()
    live2 = live_deck_combos(state(mk(leader, [kard], [oom])), 0)  # オームは山札
    assert all({c["card_id"] for c in e["cards"]} != pair for e in live2), "揃っていないのに live"


def test_find_deck_combos_excludes_incompatible_leader(repo):
    """別リーダー専用カードは、 実リーダーが非互換ならデッキコンボに入れない。"""
    from engine.combo_finder import find_deck_combos, _card_ok_with_leader

    # サッチ系「リーダー白ひげ」 要求は アラバスタ(ビビ) では非互換
    assert _card_ok_with_leader("自分のリーダーが「白ひげ」の場合、カードを引く。", {"アラバスタ王国"}, "ネフェルタリ・ビビ") is False
    assert _card_ok_with_leader("自分のリーダーが特徴《アラバスタ王国》を持つ場合、+1000。", {"アラバスタ王国"}, "ネフェルタリ・ビビ") is True


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


def test_romance_group_surfaces_high_ceiling(repo):
    """ロマン枠: 効率枠で沈む overkill (= 円卓 -10000=どんなサイズもKO) を ceiling 評価で
    上位に surface する (= ユーザー要望のロマン枠)。"""
    res = find_combos(repo, "OP04-013", per_group=8)
    rom = next((g for g in res.groups if g.key == "romance"), None)
    assert rom is not None and rom.cards
    rom_ids = {c.card_id for c in rom.cards}
    assert "OP01-027" in rom_ids  # 円卓 = 実シナジー(下げ役)の overkill → ロマン上位
    # ⚠ ロジャー(OP09-118)は単体で派手なだけでペルシナジー無し → ロマン枠に入れない (= ユーザー指摘)
    assert "OP09-118" not in rom_ids
    # 同じ円卓が効率枠(enabler)では top8 圏外 (= 効率とロマンで評価が割れる)
    en = next((g for g in res.groups if g.key == "enabler"), None)
    assert en is not None
    assert "OP01-027" not in {c.card_id for c in en.cards}


def test_opponent_turn_powerdown_excluded(repo):
    """相手ターン限定の下げ (= シャンクス OP14-027 の【相手のターン中】-1000) は、 自ターンの
    KO (= ペル【アタック時】) に噛まないので enabler/romance から除外 (= ユーザー指摘)。"""
    from engine.combo_finder import _powerdown_on_own_turn

    assert not _powerdown_on_own_turn("【相手のターン中】相手のキャラすべてを、パワー-1000。")
    assert _powerdown_on_own_turn("【アタック時】相手のキャラ1枚を、パワー-3000。")
    assert _powerdown_on_own_turn("【メイン】相手のキャラ1枚を、パワー-10000。")  # 円卓
    res = find_combos(repo, "OP04-013", per_group=30)
    for key in ("enabler", "romance"):
        g = next((gr for gr in res.groups if gr.key == key), None)
        if g:
            assert "OP14-027" not in {c.card_id for c in g.cards}


def test_unknown_card_raises(repo):
    with pytest.raises(KeyError):
        find_combos(repo, "NOPE-999")
