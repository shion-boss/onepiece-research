# -*- coding: utf-8 -*-
"""OP08 弾 (百獣海賊団 / ビッグ・マム海賊団) 効果 回帰テスト
バックフィル (自動生成 wave 088):
OP08-074 / OP08-075 / OP08-076 / OP08-077 / OP08-080 / OP08-082 /
OP08-084 / OP08-085 / OP08-086 / OP08-087 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_001.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 任意コスト を 持つカードは 人間 actor で pending_choice が
      正しい kind + 候補で立ち、 resolve_pending_choice で解決できる (= 人間が選べる)
  (3) 同じ効果を AI 文脈 (human_player_idx=None) で回しても crash せず自動解決する
      (= AI が選べる)
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id="OP01-001", overlay=None, human_idx=None,
           opp_leader_id="OP01-001", turn_player_idx=0):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=turn_player_idx / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("OP01-013")] * 30
    p1.deck = [repo.get("OP01-013")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn_player_idx
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when):
    return [p for e in overlay.get(cid).effects if e["when"] == when for p in e["do"]]


def _drain(st, pick=0, guard=10):
    """pending_choice を pick を選び続けて解決しきる。"""
    g = 0
    while st.pending_choice is not None and g < guard:
        cands = st.pending_choice.get("candidates")
        if cands is not None and len(cands) == 0:
            resolve_pending_choice(st, [])
        else:
            resolve_pending_choice(st, [pick])
        g += 1


def _acts(st, me, overlay, cid):
    return [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == cid]


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op08_wave088_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP08-074", "OP08-075", "OP08-076", "OP08-077", "OP08-080",
           "OP08-082", "OP08-084", "OP08-085", "OP08-086", "OP08-087"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP08-074 ブラックマリア (紫 CHARACTER cost3):
#    【起動メイン】【ターン1回】自分のキャラの他の「ブラックマリア」がいない場合、
#      ドン‼デッキからドン‼5枚までを、レストで追加する。その後、このターン終了時、
#      相手の場のドン‼の枚数と同じ枚数になるように自分の場のドン‼をドン‼デッキに戻す。
# --------------------------------------------------------------------------- #
def test_op08_074_activate_main_add_rested_don5_ai():
    """起動メイン: (他ブラックマリアなし) レストドン5枚を追加 + ターン終了時返却を予約 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP08-074"), sickness=False)]
    me.don_rested = 0
    me.don_remaining_in_deck = 10

    rested_before = me.don_rested
    deck_before = me.don_remaining_in_deck
    opts = _acts(st, me, overlay, "OP08-074")
    assert len(opts) == 1, f"OP08-074 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    assert me.don_rested == rested_before + 5, \
        f"レストドンが5枚追加されていない: {me.don_rested} (before {rested_before})"
    assert me.don_remaining_in_deck == deck_before - 5, \
        "ドンデッキから5枚減っていない"
    # ターン終了時 返却 が 予約されている (spec: {"do": [{"return_self_don_to_match_opp": True}]})
    sched = getattr(me, "scheduled_at_self_turn_end", [])
    assert any(
        any("return_self_don_to_match_opp" in prim for prim in s.get("do", []))
        for s in sched
    ), "ターン終了時の 自ドン返却 が 予約されていない"


def test_op08_074_other_black_maria_not_legal():
    """negative: 自分の場に他の「ブラックマリア」がいると 起動メインは legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP08-074"), sickness=False),
                     InPlay.of(repo.get("OP08-074"), sickness=False)]
    me.don_remaining_in_deck = 10

    opts = _acts(st, me, overlay, "OP08-074")
    assert len(opts) == 0, "他ブラックマリアがいる時に起動メインが legal に出てはいけない"


def test_op08_074_return_don_to_match_opp_primitive():
    """return_self_don_to_match_opp: 相手ドン枚数を超える自ドンをドンデッキに戻す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 5
    me.don_rested = 3   # 自 total 8
    me.don_remaining_in_deck = 0
    opp.don_active = 3
    opp.don_rested = 0  # 相手 total 3

    execute_effect({"return_self_don_to_match_opp": True}, st, me, opp, None)

    assert me.don_active + me.don_rested == 3, \
        f"自ドンが相手枚数(3)に合わせて返却されていない: {me.don_active + me.don_rested}"
    assert me.don_remaining_in_deck == 5, \
        f"超過5枚がドンデッキに戻っていない: {me.don_remaining_in_deck}"


