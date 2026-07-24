# -*- coding: utf-8 -*-
"""OP06 弾 効果 回帰テスト バックフィル (自動生成 wave 071):
OP06-097 / OP06-098 / OP06-100 / OP06-101 / OP06-102 / OP06-103 /
OP06-104 / OP06-106 / OP06-107 / OP06-108 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_070.py と同一方針):
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
_FILLER = "OP01-013"           # サンジ cost2 power3000 (汎用フィラー、 登場時なし)
_KERBEROS = "OP06-087"         # ケルベロス cost2 power2000 (スリラーバーク海賊団、 バニラ)
_STAGE1 = "EB02-041"           # コスト1 ステージ (cost_eq:1 コスト用ヘルパー)
_WANO = "OP01-036"             # cost1 power3000 バニラ 特徴《ワノ国》 (対象ヘルパー)


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
def test_all_wave71_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP06-097", "OP06-098", "OP06-100", "OP06-101", "OP06-102",
           "OP06-103", "OP06-104", "OP06-106", "OP06-107", "OP06-108"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP06-097 ネガティブホロウ (EVENT 黒 cost2):
#    【メイン】相手の手札1枚を捨てる。
#    【トリガー】このカードの【メイン】効果を発動する。
# --------------------------------------------------------------------------- #
def test_op06_097_main_discard_opp_hand_ai():
    """メイン: 相手の手札1枚を捨てる (AI)。 相手手札 -1・相手トラッシュ +1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.hand = [repo.get(_FILLER)] * 3
    opp.trash = []

    for prim in _do(overlay, "OP06-097", "main"):
        execute_effect(prim, st, me, opp, me.leader)
    _drain(st)

    assert len(opp.hand) == 2, f"相手手札が1枚捨てられていない: {len(opp.hand)}"
    assert len(opp.trash) == 1, f"捨てた手札が相手トラッシュにない: {len(opp.trash)}"


def test_op06_097_trigger_fires_main_discard_ai():
    """トリガー: 【メイン】効果を発動 → 相手手札1枚を捨てる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.hand = [repo.get(_FILLER)] * 3
    opp.trash = []
    # trigger 効果は場に self_inplay を持たない → current_source_card_id で自身を解決。
    st.current_source_card_id = "OP06-097"

    for prim in _do(overlay, "OP06-097", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert len(opp.hand) == 2, "トリガー経由の【メイン】発動で相手手札が減っていない"
    assert len(opp.trash) == 1, "トリガー経由で捨てた手札が相手トラッシュにない"


# --------------------------------------------------------------------------- #
#  OP06-098 スリラーバーク (STAGE 黒 cost1):
#    【起動メイン】➀,このステージをレストにできる：自分のリーダーが特徴《スリラーバーク海賊団》
#      を持つ場合、自分のトラッシュのコスト2以下の特徴《スリラーバーク海賊団》を持つキャラ
#      カード1枚までを、レストで登場させる。
# --------------------------------------------------------------------------- #
def test_op06_098_activate_main_revive_from_trash_ai():
    """起動メイン: ドン1レスト+ステージレストで トラッシュの スリラーバーク cost2 を レスト登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_THRILLER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3          # コストエリアのアクティブドン (rest_self_don 用)
    me.trash = [repo.get(_KERBEROS)]  # スリラーバーク cost2 (蘇生対象)
    stage = InPlay.of(repo.get("OP06-098"), sickness=False)
    me.stages = [stage]
    don_before = me.don_active

    for prim in _do(overlay, "OP06-098", "activate_main"):
        execute_effect(prim, st, me, opp, stage)
    _drain(st)

    ids = [c.card.card_id for c in me.characters]
    assert _KERBEROS in ids, "スリラーバークキャラがトラッシュから登場していない"
    revived = next(c for c in me.characters if c.card.card_id == _KERBEROS)
    assert revived.rested, "『レストで登場』なのにアクティブで登場している"
    assert me.don_active == don_before - 1, "コストのドンが1枚レストされていない"
    assert stage.rested, "コストとして このステージがレストされていない"


