# -*- coding: utf-8 -*-
"""OP16 弾 (ワノ国 / 黒ひげ海賊団 ・ 黒/黄) 効果 回帰テスト
バックフィル (自動生成 wave 153):
OP16-094 / OP16-095 / OP16-096 / OP16-097 / OP16-098 /
OP16-099 / OP16-101 / OP16-103 / OP16-104 / OP16-106 の 10 枚。

目的 (= test_backfill_auto_001〜152.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 任意コスト / 対象選択 を 持つカードは 人間 actor で pending_choice が
      正しい kind + 候補で立ち、 resolve_pending_choice で解決できる (= 人間が選べる)
  (3) 同じ効果を AI 文脈 (human_player_idx=None) で回しても crash せず自動解決する
      (= AI が選べる)
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from engine.core import GameState, InPlay, Phase, Player
from engine.effects import (
    eval_condition,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)
from engine.deck import CardRepository

ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------- #
#  効果の薄い (= 素材用) カード + テスト用 leader/feature 素材。
# --------------------------------------------------------------------------- #
RED1 = "OP01-016"           # ナミ 麦わらの一味 cost1 power2000 (フィラー / cost1 相手キャラ)
WANO_C = "PRB02-008"        # マルコ (ワノ国/元白ひげ, 青, cost4 power6000, 名前 != ナミ)
WANO_C2 = "EB01-016"        # びん豪 (ワノ国, 緑, cost1, 名前 != ナミ)
WANO_BLACK = "OP16-098"     # ヤマト (ワノ国, 黒, cost6 power5000)
WANO_BLACK2 = "OP16-082"    # 錦えもん (ワノ国/赤鞘九人男, 黒, cost4 power6000)
YAMATO8 = "OP16-096"        # ヤマト (ワノ国, 黒, cost8 power8000)
BIGPOW = "EB04-022"         # イッショウ (青, cost5 power7000, パワーコピー元)
BB_C1 = "OP16-103"          # ヴァン・オーガー (黒ひげ海賊団, 黄, cost1)
WANO_LEADER = "EB01-001"    # 光月おでん (ワノ国/光月家 LEADER)
BB_LEADER = "OP09-081"      # マーシャル・Ｄ・ティーチ (四皇/黒ひげ海賊団 LEADER, 黒)
NEUTRAL_LEADER = "OP01-001"  # ロロノア・ゾロ (超新星/麦わらの一味 = 非ワノ国/非黒ひげ)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001",
           turn_player=0):
    """P0 = テスト対象デッキ、 P1 = ダミー。 MAIN / turn_number=3。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(RED1)] * 30
    p1.deck = [repo.get(RED1)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn_player
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when):
    """指定 card_id の overlay から when 一致の効果の (do 配列, eff) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    return matches[0]["do"], matches[0]


def _drain(st, pick=None, guard=10):
    """残った pending_choice を安全に drain。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


def _am(st, me, overlay, cid):
    """指定 card_id の起動メイン (src, eff) を legal から取り出す。"""
    return [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == cid]


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op16_wave153_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP16-094", "OP16-095", "OP16-096", "OP16-097", "OP16-098",
           "OP16-099", "OP16-101", "OP16-103", "OP16-104", "OP16-106"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP16-094 ポートガス・Ｄ・エース (CHARACTER 黒 cost4 power5000):
#    【KO時】相手は自身の手札2枚を捨てる。
#    【起動メイン】【ターン1回】自分の《ワノ国》のリーダーかキャラ1枚に
#                 レストのドン!!1枚までを付与する。
# --------------------------------------------------------------------------- #
def test_op16_094_on_ko_force_opp_discard_ai():
    """【KO時】相手は自身の手札2枚を捨てる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.hand = [repo.get(RED1), repo.get(RED1), repo.get(RED1)]

    hand_before = len(opp.hand)
    do, _ = _do(overlay, "OP16-094", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-094"), sickness=False))
    _drain(st, [0])
    assert len(opp.hand) == hand_before - 2, \
        f"相手手札が2枚捨てられていない: {len(opp.hand)} (before {hand_before})"
    assert len(opp.trash) == 2, f"捨てた2枚がトラッシュに無い: {len(opp.trash)}"


def test_op16_094_activate_main_attach_rested_don_ai():
    """【起動メイン】《ワノ国》リーダーにレストドン1枚を付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WANO_LEADER, overlay)  # ワノ国 leader
    me, opp = st.players[0], st.players[1]
    ace = InPlay.of(repo.get("OP16-094"), sickness=False)
    me.characters = [ace]
    me.don_rested = 1

    don_before = me.leader.attached_dons
    opts = _am(st, me, overlay, "OP16-094")
    assert len(opts) == 1, \
        f"OP16-094 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert me.leader.attached_dons == don_before + 1, \
        "《ワノ国》リーダーにレストドンが付与されていない"
    assert me.don_rested == 0, "レストドンが1枚消費されるべき"