# --------------------------------------------------------------------------- #
#  OP08-075 キャンディメイデン (紫 EVENT cost1):
#    【メイン】ドン‼-1：相手のコスト2以下のキャラ1枚までを、レストにする。
#      その後、自分のライフすべてを裏向きにする。
#    【トリガー】ドン‼デッキからドン‼1枚までを、アクティブで追加する。
# --------------------------------------------------------------------------- #
def test_op08_075_main_rest_and_flip_life_ai():
    """【メイン】相手コスト2以下キャラをレスト + 自ライフすべて裏向き (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 3
    me.face_up_life_count = 3
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost1 <= 2
    victim.rested = False
    opp.characters = [victim]

    for prim in _do(overlay, "OP08-075", "main"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert victim.rested is True, "相手コスト2以下キャラがレストされていない"
    assert me.face_up_life_count == 0, "自分のライフすべてが裏向きになっていない"


def test_op08_075_main_human_rest_pick():
    """人間 + 相手のコスト2以下アクティブキャラ 複数 → target_pick modal が立ち resolve で 1 体レスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 2
    me.face_up_life_count = 2
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    a.rested = False
    b.rested = False
    opp.characters = [a, b]

    rest_prim = _do(overlay, "OP08-075", "main")[0]
    execute_effect(rest_prim, st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b.rested is True, "人間が選んだ相手キャラがレストされていない"
    assert a.rested is False, "選ばなかったキャラはレストされてはいけない"


def test_op08_075_trigger_add_active_don_ai():
    """【トリガー】ドン‼1枚をアクティブで追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 0
    me.don_remaining_in_deck = 10

    for prim in _do(overlay, "OP08-075", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert me.don_active == 1, "トリガーでアクティブドンが1枚追加されていない"


# --------------------------------------------------------------------------- #
#  OP08-076 しぬほど…おいしい♡ (紫 EVENT cost3):
#    【メイン】ドン‼デッキからドン‼1枚までを、アクティブで追加する。その後、相手の
#      パワー6000以上のキャラがいる場合、ドン‼デッキからドン‼1枚までを、アクティブで追加する。
# --------------------------------------------------------------------------- #
def test_op08_076_main_add_one_don_no_big_chara_ai():
    """【メイン】相手にパワー6000以上のキャラがいなければ アクティブドンは +1 のみ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 0
    me.don_remaining_in_deck = 10
    opp.characters = [InPlay.of(repo.get("OP01-016"), sickness=False)]  # power 2000

    for prim in _do(overlay, "OP08-076", "main"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert me.don_active == 1, \
        f"パワー6000以上不在時 アクティブドンは+1のみのはず: {me.don_active}"


def test_op08_076_main_add_two_don_with_big_chara_ai():
    """【メイン】相手にパワー6000以上のキャラがいれば アクティブドンは +2 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 0
    me.don_remaining_in_deck = 10
    opp.characters = [InPlay.of(repo.get("OP08-084"), sickness=False)]  # ジャック power 8000

    for prim in _do(overlay, "OP08-076", "main"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert me.don_active == 2, \
        f"パワー6000以上存在時 アクティブドンは+2のはず: {me.don_active}"


# --------------------------------------------------------------------------- #
#  OP08-077 覇海 (紫 EVENT cost6):
#    【メイン】ドン‼-2：自分のリーダーが特徴《百獣海賊団》か《ビッグ・マム海賊団》を
#      持つ場合、相手のコスト6以下のキャラ2枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op08_077_main_ko_two_cost6_ai():
    """【メイン】相手のコスト6以下キャラ2枚までを KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, leader_id="OP08-058", overlay=overlay)  # ビッグ・マム leader
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 <= 6
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 <= 6
    opp.characters = [a, b]

    for prim in _do(overlay, "OP08-077", "main"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert a not in opp.characters and b not in opp.characters, \
        f"相手コスト6以下キャラ2枚が KO されていない: {[c.card.card_id for c in opp.characters]}"


def test_op08_077_leader_feature_gate_in_overlay():
    """overlay の 発動条件に 自リーダー《百獣海賊団》/《ビッグ・マム海賊団》(leader_features_any) がある。"""
    overlay = _overlay()
    eff = next(e for e in overlay.get("OP08-077").effects if e["when"] == "main")
    feats = eff.get("if", {}).get("leader_features_any", [])
    assert "百獣海賊団" in feats and "ビッグ・マム海賊団" in feats, \
        f"OP08-077 の leader_features_any 条件が不足: {feats}"


def test_op08_077_main_human_ko_pick():
    """人間 + 相手のコスト6以下キャラ 複数 → target_pick modal が立ち、 drain で KO が進む。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, leader_id="OP08-058", overlay=overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)
    b = InPlay.of(repo.get("OP01-016"), sickness=False)
    c = InPlay.of(repo.get("OP08-085"), sickness=False)  # cost5 <= 6
    opp.characters = [a, b, c]

    before = len(opp.characters)
    execute_effect(_do(overlay, "OP08-077", "main")[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で KO 選択 modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    _drain(st)
    assert len(opp.characters) < before, "人間選択後 相手キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP08-080 クイーン (黒 CHARACTER cost1):
#    【登場時】自分のデッキの上から5枚を見て、「クイーン」以外の特徴《百獣海賊団》を
#      持つカード1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op08_080_on_play_search_hyakuju_ai():
    """【登場時】デッキ上5枚から「クイーン」以外の百獣海賊団を手札へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    sasaki = repo.get("OP08-082")  # ササキ 百獣海賊団 (≠ クイーン)
    me.deck = [sasaki] + [repo.get("OP01-013")] * 20  # OP01-013 は 麦わらの一味 (非該当)
    me.hand = []

    for prim in _do(overlay, "OP08-080", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-080"), sickness=True))
    _drain(st)

    assert any(c.card_id == "OP08-082" for c in me.hand), \
        f"デッキ上5枚から百獣海賊団キャラが手札に加わっていない: {[c.card_id for c in me.hand]}"


def test_op08_080_on_play_human_search_modal():
    """人間 + デッキ上に百獣海賊団 → search_top_n modal が立ち resolve で手札に加わる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    sasaki = repo.get("OP08-082")
    me.deck = [sasaki, repo.get("OP01-013"), sasaki] + [repo.get("OP01-013")] * 15
    me.hand = []

    execute_effect(_do(overlay, "OP08-080", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP08-080"), sickness=True))
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (ササキ) を選択
    _drain(st)
    assert any(c.card_id == "OP08-082" for c in me.hand), \
        "人間が選んだ百獣海賊団キャラが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP08-082 ササキ (黒 CHARACTER cost1):
#    【起動メイン】自分のドン‼1枚をレストにし、このキャラをレストにできる：
#      相手のキャラ1枚までを、このターン中、コスト-2。
# --------------------------------------------------------------------------- #
def test_op08_082_activate_main_cost_minus2_ai():
    """起動メイン: (自ドン1レスト + 自身レスト) 相手キャラ1枚 コスト-2 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    sasaki = InPlay.of(repo.get("OP08-082"), sickness=False)
    me.characters = [sasaki]
    me.don_active = 1
    victim = InPlay.of(repo.get("OP08-085"), sickness=False)  # cost5
    opp.characters = [victim]

    cost_before = victim.base_cost
    opts = _acts(st, me, overlay, "OP08-082")
    assert len(opts) == 1, f"OP08-082 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    assert victim.base_cost == cost_before - 2, \
        f"相手キャラのコストが-2されていない: {victim.base_cost} (before {cost_before})"
    assert sasaki.rested is True, "起動メインコストで ササキ がレストされるべき"
    assert me.don_active == 0, "起動メインコストで自ドン1枚がレストされるべき"


def test_op08_082_activate_main_human_target_pick():
    """人間 + 相手キャラ 複数 → cost_minus の target_pick modal が立ち resolve で -2。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    sasaki = InPlay.of(repo.get("OP08-082"), sickness=False)
    me.characters = [sasaki]
    me.don_active = 1
    a = InPlay.of(repo.get("OP08-085"), sickness=False)  # cost5
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    opp.characters = [a, b]

    opts = _acts(st, me, overlay, "OP08-082")
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    a_before = a.base_cost
    resolve_pending_choice(st, [a_idx])
    _drain(st)
    assert a.base_cost == a_before - 2, "人間が選んだ相手キャラに コスト-2 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP08-084 ジャック (黒 CHARACTER cost7):
#    このキャラのコスト+4。
#    【起動メイン】このキャラをレストにできる：カード1枚を引き、自分の手札1枚を捨てる。
#      その後、相手のコスト3以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op08_084_activate_main_draw_discard_ko_ai():
    """起動メイン: (自身レスト) 1ドロー + 手札1捨て + 相手コスト3以下1枚KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    jack = InPlay.of(repo.get("OP08-084"), sickness=False)
    me.characters = [jack]
    me.hand = []
    me.deck = [repo.get("OP01-013")] * 10
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 <= 3
    opp.characters = [victim]

    deck_before = len(me.deck)
    trash_before = len(me.trash)
    opts = _acts(st, me, overlay, "OP08-084")
    assert len(opts) == 1, f"OP08-084 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    assert victim not in opp.characters, "相手コスト3以下キャラが KO されていない"
    assert jack.rested is True, "起動メインコストで ジャック がレストされるべき"
    assert len(me.deck) == deck_before - 1, "1ドローでデッキが1枚減っていない"
    assert len(me.trash) == trash_before + 1, "手札1捨てでトラッシュが1枚増えていない"


def test_op08_084_static_cost_plus4_overlay_and_effect():
    """静的: このキャラのコスト+4 (on_attached_don n=0 set_base_cost delta 4)。"""
    repo = _repo()
    overlay = _overlay()
    static_eff = next((e for e in overlay.get("OP08-084").effects
                       if e["when"] == "on_attached_don"), None)
    assert static_eff is not None, "OP08-084 の静的コスト+4 (on_attached_don) 効果が無い"

    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    jack_def = repo.get("OP08-084")  # 印刷コスト 7
    jack = InPlay.of(jack_def, sickness=False)
    p0.characters = [jack]
    st = GameState(players=[p0, p1], phase=Phase.MAIN, effects_overlay=overlay)
    st.turn_player_idx = 0
    st.human_player_idx = None
    evaluate_static_effects(st, overlay)

    assert jack.base_cost == jack_def.cost + 4, \
        f"静的コスト+4が反映されていない: {jack.base_cost} (印刷 {jack_def.cost})"


def test_op08_084_activate_main_human_ko_pick():
    """人間 + 相手のコスト3以下キャラ 複数 → KO の target_pick modal が立ち resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    jack = InPlay.of(repo.get("OP08-084"), sickness=False)
    me.characters = [jack]
    me.hand = []
    me.deck = [repo.get("OP01-013")] * 10
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [a, b]

    opts = _acts(st, me, overlay, "OP08-084")
    fire_activate_main(st, me, opp, *opts[0])
    # draw / 手札1捨て は 選択なしで 通過 → KO の target_pick で halt
    assert st.pending_choice is not None, "人間 + 複数候補で KO 選択 modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b not in opp.characters, "人間が選んだ相手キャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP08-085 ジンベエ (黒 CHARACTER cost5):
#    【ドン‼×1】【アタック時】自分のコスト8以上のキャラがいる場合、
#      相手のコスト4以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op08_085_on_attack_ko_cost4_ai():
    """【アタック時】相手のコスト4以下キャラ1枚を KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 <= 4
    opp.characters = [victim]

    for prim in _do(overlay, "OP08-085", "on_attack"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-085"), sickness=False))
    _drain(st)

    assert victim not in opp.characters, "相手コスト4以下キャラが KO されていない"


def test_op08_085_don_gate_and_self_cost8_condition_in_overlay():
    """overlay の 発動条件に ドン‼×1 (self_attached_don_ge) と 自コスト8以上キャラ存在がある。"""
    overlay = _overlay()
    eff = next(e for e in overlay.get("OP08-085").effects if e["when"] == "on_attack")
    cond = eff.get("if", {})
    assert cond.get("self_attached_don_ge") == 1, \
        "OP08-085 の ドン‼×1 ゲート (self_attached_don_ge=1) が無い"
    filt = cond.get("self_chara_filtered_count_ge", {})
    assert filt.get("filter", {}).get("cost_ge") == 8, \
        "OP08-085 の 自コスト8以上キャラ存在条件が無い"


def test_op08_085_on_attack_human_ko_pick():
    """人間 + 相手のコスト4以下キャラ 複数 → target_pick modal が立ち resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP08-085", "on_attack")[0], st, me, opp,
                   InPlay.of(repo.get("OP08-085"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で KO 選択 modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b not in opp.characters, "人間が選んだ相手キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP08-086 ジンラミー (黒 CHARACTER cost2):
#    【登場時】相手のコスト0のキャラがいる場合、カード2枚を引き、自分の手札2枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op08_086_on_play_draw2_discard2_ai():
    """【登場時】(相手コスト0キャラ条件) 2ドロー + 手札2捨て (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("OP01-013")] * 10

    deck_before = len(me.deck)
    trash_before = len(me.trash)
    for prim in _do(overlay, "OP08-086", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-086"), sickness=True))
    _drain(st)

    assert len(me.deck) == deck_before - 2, "2ドローでデッキが2枚減っていない"
    assert len(me.trash) == trash_before + 2, "手札2捨てでトラッシュが2枚増えていない"


def test_op08_086_cond_opp_cost0_in_overlay():
    """overlay の 発動条件に 相手コスト0キャラ存在 (exists_opp_chara_cost_le=0) がある。"""
    overlay = _overlay()
    eff = next(e for e in overlay.get("OP08-086").effects if e["when"] == "on_play")
    assert eff.get("if", {}).get("exists_opp_chara_cost_le") == 0, \
        "OP08-086 の 相手コスト0キャラ存在条件が無い"


# --------------------------------------------------------------------------- #
#  OP08-087 スクラッチメン・アプー (黒 CHARACTER cost4):
#    【ブロッカー】
#    【起動メイン】【ターン1回】相手のキャラ1枚までを、このターン中、コスト-1。
# --------------------------------------------------------------------------- #
def test_op08_087_activate_main_cost_minus1_ai():
    """起動メイン: 相手キャラ1枚 コスト-1 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP08-087"), sickness=False)]
    victim = InPlay.of(repo.get("OP08-085"), sickness=False)  # cost5
    opp.characters = [victim]

    cost_before = victim.base_cost
    opts = _acts(st, me, overlay, "OP08-087")
    assert len(opts) == 1, f"OP08-087 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    assert victim.base_cost == cost_before - 1, \
        f"相手キャラのコストが-1されていない: {victim.base_cost} (before {cost_before})"


def test_op08_087_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP08-087"), sickness=False)]
    opp.characters = [InPlay.of(repo.get("OP08-085"), sickness=False)]

    opts1 = _acts(st, me, overlay, "OP08-087")
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st)

    opts2 = _acts(st, me, overlay, "OP08-087")
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


def test_op08_087_activate_main_human_target_pick():
    """人間 + 相手キャラ 複数 → cost_minus の target_pick modal が立ち resolve で -1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP08-087"), sickness=False)]
    a = InPlay.of(repo.get("OP08-085"), sickness=False)  # cost5
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    opp.characters = [a, b]

    opts = _acts(st, me, overlay, "OP08-087")
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    a_before = a.base_cost
    resolve_pending_choice(st, [a_idx])
    _drain(st)
    assert a.base_cost == a_before - 1, "人間が選んだ相手キャラに コスト-1 が反映されていない"