def test_op06_098_condition_requires_thriller_leader():
    """if 条件: リーダーが《スリラーバーク海賊団》の時だけ成立。"""
    repo = _repo()
    overlay = _overlay()
    cond = _eff(overlay, "OP06-098", "activate_main")["if"]

    st_ok = _state(repo, _LEADER_THRILLER, overlay)
    assert eval_condition(cond, st_ok, st_ok.players[0]) is True, \
        "スリラーバークリーダーで条件が成立していない"

    st_ng = _state(repo, _LEADER, overlay)
    assert eval_condition(cond, st_ng, st_ng.players[0]) is False, \
        "非スリラーバークリーダーで条件が成立している"


def test_op06_098_activate_main_human_optional_cost_modal():
    """起動メイン (人間): 任意コスト optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_THRILLER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    me.trash = [repo.get(_KERBEROS)]
    stage = InPlay.of(repo.get("OP06-098"), sickness=False)
    me.stages = [stage]

    execute_effect(_do(overlay, "OP06-098", "activate_main")[0], st, me, opp, stage)
    assert st.pending_choice is not None, "人間で任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    _drain(st)


# --------------------------------------------------------------------------- #
#  OP06-100 イヌアラシ (CHARACTER 黄 cost4):
#    【ドン!!×2】【アタック時】自分の手札1枚を捨てることができる：
#      相手のライフの枚数以下のコストを持つ相手のキャラ1枚までを、KOする。
#    【トリガー】相手のライフが3枚以下の場合、このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op06_100_on_attack_ko_opp_chara_ai():
    """アタック時: 手札1枚を捨てて 相手キャラ1枚を KO する (AI)。 相手キャラ -1・自手札 -1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)] * 2
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    opp.characters = [victim]
    src = InPlay.of(repo.get("OP06-100"), sickness=False)

    for prim in _do(overlay, "OP06-100", "on_attack"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert victim not in opp.characters, "相手キャラが KO されていない"
    assert len(me.hand) == 1, "コストの手札1枚が捨てられていない"


def test_op06_100_on_attack_human_optional_cost_modal():
    """アタック時 (人間): 任意コスト optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)] * 2
    opp.characters = [InPlay.of(repo.get(_FILLER), sickness=False)]
    src = InPlay.of(repo.get("OP06-100"), sickness=False)

    execute_effect(_do(overlay, "OP06-100", "on_attack")[0], st, me, opp, src)
    assert st.pending_choice is not None, "人間で任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    _drain(st)


@pytest.mark.skip(reason="overlay bug: OP06-100 trigger 公式テキストは『相手のライフが3枚以下』"
                         "だが overlay の if は self_life_le:3 (自分のライフ) になっている。"
                         "self/opp の取り違え = overlay 修正が必要 (人間レビュー待ち、 engine/overlay "
                         "編集はこのタスク対象外)。")
def test_op06_100_trigger_condition_matches_official_text():
    """トリガー条件: 公式は『相手のライフが3枚以下』。 overlay は self_life_le で不整合 (skip)。"""
    repo = _repo()
    overlay = _overlay()
    cond = _eff(overlay, "OP06-100", "trigger").get("if")
    # 公式テキスト = opp_life_le:3 を期待。 現 overlay は self_life_le:3。
    assert "opp_life_le" in cond, f"公式は相手ライフ条件のはず: {cond}"


# --------------------------------------------------------------------------- #
#  OP06-101 おナミ (CHARACTER 黄 cost2):
#    【登場時】自分のリーダーかキャラ1枚までは、このターン中、【バニッシュ】を得る。
#    【トリガー】相手のコスト5以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op06_101_on_play_give_banish_ai():
    """登場時: 自リーダーに【バニッシュ】を付与する (AI、 場にキャラなし → リーダー1択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP06-101"), sickness=True)

    for prim in _do(overlay, "OP06-101", "on_play"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert "バニッシュ" in me.leader.granted_keywords, \
        f"リーダーにバニッシュが付与されていない: {me.leader.granted_keywords}"


def test_op06_101_on_play_human_target_pick():
    """登場時 (人間): リーダー + キャラ の複数候補 → target_pick modal。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(_FILLER), sickness=False)]  # 候補を 2 つに
    src = InPlay.of(repo.get("OP06-101"), sickness=True)

    execute_effect(_do(overlay, "OP06-101", "on_play")[0], st, me, opp, src)
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    _drain(st)


def test_op06_101_trigger_ko_opp_chara_ai():
    """トリガー: 相手のコスト5以下のキャラ1枚を KO する (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 <= 5
    opp.characters = [victim]

    for prim in _do(overlay, "OP06-101", "trigger"):
        execute_effect(prim, st, me, opp, me.leader)
    _drain(st)

    assert victim not in opp.characters, "トリガーで相手コスト5以下キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP06-102 カマキリ (CHARACTER 黄 cost3):
#    【起動メイン】【ターン1回】コスト1のステージ1枚を持ち主のデッキの下に置くことができる：
#      相手のコスト2以下のキャラ1枚までを、KOする。
#    【トリガー】自分のライフが2枚以下の場合、このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op06_102_activate_main_ko_via_stage_ai():
    """起動メイン: コスト1ステージをデッキ下へ → 相手コスト2以下キャラ1枚を KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.stages = [InPlay.of(repo.get(_STAGE1), sickness=False)]  # コスト1ステージ
    me.deck = [repo.get(_FILLER)] * 10
    deck_before = len(me.deck)
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 <= 2
    opp.characters = [victim]
    src = InPlay.of(repo.get("OP06-102"), sickness=False)

    for prim in _do(overlay, "OP06-102", "activate_main"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert victim not in opp.characters, "相手コスト2以下キャラが KO されていない"
    assert len(me.stages) == 0, "コストのステージがデッキ下に置かれていない"
    assert len(me.deck) == deck_before + 1, "ステージがデッキの下に戻っていない"


def test_op06_102_activate_main_human_optional_cost_modal():
    """起動メイン (人間): 任意コスト optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.stages = [InPlay.of(repo.get(_STAGE1), sickness=False)]
    opp.characters = [InPlay.of(repo.get(_FILLER), sickness=False)]
    src = InPlay.of(repo.get("OP06-102"), sickness=False)

    execute_effect(_do(overlay, "OP06-102", "activate_main")[0], st, me, opp, src)
    assert st.pending_choice is not None, "人間で任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    _drain(st)


def test_op06_102_trigger_play_self_when_self_life_le2_ai():
    """トリガー: 自分のライフが2枚以下なら このカードを登場させる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2  # 自ライフ 2 枚 (<=2)
    me.trash = [repo.get("OP06-102")]  # play_self 探索元
    st.current_source_card_id = "OP06-102"
    cond = _eff(overlay, "OP06-102", "trigger").get("if")
    assert eval_condition(cond, st, me) is True, "自ライフ2枚で条件が成立していない"

    for prim in _do(overlay, "OP06-102", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    ids = [c.card.card_id for c in me.characters]
    assert "OP06-102" in ids, "トリガーでこのカードが登場していない"


# --------------------------------------------------------------------------- #
#  OP06-103 河松 (CHARACTER 黄 cost3):
#    【アタック時】自分の手札2枚を捨てることができる：
#      自分のパワー0のキャラ1枚までを、持ち主のライフの上か下に表向きで置く。
#    【トリガー】相手のライフが3枚以下の場合、このカードを登場させる。
#  注: 効果対象『パワー0のキャラ』は filter power_eq:0 = 印刷パワー0 を指すが (engine の
#      _matches_filter は CardDef の元々のパワーで判定)、 印刷パワー0 の キャラは現行 DB に
#      存在しない為、 KO なしの コスト部 (手札2枚捨て) と トリガー を assert する。
# --------------------------------------------------------------------------- #
def test_op06_103_on_attack_pays_discard_cost_ai():
    """アタック時: 任意コストを払うと 自分の手札2枚を捨てる (AI)。 自手札 -2・自トラッシュ +2。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)] * 2
    me.trash = []
    # パワー0 キャラを 1 体 用意 (base_power_override で 現在パワー0 に、 効果対象足りるように)。
    zero = InPlay.of(repo.get(_FILLER), sickness=False)
    zero.base_power_override = 0
    me.characters = [zero]
    src = InPlay.of(repo.get("OP06-103"), sickness=False)

    for prim in _do(overlay, "OP06-103", "on_attack"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert len(me.hand) == 0, f"コストの手札2枚が捨てられていない: {len(me.hand)}"
    assert len(me.trash) == 2, f"捨てた手札2枚がトラッシュにない: {len(me.trash)}"


def test_op06_103_on_attack_human_optional_cost_modal():
    """アタック時 (人間): 任意コスト optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)] * 2
    src = InPlay.of(repo.get("OP06-103"), sickness=False)

    execute_effect(_do(overlay, "OP06-103", "on_attack")[0], st, me, opp, src)
    assert st.pending_choice is not None, "人間で任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    _drain(st)


def test_op06_103_trigger_play_self_when_opp_life_le3_ai():
    """トリガー: 相手のライフが3枚以下なら このカードを登場させる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_FILLER)] * 3  # 相手ライフ 3 枚 (<=3)
    me.trash = [repo.get("OP06-103")]
    st.current_source_card_id = "OP06-103"
    cond = _eff(overlay, "OP06-103", "trigger").get("if")
    assert eval_condition(cond, st, me) is True, "相手ライフ3枚で条件が成立していない"

    for prim in _do(overlay, "OP06-103", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    ids = [c.card.card_id for c in me.characters]
    assert "OP06-103" in ids, "トリガーでこのカードが登場していない"


# --------------------------------------------------------------------------- #
#  OP06-104 菊之丞 (CHARACTER 黄 cost4):
#    【KO時】相手のライフが3枚以下の場合、自分のデッキの上から1枚までを、ライフの上に加える。
#    【トリガー】相手のライフが3枚以下の場合、このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op06_104_on_ko_put_top_to_life_when_opp_life_le3_ai():
    """KO時: 相手ライフ3以下なら デッキ上1枚をライフの上に加える (AI)。 自デッキ -1・自ライフ +1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_FILLER)] * 3  # 相手ライフ 3 枚
    me.deck = [repo.get(_FILLER)] * 10
    me.life = []
    src = InPlay.of(repo.get("OP06-104"), sickness=False)

    for prim in _do(overlay, "OP06-104", "on_ko"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert len(me.deck) == 9, f"デッキ上1枚がライフへ移っていない: {len(me.deck)}"
    assert len(me.life) == 1, f"ライフの上に1枚加えられていない: {len(me.life)}"


def test_op06_104_on_ko_condition_false_when_opp_life_ge4():
    """KO時 if 条件: 相手ライフが4枚 (>3) では成立しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_FILLER)] * 4
    cond = _eff(overlay, "OP06-104", "on_ko")["if"]
    assert eval_condition(cond, st, me) is False, \
        "相手ライフ4枚なのに条件が成立している"


