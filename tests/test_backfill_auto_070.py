# -*- coding: utf-8 -*-
"""OP06 弾 効果 回帰テスト バックフィル (自動生成 wave 070):
OP06-084 / OP06-085 / OP06-086 / OP06-088 / OP06-089 / OP06-090 /
OP06-091 / OP06-092 / OP06-093 / OP06-095 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_069.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 択一 / 任意コスト を 持つカードは 人間 actor で pending_choice が
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
    eval_condition,
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

_LEADER = "OP01-001"            # ロロノア・ゾロ (赤、 汎用リーダー・特徴なし前提)
_LEADER_THRILLER = "OP06-080"  # ゲッコー・モリア リーダー (王下七武海/スリラーバーク海賊団)
_LEADER_DRESSROSA = "EB01-040"  # キュロス リーダー (ドレスローザ)
_FILLER = "OP01-013"           # サンジ cost2 power3000 (汎用フィラー、 登場時なし)
_NAMI = "OP01-016"             # ナミ cost1 power2000 (cost<=N 対象)
_KERBEROS = "OP06-087"         # ケルベロス cost2 power2000 (スリラーバーク海賊団、 バニラ)
_COST4_VANILLA = "EB02-034"    # コーメイ cost4 power6000 (バニラ = 登場時 cascade なし)


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


def _drain(st, pick=0, guard=12):
    """pending_choice を pick で自動解決し切る (= 後続効果を流す)。"""
    g = 0
    while st.pending_choice is not None and g < guard:
        resolve_pending_choice(st, [pick])
        g += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave70_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP06-084", "OP06-085", "OP06-086", "OP06-088", "OP06-089",
           "OP06-090", "OP06-091", "OP06-092", "OP06-093", "OP06-095"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP06-084 風のジゴロウ (CHARACTER 黒 cost2):
#    【KO時】自分のリーダーかキャラ1枚までを、このターン中、パワー+1000。
# --------------------------------------------------------------------------- #
def test_op06_084_on_ko_pump_leader_ai():
    """KO時: 対象がリーダーのみなら AI はリーダーを +1000 (このターン中)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    # 場のキャラは無し → 対象は自リーダー 1 択 (= AI が自動で pump)。
    leader_before = me.leader.power
    src = InPlay.of(repo.get("OP06-084"), sickness=False)

    for prim in _do(overlay, "OP06-084", "on_ko"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert me.leader.power == leader_before + 1000, \
        f"KO時 リーダー +1000 が反映されていない: {me.leader.power} (before {leader_before})"


def test_op06_084_on_ko_human_target_pick():
    """KO時 (人間): リーダー + キャラ の複数候補 → target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(_FILLER), sickness=False)]  # 候補を 2 つに
    src = InPlay.of(repo.get("OP06-084"), sickness=False)

    execute_effect(_do(overlay, "OP06-084", "on_ko")[0], st, me, opp, src)
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    _drain(st)


# --------------------------------------------------------------------------- #
#  OP06-085 クマシー (CHARACTER 黒 cost2):
#    【ドン!!×2】【自分のターン中】自分のトラッシュのカード5枚につき、このキャラのパワー+1000。
# --------------------------------------------------------------------------- #
def test_op06_085_static_pump_per_five_trash_ai():
    """自ターン中: トラッシュ 10 枚 → 5 枚ごと +1000 = +2000 (このキャラ静的 pump)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(_FILLER)] * 10  # 10 // 5 = 2 → +2000
    kumashi = InPlay.of(repo.get("OP06-085"), sickness=False)
    me.characters = [kumashi]
    power_before = kumashi.power

    for prim in _do(overlay, "OP06-085", "on_attached_don"):
        execute_effect(prim, st, me, opp, kumashi)

    assert kumashi.power == power_before + 2000, \
        f"トラッシュ 10 枚で +2000 のはず: {kumashi.power} (before {power_before})"


