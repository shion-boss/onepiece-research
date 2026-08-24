# -*- coding: utf-8 -*-
"""再録カード (_rN) と 素カード の overlay 実装ズレ の 回帰テスト。

背景: 同じカードでも 素カード (OP04-112) と 再録 (OP04-112_r1) で overlay を 別々に
書いた 結果、 17 組 で 実装が食い違っていた。 再録は バックフィルテストの対象外だった
ため 誰も踏んでいなかった。 うち 挙動が変わる 実バグ:

  OP04-112_r1  誤った top-level if で KO ごと 「自ライフ1枚以下」 限定 になっていた
  OP05-119_r1/_r2  起動メインの ➀ (ドン1枚レスト) が欠落 = ノーコストでドン加速
  OP06-100_r1/_r2  トリガー条件が self_life_le (公式は 「相手のライフが3枚以下」)
  ST21-003_r1  「キャラ1枚まで」 なのに リーダーも対象にできた
  ST02-009_r1  filter.rested が one_self_chara_filtered で無視され レスト限定が消失

順序のみのズレ (「その後」 の実行順が逆):
  OP09-079_r1  「レストにする。 その後、 カード1枚を引く」
  ST05-011_r1  「2枚レストにする。 その後、 【ダブルアタック】を得る」

記法のみのズレ (挙動同一):
  EB01-015_r1/_r2 (target spec の typo) / OP01-078_r1 (conditions vs if) /
  OP02-004_r1 (entry 順) / OP07-033_r1・ST13-019_r1 (全角Ｄ) / OP09-069_r1 (or_clauses)

さらに 素カード側も 公式テキストと不一致だった もの (OP01-041 / OP01-051 / OP09-097 /
P-081) は 双方を 公式準拠に 書き換えた。

test_all_reprints_match_base が この クラス全体 の 恒久ガード。
"""
from __future__ import annotations

import copy
import json
import random
import re
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent


def _cond_of(eff: dict) -> dict:
    """効果の発動条件を取り出す (top-level `if` / `conditional` の両対応)。

    ⚠ 2026-08-05: 公式は 「〜できる：<条件>の場合、<効果>」 のコロン後の条件を **効果のみ** の
    gate とする (cardqa_op_02 / cardqa_st_04)。 top-level `if` に置くと **任意コストの支払いごと
    消える** ので、 overlay ではこの形の条件を `conditional` の中に移した。
    条件そのものは変わっていないので、 テストはどちらの位置でも読めればよい。
    """
    if isinstance(eff.get("if"), dict):
        return eff["if"]
    for _prim in eff.get("do") or []:
        if isinstance(_prim, dict) and "conditional" in _prim:
            return (_prim.get("conditional") or {}).get("if") or {}
    return {}


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id="OP01-001", human_idx=None, opp_leader_id="OP01-001"):
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("OP01-016")] * 30
    p1.deck = [repo.get("OP01-016")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=_overlay())
    st.turn_player_idx = 0
    st.turn_number = 3
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _eff(overlay, cid, when):
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    assert matches, f"{cid} に when={when} の効果がない"
    return matches[0]


def _strip_text(obj):
    obj = copy.deepcopy(obj)

    def walk(x):
        if isinstance(x, dict):
            x.pop("_text", None)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(obj)
    return obj


# --------------------------------------------------------------------------- #
#  クラス全体の恒久ガード
# --------------------------------------------------------------------------- #
def test_all_variants_match_base():
    """再録 (_rN) / パラレル (_pN) の overlay は 素カード と 完全一致 する (`_text` 注記を除く)。

    同一カードなので 実装が分かれてはいけない。 分かれた瞬間 「素カードでは動くが
    パラレルでは動かない (逆も)」 という 発見しにくい バグ になる。 パラレルは 実際に
    デッキに投入される ので 再録より実害が大きい。
    """
    raw = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    bad = []
    for cid in raw:
        m = re.match(r"^(.*)_[pr]\d+$", cid)
        if not m:
            continue
        base = m.group(1)
        if base in raw and _strip_text(raw[base]) != _strip_text(raw[cid]):
            bad.append(f"{base} != {cid}")
    assert not bad, "variant と素カードで overlay 実装がズレている: " + ", ".join(bad)


