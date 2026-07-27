# -*- coding: utf-8 -*-
"""OP10 弾 青 (ドレスローザ / 革命軍 / 白ひげ) 効果 回帰テスト バックフィル
(自動生成 wave 104):
OP10-044 / OP10-045 / OP10-046 / OP10-047 / OP10-048 /
OP10-049 / OP10-051 / OP10-052 / OP10-053 / OP10-055 の 10 枚
(カブ = 登場時 ドレスローザのリーダー/ステージをレストにできる：相手コスト1以下1枚を手札へ /
 キャベンディッシュ = アタック時(ターン1回) 2ドロー + 手札1枚捨て /
 キュロス = 登場時 コスト5以下のキャラ1枚まで(両陣営)を手札へ /
 コアラ = アタック時 コスト3以上革命軍1枚を手札に戻す：自身 +3000 [overlay bug で skip] /
 サイ = 登場時 ドレスローザのリーダー/ステージをレストにできる：相手コスト1以下1枚を手札へ /
 サボ = 他の自コスト7以下キャラ(除サボ)が相手効果で離れる時 代わりに自身を手札へ (replace_leave) /
 ハック = ドン1 アタック時 上3枚から革命軍キャラ1枚を公開して手札へ /
 バルトロメオ = 登場時 コスト1以下のキャラ1枚までをデッキ下へ /
 ビアン = 他のトンタッタ族キャラがいる場合 ブロッカーを得る (静的) /
 マルコ = KO時 相手コスト4以下1枚を手札へ)。

目的 (= test_backfill_auto_001〜103.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 任意コスト を 持つカードは 人間 actor で pending_choice が
      正しい kind + 候補で立ち、 resolve_pending_choice で解決できる (= 人間が選べる)
  (3) 同じ効果を AI 文脈 (human_player_idx=None) で回しても crash せず自動解決する
      (= AI が選べる)
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    evaluate_static_effects,
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
    try_replace_ko,
)

ROOT = Path(__file__).resolve().parent.parent

# よく使うテスト用カード / リーダー (テキストの前提固定)
_LEADER_GREEN = "OP01-001"      # ロロノア・ゾロ (leader、 汎用 = ドレスローザでない)
_LEADER_DRESSROSA = "EB01-040"  # キュロス (leader、 ドレスローザ)
_FILLER = "ST01-004"            # サンジ cost2 power4000 (バニラ、 埋め用/相手キャラ)
_REVO = "OP10-049"              # サボ (革命軍 cost4、 コスト3以上革命軍の victim/検索対象)
_TONTATTA = "OP10-044"          # カブ (トンタッタ族 cost1、 ビアン の相方)
_COST1 = "OP10-053"             # ビアン (cost1、 コスト1以下の bounce/deck 対象)


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


def _eff(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果 (dict) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
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
def test_all_wave104_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP10-044", "OP10-045", "OP10-046", "OP10-047", "OP10-048",
           "OP10-049", "OP10-051", "OP10-052", "OP10-053", "OP10-055"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP10-044 カブ (CHARACTER): 【登場時】自分の特徴《ドレスローザ》を持つ、リーダーか
#          ステージ1枚を、レストにできる：相手のコスト1以下のキャラ1枚までを、
#          持ち主の手札に戻す。 (optional_cost_then)
# --------------------------------------------------------------------------- #
def test_op10_044_on_play_rest_leader_bounce_opp_cost1_ai():
    """【登場時】ドレスローザ leader をレスト → 相手コスト1以下1枚を手札へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DRESSROSA, overlay)  # ドレスローザ leader
    me, opp = st.players[0], st.players[1]
    kabu = InPlay.of(repo.get("OP10-044"), sickness=True)
    small = InPlay.of(repo.get(_COST1), sickness=False)   # cost1 (<=1 → bounce 対象)
    big = InPlay.of(repo.get(_FILLER), sickness=False)     # cost2 (対象外)
    opp.characters = [small, big]

    assert me.leader.rested is False
    for prim in _eff(overlay, "OP10-044", "on_play")["do"]:
        execute_effect(prim, st, me, opp, kabu)
        _drain(st, [0])

    assert me.leader.rested is True, "コストで ドレスローザ leader がレストされるべき"
    assert small not in opp.characters, "相手のコスト1以下キャラが手札に戻っていない"
    assert big in opp.characters, "コスト2の相手キャラは対象外で残るべき"
    assert any(c.card_id == _COST1 for c in opp.hand), \
        "戻したキャラは持ち主 (相手) の手札に加わるべき"


