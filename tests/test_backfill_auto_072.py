# -*- coding: utf-8 -*-
"""OP06/OP07 弾 効果 回帰テスト バックフィル (自動生成 wave 072):
OP06-109 / OP06-110 / OP06-111 / OP06-112 / OP06-113 / OP06-114 /
OP06-115 / OP06-116 / OP06-117 / OP07-002 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_071.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 択一 / 任意コスト を 持つカードは 人間 actor で pending_choice が
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
    eval_condition,
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

_LEADER = "OP01-001"    # ロロノア・ゾロ (赤、 汎用リーダー・特徴なし前提)
_FILLER = "OP01-013"    # サンジ cost2 power3000 (汎用フィラー、 登場時なし)
_STAGE1 = "EB02-041"    # コスト1 ステージ (cost_eq:1 コスト用ヘルパー)
_SHANDRA = "OP15-100"   # カマキリ cost5 power6000 (シャンドラの戦士、 ラキ以外の対象)
_ENEL = "OP15-060"      # エネル cost6 power8000 (方舟マクシムのコスト用)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(_FILLER)] * 30
    p1.deck = [repo.get(_FILLER)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _eff(overlay, cid, when):
    """when 一致の効果 dict (do + if を含む) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    return matches[0]


def _do(overlay, cid, when):
    """指定 card_id の overlay から when 一致の効果の do (list) を返す。"""
    return _eff(overlay, cid, when)["do"]


def _drain(st, pick=0, guard=15):
    """pending_choice を pick で自動解決し切る (= 後続効果を流す)。"""
    g = 0
    while st.pending_choice is not None and g < guard:
        resolve_pending_choice(st, [pick])
        g += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave72_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP06-109", "OP06-110", "OP06-111", "OP06-112", "OP06-113",
           "OP06-114", "OP06-115", "OP06-116", "OP06-117", "OP07-002"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP06-109 傳ジロー (CHARACTER 黄 cost5 power6000):
#    【ドン!!×2】相手のライフが3枚以下の場合、このキャラは効果でKOされない。
#    【トリガー】相手のライフが3枚以下の場合、このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op06_109_static_ko_immune_when_don2_opp_life_le3():
    """常在: ドン!!×2 付与 + 相手ライフ3枚以下 → static_ko_immune が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    denjiro = InPlay.of(repo.get("OP06-109"), sickness=False)
    denjiro.attached_dons = 2  # ドン!!×2 ゲート成立
    me.characters = [denjiro]
    opp.life = [repo.get(_FILLER)] * 3  # 相手ライフ 3 枚 (<=3)

    evaluate_static_effects(st, overlay)
    assert denjiro.static_ko_immune is True, \
        "ドン2 + 相手ライフ3以下で 効果KO耐性が立っていない"


def test_op06_109_static_ko_immune_off_when_opp_life_ge4():
    """常在 negative: 相手ライフ4枚 (>3) では KO耐性が立たない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    denjiro = InPlay.of(repo.get("OP06-109"), sickness=False)
    denjiro.attached_dons = 2
    me.characters = [denjiro]
    opp.life = [repo.get(_FILLER)] * 4  # ライフ 4 枚 = 条件不成立

    evaluate_static_effects(st, overlay)
    assert denjiro.static_ko_immune is False, \
        "相手ライフ4枚なのに KO耐性が立っている"