# --------------------------------------------------------------------------- #
#  個別の 実バグ 回帰
# --------------------------------------------------------------------------- #
def test_op04_112_ko_fires_regardless_of_own_life():
    """OP04-112 ヤマト: KO は 自ライフに関係なく 発火する。

    再録は top-level if で 「自ライフ1枚以下」 を 全体に掛けており、 ライフが
    残っている 通常の登場では KO が まったく発火しなかった。
    """
    overlay = _overlay()
    for cid in ("OP04-112", "OP04-112_r1"):
        eff = _eff(overlay, cid, "on_play")
        assert "if" not in eff, f"{cid}: on_play 全体を条件で塞いではいけない"
        st = _state(_repo())
        st.players[0].life = [_repo().get("OP01-016")] * 4   # ライフ潤沢 = 条件不成立側
        st.players[1].characters = [InPlay.of(_repo().get("OP01-016"))]
        for prim in eff["do"]:
            execute_effect(prim, st, st.players[0], st.players[1], None)
        assert not st.players[1].characters, f"{cid}: ライフ4枚でも KO は発火するべき"


def test_op05_119_activate_main_costs_a_don():
    """OP05-119 ルフィ: 起動メインの ➀ (ドン1枚レスト) が コストとして要る。

    再録は cost が once_per_turn だけで、 ノーコストで ドン加速 できた。
    """
    overlay = _overlay()
    for cid in ("OP05-119", "OP05-119_r1", "OP05-119_r2"):
        eff = _eff(overlay, cid, "activate_main")
        assert eff.get("cost", {}).get("rest_self_don") == 1, \
            f"{cid}: ➀ (rest_self_don:1) が コストに無い = ノーコストでドン加速"


def test_op06_100_trigger_checks_opponent_life():
    """OP06-100 イヌアラシ: トリガーは 「相手のライフが3枚以下」 で発火する。

    再録は self_life_le になっており、 条件が 真逆 の局面で発火していた。
    """
    overlay = _overlay()
    for cid in ("OP06-100", "OP06-100_r1", "OP06-100_r2"):
        eff = _eff(overlay, cid, "trigger")
        assert _cond_of(eff).get("opp_life_le") == 3, \
            f"{cid}: トリガー条件が 公式 (相手のライフ3枚以下) と違う: {eff.get('if')}"


def test_op09_079_rests_before_drawing():
    """OP09-079 ゴムゴムの縄跳び: 「レストにする。 その後、 カード1枚を引く」 の順序。"""
    overlay = _overlay()
    for cid in ("OP09-079", "OP09-079_r1"):
        do = _eff(overlay, cid, "main")["do"]
        keys = [next(iter(p)) for p in do]
        assert keys.index("rest") < keys.index("draw"), \
            f"{cid}: 公式は レスト → ドロー の順 (実際: {keys})"


def test_st05_011_rests_two_then_grants_double_attack():
    """ST05-011 バレット: 相手キャラ 2 枚レスト → その後 ダブルアタック付与。

    再録は付与が先だった (公式は 「レストにする。 その後、 …【ダブルアタック】を得る」)。
    枚数自体は 旧形 (one_… + count:2) でも 2 枚 レストされていた。
    """
    repo = _repo()
    overlay = _overlay()
    for cid in ("ST05-011", "ST05-011_r1"):
        do = _eff(overlay, cid, "activate_main")["do"]
        keys = [next(iter(p)) for p in do]
        assert keys.index("rest") < keys.index("give_keyword"), \
            f"{cid}: 公式は レスト → ダブルアタック付与 の順 (実際: {keys})"
        st = _state(repo)
        st.players[1].characters = [InPlay.of(repo.get("OP01-016")) for _ in range(3)]
        for prim in do:
            execute_effect(prim, st, st.players[0], st.players[1], None)
        rested = sum(1 for c in st.players[1].characters if c.rested)
        assert rested == 2, f"{cid}: 公式は 2 枚までレスト (実際 {rested} 枚)"