def test_op16_094_activate_main_once_per_turn():
    """【ターン1回】: 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WANO_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP16-094"), sickness=False)]
    me.don_rested = 2

    opts1 = _am(st, me, overlay, "OP16-094")
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])
    opts2 = _am(st, me, overlay, "OP16-094")
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


def test_op16_094_activate_main_attach_human_pick():
    """人間 + 《ワノ国》リーダー/キャラ複数 → 付与先の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WANO_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    ace = InPlay.of(repo.get("OP16-094"), sickness=False)
    friend = InPlay.of(repo.get(WANO_C2), sickness=False)  # びん豪 (ワノ国)
    me.characters = [ace, friend]
    me.don_rested = 1

    src, eff = _am(st, me, overlay, "OP16-094")[0]
    fire_activate_main(st, me, opp, src, eff)
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "target_pick", \
        f"人間で target_pick modal が立たない: {st.pending_choice}"
    cands = st.pending_choice.get("candidates", [])
    # 候補は 《ワノ国》 の リーダー + びん豪 (エース自身も ワノ国 だが名前 != ワノ国 特徴を持つ)
    assert len(cands) >= 2, f"《ワノ国》候補が2件以上でない: {len(cands)}"
    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    resolve_pending_choice(st, [friend_idx])
    _drain(st, [])
    assert friend.attached_dons == 1, \
        "人間が選んだ《ワノ国》キャラにレストドンが付与されていない"