def test_op10_044_on_play_optional_cost_human_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、 承諾で発動する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DRESSROSA, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    kabu = InPlay.of(repo.get("OP10-044"), sickness=True)
    small = InPlay.of(repo.get(_COST1), sickness=False)
    opp.characters = [small]

    execute_effect(_eff(overlay, "OP10-044", "on_play")["do"][0], st, me, opp, kabu)
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾 (= 払って発動)
    _drain(st, [0])
    assert me.leader.rested is True, "承諾後 ドレスローザ leader がレストされるべき"
    assert small not in opp.characters, "承諾後 相手のコスト1以下キャラが手札に戻るべき"


# --------------------------------------------------------------------------- #
#  OP10-045 キャベンディッシュ (CHARACTER): 【アタック時】【ターン1回】カード2枚を引き、
#          自分の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op10_045_on_attack_draw2_discard1_ai():
    """アタック時: 2ドロー + 手札1枚捨て = 手札 net +1 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    cav = InPlay.of(repo.get("OP10-045"), sickness=False)
    me.characters = [cav]
    me.hand = [repo.get(_FILLER)]  # 捨てる元手 1 枚
    hand_before = len(me.hand)
    deck_before = len(me.deck)

    for prim in _eff(overlay, "OP10-045", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, cav)
        _drain(st, [0])

    assert len(me.hand) == hand_before + 1, \
        f"2ドロー + 1捨て で 手札は net +1 のはず: {len(me.hand)} (before {hand_before})"
    assert len(me.deck) == deck_before - 2, "デッキから2枚引かれるべき"


# --------------------------------------------------------------------------- #
#  OP10-046 キュロス (CHARACTER): 【登場時】コスト5以下のキャラ1枚までを、
#          持ち主の手札に戻す。 (両陣営)
# --------------------------------------------------------------------------- #
def test_op10_046_on_play_bounce_cost_le5_ai():
    """【登場時】コスト5以下のキャラ1枚を手札へ (AI = 相手キャラ優先)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    kuros = InPlay.of(repo.get("OP10-046"), sickness=True)
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (<=5)
    opp.characters = [victim]

    for prim in _eff(overlay, "OP10-046", "on_play")["do"]:
        execute_effect(prim, st, me, opp, kuros)
        _drain(st, [0])

    assert victim not in opp.characters, "コスト5以下の相手キャラが手札に戻っていない"
    assert any(c.card_id == _FILLER for c in opp.hand), \
        "戻したキャラは持ち主 (相手) の手札に加わるべき"


def test_op10_046_on_play_human_target_pick():
    """人間 + 複数候補 → target_pick modal が立ち、 resolve で選んだキャラを手札へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    kuros = InPlay.of(repo.get("OP10-046"), sickness=True)
    a = InPlay.of(repo.get(_FILLER), sickness=False)   # cost2
    b = InPlay.of(repo.get(_COST1), sickness=False)    # cost1
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP10-046", "on_play")["do"][0], st, me, opp, kuros)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    bi = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [bi])
    _drain(st, [bi])
    assert b not in opp.characters, "人間が選んだキャラが手札に戻っていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP10-047 コアラ (CHARACTER): 【アタック時】自分のコスト3以上の特徴《革命軍》キャラ
#          1枚を持ち主の手札に戻すことができる：このキャラは、このターン中、パワー+3000。
#
#  ⚠ overlay bug: optional_cost_then の effect に コスト分の返却 (return_self_chara_to_hand)
#     とは別に `return_to_hand: one_self_chara_filtered (filter 空)` が二重に入っており、
#     コスト対象に加えて コアラ自身も手札に戻ってしまう (= 場に残らず +3000 も無意味)。
#     公式テキストは「戻すのはコストの革命軍キャラ1枚のみ、 コアラは場に残って +3000」。
#     engine/overlay の実バグなので このタスクでは修正せず skip (= 人間レビューへ)。
# --------------------------------------------------------------------------- #
def test_op10_047_on_attack_return_revo_pump_self():
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    koala = InPlay.of(repo.get("OP10-047"), sickness=False)
    revo = InPlay.of(repo.get(_REVO), sickness=False)  # サボ cost4 革命軍 (コスト対象)
    me.characters = [koala, revo]
    base = koala.card.power

    for prim in _eff(overlay, "OP10-047", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, koala)
        _drain(st, [0])

    assert koala in me.characters, "コアラは場に残るべき (コストで戻すのは革命軍キャラのみ)"
    assert koala.power == base + 3000, "コアラは +3000 されるべき"
    assert revo not in me.characters, "コストの革命軍キャラは手札に戻るべき"


# --------------------------------------------------------------------------- #
#  OP10-048 サイ (CHARACTER): 【登場時】自分の特徴《ドレスローザ》を持つ、リーダーか
#          ステージ1枚を、レストにできる：相手のコスト1以下のキャラ1枚までを、
#          持ち主の手札に戻す。 (= OP10-044 と同一効果)
# --------------------------------------------------------------------------- #
def test_op10_048_on_play_rest_leader_bounce_opp_cost1_ai():
    """【登場時】ドレスローザ leader をレスト → 相手コスト1以下1枚を手札へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DRESSROSA, overlay)
    me, opp = st.players[0], st.players[1]
    sai = InPlay.of(repo.get("OP10-048"), sickness=True)
    small = InPlay.of(repo.get(_COST1), sickness=False)  # cost1
    opp.characters = [small]

    assert me.leader.rested is False
    for prim in _eff(overlay, "OP10-048", "on_play")["do"]:
        execute_effect(prim, st, me, opp, sai)
        _drain(st, [0])

    assert me.leader.rested is True, "コストで ドレスローザ leader がレストされるべき"
    assert small not in opp.characters, "相手のコスト1以下キャラが手札に戻っていない"