def test_st21_003_cannot_target_leader():
    """ST21-003 サンジ: 「キャラ1枚まで」 なので リーダーは対象外。"""
    overlay = _overlay()
    for cid in ("ST21-003", "ST21-003_r1"):
        do = _eff(overlay, cid, "on_play")["do"]
        spec = do[0]["prevent_blocker_for_attacker"]["target"]["type"]
        assert "leader" not in spec, f"{cid}: リーダーを対象に含めてはいけない ({spec})"


def test_st02_009_untaps_the_rested_one_not_the_strongest():
    """ST02-009 ロー: 「自分のレストの…をアクティブにする」 = レスト中のみ対象。

    再録は filter 側に rested を書いていたが one_self_chara_filtered は
    それを読まず (target 直下の rested_required のみ)、 レスト限定が silent に消えていた。
    結果 パワー最大の *アクティブな* キャラを選んで 何も起きず、 実際にレストしている
    キャラは 起きないままだった。 engine 側も filter 直書きを honor するよう寛容化済み。
    """
    repo = _repo()
    overlay = _overlay()
    for cid in ("ST02-009", "ST02-009_r1"):
        st = _state(repo)
        strong_active = InPlay.of(repo.get("OP14-016"))   # power 7000 / 超新星
        strong_active.rested = False
        weak_rested = InPlay.of(repo.get("EB01-015"))     # power 1000 / 超新星
        weak_rested.rested = True
        st.players[0].characters = [strong_active, weak_rested]
        for prim in _eff(overlay, cid, "on_play")["do"]:
            execute_effect(prim, st, st.players[0], st.players[1], None)
        assert not weak_rested.rested, \
            f"{cid}: レスト中のキャラが起きていない (パワー最大の active を選んでいる)"


def test_engine_honors_filter_rested_on_one_self_chara_filtered():
    """engine: one_self_chara_filtered が filter.rested を honor する (記法揺れ耐性)。

    _matches_filter は CardDef ベースで rested を知らず、 未知キーを黙って無視する。
    target 直下の rested_required しか見ないと 「レスト限定」 が silent に消える。
    """
    repo = _repo()
    st = _state(repo)
    strong_active = InPlay.of(repo.get("OP14-016"))
    strong_active.rested = False
    weak_rested = InPlay.of(repo.get("EB01-015"))
    weak_rested.rested = True
    st.players[0].characters = [strong_active, weak_rested]
    prim = {"untap_chara": {"target": {"type": "one_self_chara_filtered",
                                       "filter": {"rested": True}}, "limit": 1}}
    execute_effect(prim, st, st.players[0], st.players[1], None)
    assert not weak_rested.rested, "filter.rested がレスト中のキャラを選べていない"


def test_op01_051_plays_only_character_cards():
    """OP01-051 キッド: 「キャラカード1枚まで」 = イベント/ステージは登場対象外。"""
    overlay = _overlay()
    for cid in ("OP01-051", "OP01-051_r1"):
        do = _eff(overlay, cid, "activate_main")["do"]
        filt = do[0]["play_from_hand"]["filter"]
        assert filt.get("category") == "CHARACTER", \
            f"{cid}: 公式は 「キャラカード」 = category 指定が要る ({filt})"


def test_op01_041_cost_matches_official_text():
    """OP01-041 モモの助: コストは ① + 自レスト。 【ターン1回】 は 公式テキストに無い。"""
    overlay = _overlay()
    for cid in ("OP01-041", "OP01-041_r1"):
        eff = _eff(overlay, cid, "activate_main")
        cost = eff.get("cost", {})
        assert cost.get("rest_self_don") == 1, f"{cid}: ① (rest_self_don:1) が無い"
        assert cost.get("rest_self") is True, f"{cid}: 自レストが無い"
        assert "once_per_turn" not in cost, \
            f"{cid}: 公式テキストに 【ターン1回】 は無い"
        assert eff["do"][0]["search_top_n"]["public"] is True, \
            f"{cid}: 公式は 「公開し、 手札に加える」"