def test_op06_085_condition_requires_self_turn():
    """if 条件: 自分のターン中のみ成立 (= 相手ターン中は不成立)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me = st.players[0]
    cond = _eff(overlay, "OP06-085", "on_attached_don")["if"]
    assert eval_condition(cond, st, me) is True, "自ターン中で条件が成立していない"

    st.turn_player_idx = 1  # 相手ターンに切替
    assert eval_condition(cond, st, me) is False, "相手ターン中なのに条件が成立している"


# --------------------------------------------------------------------------- #
#  OP06-086 ゲッコー・モリア (CHARACTER 黒 cost8):
#    【登場時】自分のトラッシュのコスト4以下のキャラ1枚までとコスト2以下のキャラ1枚までを
#      選び、1枚を登場させ、残りをレストで登場させる。
# --------------------------------------------------------------------------- #
def test_op06_086_on_play_revive_two_from_trash_ai():
    """登場時: トラッシュから cost4以下1枚 (アクティブ) + cost2以下1枚 (レスト) を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(_COST4_VANILLA), repo.get(_KERBEROS)]  # cost4 pow6000 / cost2 pow2000
    src = InPlay.of(repo.get("OP06-086"), sickness=True)

    for prim in _do(overlay, "OP06-086", "on_play"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    ids = [c.card.card_id for c in me.characters]
    assert _COST4_VANILLA in ids, "コスト4以下キャラがトラッシュから登場していない"
    assert _KERBEROS in ids, "コスト2以下キャラがトラッシュから登場していない"
    active = next(c for c in me.characters if c.card.card_id == _COST4_VANILLA)
    rested = next(c for c in me.characters if c.card.card_id == _KERBEROS)
    assert not active.rested, "1 枚目 (登場) がレストになっている"
    assert rested.rested, "2 枚目 (レストで登場) がアクティブになっている"


def test_op06_086_on_play_human_first_pick_modal():
    """登場時 (人間): 1 枚目 (cost4以下) の候補が複数 → play_from_trash_pick modal。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    # cost4以下 の 候補を 2 枚 (コーメイ cost4 / ケルベロス cost2) にして modal を強制。
    me.trash = [repo.get(_COST4_VANILLA), repo.get(_KERBEROS)]
    src = InPlay.of(repo.get("OP06-086"), sickness=True)

    execute_effect(_do(overlay, "OP06-086", "on_play")[0], st, me, opp, src)
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "play_from_trash_pick", \
        f"kind が play_from_trash_pick でない: {st.pending_choice.get('kind')}"
    _drain(st)


# --------------------------------------------------------------------------- #
#  OP06-088 サイ (CHARACTER 黒 cost3):
#    自分のリーダーが特徴《ドレスローザ》を持ち、自分のリーダーがアクティブの場合、
#      このキャラのパワー+2000。 (常在)
# --------------------------------------------------------------------------- #
def test_op06_088_condition_true_when_dressrosa_and_active():
    """条件: リーダー《ドレスローザ》 かつ アクティブ → True。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DRESSROSA, overlay)
    me = st.players[0]
    cond = _eff(overlay, "OP06-088", "on_attached_don")["if"]
    assert eval_condition(cond, st, me) is True, \
        "《ドレスローザ》 かつ アクティブで条件が成立していない"


def test_op06_088_condition_false_when_leader_rested():
    """条件: リーダーがレスト中なら self_leader_active が不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DRESSROSA, overlay)
    me = st.players[0]
    me.leader.rested = True
    cond = _eff(overlay, "OP06-088", "on_attached_don")["if"]
    assert eval_condition(cond, st, me) is False, \
        "リーダーがレスト中なのに条件が成立している"


def test_op06_088_condition_false_when_not_dressrosa():
    """条件: 非《ドレスローザ》 リーダーでは不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)  # 特徴なしリーダー
    me = st.players[0]
    cond = _eff(overlay, "OP06-088", "on_attached_don")["if"]
    assert eval_condition(cond, st, me) is False, \
        "非《ドレスローザ》 なのに条件が成立している"


