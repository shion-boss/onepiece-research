# -*- coding: utf-8 -*-
"""OP05 弾 効果 回帰テスト バックフィル (自動生成 wave 058):
OP05-053 / OP05-054 / OP05-055 / OP05-056 / OP05-057 / OP05-058 /
OP05-059 / OP05-060 / OP05-061 / OP05-062 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_057.py と同一方針):
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

# よく使うテスト用カード (テキストの前提固定)
_LEADER_NEUTRAL = "OP01-001"   # ロロノア・ゾロ (赤、 単色)
_LEADER_MULTI = "EB03-001"     # ネフェルタリ・ビビ (赤/青、 多色)
_NAMI = "OP01-016"             # ナミ cost1 power2000
_RED_C2 = "ST01-004"           # サンジ cost2 power4000
_RED_C3 = "EB02-003"           # トニートニー・チョッパー cost3 power3000
_ISSHO_C6 = "OP05-042"         # イッショウ cost6 power6000 (cost>N の耐性チェック用)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(_RED_C2)] * 30
    p1.deck = [repo.get(_RED_C2)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果の do (list) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e["do"]
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]["do"]


def _eff(overlay, cid, when):
    """when 一致の効果 dict (do + if を含む) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    return matches[0]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave58_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP05-053", "OP05-054", "OP05-055", "OP05-056", "OP05-057",
           "OP05-058", "OP05-059", "OP05-060", "OP05-061", "OP05-062"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP05-053 モザンビア (CHARACTER 青 cost1 power2000 海軍):