def test_op09_097_pumps_the_same_card_it_negated():
    """OP09-097 闇水: 「1枚までを、 効果を無効にし、 パワー-4000」 = 同一の 1 枚 に両方。

    以前は target を 2 回 別々に解決しており、 別のカードに当たりうる形だった
    (human なら modal が 2 回 出て 実際に割れる)。
    """
    repo = _repo()
    overlay = _overlay()
    for cid in ("OP09-097", "OP09-097_r1"):
        do = _eff(overlay, cid, "counter")["do"]
        assert do[1]["power_pump"]["target"] == "opp_just_negated_any", \
            f"{cid}: パワー-4000 は negate した その 1 枚 に当てる"
        st = _state(repo)
        strong = InPlay.of(repo.get("OP01-016"))
        weak = InPlay.of(repo.get("OP01-016"))
        st.players[1].characters = [strong, weak]
        for prim in do:
            execute_effect(prim, st, st.players[0], st.players[1], None)
        negated = [c for c in st.players[1].characters if "効果無効" in c.granted_keywords]
        assert len(negated) == 1, f"{cid}: 無効化は 1 枚 のはず"
        pumped = [c for c in st.players[1].characters if c.power < c.card.power]
        assert pumped == negated, f"{cid}: パワー減は 無効化したのと同じカードに乗るべき"


def test_p081_requires_blue_crossguild_characters():
    """P-081: 条件は 「自分の"青の"特徴《クロスギルド》を持つキャラが3枚以上」。

    再録は色条件が抜けており、 青以外のクロスギルドでも 条件を満たしてしまった。
    また 公式テキストに 【ターン1回】 は無い。

    ⚠ 2026-08-24: 素の `P-081` は **cards.json に存在しない** (実在は _p1/_p2/_r1 の 3 種)
      ので overlay から削除した。 検査対象を **実在する 3 変種** に置き換える
      (= カバレッジはむしろ増える)。 詳細は tests/test_overlay_keys_exist.py。
    """
    overlay = _overlay()
    for cid in ("P-081_p1", "P-081_p2", "P-081_r1"):
        eff = _eff(overlay, cid, "activate_main")
        cond = _cond_of(eff)["self_chara_filtered_count_ge"]
        assert cond["filter"].get("color") == "青", f"{cid}: 「青の」 条件が抜けている"
        assert cond["filter"].get("feature") == "クロスギルド"
        assert cond["count"] == 3
        assert "once_per_turn" not in eff.get("cost", {}), \
            f"{cid}: 公式テキストに 【ターン1回】 は無い"
        # ⚠ 2026-08-05: コロン後の条件は効果のみを gate するので do は `conditional` で
        #   包まれている (top-level `if` だと任意コストの支払いごと消える、 cardqa_op_02)。
        _inner = eff["do"][0]
        if "conditional" in _inner:
            _inner = _inner["conditional"]["do"][0]
        filt = _inner["play_from_hand"]["filter"]
        assert filt.get("category") == "CHARACTER" and filt.get("cost_eq") == 5, \
            f"{cid}: 公式は 「コスト5の…キャラカード」 ({filt})"


def test_eb01_015_uses_canonical_target_spec():
    """EB01-015 アプー: target spec の typo (…_2cost) を 正規形 に統一。"""
    overlay = _overlay()
    for cid in ("EB01-015", "EB01-015_r1", "EB01-015_r2"):
        do = _eff(overlay, cid, "on_play")["do"]
        assert do[0]["rest"] == "one_opponent_character_cost_le_2", \
            f"{cid}: target spec が 正規形 でない ({do[0]['rest']})"