def test_op06_109_static_ko_immune_off_when_don1():
    """常在 negative: ドン!!×1 (n=2 未満) では KO耐性が立たない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    denjiro = InPlay.of(repo.get("OP06-109"), sickness=False)
    denjiro.attached_dons = 1  # ドン1 = ゲート未達
    me.characters = [denjiro]
    opp.life = [repo.get(_FILLER)] * 3

    evaluate_static_effects(st, overlay)
    assert denjiro.static_ko_immune is False, \
        "ドン1枚なのに KO耐性が立っている"


def test_op06_109_trigger_play_self_when_opp_life_le3_ai():
    """トリガー: 相手のライフが3枚以下なら このカードを登場させる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_FILLER)] * 3
    me.trash = [repo.get("OP06-109")]
    st.current_source_card_id = "OP06-109"
    cond = _eff(overlay, "OP06-109", "trigger").get("if")
    assert eval_condition(cond, st, me) is True, "相手ライフ3枚で条件が成立していない"

    for prim in _do(overlay, "OP06-109", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    ids = [c.card.card_id for c in me.characters]
    assert "OP06-109" in ids, "トリガーでこのカードが登場していない"


# --------------------------------------------------------------------------- #
#  OP06-110 ネコマムシ (CHARACTER 黄 cost4 power5000):
#    【ドン!!×2】このキャラは相手のアクティブのキャラにもアタックできる。
#    【トリガー】相手のライフが3枚以下の場合、このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op06_110_static_attack_active_when_don2():
    """常在: ドン!!×2 付与 → 「アクティブアタック可」 キーワードを得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    neko = InPlay.of(repo.get("OP06-110"), sickness=False)
    neko.attached_dons = 2  # ドン!!×2
    me.characters = [neko]

    evaluate_static_effects(st, overlay)
    assert "アクティブアタック可" in neko.granted_keywords, \
        f"ドン2で アクティブアタック可 が付与されていない: {neko.granted_keywords}"


def test_op06_110_trigger_play_self_when_opp_life_le3_ai():
    """トリガー: 相手のライフが3枚以下なら このカードを登場させる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_FILLER)] * 3
    me.trash = [repo.get("OP06-110")]
    st.current_source_card_id = "OP06-110"

    for prim in _do(overlay, "OP06-110", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    ids = [c.card.card_id for c in me.characters]
    assert "OP06-110" in ids, "トリガーでこのカードが登場していない"


# --------------------------------------------------------------------------- #
#  OP06-111 ブラハム (CHARACTER 黄 cost3):
#    【起動メイン】【ターン1回】コスト1のステージ1枚を持ち主のデッキの下に置くことができる：
#      相手のコスト4以下のキャラ1枚までを、レストにする。
#    【トリガー】自分のライフが2枚以下の場合、このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op06_111_activate_main_rest_via_stage_ai():
    """起動メイン: コスト1ステージをデッキ下へ → 相手コスト4以下キャラ1枚をレスト (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    braham = InPlay.of(repo.get("OP06-111"), sickness=False)
    me.characters = [braham]
    me.stages = [InPlay.of(repo.get(_STAGE1), sickness=False)]  # コスト1ステージ
    me.deck = [repo.get(_FILLER)] * 10
    deck_before = len(me.deck)
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 <= 4
    opp.characters = [victim]

    options = list_activate_main_effects(st, me, overlay)
    braham_opts = [(src, eff) for (src, eff) in options
                   if src.card.card_id == "OP06-111"]
    assert len(braham_opts) == 1, \
        f"OP06-111 の起動メインが legal に出ない: {len(braham_opts)}"
    fire_activate_main(st, me, opp, *braham_opts[0])
    _drain(st)

    assert victim.rested is True, "相手コスト4以下キャラがレストされていない"
    assert len(me.stages) == 0, "コストのステージがデッキ下に置かれていない"
    assert len(me.deck) == deck_before + 1, "ステージがデッキの下に戻っていない"


def test_op06_111_activate_main_human_optional_cost_modal():
    """起動メイン (人間): 任意コスト optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP06-111"), sickness=False)]
    me.stages = [InPlay.of(repo.get(_STAGE1), sickness=False)]
    opp.characters = [InPlay.of(repo.get(_FILLER), sickness=False)]

    execute_effect(_do(overlay, "OP06-111", "activate_main")[0], st, me, opp,
                   me.characters[0])
    assert st.pending_choice is not None, "人間で任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    _drain(st)


def test_op06_111_trigger_play_self_when_self_life_le2_ai():
    """トリガー: 自分のライフが2枚以下なら このカードを登場させる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2  # 自ライフ 2 枚 (<=2)
    me.trash = [repo.get("OP06-111")]
    st.current_source_card_id = "OP06-111"
    cond = _eff(overlay, "OP06-111", "trigger").get("if")
    assert eval_condition(cond, st, me) is True, "自ライフ2枚で条件が成立していない"

    for prim in _do(overlay, "OP06-111", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    ids = [c.card.card_id for c in me.characters]
    assert "OP06-111" in ids, "トリガーでこのカードが登場していない"


# --------------------------------------------------------------------------- #
#  OP06-112 雷ぞう (CHARACTER 黄 cost3):
#    【アタック時】自分の手札1枚を捨てることができる：相手のドン!!1枚までを、レストにする。
#    【トリガー】相手のライフが3枚以下の場合、このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op06_112_on_attack_rest_opp_don_ai():
    """アタック時: 手札1枚を捨てて 相手のドン!!1枚をレストにする (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]
    opp.don_active = 3
    opp.don_rested = 0
    src = InPlay.of(repo.get("OP06-112"), sickness=False)

    for prim in _do(overlay, "OP06-112", "on_attack"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert len(me.hand) == 0, "コストの手札1枚が捨てられていない"
    assert opp.don_active == 2, f"相手アクティブドンが1枚減っていない: {opp.don_active}"
    assert opp.don_rested == 1, f"相手ドンが1枚レストされていない: {opp.don_rested}"


def test_op06_112_on_attack_human_optional_cost_modal():
    """アタック時 (人間): 任意コスト optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]
    opp.don_active = 3
    src = InPlay.of(repo.get("OP06-112"), sickness=False)

    execute_effect(_do(overlay, "OP06-112", "on_attack")[0], st, me, opp, src)
    assert st.pending_choice is not None, "人間で任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    _drain(st)


def test_op06_112_trigger_play_self_when_opp_life_le3_ai():
    """トリガー: 相手のライフが3枚以下なら このカードを登場させる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_FILLER)] * 3
    me.trash = [repo.get("OP06-112")]
    st.current_source_card_id = "OP06-112"

    for prim in _do(overlay, "OP06-112", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    ids = [c.card.card_id for c in me.characters]
    assert "OP06-112" in ids, "トリガーでこのカードが登場していない"


# --------------------------------------------------------------------------- #
#  OP06-113 ラキ (CHARACTER 黄 cost1 power1000):
#    「ラキ」以外の自分の特徴《シャンドラの戦士》を持つキャラがいる場合、
#      このキャラは【ブロッカー】を得る。
# --------------------------------------------------------------------------- #
def test_op06_113_gains_blocker_with_other_shandra():
    """常在: ラキ以外の《シャンドラの戦士》キャラが場にいれば【ブロッカー】を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    raki = InPlay.of(repo.get("OP06-113"), sickness=False)
    other = InPlay.of(repo.get(_SHANDRA), sickness=False)  # ラキ以外の シャンドラの戦士
    me.characters = [raki, other]

    evaluate_static_effects(st, overlay)
    assert "ブロッカー" in raki.static_granted_keywords, \
        f"他の シャンドラの戦士 がいるのに ブロッカー が付与されていない: {raki.static_granted_keywords}"


def test_op06_113_no_blocker_when_alone():
    """常在 negative: ラキ 単独 (他の シャンドラの戦士 なし) では ブロッカー を得ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    raki = InPlay.of(repo.get("OP06-113"), sickness=False)
    me.characters = [raki]  # ラキ のみ

    evaluate_static_effects(st, overlay)
    assert "ブロッカー" not in raki.static_granted_keywords, \
        "他の シャンドラの戦士 がいないのに ブロッカー が付与されている"


# --------------------------------------------------------------------------- #
#  OP06-114 ワイパー (CHARACTER 黄 cost5 power7000):
#    【登場時】コスト1のステージ1枚を持ち主のデッキの下に置くことができる：
#      自分のデッキの上から5枚を見て、「アッパーヤード」か特徴《シャンドラの戦士》を持つ
#      カード1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op06_114_on_play_search_shandra_ai():
    """登場時: デッキ上5枚から《シャンドラの戦士》カードを手札に加える (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_SHANDRA)] + [repo.get(_FILLER)] * 10  # 上に シャンドラの戦士
    me.hand = []
    # ⚠ 公式 「【登場時】コスト1のステージ1枚を持ち主のデッキの下に置くことができる：…」
    #   = コロン前が発動コスト (cardqa_st_06)。 コスト1のステージが要る (2026-08-05 に実装)。
    me.stages = [InPlay.of(repo.get("OP02-048"), sickness=False)]  # ワノ国 = cost1
    src = InPlay.of(repo.get("OP06-114"), sickness=True)

    for prim in _do(overlay, "OP06-114", "on_play"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert any(c.card_id == _SHANDRA for c in me.hand), \
        f"デッキ上5枚から シャンドラの戦士 が手札に加わっていない: {[c.card_id for c in me.hand]}"
    assert not me.stages, "コスト (コスト1のステージ) が支払われていない"


def test_op06_114_on_play_not_free_without_cost1_stage():
    """⚠ 対照: コスト1のステージが どちらの場にも無ければ サーチしない (= タダ撃ち禁止)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_SHANDRA)] + [repo.get(_FILLER)] * 10
    me.hand = []
    src = InPlay.of(repo.get("OP06-114"), sickness=True)

    for prim in _do(overlay, "OP06-114", "on_play"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert not me.hand, "コストを払えないのにサーチが発動している"


def test_op06_114_cost_can_use_opponent_stage():
    """公式は 「コスト1のステージ1枚」 = 修飾なし = **両陣営**。 相手のステージでも払える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_SHANDRA)] + [repo.get(_FILLER)] * 10
    me.hand = []
    me.stages = []
    opp.stages = [InPlay.of(repo.get("OP02-048"), sickness=False)]
    src = InPlay.of(repo.get("OP06-114"), sickness=True)

    for prim in _do(overlay, "OP06-114", "on_play"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert any(c.card_id == _SHANDRA for c in me.hand), \
        "相手のステージをコストにしてサーチできていない"
    assert not opp.stages, "相手のステージがコストとして支払われていない"
    assert opp.deck[-1].card_id == "OP02-048", \
        "相手のステージは **持ち主 (= 相手) の** デッキの下に置かれるべき"


def test_op06_114_on_play_human_search_modal():
    """登場時 (人間): デッキ上5枚に候補が複数 → search_top_n modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_SHANDRA), repo.get(_FILLER), repo.get(_SHANDRA)] \
        + [repo.get(_FILLER)] * 8
    me.hand = []
    me.stages = [InPlay.of(repo.get("OP02-048"), sickness=False)]  # コスト1ステージ
    src = InPlay.of(repo.get("OP06-114"), sickness=True)

    execute_effect(_do(overlay, "OP06-114", "on_play")[0], st, me, opp, src)
    # コロン前が発動コストなので、 人間はまず 払う/見送る を選ぶ
    assert st.pending_choice is not None, "人間 + 任意コストで modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"任意コスト確認 modal が先に立たない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])   # 払う
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭候補を選ぶ
    _drain(st)
    assert any(c.card_id == _SHANDRA for c in me.hand), \
        "人間が選んだ シャンドラの戦士 が手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP06-115 お前が消えろ (EVENT 黄):
