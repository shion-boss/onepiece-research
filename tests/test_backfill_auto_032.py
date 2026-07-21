# -*- coding: utf-8 -*-
"""OP02 弾 (紫 インペルダウン系) 効果 回帰テスト バックフィル (自動生成 wave 032):
OP02-075 / OP02-076 / OP02-078 / OP02-079 / OP02-082 / OP02-083 /
OP02-085 / OP02-089 / OP02-090 / OP02-091 の 10 枚。

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
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("OP01-013")] * 30
    p1.deck = [repo.get("OP01-013")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _get_eff(overlay, cid, when):
    return next(e for e in overlay.get(cid).effects if e["when"] == when)


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op02_wave32_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP02-075", "OP02-076", "OP02-078", "OP02-079", "OP02-082",
           "OP02-083", "OP02-085", "OP02-089", "OP02-090", "OP02-091"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP02-075 シキ: 【トリガー】ドン!!-1 で 自身を登場させることができる
#                 (optional_cost_then: pay_don1 → play_self)
# --------------------------------------------------------------------------- #
def test_op02_075_shiki_trigger_play_self_ai():
    """AI: ドン1枚を払って自身を場に登場させる (トリガー発動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP02-075")]  # 手札の自身 (= トリガー元)
    me.don_active = 1                 # ドン-1 コスト用
    st.current_source_card_id = "OP02-075"

    trig = _get_eff(overlay, "OP02-075", "trigger")
    for prim in trig["do"]:
        execute_effect(prim, st, me, opp, None)

    assert any(c.card.card_id == "OP02-075" for c in me.characters), \
        "ドン払いで自身が登場していない"
    assert not any(c.card_id == "OP02-075" for c in me.hand), \
        "登場した自身が手札から取り除かれていない"
    assert me.don_active == 0, "ドン-1 のコストが支払われていない"


def test_op02_075_shiki_trigger_optional_cost_confirm_human():
    """人間: 任意コスト (= 「〜できる」) の確認 modal が立ち、 承諾で登場する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP02-075")]
    me.don_active = 1
    st.current_source_card_id = "OP02-075"

    trig = _get_eff(overlay, "OP02-075", "trigger")
    execute_effect(trig["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 任意コストの確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾 (= 払って発動)
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [1])
        guard += 1
    assert any(c.card.card_id == "OP02-075" for c in me.characters), \
        "人間承諾後に自身が登場していない"


# --------------------------------------------------------------------------- #
#  OP02-076 シリュウ: 【登場時】ドン!!-1：相手のコスト1以下のキャラ1枚までを、KOする
# --------------------------------------------------------------------------- #
def test_op02_076_shiryu_on_play_ko_cost1_ai():
    """AI: 相手のコスト1以下キャラを KO する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost1
    opp.characters = [victim]

    on_play = _get_eff(overlay, "OP02-076", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-076"), sickness=True))

    assert victim not in opp.characters, "相手のコスト1キャラが KO されていない"


def test_op02_076_shiryu_on_play_ko_high_cost_immune():
    """コスト2以上のキャラは対象外 → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    survivor = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2
    opp.characters = [survivor]

    on_play = _get_eff(overlay, "OP02-076", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-076"), sickness=True))

    assert survivor in opp.characters, "コスト2キャラが KO されてはいけない (対象外)"


def test_op02_076_shiryu_on_play_ko_human_pick():
    """人間 + 相手のコスト1キャラ 複数 → target_pick modal が立ち resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)   # ナミ cost1
    b = InPlay.of(repo.get("EB04-002"), sickness=False)   # ボニー cost1
    opp.characters = [a, b]

    on_play = _get_eff(overlay, "OP02-076", "on_play")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP02-076"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [b_idx])
        guard += 1
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP02-078 ダイフゴー: 【登場時】ドン!!-2：手札から「ダイフゴー」以外のコスト3以下
#                       特徴《SMILE》キャラ1枚までを登場させる
# --------------------------------------------------------------------------- #
def test_op02_078_daifugo_on_play_play_from_hand_ai():
    """AI: 手札から SMILE コスト3以下キャラ (ドボン) を登場させる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP02-080")]  # ドボン cost2 SMILE

    on_play = _get_eff(overlay, "OP02-078", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-078"), sickness=True))

    assert any(c.card.card_id == "OP02-080" for c in me.characters), \
        "手札から SMILE キャラ (ドボン) が登場していない"
    assert not any(c.card_id == "OP02-080" for c in me.hand), \
        "登場した SMILE キャラが手札から取り除かれていない"


def test_op02_078_daifugo_on_play_play_from_hand_human_pick():
    """人間 + 手札に SMILE コスト3以下 複数 → play_from_hand_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    # 2 種の SMILE cost3以下 を手札に
    me.hand = [repo.get("OP02-080"), repo.get("OP08-083")]  # ドボン / シープスヘッド

    on_play = _get_eff(overlay, "OP02-078", "on_play")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP02-078"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    guard = 0
    while st.pending_choice is not None and guard < 6:
        resolve_pending_choice(st, [0])
        guard += 1
    assert any(c.card.card_id in ("OP02-080", "OP08-083")
               for c in me.characters), \
        "人間が選んだ SMILE キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP02-079 ダグラス・バレット: 【登場時】ドン!!-1：相手のコスト4以下キャラ1枚まで、
#                                レストにする
# --------------------------------------------------------------------------- #
def test_op02_079_barrett_on_play_rest_cost4_ai():
    """AI: 相手のコスト4以下のアクティブキャラをレストにする。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    victim.rested = False
    opp.characters = [victim]

    on_play = _get_eff(overlay, "OP02-079", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-079"), sickness=True))

    assert victim.rested is True, "相手のコスト4以下キャラがレストされていない"


def test_op02_079_barrett_on_play_rest_human_pick():
    """人間 + 相手のコスト4以下キャラ 複数 → target_pick modal が立ち resolve でレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [a, b]

    on_play = _get_eff(overlay, "OP02-079", "on_play")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP02-079"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で rest modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [b_idx])
        guard += 1
    assert b.rested is True, "人間が選んだキャラがレストされていない"
    assert a.rested is False, "選ばなかったキャラはアクティブのままであるべき"


# --------------------------------------------------------------------------- #
#  OP02-082 バーンディ・ワールド: 【起動メイン】ドン!!-8：このキャラは
#                                 このターン中 パワー+792000
# --------------------------------------------------------------------------- #
def test_op02_082_burndy_activate_main_self_pump():
    """自身に +792000 (対象選択なし・target self の単純 pump)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    burndy = InPlay.of(repo.get("OP02-082"), sickness=False)  # power 8000
    me.characters = [burndy]

    power_before = burndy.power
    eff = _get_eff(overlay, "OP02-082", "activate_main")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, burndy)

    assert burndy.power == power_before + 792000, \
        f"起動メインの自己 +792000 が反映されていない: {burndy.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  OP02-083 ハンニャバル: 【登場時】デッキ上5枚を見て「ハンニャバル」以外の
#                         紫の特徴《インペルダウン》カード1枚までを手札へ、 残りデッキ下
# --------------------------------------------------------------------------- #
def test_op02_083_hannyabal_on_play_search_ai():
    """AI: デッキ上5枚から 紫インペルダウンカード (ドミノ) を手札に加える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    domino = repo.get("OP02-081")  # ドミノ 紫 インペルダウン
    assert "インペルダウン" in (domino.features or ""), "テスト前提: OP02-081 は インペルダウン"
    me.deck = [domino] + [repo.get("OP01-013")] * 20
    me.hand = []

    on_play = _get_eff(overlay, "OP02-083", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-083"), sickness=True))

    assert any(c.card_id == "OP02-081" for c in me.hand), \
        "デッキ上5枚から 紫インペルダウンカードが手札に加わっていない"


def test_op02_083_hannyabal_on_play_search_human_pick():
    """人間 + デッキ上5枚に該当カードあり → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    domino = repo.get("OP02-081")
    me.deck = [domino, repo.get("OP01-013"), domino] + [repo.get("OP01-013")] * 15
    me.hand = []

    on_play = _get_eff(overlay, "OP02-083", "on_play")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP02-083"), sickness=True))

    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (ドミノ) を選択
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [])
        guard += 1
    assert any(c.card_id == "OP02-081" for c in me.hand), \
        "人間が選んだ 紫インペルダウンカードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP02-085 マゼラン: 【登場時】ドン!!-1：相手はドン1枚をドンデッキに戻す /
#                     【相手のターン中】このキャラKO時、相手はドン2枚を戻す
# --------------------------------------------------------------------------- #
def test_op02_085_magellan_on_play_return_opp_don_ai():
    """AI: 登場時に相手のドン1枚をドンデッキへ戻す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.don_active = 3
    opp.don_remaining_in_deck = 5

    active_before = opp.don_active
    remain_before = opp.don_remaining_in_deck
    on_play = _get_eff(overlay, "OP02-085", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-085"), sickness=True))

    assert opp.don_active == active_before - 1, "相手のドンが1枚戻されていない"
    assert opp.don_remaining_in_deck == remain_before + 1, \
        "戻したドンがドンデッキに加算されていない"


def test_op02_085_magellan_on_ko_return_opp_don2():
    """【相手のターン中】自身KO時: 相手はドン2枚をドンデッキへ戻す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.don_active = 4
    opp.don_remaining_in_deck = 4

    active_before = opp.don_active
    on_ko = _get_eff(overlay, "OP02-085", "on_ko")
    for prim in on_ko["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-085"), sickness=True))

    assert opp.don_active == active_before - 2, "KO時に相手のドンが2枚戻されていない"


# --------------------------------------------------------------------------- #
#  OP02-089 地獄の審判 (EVENT): 【カウンター】ドン!!-1：相手のリーダーかキャラ
#                               合計2枚まで、 このターン中 パワー-3000
# --------------------------------------------------------------------------- #
def test_op02_089_hell_judgment_counter_debuff_ai():
    """AI: 相手のリーダー/キャラ 合計2枚に -3000 (キャラ優先)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # power 3000
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # power 3000
    opp.characters = [a, b]

    a_before, b_before = a.power, b.power
    counter = _get_eff(overlay, "OP02-089", "counter")
    for prim in counter["do"]:
        execute_effect(prim, st, me, opp, None)

    assert a.power == a_before - 3000 and b.power == b_before - 3000, \
        f"相手キャラ2枚への -3000 が反映されていない: {a.power}/{b.power}"


def test_op02_089_hell_judgment_counter_debuff_human_pick():
    """人間 + 相手リーダー+キャラ2 (計3候補>2) → target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)
    b = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [a, b]

    counter = _get_eff(overlay, "OP02-089", "counter")
    execute_effect(counter["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 3候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    assert st.pending_choice.get("limit") == 2, \
        f"limit が 2 でない: {st.pending_choice.get('limit')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 3, f"候補 (リーダー+キャラ2) が 3 件でない: {len(cands)}"

    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    a_before, b_before = a.power, b.power
    resolve_pending_choice(st, [a_idx, b_idx])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [a_idx, b_idx])
        guard += 1
    assert a.power == a_before - 3000 and b.power == b_before - 3000, \
        "人間が選んだ2枚に -3000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP02-090 毒竜 (EVENT): 【メイン】ドン!!-1：相手のキャラ1枚まで、 このターン中 -3000
# --------------------------------------------------------------------------- #
def test_op02_090_dokuryu_main_debuff_ai():
    """AI: 相手キャラ1枚に -3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # power 3000
    opp.characters = [victim]

    power_before = victim.power
    main = _get_eff(overlay, "OP02-090", "main")
    for prim in main["do"]:
        execute_effect(prim, st, me, opp, None)

    assert victim.power == power_before - 3000, \
        f"相手キャラ -3000 が反映されていない: {victim.power} (before {power_before})"


def test_op02_090_dokuryu_main_debuff_human_pick():
    """人間 + 相手キャラ 複数 → target_pick modal が立ち resolve で -3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # power 3000
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # power 2000
    opp.characters = [a, b]

    main = _get_eff(overlay, "OP02-090", "main")
    execute_effect(main["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [b_idx])
        guard += 1
    assert b.power == b_before - 3000, "人間が選んだ相手キャラに -3000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP02-091 毒の道 (EVENT): 【メイン】ドン!!デッキからドン1枚までをアクティブで追加
# --------------------------------------------------------------------------- #
def test_op02_091_dokunomichi_main_add_don_ai():
    """AI: ドンデッキからドン1枚をアクティブで場に追加する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 2
    me.don_remaining_in_deck = 8

    active_before = me.don_active
    remain_before = me.don_remaining_in_deck
    main = _get_eff(overlay, "OP02-091", "main")
    for prim in main["do"]:
        execute_effect(prim, st, me, opp, None)

    assert me.don_active == active_before + 1, "アクティブドンが1枚追加されていない"
    assert me.don_remaining_in_deck == remain_before - 1, \
        "ドンデッキ残数が1枚減っていない"