#    【自分のターン中】【ターン1回】自分がドローフェイズ以外でカードを引いた時、
#      このキャラは、このターン中、パワー+2000。 (power_pump self +2000)
# --------------------------------------------------------------------------- #
def test_op05_053_self_power_pump():
    """トリガー do (power_pump self +2000): 自身の power が +2000 される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    mozan = InPlay.of(repo.get("OP05-053"), sickness=False)  # power2000
    me.characters = [mozan]

    eff = _eff(overlay, "OP05-053", "on_self_draw_non_draw_phase")
    assert eff.get("if", {}).get("self_turn") is True, \
        "overlay の 発火条件 self_turn=True が無い"
    power_before = mozan.power
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, mozan)

    assert mozan.power == power_before + 2000, \
        f"自己 +2000 が反映されていない: {mozan.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  OP05-054 モンキー・D・ガープ (CHARACTER 青 cost3 power3000 海軍):
#    【登場時】カード2枚を引き、自分の手札2枚を好きな順番でデッキの下に置く。
#    (draw 2 + self_hand_to_deck_bottom 2)
# --------------------------------------------------------------------------- #
def test_op05_054_on_play_draw2_bottom2_ai():
    """登場時 (AI): 2 枚引いて 手札 2 枚をデッキの下に置く。
    手札 0 → draw2 で 2 枚 → その 2 枚を底に戻すので 手札は再び 0、 デッキ総数不変。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    # デッキ上 2 枚を識別できるカードにする (draw されるカード)
    top0 = repo.get(_NAMI)
    top1 = repo.get(_RED_C3)
    me.deck = [top0, top1] + [repo.get(_RED_C2)] * 28
    deck_before = len(me.deck)

    for prim in _do(overlay, "OP05-054", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-054"), sickness=False))
    _drain(st)

    assert len(me.hand) == 0, \
        f"draw2 → bottom2 で手札が元 (0) に戻っていない: {len(me.hand)}"
    assert len(me.deck) == deck_before, \
        f"デッキ総数が変わっている (2 引いて 2 戻すので不変のはず): {len(me.deck)}"
    # 引いた 2 枚が デッキの下 (末尾) に置かれている
    bottom_ids = {c.card_id for c in me.deck[-2:]}
    assert _NAMI in bottom_ids and _RED_C3 in bottom_ids, \
        f"引いた 2 枚がデッキ末尾に戻っていない: {bottom_ids}"


def test_op05_054_on_play_human_bottom_pick():
    """登場時 (人間): 引いた後 手札 > 2 → self_hand_to_deck_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_ISSHO_C6)]  # 既存 1 枚 + draw2 = 3 枚 → 選択が発生
    me.deck = [repo.get(_NAMI), repo.get(_RED_C3)] + [repo.get(_RED_C2)] * 28

    for prim in _do(overlay, "OP05-054", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-054"), sickness=False))

    assert st.pending_choice is not None, \
        "人間 + 手札 3 枚で self_hand_to_deck 選択 modal が立たない"
    assert st.pending_choice.get("kind") == "self_hand_to_deck_pick", \
        f"kind が self_hand_to_deck_pick でない: {st.pending_choice.get('kind')}"
    assert st.pending_choice.get("limit") == 2, \
        f"デッキ下へ置く枚数 (limit) が 2 でない: {st.pending_choice.get('limit')}"
    _drain(st, pick=[0, 1])
    assert len(me.hand) == 1, \
        f"手札 3 枚から 2 枚をデッキ下へ置いた後は 1 枚のはず: {len(me.hand)}"


# --------------------------------------------------------------------------- #
#  OP05-055 X・ドレーク (CHARACTER 青 cost5 power6000 海軍):
#    【ブロッカー】【登場時】自分のデッキの上から5枚を見て、好きな順番に並び替え、
#      デッキの上か下に置く。 (look_top_reorder depth5 to=choice)
# --------------------------------------------------------------------------- #
def test_op05_055_on_play_look_top_reorder_ai():
    """登場時 (AI): デッキ上 5 枚を コスト昇順に並び替えて上に置く (crash せず並ぶ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    # デッキ上 5 枚を コスト降順 (6,3,2,1,1) に仕込む → 効果で昇順に並ぶはず
    me.deck = [
        repo.get(_ISSHO_C6),  # 6
        repo.get(_RED_C3),    # 3
        repo.get(_RED_C2),    # 2
        repo.get(_NAMI),      # 1
        repo.get(_NAMI),      # 1
    ] + [repo.get(_RED_C2)] * 25
    deck_before = len(me.deck)

    for prim in _do(overlay, "OP05-055", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-055"), sickness=False))
    _drain(st)

    assert len(me.deck) == deck_before, "デッキ枚数が変わってはいけない (並び替えのみ)"
    top5_costs = [c.cost for c in me.deck[:5]]
    assert top5_costs == sorted(top5_costs), \
        f"デッキ上 5 枚が コスト昇順に並んでいない: {top5_costs}"


# --------------------------------------------------------------------------- #
#  OP05-056 X・バレルズ (CHARACTER 青 cost2 power2000 元海軍):
#    【登場時】このキャラ以外の自分のキャラ1枚をデッキの下に置くことができる：
#      カード1枚を引く。 (overlay do = draw 1)
# --------------------------------------------------------------------------- #
def test_op05_056_on_play_draw1():
    """登場時: **このキャラ以外の自分のキャラ1枚をデッキの下に置いて** カード 1 枚を引く。

    ⚠ 公式は 「【登場時】このキャラ以外の自分のキャラ1枚をデッキの下に置くことができる：
    カード1枚を引く。」 = コロン前が発動コスト (cardqa_st_06)。 生贄が居なければ引けない。
    """
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    src = InPlay.of(repo.get("OP05-056"), sickness=False)
    fodder = InPlay.of(repo.get("ST01-004"), sickness=False)
    me.characters = [src, fodder]   # コストに使える 「このキャラ以外」 が 1 枚
    hand_before = len(me.hand)
    deck_before = len(me.deck)

    for prim in _do(overlay, "OP05-056", "on_play"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert len(me.hand) == hand_before + 1, \
        f"カード 1 枚が引かれていない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 1 + 1, \
        f"デッキ枚数が (引く-1 + コストで戻る+1) になっていない: {len(me.deck)}"
    assert [c.card.card_id for c in me.characters] == ["OP05-056"], \
        "コストで 「このキャラ以外」 の自キャラがデッキ下に置かれていない"


def test_op05_056_on_play_not_free_without_other_chara():
    """⚠ 対照: 「このキャラ以外」 の自キャラが居なければ コストを払えずドローしない。

    発動元自身を除外しないと 「自分だけの盤面」 でもタダでドローできてしまう
    (= except_self、 2026-08-05 に是正)。
    """
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    src = InPlay.of(repo.get("OP05-056"), sickness=False)
    me.characters = [src]           # 自分自身のみ = 払えない
    deck_before = len(me.deck)

    for prim in _do(overlay, "OP05-056", "on_play"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert not me.hand, "コストを払えないのにドローしている"
    assert len(me.deck) == deck_before, "コストを払えないのにデッキが動いている"
    assert len(me.characters) == 1, "発動元自身がコストに使われている"


# --------------------------------------------------------------------------- #
#  OP05-057 犬噛紅蓮 (EVENT 青 cost2 海軍):
#    【メイン】自分のリーダーかキャラ1枚までを、このターン中、パワー+3000。
#      その後、コスト2以下のキャラ1枚までを、持ち主のデッキの下に置く。
#    【トリガー】コスト3以下のキャラ1枚までを、持ち主の手札に戻す。
# --------------------------------------------------------------------------- #
def test_op05_057_main_return_deck_bottom_ai():
    """メイン: (その後の) 相手キャラ 1 枚を持ち主のデッキの下に置く (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_RED_C2), sickness=False)  # cost2 (<=2)
    opp.characters = [victim]
    opp_deck_before = len(opp.deck)

    do = _do(overlay, "OP05-057", "main", needle="return_to_deck_bottom")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-057"), sickness=False))
    _drain(st, pick=[0])

    assert victim not in opp.characters, "相手キャラがデッキの下に置かれていない"
    assert len(opp.deck) == opp_deck_before + 1, \
        "対象が持ち主 (相手) のデッキの下に戻っていない"


def test_op05_057_main_human_pick():
    """メイン (人間): 相手キャラ複数 → return_to_deck_bottom の target_pick modal。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_NAMI), sickness=False)
    b = InPlay.of(repo.get(_RED_C2), sickness=False)
    opp.characters = [a, b]

    do = _do(overlay, "OP05-057", "main", needle="return_to_deck_bottom")
    # power_pump 部を飛ばし return 部のみを 人間文脈で発火
    return_prim = next(p for p in do if "return_to_deck_bottom" in p)
    execute_effect(return_prim, st, me, opp,
                   InPlay.of(repo.get("OP05-057"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[b_idx])
    assert b not in opp.characters, "人間が選んだキャラがデッキに戻されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


def test_op05_057_trigger_return_hand_ai():
    """トリガー: 相手のコスト3以下キャラ 1 枚を持ち主の手札に戻す (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_RED_C3), sickness=False)  # cost3 (<=3)
    opp.characters = [victim]

    for prim in _do(overlay, "OP05-057", "trigger"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-057"), sickness=False))
    _drain(st, pick=[0])

    assert victim not in opp.characters, "相手のコスト3以下キャラが手札に戻されていない"
    assert any(c.card_id == _RED_C3 for c in opp.hand), \
        "対象が持ち主 (相手) の手札に戻っていない"


# --------------------------------------------------------------------------- #
#  OP05-058 命がも゛ったいだいっ!!!! (EVENT 青 cost8 海軍):
#    【メイン】コスト3以下のキャラすべてを、持ち主のデッキの下に置く。その後、
#      お互いは手札が5枚になるように、自身の手札を捨てる。
#    【トリガー】コスト2以下のキャラすべてを、持ち主のデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op05_058_main_sweep_and_hand_to_5_ai():
    """メイン (AI): 両陣営のコスト3以下キャラすべてを デッキ下へ、
    その後 お互いの手札を 5 枚にする。 コスト6キャラ (>3) は残る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    my3 = InPlay.of(repo.get(_RED_C3), sickness=False)     # cost3 (<=3)
    opp1 = InPlay.of(repo.get(_NAMI), sickness=False)      # cost1 (<=3)
    opp6 = InPlay.of(repo.get(_ISSHO_C6), sickness=False)  # cost6 (>3、 残る)
    me.characters = [my3]
    opp.characters = [opp1, opp6]
    me.hand = [repo.get(_RED_C2)] * 7   # 7 → 5
    opp.hand = [repo.get(_RED_C2)] * 7  # 7 → 5

    for prim in _do(overlay, "OP05-058", "main"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-058"), sickness=False))
    _drain(st)

    assert my3 not in me.characters, "自分のコスト3以下キャラがデッキ下へ置かれていない"
    assert opp1 not in opp.characters, "相手のコスト1キャラがデッキ下へ置かれていない"
    assert opp6 in opp.characters, "コスト6キャラ (>3) は対象外で残るべき"
    assert len(me.hand) == 5, f"自分の手札が 5 枚になっていない: {len(me.hand)}"
    assert len(opp.hand) == 5, f"相手の手札が 5 枚になっていない: {len(opp.hand)}"


def test_op05_058_trigger_sweep_cost_le_2_ai():
    """トリガー: 相手のコスト2以下キャラすべてを デッキ下へ。 コスト3は残る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    opp1 = InPlay.of(repo.get(_NAMI), sickness=False)   # cost1 (<=2)
    opp2 = InPlay.of(repo.get(_RED_C2), sickness=False)  # cost2 (<=2)
    opp3 = InPlay.of(repo.get(_RED_C3), sickness=False)  # cost3 (>2、 残る)
    opp.characters = [opp1, opp2, opp3]

    for prim in _do(overlay, "OP05-058", "trigger"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-058"), sickness=False))
    _drain(st)

    assert opp1 not in opp.characters, "相手のコスト1キャラがデッキ下へ置かれていない"
    assert opp2 not in opp.characters, "相手のコスト2キャラがデッキ下へ置かれていない"
    assert opp3 in opp.characters, "コスト3キャラ (>2) は対象外で残るべき"


# --------------------------------------------------------------------------- #
#  OP05-059 始めよう”暴力の世界”!!! (EVENT 青 cost5 四皇/百獣海賊団):
#    【メイン】自分のリーダーが多色の場合、カード1枚を引く。その後、
#      コスト5以下のキャラ1枚までを、持ち主の手札に戻す。
#    【トリガー】自分のリーダーが多色の場合、カード2枚を引く。
# --------------------------------------------------------------------------- #
def test_op05_059_main_draw_and_return_self_ai():
    """メイン (多色リーダー、 AI): 1 枚引き、 自分のコスト5以下キャラ 1 枚を手札に戻す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MULTI, overlay)  # 多色リーダー
    me, opp = st.players[0], st.players[1]
    me.hand = []
    friend = InPlay.of(repo.get(_RED_C2), sickness=False)  # cost2 (<=5)
    me.characters = [friend]

    eff = _eff(overlay, "OP05-059", "main")
    assert eff.get("if", {}).get("leader_multicolor") is True, \
        "overlay の 発火条件 leader_multicolor=True が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-059"), sickness=False))
    _drain(st, pick=[0])

    assert friend not in me.characters, "自分のコスト5以下キャラが手札に戻されていない"
    # draw1 (+1) と 手札に戻った friend (+1) で 手札 2 枚
    assert any(c.card_id == _RED_C2 for c in me.hand), \
        "戻したキャラが手札に入っていない"
    assert len(me.hand) == 2, f"draw1 + 戻し1 で手札 2 枚のはず: {len(me.hand)}"


def test_op05_059_main_human_pick():
    """メイン (人間、 多色): 自分のコスト5以下キャラ複数 → return_to_hand の target_pick。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MULTI, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    a = InPlay.of(repo.get(_NAMI), sickness=False)    # cost1
    b = InPlay.of(repo.get(_RED_C2), sickness=False)  # cost2
    me.characters = [a, b]

    do = _do(overlay, "OP05-059", "main")
    return_prim = next(p for p in do if "return_to_hand" in p)
    execute_effect(return_prim, st, me, opp,
                   InPlay.of(repo.get("OP05-059"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[b_idx])
    assert b not in me.characters, "人間が選んだキャラが手札に戻されていない"
    assert a in me.characters, "選ばなかったキャラは残るべき"


def test_op05_059_main_no_draw_when_monocolor():
    """メイン (単色リーダー): leader_multicolor 条件不成立 → entry の if で不発 (引かない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)  # 単色リーダー
    me, opp = st.players[0], st.players[1]
    from engine.effects import eval_condition
    eff = _eff(overlay, "OP05-059", "main")
    assert eval_condition(eff.get("if", {}), st, me, None) is False, \
        "単色リーダーで leader_multicolor 条件が不成立にならない"


# --------------------------------------------------------------------------- #
#  OP05-060 モンキー・D・ルフィ (LEADER 紫 power5000 麦わらの一味):
#    【起動メイン】【ターン1回】自分のライフの上から1枚を手札に加えることができる：
#      自分の場のドン!!が0枚か、3枚以上ある場合、ドン!!デッキからドン!!1枚までを、
#      アクティブで追加する。 (life_to_hand1 + conditional add_don1)
# --------------------------------------------------------------------------- #
def test_op05_060_activate_main_life_and_add_don():
    """起動メイン: ライフ1→手札、 場のドン3枚 (>=3) 条件成立 → ドン1アクティブ追加。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP05-060", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_NAMI), repo.get(_RED_C3)]  # ライフ 2
    me.hand = []
    me.don_active = 3   # 場のドン 3 (>=3) → 条件成立
    me.don_remaining_in_deck = 5

    options = list_activate_main_effects(st, me, overlay)
    luffy_opts = [(src, eff) for (src, eff) in options
                  if src.card.card_id == "OP05-060"]
    assert len(luffy_opts) == 1, \
        f"OP05-060 の起動メインが legal に出ない: {len(luffy_opts)}"
    fire_activate_main(st, me, opp, *luffy_opts[0])
    _drain(st)

    assert len(me.life) == 1, f"ライフ 1 枚が手札に加わっていない: life={len(me.life)}"
    assert len(me.hand) == 1, f"ライフ 1 枚が手札に来ていない: hand={len(me.hand)}"
    assert me.don_active == 4, \
        f"条件成立でドン1アクティブ追加されていない: don_active={me.don_active}"
    assert me.don_remaining_in_deck == 4, "ドンデッキが 1 枚減っていない"


def test_op05_060_activate_main_no_don_when_field_1_or_2():
    """場のドンが 1 or 2 枚 (0でも3以上でもない) → 追加ドンなし、 ライフ手札化のみ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP05-060", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_NAMI), repo.get(_RED_C3)]
    me.hand = []
    me.don_active = 2   # 場のドン 2 (0でも3以上でもない) → 条件不成立
    me.don_remaining_in_deck = 5

    luffy_opts = [(src, eff) for (src, eff) in list_activate_main_effects(st, me, overlay)
                  if src.card.card_id == "OP05-060"]
    fire_activate_main(st, me, opp, *luffy_opts[0])
    _drain(st)

    assert len(me.life) == 1, "ライフ 1 枚が手札に加わっていない"
    assert me.don_active == 2, \
        f"条件不成立なのにドンが追加されている: don_active={me.don_active}"


def test_op05_060_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP05-060", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_NAMI), repo.get(_RED_C3), repo.get(_NAMI)]
    me.don_active = 3
    me.don_remaining_in_deck = 5

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP05-060"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st)

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP05-060"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP05-061 ウソ八 (CHARACTER 紫 cost3 power4000 麦わらの一味):
#    【ドン!!×1】【アタック時】自分の場にドン!!が8枚以上ある場合、
#      相手のコスト4以下のキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_op05_061_on_attack_rest_ai():
    """アタック時 (ドン8+ゲート): 相手のコスト4以下キャラ 1 枚をレストにする (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_RED_C3), sickness=False)  # cost3 (<=4)
    opp.characters = [victim]

    eff = _eff(overlay, "OP05-061", "on_attack")
    assert eff.get("if", {}).get("self_don_ge") == 8, \
        "overlay の 発火条件 self_don_ge=8 が無い"
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-061"), sickness=False))
    _drain(st, pick=[0])

    assert victim.rested is True, "相手のコスト4以下キャラがレストになっていない"


def test_op05_061_on_attack_human_pick():
    """アタック時 (人間): 相手のコスト4以下キャラ複数 → rest の target_pick modal。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_NAMI), sickness=False)    # cost1
    b = InPlay.of(repo.get(_RED_C3), sickness=False)  # cost3
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP05-061", "on_attack")[0], st, me, opp,
                   InPlay.of(repo.get("OP05-061"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[b_idx])
    assert b.rested is True, "人間が選んだキャラがレストになっていない"
    assert a.rested is False, "選ばなかったキャラはレストにならないべき"


# --------------------------------------------------------------------------- #
#  OP05-062 おナミ (CHARACTER 紫 cost1 power1000 麦わらの一味):
#    自分の場にドン!!が10枚ある場合、このキャラは【ブロッカー】を得る。
#    (静的 on_attached_don n=0、 if self_don_ge=10、 give_keyword ブロッカー)
# --------------------------------------------------------------------------- #
def test_op05_062_static_gains_blocker_at_don_10():
    """場のドン10枚 (>=10) 条件成立 → 【ブロッカー】を得る。"""
    repo = _repo()
    overlay = _overlay()
    p0 = Player(name="P0", leader=InPlay.of(repo.get(_LEADER_NEUTRAL), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(_LEADER_NEUTRAL), sickness=False))
    onami = InPlay.of(repo.get("OP05-062"), sickness=False)
    p0.characters = [onami]
    st = GameState(players=[p0, p1], phase=Phase.MAIN, effects_overlay=overlay)
    st.turn_player_idx = 0
    st.human_player_idx = None
    p0.don_active = 10  # 場のドン 10 (>=10) → 条件成立

    evaluate_static_effects(st, overlay)
    assert onami.is_blocker_now, \
        f"ドン10枚で【ブロッカー】を得ていない: {onami.static_granted_keywords}"


def test_op05_062_static_no_blocker_below_don_10():
    """場のドン9枚 (<10) → 【ブロッカー】を得ない。"""
    repo = _repo()
    overlay = _overlay()
    p0 = Player(name="P0", leader=InPlay.of(repo.get(_LEADER_NEUTRAL), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(_LEADER_NEUTRAL), sickness=False))
    onami = InPlay.of(repo.get("OP05-062"), sickness=False)
    p0.characters = [onami]
    st = GameState(players=[p0, p1], phase=Phase.MAIN, effects_overlay=overlay)
    st.turn_player_idx = 0
    st.human_player_idx = None
    p0.don_active = 9  # 場のドン 9 (<10) → 条件不成立

    evaluate_static_effects(st, overlay)
    assert not onami.is_blocker_now, \
        f"ドン9枚で【ブロッカー】を得てはいけない: {onami.static_granted_keywords}"