def test_op10_048_on_play_no_cost_payable_without_dressrosa_leader():
    """ドレスローザでない leader ではコストが払えず 相手キャラは戻らない (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)  # OP01-001 = ドレスローザでない
    me, opp = st.players[0], st.players[1]
    sai = InPlay.of(repo.get("OP10-048"), sickness=True)
    small = InPlay.of(repo.get(_COST1), sickness=False)
    opp.characters = [small]

    for prim in _eff(overlay, "OP10-048", "on_play")["do"]:
        execute_effect(prim, st, me, opp, sai)
        _drain(st, [0])

    assert me.leader.rested is False, "ドレスローザでない leader はレストできない"
    assert small in opp.characters, \
        "コスト (ドレスローザレスト) を払えない場合 相手キャラは戻らない"


# --------------------------------------------------------------------------- #
#  OP10-049 サボ (CHARACTER): 「サボ」以外の自分の元々のコスト7以下のキャラが相手の
#          効果で場を離れる場合、代わりにこのキャラを持ち主の手札に戻すことができる。
#          (replace_leave、【ターン1回】、 任意)
# --------------------------------------------------------------------------- #
def test_op10_049_replace_leave_other_cost_le7_by_opp_ai():
    """他の自コスト7以下キャラが相手効果で離れる → 代わりに サボ を手札へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    sabo = InPlay.of(repo.get("OP10-049"), sickness=False)
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (<=7)
    me.characters = [sabo, victim]

    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "他の自コスト7以下キャラの相手効果離脱が サボ で置換されていない"
    assert sabo not in me.characters, "置換で サボ は場を離れるべき"
    assert any(c.card_id == "OP10-049" for c in me.hand), \
        "置換で サボ は持ち主の手札に戻るべき"
    assert victim in me.characters, "置換成立時 victim は場に残るべき"


def test_op10_049_replace_leave_not_by_own_effect():
    """自分の効果 (by_opp_effect=False) 由来の離脱は 置換対象外 (相手効果限定)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    sabo = InPlay.of(repo.get("OP10-049"), sickness=False)
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [sabo, victim]

    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=False, leave_kind="ko",
    )
    assert replaced is False, "自分の効果由来の離脱で置換が成立してはいけない"
    assert sabo in me.characters, "置換不成立時 サボ は場に残る"


# --------------------------------------------------------------------------- #
#  OP10-051 ハック (CHARACTER): 【ドン‼×1】【アタック時】自分のデッキの上から3枚を見て、
#          特徴《革命軍》を持つキャラカード1枚までを公開し、手札に加える。
#          その後、残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op10_051_on_attack_search_revo_to_hand_ai():
    """ドン1付与 + アタック時: 上3枚から革命軍キャラ1枚を手札へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    hack = InPlay.of(repo.get("OP10-051"), sickness=False)
    hack.attached_dons = 1  # 【ドン‼×1】ゲート成立
    me.characters = [hack]
    me.hand = []
    # 上3枚: サボ (革命軍) を先頭 → 手札へ。 残りは filler → デッキ下
    me.deck = [repo.get(_REVO), repo.get(_FILLER), repo.get(_FILLER)] + [repo.get(_FILLER)] * 10

    for prim in _eff(overlay, "OP10-051", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, hack)
        _drain(st, [0])

    assert any(c.card_id == _REVO for c in me.hand), \
        f"上3枚から革命軍キャラが手札に加わっていない: {[c.card_id for c in me.hand]}"