def test_op06_088_static_pump_plus_2000():
    """効果 do: power_pump self +2000 で このキャラのパワーが +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DRESSROSA, overlay)
    me, opp = st.players[0], st.players[1]
    sai = InPlay.of(repo.get("OP06-088"), sickness=False)
    me.characters = [sai]
    power_before = sai.power

    for prim in _do(overlay, "OP06-088", "on_attached_don"):
        execute_effect(prim, st, me, opp, sai)

    assert sai.power == power_before + 2000, \
        f"+2000 が反映されていない: {sai.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  OP06-089 タララン (CHARACTER 黒 cost2):
#    【登場時】/【KO時】自分のデッキの上から3枚をトラッシュに置く。
# --------------------------------------------------------------------------- #
def test_op06_089_on_play_mill_three_ai():
    """登場時: デッキ上3枚をトラッシュに置く (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 10
    me.trash = []
    deck_before = len(me.deck)
    src = InPlay.of(repo.get("OP06-089"), sickness=True)

    for prim in _do(overlay, "OP06-089", "on_play"):
        execute_effect(prim, st, me, opp, src)

    assert len(me.deck) == deck_before - 3, "登場時 デッキ上3枚がトラッシュに置かれていない"
    assert len(me.trash) == 3, "トラッシュに3枚追加されていない"


def test_op06_089_on_ko_mill_three_ai():
    """KO時: デッキ上3枚をトラッシュに置く (AI、 on_ko エントリ経由)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 10
    me.trash = []
    src = InPlay.of(repo.get("OP06-089"), sickness=False)

    for prim in _do(overlay, "OP06-089", "on_ko"):
        execute_effect(prim, st, me, opp, src)

    assert len(me.deck) == 7, "KO時 デッキ上3枚がトラッシュに置かれていない"
    assert len(me.trash) == 3, "KO時 トラッシュに3枚追加されていない"


def test_op06_089_has_both_on_play_and_on_ko():
    """overlay: 登場時 と KO時 の両方に mill_self_top が登録されている。"""
    overlay = _overlay()
    play_do = _do(overlay, "OP06-089", "on_play")
    ko_do = _do(overlay, "OP06-089", "on_ko")
    assert any("mill_self_top" in p for p in play_do), "on_play に mill_self_top がない"
    assert any("mill_self_top" in p for p in ko_do), "on_ko に mill_self_top がない"


# --------------------------------------------------------------------------- #
#  OP06-090 ドクトル・ホグバック (CHARACTER 黒 cost4):
#    【登場時】自分のトラッシュのカード2枚を好きな順番でデッキの下に戻すことができる：
#      自分のトラッシュの「ドクトル・ホグバック」以外の特徴《スリラーバーク海賊団》を持つ
#      カード1枚までを、手札に加える。
# --------------------------------------------------------------------------- #
def test_op06_090_on_play_optional_cost_then_recover_ai():
    """登場時: トラッシュ2枚をデッキ下 → スリラーバークカード1枚を手札へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    # コスト用フィラー2枚 (先頭) + 回収対象スリラーバーク1枚。
    me.trash = [repo.get(_FILLER), repo.get(_FILLER), repo.get(_KERBEROS)]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 10
    deck_before = len(me.deck)
    src = InPlay.of(repo.get("OP06-090"), sickness=True)

    for prim in _do(overlay, "OP06-090", "on_play"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert any(c.card_id == _KERBEROS for c in me.hand), \
        "スリラーバークカードが手札に回収されていない"
    assert len(me.deck) == deck_before + 2, "コストのトラッシュ2枚がデッキ下に戻っていない"


def test_op06_090_on_play_human_optional_cost_modal():
    """登場時 (人間): 任意コスト optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(_FILLER), repo.get(_FILLER), repo.get(_KERBEROS)]
    src = InPlay.of(repo.get("OP06-090"), sickness=True)

    execute_effect(_do(overlay, "OP06-090", "on_play")[0], st, me, opp, src)
    assert st.pending_choice is not None, "人間で任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    _drain(st)


# --------------------------------------------------------------------------- #
#  OP06-091 ビクトリア・シンドリー (CHARACTER 黒 cost1):
#    【登場時】自分のリーダーが特徴《スリラーバーク海賊団》を持つ場合、
#      デッキの上から5枚をトラッシュに置く。
# --------------------------------------------------------------------------- #
def test_op06_091_on_play_mill_five_with_thriller_leader_ai():
    """登場時: スリラーバークリーダーなら デッキ上5枚をトラッシュ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_THRILLER, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 10
    me.trash = []
    src = InPlay.of(repo.get("OP06-091"), sickness=True)

    for prim in _do(overlay, "OP06-091", "on_play"):
        execute_effect(prim, st, me, opp, src)

    assert len(me.deck) == 5, "デッキ上5枚がトラッシュに置かれていない"
    assert len(me.trash) == 5, "トラッシュに5枚追加されていない"


def test_op06_091_condition_requires_thriller_leader():
    """if 条件: リーダーが《スリラーバーク海賊団》の時だけ成立。"""
    repo = _repo()
    overlay = _overlay()
    cond = _eff(overlay, "OP06-091", "on_play")["if"]

    st_ok = _state(repo, _LEADER_THRILLER, overlay)
    assert eval_condition(cond, st_ok, st_ok.players[0]) is True, \
        "スリラーバークリーダーで条件が成立していない"

    st_ng = _state(repo, _LEADER, overlay)
    assert eval_condition(cond, st_ng, st_ng.players[0]) is False, \
        "非スリラーバークリーダーで条件が成立している"


# --------------------------------------------------------------------------- #
#  OP06-092 ブルック (CHARACTER 黒 cost6):
#    【登場時】以下から1つを選ぶ。
#      ・相手のコスト4以下のキャラ1枚までを、トラッシュに置く。
#      ・相手は自身のトラッシュのカード3枚を好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op06_092_option_trash_opp_chara_ai():
    """option 0 (do 直接): 相手コスト4以下キャラ1枚をトラッシュに置く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 <= 4
    opp.characters = [victim]
    opts = _do(overlay, "OP06-092", "on_play")[0]["choice_effect"]["options"]

    for prim in opts[0]["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert victim not in opp.characters, "相手コスト4以下キャラがトラッシュに置かれていない"
    assert any(c.card_id == _FILLER for c in opp.trash), \
        "トラッシュに置かれたキャラが相手トラッシュにない"


def test_op06_092_option_opp_trash_to_deck_ai():
    """option 1 (do 直接): 相手トラッシュ3枚をデッキ下に置く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.trash = [repo.get(_FILLER)] * 4
    opp.deck = [repo.get(_FILLER)] * 5
    deck_before = len(opp.deck)
    opts = _do(overlay, "OP06-092", "on_play")[0]["choice_effect"]["options"]

    for prim in opts[1]["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert len(opp.trash) == 1, "相手トラッシュ3枚がデッキ下へ移っていない"
    assert len(opp.deck) == deck_before + 3, "相手デッキ下に3枚追加されていない"


def test_op06_092_on_play_human_option_modal():
    """登場時 (人間): option_pick modal が 2 択で立ち、 解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    opp.characters = [InPlay.of(repo.get(_FILLER), sickness=False)]
    opp.trash = [repo.get(_FILLER)] * 3

    execute_effect(_do(overlay, "OP06-092", "on_play")[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間で option_pick modal が立たない"
    assert st.pending_choice.get("kind") == "option_pick", \
        f"kind が option_pick でない: {st.pending_choice.get('kind')}"
    assert len(st.pending_choice.get("options", [])) == 2, "択が 2 件でない"
    _drain(st)


def test_op06_092_on_play_ai_no_crash():
    """登場時 (AI): choice_effect を AI 文脈でそのまま実行しても crash しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.characters = [InPlay.of(repo.get(_FILLER), sickness=False)]
    opp.trash = [repo.get(_FILLER)] * 3

    execute_effect(_do(overlay, "OP06-092", "on_play")[0], st, me, opp, None)
    _drain(st)  # crash しないことが assert (例外を投げれば test 失敗)


# --------------------------------------------------------------------------- #
#  OP06-093 ペローナ (CHARACTER 黒 cost4):
#    【登場時】相手の手札が5枚以上ある場合、以下から1つを選ぶ。
#      ・相手は自身の手札1枚を捨てる。
#      ・相手のキャラ1枚までを、このターン中、コスト-3。
# --------------------------------------------------------------------------- #
def test_op06_093_condition_requires_opp_hand_ge_5():
    """if 条件: 相手手札 5 枚以上で成立、 4 枚では不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    cond = _eff(overlay, "OP06-093", "on_play")["if"]

    opp.hand = [repo.get(_FILLER)] * 5
    assert eval_condition(cond, st, me) is True, "相手手札5枚で条件が成立していない"

    opp.hand = [repo.get(_FILLER)] * 4
    assert eval_condition(cond, st, me) is False, "相手手札4枚なのに条件が成立している"


def test_op06_093_option_discard_opp_hand_ai():
    """option 0 (do 直接): 相手手札1枚を捨てる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.hand = [repo.get(_FILLER)] * 5
    opp.trash = []
    opts = _do(overlay, "OP06-093", "on_play")[0]["choice_effect"]["options"]

    for prim in opts[0]["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert len(opp.hand) == 4, "相手手札が1枚捨てられていない"
    assert len(opp.trash) == 1, "捨てた手札が相手トラッシュにない"


def test_op06_093_option_cost_minus_three_ai():
    """option 1 (do 直接): 相手キャラ1枚のコストを -3 (このターン中)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    opp.characters = [victim]
    cost_before = victim.base_cost  # = 2
    opts = _do(overlay, "OP06-093", "on_play")[0]["choice_effect"]["options"]

    for prim in opts[1]["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    # コスト2 に -3 → base_cost は 0 未満クランプ (max(0, ...)) で 0。
    assert victim.base_cost < cost_before, \
        f"コスト-3 が反映されていない: {victim.base_cost} (before {cost_before})"
    assert victim.base_cost == 0, \
        f"コスト2 に -3 で base_cost=0 のはず: {victim.base_cost}"


def test_op06_093_on_play_human_option_modal():
    """登場時 (人間): option_pick modal が立ち、 解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    opp.hand = [repo.get(_FILLER)] * 5
    opp.characters = [InPlay.of(repo.get(_FILLER), sickness=False)]

    execute_effect(_do(overlay, "OP06-093", "on_play")[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間で option_pick modal が立たない"
    assert st.pending_choice.get("kind") == "option_pick", \
        f"kind が option_pick でない: {st.pending_choice.get('kind')}"
    _drain(st)


# --------------------------------------------------------------------------- #
#  OP06-095 影の集合地 (EVENT 黒 cost2):
#    【メイン】/【カウンター】自分のリーダーは、このターン中、パワー+1000。その後、
#      自分のコスト2以下の特徴《スリラーバーク海賊団》を持つキャラを任意の枚数KOしてもよい。
#      KOしたキャラ1枚につき、自分のリーダーは、このターン中、パワー+1000。
#    【トリガー】カード2枚を引き、自分の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op06_095_main_pump_and_ko_synergy_ai():
    """メイン: リーダー +1000 → スリラーバークキャラ1体KO でさらに +1000 = +2000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_THRILLER, overlay)
    me, opp = st.players[0], st.players[1]
    fodder = InPlay.of(repo.get(_KERBEROS), sickness=False)  # スリラーバーク cost2
    me.characters = [fodder]
    leader_before = me.leader.power

    for prim in _do(overlay, "OP06-095", "main"):
        execute_effect(prim, st, me, opp, me.leader)
    _drain(st)

    assert fodder not in me.characters, "スリラーバークキャラが KO されていない"
    assert any(c.card_id == _KERBEROS for c in me.trash), "KO キャラがトラッシュにない"
    assert me.leader.power == leader_before + 2000, \
        f"リーダー +1000 + KO1体分 +1000 = +2000 のはず: {me.leader.power} (before {leader_before})"


def test_op06_095_main_pump_only_when_no_fodder_ai():
    """メイン: KO 対象なしなら リーダー +1000 のみ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_THRILLER, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = []  # KO 対象なし
    leader_before = me.leader.power

    for prim in _do(overlay, "OP06-095", "main"):
        execute_effect(prim, st, me, opp, me.leader)
    _drain(st)

    assert me.leader.power == leader_before + 1000, \
        f"KO 対象なしで リーダー +1000 のみのはず: {me.leader.power} (before {leader_before})"


def test_op06_095_trigger_draw_two_discard_one_ai():
    """トリガー: カード2枚を引き、 手札1枚を捨てる (AI)。 net 手札 +1・デッキ-2・トラッシュ+1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)] * 2
    me.deck = [repo.get(_FILLER)] * 10
    me.trash = []

    for prim in _do(overlay, "OP06-095", "trigger"):
        execute_effect(prim, st, me, opp, me.leader)
    _drain(st)

    assert len(me.deck) == 8, f"2ドローでデッキが8枚のはず: {len(me.deck)}"
    assert len(me.hand) == 3, f"2ドロー1捨てで手札3枚のはず: {len(me.hand)}"
    assert len(me.trash) == 1, f"手札1枚が捨てられトラッシュ1枚のはず: {len(me.trash)}"