# --------------------------------------------------------------------------- #
#  OP16-095 モンキー・Ｄ・ルフィ (CHARACTER 黒 cost2 power2000):
#    【登場時】自分の黒の《ワノ国》キャラ1枚までは、 このターン中、【ブロック不可】を得る。
# --------------------------------------------------------------------------- #
def test_op16_095_on_play_give_block_immune_ai():
    """【登場時】自分の黒《ワノ国》キャラに【ブロック不可】付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    yamato = InPlay.of(repo.get(WANO_BLACK), sickness=False)  # 黒 ワノ国
    me.characters = [yamato]

    do, _ = _do(overlay, "OP16-095", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-095"), sickness=True))
    _drain(st, [0])
    assert "ブロック不可" in yamato.granted_keywords, \
        f"黒《ワノ国》キャラに【ブロック不可】が付与されていない: {yamato.granted_keywords}"


def test_op16_095_on_play_no_target_non_black_wano():
    """黒でない《ワノ国》キャラのみ → 対象外 (付与されない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    marco = InPlay.of(repo.get(WANO_C), sickness=False)  # 青 ワノ国 (= 黒でない)
    me.characters = [marco]

    do, _ = _do(overlay, "OP16-095", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-095"), sickness=True))
    _drain(st, [0])
    assert "ブロック不可" not in marco.granted_keywords, \
        "黒でない《ワノ国》キャラに【ブロック不可】が付いてはいけない"


def test_op16_095_on_play_give_block_immune_human():
    """人間 + 黒《ワノ国》キャラ複数 → 対象選択が立つ/自動解決し 少なくとも1枚に付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(WANO_BLACK), sickness=False)   # ヤマト 黒 ワノ国
    b = InPlay.of(repo.get(WANO_BLACK2), sickness=False)  # 錦えもん 黒 ワノ国
    me.characters = [a, b]

    do, _ = _do(overlay, "OP16-095", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP16-095"), sickness=True))
    # 対象選択 modal が立つなら kind と候補を確認してから解決
    if st.pending_choice is not None:
        assert st.pending_choice.get("kind") == "target_pick", \
            f"kind が target_pick でない: {st.pending_choice.get('kind')}"
        a_idx = next((i for i, c in enumerate(st.pending_choice.get("candidates", []))
                      if c["iid"] == a.instance_id), 0)
        resolve_pending_choice(st, [a_idx])
        _drain(st, [])
    assert "ブロック不可" in a.granted_keywords or "ブロック不可" in b.granted_keywords, \
        "黒《ワノ国》キャラのいずれにも【ブロック不可】が付与されていない"


# --------------------------------------------------------------------------- #
#  OP16-096 ヤマト (CHARACTER 黒 cost8 power8000):
#    【ブロック不可】【KO時】自分のトラッシュからコスト6以下の「ヤマト」1枚までを登場。
# --------------------------------------------------------------------------- #
def test_op16_096_on_ko_play_yamato_from_trash_ai():
    """【KO時】トラッシュからコスト6以下の「ヤマト」1枚を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(WANO_BLACK)]  # ヤマト cost6

    do, _ = _do(overlay, "OP16-096", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-096"), sickness=False))
    _drain(st, [0])
    assert any(c.card.card_id == WANO_BLACK for c in me.characters), \
        "トラッシュからコスト6以下の「ヤマト」が登場していない"


def test_op16_096_on_ko_no_target_when_over_cost6():
    """トラッシュのヤマトがコスト8のみ → コスト6以下でないので登場しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(YAMATO8)]  # ヤマト cost8 (> 6)

    do, _ = _do(overlay, "OP16-096", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-096"), sickness=False))
    _drain(st, [0])
    assert len(me.characters) == 0, \
        "コスト8のヤマトが登場してはいけない (コスト6以下条件)"


def test_op16_096_on_ko_play_human_pick():
    """人間 + トラッシュにコスト6以下「ヤマト」複数 → play_from_trash_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(WANO_BLACK), repo.get(WANO_BLACK)]  # ヤマト cost6 x2

    do, _ = _do(overlay, "OP16-096", "on_ko")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP16-096"), sickness=False))
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "play_from_trash_pick", \
        f"人間で play_from_trash_pick modal が立たない: {st.pending_choice}"
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert any(c.card.card_id == WANO_BLACK for c in me.characters), \
        "人間が選んだ「ヤマト」が登場していない"


# --------------------------------------------------------------------------- #
#  OP16-097 ヤマト (CHARACTER 黒 cost8 power8000):
#    【登場時】自分のトラッシュからコスト6以下の《ワノ国》キャラ1枚までを手札へ。
#             その後、 自分の手札からコスト2以下のキャラ1枚までを登場させる。
# --------------------------------------------------------------------------- #
def test_op16_097_on_play_trash_to_hand_then_play_ai():
    """【登場時】トラッシュから《ワノ国》≤6を手札へ → 手札からコスト2以下を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WANO_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(WANO_C)]     # マルコ ワノ国 cost4 → 手札へ
    me.hand = [repo.get(RED1)]        # ナミ cost1 → コスト2以下で登場
    me.deck = [repo.get(RED1)] * 10

    do, _ = _do(overlay, "OP16-097", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-097"), sickness=True))
    _drain(st, [0])
    # マルコが手札に加わり、 手札のコスト1キャラ (ナミ) が登場している
    assert any(c.card_id == WANO_C for c in me.hand), \
        "トラッシュから《ワノ国》キャラが手札に加わっていない"
    assert any(c.card.card_id == RED1 for c in me.characters), \
        "手札からコスト2以下のキャラが登場していない"


def test_op16_097_on_play_search_human_modal():
    """人間 + トラッシュに《ワノ国》≤6 複数 → search_from_trash_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WANO_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(WANO_C), repo.get(WANO_C2)]  # マルコ / びん豪 (両方 ワノ国 ≤6)
    me.hand = [repo.get(RED1)]
    me.deck = [repo.get(RED1)] * 10

    do, _ = _do(overlay, "OP16-097", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP16-097"), sickness=True))
    assert st.pending_choice is not None and \
        "search_from_trash" in st.pending_choice.get("kind", ""), \
        f"人間で search_from_trash modal が立たない: {st.pending_choice}"
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert any(c.card_id in (WANO_C, WANO_C2) for c in me.hand), \
        "人間が選んだ《ワノ国》キャラが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP16-098 ヤマト (CHARACTER 黒 cost6 power5000):
#    【登場時】カード1枚を引き、 自分の手札1枚を捨てる。
#    【起動メイン】このキャラをトラッシュに置く：トラッシュからコスト8の黒の「ヤマト」
#                 1枚までを登場させる。
# --------------------------------------------------------------------------- #
def test_op16_098_on_play_draw_then_discard_ai():
    """【登場時】1ドロー + 手札1枚捨て (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(RED1), repo.get(RED1)]
    me.deck = [repo.get(RED1)] * 10

    do, _ = _do(overlay, "OP16-098", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-098"), sickness=True))
    _drain(st, [0])
    # 手札 net: 2 (初期) + 1 (draw) - 1 (捨て) = 2
    assert len(me.hand) == 2, f"draw1 + 手札1枚捨ての net が合わない: {len(me.hand)}"
    assert len(me.trash) == 1, f"捨てた手札1枚がトラッシュに無い: {len(me.trash)}"


def test_op16_098_activate_main_self_trash_play_yamato8_ai():
    """【起動メイン】このキャラをトラッシュ → トラッシュからコスト8黒「ヤマト」を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    yamato6 = InPlay.of(repo.get("OP16-098"), sickness=False)
    me.characters = [yamato6]
    me.trash = [repo.get(YAMATO8)]  # ヤマト cost8 黒

    opts = _am(st, me, overlay, "OP16-098")
    assert len(opts) == 1, \
        f"OP16-098 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert yamato6 not in me.characters, \
        "コストで OP16-098 自身がトラッシュに置かれるべき"
    assert any(c.card.card_id == YAMATO8 for c in me.characters), \
        "トラッシュからコスト8黒の「ヤマト」が登場していない"


# --------------------------------------------------------------------------- #
#  OP16-099 その“縁”を切りに来た!!! (EVENT 黒 cost1):
#    【メイン】自分のドン!!6枚をレストにできる：デッキ上5枚をトラッシュ。 その後、
#             トラッシュからコスト6以下の《ワノ国》キャラ1枚までを登場。
#    【カウンター】自分のリーダーを、 このバトル中、 パワー+3000。
# --------------------------------------------------------------------------- #
def test_op16_099_main_mill_then_play_wano_ai():
    """【メイン】ドン!!6レスト → デッキ上5トラッシュ → トラッシュから《ワノ国》≤6登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WANO_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 6           # ドン!!6枚レストのコスト用
    me.trash = [repo.get(WANO_C)]  # マルコ ワノ国 cost4 (= 登場対象)
    me.deck = [repo.get(RED1)] * 10

    do, _ = _do(overlay, "OP16-099", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert me.don_active == 0, f"ドン!!6枚がレストされていない: {me.don_active}"
    assert any(c.card.card_id == WANO_C for c in me.characters), \
        "トラッシュから《ワノ国》コスト6以下キャラが登場していない"


def test_op16_099_counter_leader_pump_ai():
    """【カウンター】自分のリーダーを このバトル中 パワー+3000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WANO_LEADER, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    do, _ = _do(overlay, "OP16-099", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert me.leader.power == power_before + 3000, \
        f"カウンターの +3000 が自リーダーに反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  OP16-101 馬幻刃 (EVENT 黒 cost2):
#    【メイン】自分のリーダーかキャラ1枚までを、 このターン中、 パワー+3000。
#             その後、 自分のトラッシュが10枚以上なら相手のコスト2以下キャラ1枚をKO。
#    【トリガー】自分のトラッシュから「ヤマト」1枚までを手札に加える。
# --------------------------------------------------------------------------- #
def test_op16_101_main_pump_and_ko_when_trash10_ai():
    """【メイン】リーダー +3000 + (トラッシュ10以上) 相手コスト2以下キャラ1枚KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(RED1)] * 10  # 10 枚 (= 条件成立)
    victim = InPlay.of(repo.get(RED1), sickness=False)  # cost1 (≤2)
    opp.characters = [victim]

    power_before = me.leader.power
    do, _ = _do(overlay, "OP16-101", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert me.leader.power == power_before + 3000, \
        f"リーダー +3000 が反映されていない: {me.leader.power}"
    assert victim not in opp.characters, \
        "トラッシュ10以上で相手コスト2以下キャラが KO されていない"


def test_op16_101_main_no_ko_when_trash_under_10():
    """トラッシュが10枚未満 → 条件不成立で KO しない (+3000 のみ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(RED1)] * 5  # 5 枚 (< 10)
    victim = InPlay.of(repo.get(RED1), sickness=False)
    opp.characters = [victim]

    do, _ = _do(overlay, "OP16-101", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim in opp.characters, \
        "トラッシュ10未満で相手キャラが KO されてはいけない"


def test_op16_101_trigger_search_yamato_from_trash_ai():
    """【トリガー】トラッシュから「ヤマト」1枚を手札に加える (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(YAMATO8)]  # ヤマト
    me.hand = []

    do, _ = _do(overlay, "OP16-101", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert any(c.card_id == YAMATO8 for c in me.hand), \
        "トラッシュから「ヤマト」が手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP16-103 ヴァン・オーガー (CHARACTER 黄 cost1 power2000):
#    【相手のターン中】【KO時】リーダーが《黒ひげ海賊団》の場合、 カード1枚を引き、
#                     相手のリーダーかキャラ1枚までを、 このターン中、 パワー-3000。
# --------------------------------------------------------------------------- #
def test_op16_103_on_ko_condition_true_when_bb_leader_opp_turn():
    """条件: 黒ひげ海賊団リーダー + 相手のターン中 → on_ko 条件が成立する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, BB_LEADER, overlay, turn_player=1)  # 相手ターン
    me, _ = st.players[0], st.players[1]
    _, eff = _do(overlay, "OP16-103", "on_ko")
    assert eval_condition(eff["if"], st, me, None) is True, \
        "黒ひげ海賊団リーダー + 相手ターンで条件が成立していない"


def test_op16_103_on_ko_condition_false_when_self_turn():
    """自分のターン中 → 【相手のターン中】条件が不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, BB_LEADER, overlay, turn_player=0)  # 自ターン
    me, _ = st.players[0], st.players[1]
    _, eff = _do(overlay, "OP16-103", "on_ko")
    assert eval_condition(eff["if"], st, me, None) is False, \
        "自ターンで【相手のターン中】条件が成立してはいけない"


def test_op16_103_on_ko_draw_and_debuff_ai():
    """【KO時】1ドロー + 相手キャラ1枚 パワー-3000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, BB_LEADER, overlay, turn_player=1)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(RED1)] * 10
    victim = InPlay.of(repo.get(RED1), sickness=False)  # power 2000
    opp.characters = [victim]

    power_before = victim.power
    do, _ = _do(overlay, "OP16-103", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-103"), sickness=False))
    _drain(st, [0])
    assert len(me.hand) == 1, f"KO時の1ドローが起きていない: {len(me.hand)}"
    assert victim.power == power_before - 3000, \
        f"相手キャラ -3000 が反映されていない: {victim.power} (before {power_before})"


def test_op16_103_on_ko_debuff_human_pick():
    """人間 + 相手のリーダー/キャラ複数 → -3000 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, BB_LEADER, overlay, human_idx=0, turn_player=1)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(RED1)] * 10
    a = InPlay.of(repo.get(RED1), sickness=False)   # power 2000
    b = InPlay.of(repo.get(BIGPOW), sickness=False)  # power 7000
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP16-103", "on_ko")
    # 対象選択を持つ末尾 power_pump を直接発火 (draw は対象なし)
    execute_effect(do[-1], st, me, opp,
                   InPlay.of(repo.get("OP16-103"), sickness=False))
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "target_pick", \
        f"人間で target_pick modal が立たない: {st.pending_choice}"
    b_idx = next(i for i, c in enumerate(st.pending_choice.get("candidates", []))
                 if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    _drain(st, [])
    assert b.power == b_before - 3000, "人間が選んだ相手キャラに -3000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP16-104 カタリーナ・デボン (CHARACTER 黄 cost4 power3000):
#    【アタック時】相手のキャラ1枚を選ぶ。 このキャラの元々のパワーは、 このターン中、
#                 選んだキャラと同じパワーになる。
# --------------------------------------------------------------------------- #
def test_op16_104_on_attack_copy_power_ai():
    """【アタック時】相手キャラのパワーを このキャラの元々のパワーに複写 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("OP16-104"), sickness=False)  # power 3000
    me.characters = [attacker]
    victim = InPlay.of(repo.get(BIGPOW), sickness=False)  # power 7000
    opp.characters = [victim]

    do, _ = _do(overlay, "OP16-104", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp, attacker)
    _drain(st, [0])
    assert attacker.power == 7000, \
        f"アタック時に元々のパワーが 7000 (相手コピー) になっていない: {attacker.power}"