# --------------------------------------------------------------------------- #
#  パラレル (_pN) 側で見つかった 実バグ の 回帰
#  (素カードも誤っていたもの = ★ は 全 variant で 公式準拠に書き換え済)
# --------------------------------------------------------------------------- #
def test_op01_016_nami_reveals_the_searched_card():
    """★OP01-016 ナミ: 公式 「1枚までを公開し、手札に加える」 = public。

    素カードが public:false (= 非公開) で、 パラレル 8 種だけ true だった。
    公開かどうかは 相手の情報量 が変わる = ゲーム上の実差。
    """
    overlay = _overlay()
    for cid in ["OP01-016"] + [f"OP01-016_p{i}" for i in range(1, 8)]:
        spec = _eff(overlay, cid, "on_play")["do"][0]["search_top_n"]
        assert spec["public"] is True, f"{cid}: 公式は 「公開し、 手札に加える」"


def test_op06_080_moria_requires_attached_don():
    """★OP06-080 モリア (リーダー): 公式 【ドン‼×1】 = 付与ドン1枚以上 が条件。

    素カードに条件が無く、 ドン未付与でも 起動できた (= メタデッキのリーダー)。
    """
    overlay = _overlay()
    for cid in ("OP06-080", "OP06-080_p1", "OP06-080_p2"):
        if overlay.get(cid) is None:
            continue
        eff = _eff(overlay, cid, "on_attack")
        assert _cond_of(eff).get("self_attached_don_ge") == 1, \
            f"{cid}: 【ドン‼×1】 の条件が無い = ドン未付与でも発動できてしまう"


def test_op12_073_pumps_only_the_named_and_featured():
    """OP12-073 ロー: 「ロシナンテ」 と 特徴《ハートの海賊団》 を持つキャラ限定。

    パラレルは all_self_team (= リーダー含む全体) で、 無関係なキャラまで +1000 していた。
    """
    overlay = _overlay()
    for cid in ("OP12-073", "OP12-073_p1"):
        tgt = _eff(overlay, cid, "on_play")["do"][1]["power_pump"]["target"]
        assert isinstance(tgt, dict) and tgt["type"] == "all_self_chara_filtered", \
            f"{cid}: 対象が絞られていない ({tgt})"


def test_op15_058_enel_attaches_up_to_four():
    """OP15-058 エネル: 「レストのドン‼4枚**までを**、付与する」 = up_to。

    パラレルは up_to 欠落で 4 枚固定だった。
    """
    overlay = _overlay()
    for cid in ("OP15-058", "OP15-058_p1"):
        spec = _eff(overlay, cid, "activate_main")["do"][2]["attach_rested_don"]
        assert spec.get("up_to") is True, f"{cid}: 「4枚まで」 の up_to が無い"


def test_op14_020_mihawk_rests_any_own_card():
    """OP14-020 ミホーク: 「自分のカード1枚をレストにできる」 = 任意の自分のカード。

    パラレルは rest_self (= 自分自身固定) だった。
    """
    overlay = _overlay()
    for cid in ("OP14-020", "OP14-020_p1"):
        cost = _eff(overlay, cid, "activate_main")["cost"]
        assert cost.get("rest_own_card") == 1, f"{cid}: 「自分のカード1枚」 でない ({cost})"


def test_p106_parallels_have_the_trigger():
    """★P-106 ルフィ: パラレルに 【トリガー】 が丸ごと欠落していた。"""
    overlay = _overlay()
    for cid in ("P-106", "P-106_p1", "P-106_p2"):
        whens = [e.get("when") for e in overlay.get(cid).effects]
        assert "trigger" in whens, f"{cid}: 【トリガー】 効果が無い ({whens})"


def test_st03_003_targets_either_side():
    """★ST03-003 クロコダイル: 公式は 「相手の」 が無い = 両陣営のキャラが対象。

    双方とも 相手限定 になっていた。 同文型 (「コストN以下のキャラ1枚まで、 持ち主の
    デッキの下に置く」) の OP10-046/OP07-040 等は 両陣営 で実装されている。
    """
    overlay = _overlay()
    for cid in ("ST03-003", "ST03-003_p1", "ST03-003_p2"):
        if overlay.get(cid) is None:
            continue
        eff = _eff(overlay, cid, "on_block")
        assert eff["do"][0]["return_to_deck_bottom"] == "one_character_either_cost_le_2", \
            f"{cid}: 両陣営対象になっていない"
        assert "self_don_ge" not in _cond_of(eff), \
            f"{cid}: self_don_ge は 【ドン‼×1】 (= 付与ドン) と無関係"