def test_op10_051_on_attack_don_gate_condition():
    """【ドン‼×1】ゲート: 付与ドン 0 枚では条件不成立 (overlay の if を検証)。"""
    repo = _repo()
    overlay = _overlay()
    eff = _eff(overlay, "OP10-051", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay に 【ドン‼×1】ゲート (self_attached_don_ge=1) が無い"


# --------------------------------------------------------------------------- #
#  OP10-052 バルトロメオ (CHARACTER): 【ブロッカー】【登場時】コスト1以下のキャラ1枚まで
#          を、持ち主のデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op10_052_on_play_return_cost1_to_deck_bottom_ai():
    """【登場時】相手コスト1以下1枚を持ち主のデッキ下へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    bart = InPlay.of(repo.get("OP10-052"), sickness=True)
    small = InPlay.of(repo.get(_COST1), sickness=False)  # cost1 (<=1)
    opp.characters = [small]
    opp.deck = [repo.get(_FILLER)] * 5
    deck_before = len(opp.deck)

    for prim in _eff(overlay, "OP10-052", "on_play")["do"]:
        execute_effect(prim, st, me, opp, bart)
        _drain(st, [0])

    assert small not in opp.characters, "相手のコスト1以下キャラがデッキに戻っていない"
    assert len(opp.deck) == deck_before + 1, "相手デッキが1枚増えるべき"
    assert opp.deck[-1].card_id == _COST1, "戻したキャラは持ち主のデッキ下に置かれるべき"


def test_op10_052_on_play_no_effect_on_cost2_target():
    """コスト2の相手キャラは対象外 (コスト1以下限定) → デッキに戻らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    bart = InPlay.of(repo.get("OP10-052"), sickness=True)
    big = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (対象外)
    opp.characters = [big]

    for prim in _eff(overlay, "OP10-052", "on_play")["do"]:
        execute_effect(prim, st, me, opp, bart)
        _drain(st, [0])

    assert big in opp.characters, "コスト2の相手キャラはデッキに戻ってはいけない"


# --------------------------------------------------------------------------- #
#  OP10-053 ビアン (CHARACTER): 「ビアン」以外の自分の特徴《トンタッタ族》を持つキャラ
#          がいる場合、このキャラは【ブロッカー】を得る。 (静的)
# --------------------------------------------------------------------------- #
def test_op10_053_static_blocker_with_other_tontatta():
    """他のトンタッタ族キャラがいる場合、 ビアンは ブロッカー を得る (静的)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    bian = InPlay.of(repo.get("OP10-053"), sickness=False)
    kabu = InPlay.of(repo.get(_TONTATTA), sickness=False)  # カブ (トンタッタ族)
    me.characters = [bian, kabu]

    evaluate_static_effects(st, overlay)
    assert bian.is_blocker_now is True, \
        "他のトンタッタ族キャラがいる時 ビアンは ブロッカー を得るべき"


def test_op10_053_static_no_blocker_alone():
    """他のトンタッタ族キャラがいない場合、 ビアンは ブロッカー を得ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    bian = InPlay.of(repo.get("OP10-053"), sickness=False)
    filler = InPlay.of(repo.get(_FILLER), sickness=False)  # トンタッタ族でない
    me.characters = [bian, filler]

    evaluate_static_effects(st, overlay)
    assert bian.is_blocker_now is False, \
        "トンタッタ族が他にいない時 ビアンは ブロッカー を得てはいけない"


# --------------------------------------------------------------------------- #
#  OP10-055 マルコ (CHARACTER): 【ブロッカー】【KO時】相手のコスト4以下のキャラ1枚まで
#          を、持ち主の手札に戻す。
# --------------------------------------------------------------------------- #
def test_op10_055_on_ko_bounce_opp_cost_le4_ai():
    """【KO時】相手のコスト4以下キャラ1枚を手札へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    marco = InPlay.of(repo.get("OP10-055"), sickness=False)
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (<=4)
    opp.characters = [victim]

    for prim in _eff(overlay, "OP10-055", "on_ko")["do"]:
        execute_effect(prim, st, me, opp, marco)
        _drain(st, [0])

    assert victim not in opp.characters, "KO時に相手のコスト4以下キャラが手札に戻っていない"
    assert any(c.card_id == _FILLER for c in opp.hand), \
        "戻したキャラは持ち主 (相手) の手札に加わるべき"


def test_op10_055_on_ko_no_bounce_cost5_target():
    """コスト5の相手キャラは対象外 (コスト4以下限定) → 手札に戻らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    marco = InPlay.of(repo.get("OP10-055"), sickness=False)
    big = InPlay.of(repo.get("OP10-046"), sickness=False)  # キュロス cost7 (対象外)
    opp.characters = [big]

    for prim in _eff(overlay, "OP10-055", "on_ko")["do"]:
        execute_effect(prim, st, me, opp, marco)
        _drain(st, [0])

    assert big in opp.characters, "コスト4超の相手キャラは手札に戻ってはいけない"