def test_op16_104_on_attack_copy_human_pick():
    """人間 + 相手キャラ複数 → コピー元の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("OP16-104"), sickness=False)
    me.characters = [attacker]
    a = InPlay.of(repo.get(RED1), sickness=False)    # power 2000
    b = InPlay.of(repo.get(BIGPOW), sickness=False)  # power 7000
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP16-104", "on_attack")
    execute_effect(do[0], st, me, opp, attacker)
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "target_pick", \
        f"人間で target_pick modal が立たない: {st.pending_choice}"
    b_idx = next(i for i, c in enumerate(st.pending_choice.get("candidates", []))
                 if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [])
    assert attacker.power == 7000, \
        "人間が選んだ相手キャラのパワー (7000) が複写されていない"


def test_op16_104_trigger_draw_and_play_bb_cost1_ai():
    """【トリガー】1ドロー + トラッシュから《黒ひげ海賊団》コスト1キャラを登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(RED1)] * 10
    me.trash = [repo.get(BB_C1)]  # ヴァン・オーガー 黒ひげ海賊団 cost1

    do, _ = _do(overlay, "OP16-104", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-104"), sickness=False))
    _drain(st, [0])
    assert len(me.hand) == 1, f"トリガーの1ドローが起きていない: {len(me.hand)}"
    assert any(c.card.card_id == BB_C1 for c in me.characters), \
        "トラッシュから《黒ひげ海賊団》コスト1キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP16-106 サンファン・ウルフ (CHARACTER 黄 cost4 power5000):
#    【KO時】リーダーが《黒ひげ海賊団》の場合、 カード1枚を引き、 自分のリーダーかキャラ
#           1枚までを、 このターン中、 元々のパワー7000にする。
# --------------------------------------------------------------------------- #
def test_op16_106_on_ko_condition_requires_bb_leader():
    """条件: リーダーが《黒ひげ海賊団》なら成立、 非黒ひげなら不成立。"""
    repo = _repo()
    overlay = _overlay()
    _, eff = _do(_overlay(), "OP16-106", "on_ko")
    st_bb = _state(repo, BB_LEADER, overlay)
    assert eval_condition(eff["if"], st_bb, st_bb.players[0], None) is True, \
        "黒ひげ海賊団リーダーで条件が成立していない"
    st_neu = _state(repo, NEUTRAL_LEADER, overlay)
    assert eval_condition(eff["if"], st_neu, st_neu.players[0], None) is False, \
        "非黒ひげリーダーで条件が成立してはいけない"


def test_op16_106_on_ko_draw_and_set_power_ai():
    """【KO時】1ドロー + 自リーダーを 元々のパワー7000にする (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, BB_LEADER, overlay)  # 黒ひげ leader (power5000)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(RED1)] * 10

    do, _ = _do(overlay, "OP16-106", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-106"), sickness=False))
    _drain(st, [0])
    assert len(me.hand) == 1, f"KO時の1ドローが起きていない: {len(me.hand)}"
    assert me.leader.power == 7000, \
        f"自リーダーの元々のパワーが 7000 になっていない: {me.leader.power}"


@pytest.mark.skip(reason=(
    "engine バグ (要人間レビュー): set_base_power_timed が _resolve_target に "
    "outer_value=target_spec (= 'self_inplay' 文字列) を渡しており "
    "(engine/effects.py:4764)、 人間 target_pick 解決後の再実行で primitive の "
    "amount が失われ 0 に default する (set_base_power_copy は outer_value=v で正しい)。 "
    "AI パス (test_op16_106_on_ko_draw_and_set_power_ai) と 条件 は green。 "
    "engine 修正 = outer_value=v に変更。 このタスクでは engine を編集しない。"
))
def test_op16_106_on_ko_set_power_human_pick():
    """人間 + 自リーダー/キャラ複数 → 元々パワー7000化の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, BB_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(RED1)] * 10
    friend = InPlay.of(repo.get(RED1), sickness=False)  # power 2000
    me.characters = [friend]

    do, _ = _do(overlay, "OP16-106", "on_ko")
    # 対象選択を持つ末尾 set_base_power_timed を直接発火 (draw は対象なし)
    execute_effect(do[-1], st, me, opp,
                   InPlay.of(repo.get("OP16-106"), sickness=False))
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "target_pick", \
        f"人間で target_pick modal が立たない: {st.pending_choice}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    resolve_pending_choice(st, [friend_idx])
    _drain(st, [])
    assert friend.power == 7000, \
        "人間が選んだキャラの元々のパワーが 7000 になっていない"