def test_op06_104_trigger_play_self_when_opp_life_le3_ai():
    """トリガー: 相手のライフが3枚以下なら このカードを登場させる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_FILLER)] * 3
    me.trash = [repo.get("OP06-104")]
    st.current_source_card_id = "OP06-104"

    for prim in _do(overlay, "OP06-104", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    ids = [c.card.card_id for c in me.characters]
    assert "OP06-104" in ids, "トリガーでこのカードが登場していない"


# --------------------------------------------------------------------------- #
#  OP06-106 光月日和 (CHARACTER 黄 cost2):
#    【登場時】自分のライフの上か下から1枚を手札に加えることができる：
#      自分の手札1枚までを、ライフの上に加える。
# --------------------------------------------------------------------------- #
def test_op06_106_on_play_life_hand_swap_ai():
    """登場時: ライフ1枚を手札へ → 手札1枚をライフへ (AI)。 net 枚数不変・カードが入れ替わる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3          # ライフ = フィラー
    me.hand = [repo.get(_KERBEROS)]            # 手札 = 識別可能な別カード
    src = InPlay.of(repo.get("OP06-106"), sickness=True)

    for prim in _do(overlay, "OP06-106", "on_play"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    # コスト (ライフ→手札) → 効果 (手札→ライフ) の swap。 手札の別カードが ライフへ移り、
    # ライフのフィラーが 手札へ移る。 総枚数は不変。
    assert len(me.life) == 3, f"ライフ総数が変化している: {len(me.life)}"
    assert len(me.hand) == 1, f"手札総数が変化している: {len(me.hand)}"
    assert any(c.card_id == _KERBEROS for c in me.life), \
        "手札のカードがライフに加えられていない"
    assert any(c.card_id == _FILLER for c in me.hand), \
        "ライフのカードが手札に加えられていない"


def test_op06_106_on_play_human_optional_cost_modal():
    """登場時 (人間): 任意コスト optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    me.hand = [repo.get(_KERBEROS)]
    src = InPlay.of(repo.get("OP06-106"), sickness=True)

    execute_effect(_do(overlay, "OP06-106", "on_play")[0], st, me, opp, src)
    assert st.pending_choice is not None, "人間で任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    _drain(st)


# --------------------------------------------------------------------------- #
#  OP06-107 光月モモの助 (CHARACTER 黄 cost5):
#    【ブロッカー】【登場時】自分の、「光月モモの助」以外の特徴《ワノ国》を持つキャラ1枚までを、
#      持ち主のライフの上か下に表向きで加える。
# --------------------------------------------------------------------------- #
def test_op06_107_on_play_wano_chara_to_life_ai():
    """登場時: 自分の《ワノ国》キャラ1枚をライフに加える (AI)。 自キャラ -1・自ライフ +1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    wano = InPlay.of(repo.get(_WANO), sickness=False)  # 特徴《ワノ国》 (モモの助以外)
    me.characters = [wano]
    me.life = []
    src = InPlay.of(repo.get("OP06-107"), sickness=True)

    for prim in _do(overlay, "OP06-107", "on_play"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert wano not in me.characters, "《ワノ国》キャラが場から離れていない"
    assert len(me.life) == 1, f"《ワノ国》キャラがライフに加えられていない: {len(me.life)}"
    assert me.life[0].card_id == _WANO, "ライフに加わったのが 対象キャラでない"


def test_op06_107_on_play_human_target_pick():
    """登場時 (人間): 《ワノ国》キャラ 複数候補 → target_pick modal。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(_WANO), sickness=False),
                     InPlay.of(repo.get(_WANO), sickness=False)]  # 候補 2 体
    me.life = []
    src = InPlay.of(repo.get("OP06-107"), sickness=True)

    execute_effect(_do(overlay, "OP06-107", "on_play")[0], st, me, opp, src)
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    _drain(st)


# --------------------------------------------------------------------------- #
#  OP06-108 天狗山飛徹 (CHARACTER 黄 cost1):
#    【トリガー】自分の特徴《ワノ国》を持つリーダーかキャラ1枚は、このターン中、パワー+2000。
# --------------------------------------------------------------------------- #
def test_op06_108_trigger_power_pump_wano_ai():
    """トリガー: 自分の《ワノ国》キャラ1枚に パワー+2000 (このターン中、 AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    wano = InPlay.of(repo.get(_WANO), sickness=False)  # 特徴《ワノ国》
    me.characters = [wano]
    power_before = wano.power

    for prim in _do(overlay, "OP06-108", "trigger"):
        execute_effect(prim, st, me, opp, me.leader)
    _drain(st)

    assert wano.power == power_before + 2000, \
        f"《ワノ国》キャラに +2000 が反映されていない: {wano.power} (before {power_before})"


def test_op06_108_trigger_human_target_pick():
    """トリガー (人間): 《ワノ国》キャラ 複数候補 → target_pick modal。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(_WANO), sickness=False),
                     InPlay.of(repo.get(_WANO), sickness=False)]  # 候補 2 体

    execute_effect(_do(overlay, "OP06-108", "trigger")[0], st, me, opp, me.leader)
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    _drain(st)