#    【カウンター】自分の手札1枚を捨てることができる：
#      自分のリーダーかキャラ1枚までを、このバトル中、パワー+3000。
#    【トリガー】自分のライフが0枚の場合、自分のデッキの上から1枚までを、ライフの上に加える。
#      その後、自分の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op06_115_counter_pump_self_ai():
    """カウンター: 手札1枚を捨てて 自リーダー1枚を +3000 (AI、 場にキャラなし → リーダー)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]
    power_before = me.leader.power

    for prim in _do(overlay, "OP06-115", "counter"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert me.leader.power == power_before + 3000, \
        f"カウンターの +3000 が自リーダーに反映されていない: {me.leader.power}"
    assert len(me.hand) == 0, "コストの手札1枚が捨てられていない"


def test_op06_115_counter_human_optional_cost_modal():
    """カウンター (人間): 任意コスト optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]

    execute_effect(_do(overlay, "OP06-115", "counter")[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間で任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    _drain(st)


def test_op06_115_trigger_put_top_to_life_then_discard_ai():
    """トリガー: 自ライフ0枚 → デッキ上1枚をライフの上に、 その後手札1枚を捨てる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = []                       # 自ライフ 0 枚 (= 公式条件)
    me.deck = [repo.get(_FILLER)] * 10
    me.hand = [repo.get(_FILLER)]       # 捨てる手札
    deck_before = len(me.deck)

    for prim in _do(overlay, "OP06-115", "trigger"):
        execute_effect(prim, st, me, opp, me.leader)
    _drain(st)

    assert len(me.life) == 1, f"デッキ上1枚がライフの上に加えられていない: {len(me.life)}"
    assert len(me.deck) == deck_before - 1, "デッキ上1枚が消費されていない"
    assert len(me.hand) == 0, "その後の手札1枚捨てが起きていない"


# --------------------------------------------------------------------------- #
#  OP06-116 排撃 (EVENT 黄 cost4):
#    【メイン】以下から1つを選ぶ。
#      ・相手のコスト5以下のキャラ1枚までを、KOする。
#      ・相手のライフが1枚の場合、相手に1ダメージを与える。その後、自分のライフの上から
#        1枚を手札に加える。
#    【トリガー】1ドロー。
# --------------------------------------------------------------------------- #
def test_op06_116_main_ko_option_ai():
    """メイン: 択一の1つ目 (相手コスト5以下キャラ1枚KO) を AI 自動選択。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 <= 5
    opp.characters = [victim]

    for prim in _do(overlay, "OP06-116", "main"):
        execute_effect(prim, st, me, opp, me.leader)
    _drain(st)

    assert victim not in opp.characters, "相手コスト5以下キャラが KO されていない"


def test_op06_116_main_human_option_pick_modal():
    """メイン (人間): 択一 option_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    opp.characters = [InPlay.of(repo.get(_FILLER), sickness=False)]

    execute_effect(_do(overlay, "OP06-116", "main")[0], st, me, opp, me.leader)
    assert st.pending_choice is not None, "人間で択一 modal が立たない"
    assert st.pending_choice.get("kind") == "option_pick", \
        f"kind が option_pick でない: {st.pending_choice.get('kind')}"
    _drain(st)


def test_op06_116_trigger_draw_ai():
    """トリガー: 1ドロー (AI)。 自手札 +1・自デッキ -1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 10
    deck_before = len(me.deck)

    for prim in _do(overlay, "OP06-116", "trigger"):
        execute_effect(prim, st, me, opp, me.leader)
    _drain(st)

    assert len(me.hand) == 1, "トリガーの1ドローが起きていない"
    assert len(me.deck) == deck_before - 1, "デッキが1枚減っていない"


# --------------------------------------------------------------------------- #
#  OP06-117 方舟マクシム (STAGE 黄 cost1):
#    【起動メイン】【ターン1回】このカードと自分の「エネル」1枚をレストにできる：
#      相手のコスト2以下のキャラすべてを、KOする。
# --------------------------------------------------------------------------- #
def test_op06_117_activate_main_ko_all_cost2_ai():
    """起動メイン: 自身+エネルをレスト → 相手コスト2以下キャラすべてを KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("OP06-117"), sickness=False)
    me.stages = [stage]
    enel = InPlay.of(repo.get(_ENEL), sickness=False)  # コスト用「エネル」
    me.characters = [enel]
    v1 = InPlay.of(repo.get(_FILLER), sickness=False)   # cost2 <= 2
    v2 = InPlay.of(repo.get(_FILLER), sickness=False)   # cost2 <= 2
    opp.characters = [v1, v2]

    options = list_activate_main_effects(st, me, overlay)
    maxim_opts = [(src, eff) for (src, eff) in options
                  if src.card.card_id == "OP06-117"]
    assert len(maxim_opts) == 1, \
        f"OP06-117 の起動メインが legal に出ない: {len(maxim_opts)}"
    fire_activate_main(st, me, opp, *maxim_opts[0])
    _drain(st)

    assert v1 not in opp.characters and v2 not in opp.characters, \
        "相手コスト2以下キャラが全て KO されていない"
    assert stage.rested is True, "コストで方舟マクシムがレストされていない"
    assert enel.rested is True, "コストでエネルがレストされていない"


def test_op06_117_activate_main_human_optional_cost_modal():
    """起動メイン (人間): 任意コスト optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("OP06-117"), sickness=False)
    me.stages = [stage]
    me.characters = [InPlay.of(repo.get(_ENEL), sickness=False)]
    opp.characters = [InPlay.of(repo.get(_FILLER), sickness=False)]

    execute_effect(_do(overlay, "OP06-117", "activate_main")[0], st, me, opp, stage)
    assert st.pending_choice is not None, "人間で任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    _drain(st)


# --------------------------------------------------------------------------- #
#  OP07-002 アイン (CHARACTER 赤 cost7 power6000):
#    【登場時】相手のキャラ1枚までを、このターン中、パワー0にする。
# --------------------------------------------------------------------------- #
def test_op07_002_on_play_power_to_zero_ai():
    """登場時: 相手キャラ1枚を このターン中 パワー0 相当にする (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # power 3000
    opp.characters = [victim]
    src = InPlay.of(repo.get("OP07-002"), sickness=True)

    for prim in _do(overlay, "OP07-002", "on_play"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert victim.power <= 0, \
        f"相手キャラのパワーが0以下に落ちていない: {victim.power}"


def test_op07_002_on_play_human_target_pick():
    """登場時 (人間): 相手キャラ 複数候補 → target_pick modal。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    opp.characters = [InPlay.of(repo.get(_FILLER), sickness=False),
                      InPlay.of(repo.get(_FILLER), sickness=False)]  # 候補 2 体
    src = InPlay.of(repo.get("OP07-002"), sickness=True)

    execute_effect(_do(overlay, "OP07-002", "on_play")[0], st, me, opp, src)
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    _drain(st)