def test_eb03_013_plays_zou_as_a_stage():
    """EB03-013 キャロット: 「ゾウ」 (= OP08-039) は STAGE。 登場は play_stage_from_hand。"""
    repo = _repo()
    overlay = _overlay()
    assert repo.get("OP08-039").category.value == "STAGE"
    for cid in ("EB03-013", "EB03-013_p1"):
        do = _eff(overlay, cid, "activate_main")["do"]
        assert "play_stage_from_hand" in do[1], f"{cid}: ゾウ は STAGE なので stage 登場が正"


def test_op07_019_keeps_the_optional_cost_declinable():
    """OP07-019 ボニー: ➀ は 「できる：」 = optional_cost_then。

    top-level cost に畳むと 人間が 「払わない」 を選べなくなる
    (= feedback_optional_cost_then_human_decline)。
    """
    overlay = _overlay()
    for cid in ("OP07-019", "OP07-019_p1", "OP07-019_p2", "OP07-019_p3"):
        if overlay.get(cid) is None:
            continue
        eff = _eff(overlay, cid, "opp_attack")
        assert "optional_cost_then" in eff["do"][0], f"{cid}: 任意コストが top-level に畳まれている"
        assert "rest_self_don" not in eff.get("cost", {}), \
            f"{cid}: ➀ を必須コスト化してはいけない"


def test_st03_017_draws_conditionally_in_one_effect():
    """ST03-017 メロメロ甘風: 「パワー+4000。 その後、 手札3枚以下なら1枚引く」。"""
    repo = _repo()
    overlay = _overlay()
    for cid in ("ST03-017", "ST03-017_p1", "ST03-017_p2"):
        if overlay.get(cid) is None:
            continue
        entries = [e for e in overlay.get(cid).effects if e.get("when") == "counter"]
        assert len(entries) == 1, f"{cid}: counter entry は 1 つ (「その後」 は同一効果内)"
        do = entries[0]["do"]
        assert "conditional" in do[1], f"{cid}: 条件付きドローが conditional でない"
        # 手札 2 枚 (≤3) → 引く / 手札 5 枚 (>3) → 引かない
        for hand_n, expect_draw in ((2, True), (5, False)):
            st = _state(repo)
            st.players[0].hand = [repo.get("OP01-016")] * hand_n
            before = len(st.players[0].hand)
            for prim in do:
                execute_effect(prim, st, st.players[0], st.players[1], None)
            drew = len(st.players[0].hand) > before
            assert drew is expect_draw, \
                f"{cid}: 手札{hand_n}枚 で ドロー={drew} (期待 {expect_draw})"


def test_no_overlay_entry_for_nonexistent_variant():
    """overlay に `_pN` / `_rN` キーが有るのに **そのカードが cards.json に無い** ものを検出。

    実在しないカードの overlay は どの経路からも到達できない = 差分検証もテストも通らない
    「死にデータ」 で、 カバレッジ計算の分母だけを汚す。 新弾取込で先に overlay を書いた場合も
    ここで気づける (取込後にカードが現れれば自動で解消する)。

    ⚠ **base キー** (= `P-081` のように variant だけが実在し base は印刷されていない) は
      variant 比較の基準として意図的に置いているので除外する。
    """
    import json as _json

    ov = _json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    cards = {c["card_id"] for c in _json.loads(
        (ROOT / "db" / "cards.json").read_text(encoding="utf-8"))}
    ghosts = sorted(
        k for k in ov
        if not k.startswith("_") and k not in cards
        and ("_p" in k or "_r" in k)          # base キーは除外 (variant 比較の基準)
    )
    assert not ghosts, (
        "実在しないカードの overlay エントリ (cards.json に無い variant): "
        f"{ghosts} → 誤記なら削除、 新弾なら scraper でカードを取り込む"
    )
