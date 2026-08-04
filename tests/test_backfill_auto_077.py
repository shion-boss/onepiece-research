# -*- coding: utf-8 -*-
"""OP07 弾 効果 回帰テスト バックフィル (自動生成 wave 077):
OP07-050 / OP07-052 / OP07-053 / OP07-054 / OP07-055 / OP07-057 /
OP07-058 / OP07-060 / OP07-061 / OP07-062 の 10 枚
(九蛇海賊団 / 王下七武海 青 + フォクシー海賊団 / ヴィンスモーク家 紫)。

目的 (= 永続的 pytest による担保、 test_backfill_auto_076.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 択一 を 持つカードは 人間 actor で pending_choice が
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
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

_LEADER = "OP01-001"         # ロロノア・ゾロ (赤、 直接 execute_effect なので色は無関係)
_KUJA_LEADER = "OP14-041"    # ボア・ハンコック (青、 特徴《九蛇海賊団》を持つ leader)
_FOXY_LEADER = "OP07-059"    # フォクシー (特徴《フォクシー海賊団》を持つ leader)
_VIN_LEADER = "OP12-041"     # サンジ (特徴《ヴィンスモーク家》を持つ leader)
_SHICHI_LEADER = "OP16-080"  # ティーチ (特徴《王下七武海》を持つ leader)
_FILLER = "OP01-013"         # サンジ cost2 power3000 (汎用フィラー)
_KUJA_A = "OP16-111"         # ボア・サンダーソニア cost4 (九蛇海賊団)
_KUJA_B = "OP14-105"         # ゴルゴン三姉妹 cost6 (王下七武海/九蛇海賊団)
_AMAZON = "OP08-048"         # スイトピー cost4 (アマゾン・リリー、 バニラ)
_SHICHI_CHAR = "OP07-040"    # クロコダイル cost4 (王下七武海)
_VIN1 = "OP10-063"           # ヴィンスモーク・サンジ cost1 power2000 (ヴィンスモーク家)
_VIN2 = "OP06-063"           # ヴィンスモーク・ソラ cost1 (ヴィンスモーク家)
_OPP_C2 = "OP01-013"         # サンジ cost2 (相手の cost<=3/<=2 対象)
_OPP_C1 = "OP06-025"         # ケイミー cost1 (相手の cost<=3/<=2 対象 2 体目)


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
def test_all_wave77_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP07-050", "OP07-052", "OP07-053", "OP07-054", "OP07-055",
           "OP07-057", "OP07-058", "OP07-060", "OP07-061", "OP07-062"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP07-050 ボア・サンダーソニア (CHARACTER 青 cost3):
#    【登場時】自分の場に特徴《アマゾン・リリー》か《九蛇海賊団》を持つキャラが2枚以上
#      いる場合、相手のコスト3以下のキャラ1枚までを、持ち主の手札に戻す。
# --------------------------------------------------------------------------- #
def test_op07_050_on_play_bounce_opp_cost3_ai():
    """登場時: 相手のコスト3以下キャラ1枚を持ち主の手札に戻す (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(_KUJA_A), sickness=False),
                     InPlay.of(repo.get(_KUJA_B), sickness=False)]
    victim = InPlay.of(repo.get(_OPP_C2), sickness=False)  # cost2
    opp.characters = [victim]
    opp.hand = []

    for prim in _do(overlay, "OP07-050", "on_play"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert victim not in opp.characters, "相手のコスト3以下キャラが場に残っている"
    assert any(c.card_id == _OPP_C2 for c in opp.hand), \
        "戻したキャラが相手の手札に加わっていない"


def test_op07_050_feature_count_condition():
    """条件: 自場に《アマゾン・リリー》/《九蛇海賊団》が2枚以上で成立、 1枚で不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me = st.players[0]
    cond = _eff(overlay, "OP07-050", "on_play").get("if")
    assert cond is not None, "OP07-050 on_play に特徴カウント条件がない"
    me.characters = [InPlay.of(repo.get(_KUJA_A), sickness=False)]
    assert eval_condition(cond, st, me) is False, "九蛇1枚で条件が成立してはいけない"
    me.characters.append(InPlay.of(repo.get(_AMAZON), sickness=False))
    assert eval_condition(cond, st, me) is True, "九蛇+アマゾン2枚で条件が成立するべき"


def test_op07_050_on_play_human_pick():
    """登場時 (人間): 相手のコスト3以下キャラが2体 → target_pick modal → 1体を戻す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(_KUJA_A), sickness=False),
                     InPlay.of(repo.get(_KUJA_B), sickness=False)]
    a = InPlay.of(repo.get(_OPP_C2), sickness=False)  # cost2
    b = InPlay.of(repo.get(_OPP_C1), sickness=False)  # cost1
    opp.characters = [a, b]
    opp.hand = []

    execute_effect(_do(overlay, "OP07-050", "on_play")[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b not in opp.characters, "人間が選んだキャラが場から戻っていない"
    assert a in opp.characters, "選ばなかったキャラは場に残るべき"


# --------------------------------------------------------------------------- #
#  OP07-052 ボア・マリーゴールド (CHARACTER 青 cost5):
#    【登場時】自分の場に特徴《アマゾン・リリー》か《九蛇海賊団》を持つキャラが2枚以上
#      いる場合、コスト2以下のキャラ1枚までを、持ち主のデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op07_052_on_play_return_opp_cost2_to_deck_bottom_ai():
    """登場時: 相手のコスト2以下キャラ1枚を持ち主のデッキの下に置く (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(_KUJA_A), sickness=False),
                     InPlay.of(repo.get(_KUJA_B), sickness=False)]
    victim = InPlay.of(repo.get(_OPP_C2), sickness=False)  # cost2
    opp.characters = [victim]
    opp.deck = [repo.get(_FILLER)] * 5
    deck_before = len(opp.deck)

    for prim in _do(overlay, "OP07-052", "on_play"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert victim not in opp.characters, "相手のコスト2以下キャラが場に残っている"
    assert len(opp.deck) == deck_before + 1, "相手デッキの下に1枚加わるべき"
    assert opp.deck[-1].card_id == _OPP_C2, "戻したキャラがデッキの一番下にない"


def test_op07_052_feature_count_condition():
    """条件: OP07-050 と同じ 特徴2枚以上カウント (九蛇/アマゾン)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me = st.players[0]
    cond = _eff(overlay, "OP07-052", "on_play").get("if")
    assert cond is not None, "OP07-052 on_play に特徴カウント条件がない"
    me.characters = [InPlay.of(repo.get(_KUJA_A), sickness=False)]
    assert eval_condition(cond, st, me) is False, "1枚で条件が成立してはいけない"
    me.characters.append(InPlay.of(repo.get(_KUJA_B), sickness=False))
    assert eval_condition(cond, st, me) is True, "2枚で条件が成立するべき"


# --------------------------------------------------------------------------- #
#  OP07-053 ポートガス・D・エース (CHARACTER 青 cost5):
#    【ブロッカー】【登場時】カード2枚を引き、自分の手札2枚を好きな順番で並び替え、
#      デッキの上か下に置く。
# --------------------------------------------------------------------------- #
def test_op07_053_on_play_draw2_then_hand_to_deck_ai():
    """登場時: 2枚引き → 手札2枚をデッキに戻す (net で手札/デッキ枚数は不変、 AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER), repo.get(_FILLER)]
    me.deck = [repo.get(_FILLER)] * 10
    hand_before = len(me.hand)
    deck_before = len(me.deck)

    for prim in _do(overlay, "OP07-053", "on_play"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    # draw +2 / put-back -2 = 手札は不変、 デッキも -2(draw) +2(戻し) = 不変
    assert len(me.hand) == hand_before, \
        f"手札枚数 net が合わない: {len(me.hand)} (before {hand_before})"
    assert len(me.deck) == deck_before, \
        f"デッキ枚数 net が合わない: {len(me.deck)} (before {deck_before})"


# --------------------------------------------------------------------------- #
#  OP07-054 マーガレット (CHARACTER 青 cost3):
#    【ブロッカー】【登場時】カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op07_054_on_play_draw_ai():
    """登場時: カード1枚を引く (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 5
    deck_before = len(me.deck)

    for prim in _do(overlay, "OP07-054", "on_play"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert len(me.hand) == 1, "登場時の draw が起きていない"
    assert len(me.deck) == deck_before - 1, "デッキから1枚引かれるべき"


# --------------------------------------------------------------------------- #
#  OP07-055 蛇ダンス (EVENT 青 cost2):
#    【カウンター】自分のリーダーかキャラ1枚までを、このバトル中、パワー+4000。
# --------------------------------------------------------------------------- #
def test_op07_055_counter_pump_leader_ai():
    """カウンター: 自分のリーダー(既定)を このバトル中 パワー+4000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = []  # 候補はリーダーのみ → AI はリーダーを pump
    power_before = me.leader.power

    for prim in _do(overlay, "OP07-055", "counter"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert me.leader.power == power_before + 4000, \
        f"カウンターの +4000 が自リーダーに反映されていない: {me.leader.power}"


def test_op07_055_counter_pump_human_pick():
    """カウンター (人間): リーダー + キャラ → target_pick modal → 選んだ方に +4000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [friend]

    execute_effect(_do(overlay, "OP07-055", "counter")[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    _drain(st)
    assert friend.power == friend_before + 4000, \
        "人間が選んだキャラに +4000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP07-057 芳香脚 (EVENT 青 cost2):
#    【メイン】自分の特徴《王下七武海》を持つ、リーダーかキャラ1枚までを選び、
#      このターン中、パワー+2000。その後、相手は、このターン中、選んだカードがアタック
#      する場合【ブロッカー】を発動できない。
#    【トリガー】カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op07_057_main_pump_shichibukai_ai():
    """メイン: 自分の《王下七武海》キャラを このターン中 パワー+2000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    croc = InPlay.of(repo.get(_SHICHI_CHAR), sickness=False)  # 王下七武海
    me.characters = [croc]
    before = croc.power

    for prim in _do(overlay, "OP07-057", "main"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert croc.power == before + 2000, \
        f"《王下七武海》キャラに +2000 が反映されていない: {croc.power} (before {before})"


def test_op07_057_main_pump_human_pick():
    """メイン (人間): 王下七武海 リーダー + 王下七武海 キャラ → target_pick → 選択で +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SHICHI_LEADER, overlay, human_idx=0)  # 王下七武海 leader
    me, opp = st.players[0], st.players[1]
    croc = InPlay.of(repo.get(_SHICHI_CHAR), sickness=False)
    me.characters = [croc]

    execute_effect(_do(overlay, "OP07-057", "main")[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    croc_idx = next(i for i, c in enumerate(cands) if c["iid"] == croc.instance_id)
    croc_before = croc.power
    resolve_pending_choice(st, [croc_idx])
    _drain(st)
    assert croc.power == croc_before + 2000, \
        "人間が選んだ《王下七武海》キャラに +2000 が反映されていない"


def test_op07_057_trigger_draw_ai():
    """トリガー: カード1枚を引く (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 5

    for prim in _do(overlay, "OP07-057", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert len(me.hand) == 1, "トリガーの draw が起きていない"


# --------------------------------------------------------------------------- #
#  OP07-058 女ヶ島 (STAGE 青 cost1):
#    【起動メイン】自分の手札1枚を捨て、このステージをレストにできる：自分のリーダーが
#      特徴《九蛇海賊団》を持つ場合、自分の特徴《アマゾン・リリー》か《九蛇海賊団》を持つ
#      キャラ1枚までを、持ち主の手札に戻す。
# --------------------------------------------------------------------------- #
def test_op07_058_activate_return_kuja_chara_ai():
    """起動メイン: 手札1捨て + ステージレスト → 九蛇/アマゾンキャラ1枚を手札に戻す (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _KUJA_LEADER, overlay)  # 九蛇海賊団 leader → 条件成立
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("OP07-058"), sickness=False)
    me.stages = [stage]
    target = InPlay.of(repo.get(_KUJA_A), sickness=False)  # 九蛇海賊団
    me.characters = [target]
    me.hand = [repo.get(_FILLER)]  # 捨てるコスト用

    options = list_activate_main_effects(st, me, overlay)
    opts = [(src, eff) for (src, eff) in options
            if src.card.card_id == "OP07-058"]
    assert len(opts) == 1, f"OP07-058 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    assert target not in me.characters, "九蛇キャラが手札に戻っていない (場に残存)"
    assert any(c.card_id == _KUJA_A for c in me.hand), \
        "戻した九蛇キャラが手札に加わっていない"
    assert stage.rested is True, "起動メインコストでステージがレストされるべき"


def test_op07_058_activate_condition_requires_kuja_leader():
    """negative: リーダーが《九蛇海賊団》でなければ起動メインが legal に出ない。"""
    # ⚠ 2026-08-05 是正: 公式は 「〜できる：<条件>の場合、<効果>」 のコロン後の条件を
    #   **効果のみ** の gate とする。 任意コストは条件不成立でも支払える。
    #   一次情報 (cardqa_op_02): 「自分のリーダーが「エンポリオ・イワンコフ」ではない場合、
    #   この【起動メイン】効果を発動できますか？」 → 「はい、できます。 その場合、このカードを
    #   レストにしますが、 **その後の効果では何も起きません**」。
    #   → 「条件不成立なら legal に出ない」 は **行動の合法性ごと消す旧バグ** を固定していた。
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)  # 九蛇海賊団 でない leader
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("OP07-058"), sickness=False)
    me.stages = [stage]
    me.characters = [InPlay.of(repo.get(_KUJA_A), sickness=False)]
    me.hand = [repo.get(_FILLER)]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP07-058"]
    assert len(opts) == 1, (
        "任意コストは条件不成立でも払えるので legal に残るべき (公式: cardqa_op_02)"
    )


# --------------------------------------------------------------------------- #
#  OP07-060 イトミミズ (CHARACTER 紫 cost3):
#    【起動メイン】【ターン1回】自分のリーダーが特徴《フォクシー海賊団》を持ち、自分の
#      他の「イトミミズ」がいない場合、ドン‼デッキからドン‼1枚までを、レストで追加する。
# --------------------------------------------------------------------------- #
def test_op07_060_activate_add_rested_don_ai():
    """起動メイン: ドンデッキからレストドン1枚を追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _FOXY_LEADER, overlay)  # フォクシー海賊団 leader
    me, opp = st.players[0], st.players[1]
    ito = InPlay.of(repo.get("OP07-060"), sickness=False)
    me.characters = [ito]
    me.don_remaining_in_deck = 5
    rested_before = me.don_rested
    deck_before = me.don_remaining_in_deck

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP07-060"]
    assert len(opts) == 1, f"OP07-060 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    assert me.don_rested == rested_before + 1, "レストドンが1枚追加されていない"
    assert me.don_remaining_in_deck == deck_before - 1, "ドンデッキから1枚減るべき"


def test_op07_060_activate_once_per_turn():
    """【ターン1回】: 一度発動すると再び legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _FOXY_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP07-060"), sickness=False)]
    me.don_remaining_in_deck = 5

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP07-060"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st)

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP07-060"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


def test_op07_060_activate_condition_negatives():
    """negative: フォクシー以外の leader / 他のイトミミズがいる場合は legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    # (a) フォクシー でない leader
    st = _state(repo, _LEADER, overlay)
    me = st.players[0]
    me.characters = [InPlay.of(repo.get("OP07-060"), sickness=False)]
    me.don_remaining_in_deck = 5
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP07-060"]
    assert len(opts) == 0, "フォクシーでないリーダーで legal に出てはいけない"

    # (b) フォクシー leader + イトミミズが2体
    st2 = _state(repo, _FOXY_LEADER, overlay)
    me2 = st2.players[0]
    me2.characters = [InPlay.of(repo.get("OP07-060"), sickness=False),
                      InPlay.of(repo.get("OP07-060"), sickness=False)]
    me2.don_remaining_in_deck = 5
    opts2 = [o for o in list_activate_main_effects(st2, me2, overlay)
             if o[0].card.card_id == "OP07-060"]
    assert len(opts2) == 0, "他の「イトミミズ」がいる場合は legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP07-061 ヴィンスモーク・サンジ (CHARACTER 紫 cost1):
#    【登場時】ドン!!-1：自分のリーダーが特徴《ヴィンスモーク家》を持つ場合、
#      カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op07_061_on_play_draw_ai():
    """登場時: (ドン-1 支払い後) カード1枚を引く (AI、 do 部分)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _VIN_LEADER, overlay)  # ヴィンスモーク家 leader
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 5
    deck_before = len(me.deck)

    for prim in _do(overlay, "OP07-061", "on_play"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert len(me.hand) == 1, "登場時の draw が起きていない"
    assert len(me.deck) == deck_before - 1, "デッキから1枚引かれるべき"


def test_op07_061_leader_feature_condition():
    """条件: リーダーが《ヴィンスモーク家》で成立、 そうでなければ不成立。"""
    repo = _repo()
    overlay = _overlay()
    cond = _eff(overlay, "OP07-061", "on_play").get("if")
    assert cond is not None, "OP07-061 に leader_feature 条件がない"
    st_ok = _state(repo, _VIN_LEADER, overlay)
    assert eval_condition(cond, st_ok, st_ok.players[0]) is True, \
        "ヴィンスモーク家 leader で条件が成立するべき"
    st_ng = _state(repo, _LEADER, overlay)
    assert eval_condition(cond, st_ng, st_ng.players[0]) is False, \
        "ヴィンスモーク家でない leader で条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP07-062 ヴィンスモーク・レイジュ (CHARACTER 紫 cost1):
#    【登場時】自分の場のドン!!が相手の場のドン!!の枚数以下の場合、自分のコスト1の
#      特徴《ヴィンスモーク家》を持つキャラ1枚までを、持ち主の手札に戻す。
# --------------------------------------------------------------------------- #
def test_op07_062_on_play_bounce_self_vinsmoke_ai():
    """登場時: 自分のコスト1《ヴィンスモーク家》キャラ1枚を手札に戻す (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    target = InPlay.of(repo.get(_VIN1), sickness=False)  # cost1 ヴィンスモーク家
    me.characters = [target]
    me.hand = []

    for prim in _do(overlay, "OP07-062", "on_play"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert target not in me.characters, "コスト1ヴィンスモーク家キャラが場に残っている"
    assert any(c.card_id == _VIN1 for c in me.hand), \
        "戻したキャラが自分の手札に加わっていない"


def test_op07_062_don_diff_condition():
    """条件: 自ドン <= 相手ドン で成立 (don_diff_le 0)、 自ドンが多いと不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    cond = _eff(overlay, "OP07-062", "on_play").get("if")
    assert cond is not None, "OP07-062 に don_diff 条件がない"
    # 自0 相手0 → 0<=0 成立
    assert eval_condition(cond, st, me, opp) is True, \
        "自ドン<=相手ドンで条件が成立するべき"
    # 自ドンを増やす → 不成立
    me.don_active = 2
    assert eval_condition(cond, st, me, opp) is False, \
        "自ドンが相手より多いと条件が成立してはいけない"


def test_op07_062_on_play_human_pick():
    """登場時 (人間): コスト1《ヴィンスモーク家》が2体 → target_pick modal → 1体を戻す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_VIN1), sickness=False)
    b = InPlay.of(repo.get(_VIN2), sickness=False)
    me.characters = [a, b]
    me.hand = []

    execute_effect(_do(overlay, "OP07-062", "on_play")[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b not in me.characters, "人間が選んだキャラが手札に戻っていない"
    assert a in me.characters, "選ばなかったキャラは場に残るべき"
