# -*- coding: utf-8 -*-
"""OP13 (青 蛇姫海賊団・ボア/白ひげ海賊団・ワノ国 系 + 紫 ロジャー海賊団) 効果 回帰テスト
バックフィル (自動生成 wave 128):
OP13-050 / OP13-052 / OP13-053 / OP13-054 / OP13-055 /
OP13-056 / OP13-057 / OP13-058 / OP13-059 / OP13-060 の 10 枚。

目的 (= test_backfill_auto_001〜127.py と同一方針):
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
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
    trigger_counter_event,
    trigger_main_event,
    trigger_on_attack,
    trigger_on_play,
    try_replace_ko,
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


def _do(overlay, cid, when, must_contain=None):
    """指定 card_id の overlay から when 一致 (+ do[0] に must_contain キー) の効果の do を返す。"""
    for e in overlay.get(cid).effects:
        if e.get("when") != when:
            continue
        if must_contain is not None and must_contain not in e["do"][0]:
            continue
        return e["do"], e
    raise AssertionError(f"{cid} に when={when} (contain={must_contain}) の効果がない")


def _drain(st, guard=14):
    """pending_choice を種別ごとに適切に選び続けて解決しきる。"""
    g = 0
    while st.pending_choice is not None and g < guard:
        kind = st.pending_choice.get("kind", "")
        if kind in ("optional_cost_confirm", "reveal_top_play_confirm",
                    "replace_ko_optional"):
            resolve_pending_choice(st, [1])
        else:
            cands = (st.pending_choice.get("candidates")
                     or st.pending_choice.get("cards")
                     or st.pending_choice.get("options") or [])
            resolve_pending_choice(st, [0] if len(cands) > 0 else [])
        g += 1


# 定番 leader / helper カード
_NEUTRAL = "OP01-001"        # ロロノア・ゾロ (leader、 超新星/麦わらの一味)
_WB_LEADER = "OP02-001"      # エドワード・ニューゲート (leader、 四皇/白ひげ海賊団)
_HANCOCK_LEADER = "OP07-038"  # ボア・ハンコック (leader、 青)
_FILLER = "OP01-013"         # サンジ (麦わらの一味 cost2 pow3000 CHARACTER)
_VICTIM = "OP01-016"         # ナミ (麦わらの一味 cost1 pow2000 CHARACTER)
_HANCOCK_C3 = "OP13-051"     # ボア・ハンコック (CHARACTER 青 cost3 pow5000)
_HANCOCK_C3B = "ST03-013"    # ボア・ハンコック (CHARACTER 青 cost3 pow1000)
_HANCOCK_C6 = "OP07-051"     # ボア・ハンコック (CHARACTER 青 cost6 pow8000)
_WB_C1 = "OP13-045"          # ハルタ (CHARACTER 青 cost1 pow2000、 白ひげ海賊団)
_ROGER_C1 = "OP13-065"       # シャンクス (CHARACTER 紫 cost1 pow2000、 ロジャー海賊団)


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave128_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP13-050", "OP13-052", "OP13-053", "OP13-054", "OP13-055",
           "OP13-056", "OP13-057", "OP13-058", "OP13-059", "OP13-060"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP13-050 ボア・サンダーソニア (CHARACTER 青 cost2 pow3000):
#    【登場時】自リーダーが「ボア・ハンコック」の場合、自分の手札から
#      コスト3以下の「ボア・ハンコック」1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op13_050_on_play_deploy_hancock_ai():
    """【登場時】 自リーダーが ボア・ハンコック → 手札の cost3以下 ボア・ハンコック を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _HANCOCK_LEADER, overlay)  # ボア・ハンコック leader → 条件成立
    me, opp = st.players[0], st.players[1]
    sonia = InPlay.of(repo.get("OP13-050"), sickness=True)
    me.characters = [sonia]
    me.hand = [repo.get(_HANCOCK_C3)]  # ボア・ハンコック cost3

    trigger_on_play(st, me, opp, sonia, overlay)
    _drain(st)

    assert any(c.card.card_id == _HANCOCK_C3 for c in me.characters), \
        "手札の cost3以下 ボア・ハンコック が登場していない"
    assert len(me.hand) == 0, "登場した ボア・ハンコック が手札から抜けていない"


def test_op13_050_on_play_no_deploy_when_leader_not_hancock():
    """負例: 自リーダーが ボア・ハンコック でなければ 条件不成立 → 登場は起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)  # ゾロ leader → 条件不成立
    me, opp = st.players[0], st.players[1]
    sonia = InPlay.of(repo.get("OP13-050"), sickness=True)
    me.characters = [sonia]
    me.hand = [repo.get(_HANCOCK_C3)]

    trigger_on_play(st, me, opp, sonia, overlay)
    _drain(st)

    assert not any(c.card.card_id == _HANCOCK_C3 for c in me.characters), \
        "条件不成立で ボア・ハンコック が登場してはいけない"
    assert len(me.hand) == 1, "条件不成立で手札は減ってはいけない"


def test_op13_050_on_play_deploy_human_pick():
    """人間 + 手札に cost3以下 ボア・ハンコック 複数 → 登場先を選ぶ play_from_hand modal。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _HANCOCK_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    sonia = InPlay.of(repo.get("OP13-050"), sickness=True)
    me.characters = [sonia]
    me.hand = [repo.get(_HANCOCK_C3), repo.get(_HANCOCK_C3B)]  # cost3 ハンコック 2 種

    trigger_on_play(st, me, opp, sonia, overlay)

    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st)
    assert any(c.card.card_id in (_HANCOCK_C3, _HANCOCK_C3B) for c in me.characters), \
        "人間が選んだ ボア・ハンコック が登場していない"


# --------------------------------------------------------------------------- #
#  OP13-052 ボア・マリーゴールド (CHARACTER 青 cost5 pow4000):
#    【ブロッカー】【登場時】自リーダーが「ボア・ハンコック」の場合、自分の手札から
#      コスト6以下の「ボア・ハンコック」1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op13_052_on_play_deploy_hancock_cost6_ai():
    """【登場時】 自リーダー ボア・ハンコック → 手札の cost6以下 ボア・ハンコック を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _HANCOCK_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    marigold = InPlay.of(repo.get("OP13-052"), sickness=True)
    me.characters = [marigold]
    me.hand = [repo.get(_HANCOCK_C6)]  # ボア・ハンコック cost6

    trigger_on_play(st, me, opp, marigold, overlay)
    _drain(st)

    assert any(c.card.card_id == _HANCOCK_C6 for c in me.characters), \
        "手札の cost6以下 ボア・ハンコック が登場していない"


# --------------------------------------------------------------------------- #
#  OP13-053 マーシャル・Ｄ・ティーチ (CHARACTER 青 cost4 pow5000):
#    【アタック時】自分の『白ひげ海賊団』を含む特徴を持つキャラ1枚をトラッシュに置くこと
#      ができる：カード1枚を引き、このキャラは、このターン中、【バニッシュ】を得る。
#  ⚠ overlay 不整合: 公式テキストは「カード1枚を引き」を含むが、 overlay の effect は
#     give_keyword バニッシュ のみで draw:1 が欠落している (= 実測 hand_delta=0)。
#     公式テキスト忠実な assert (draw + banish) が通らないため skip し、 overlay 修正を
#     人間レビューに回す (= このタスクでは engine/overlay を編集しない方針)。
# --------------------------------------------------------------------------- #
def test_op13_053_on_attack_ko_cost_draw_and_banish():
    """【アタック時】 白ひげキャラ1枚をトラッシュ (コスト) → 1ドロー + 自身バニッシュ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    teach = InPlay.of(repo.get("OP13-053"), sickness=False)
    haruta = InPlay.of(repo.get(_WB_C1), sickness=False)  # 白ひげ (トラッシュコスト用)
    me.characters = [teach, haruta]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 10

    hand_before = len(me.hand)
    do, _ = _do(overlay, "OP13-053", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp, teach)
    _drain(st)

    assert haruta not in me.characters, "コストで白ひげキャラがトラッシュに置かれるべき"
    assert len(me.hand) == hand_before + 1, "公式テキストの『カード1枚を引き』が発火していない"
    assert teach.is_banish_now is True, "自身に【バニッシュ】が付与されていない"


# --------------------------------------------------------------------------- #
#  OP13-054 ヤマト (CHARACTER 青 cost5 pow6000):
#    【登場時】自分のライフが3枚以下の場合、カード2枚を引く。その後、自分のリーダーに
#      レストのドン‼1枚までを、付与する。
# --------------------------------------------------------------------------- #
def test_op13_054_on_play_draw_and_attach_when_life_le3_ai():
    """【登場時】 自ライフ3以下 → 2ドロー + 自リーダーにレストドン1付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3  # ライフ 3 (≤3、 条件成立)
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 10
    me.don_rested = 2
    yamato = InPlay.of(repo.get("OP13-054"), sickness=True)
    me.characters = [yamato]

    deck_before = len(me.deck)
    rested_before = me.don_rested
    leader_don_before = me.leader.attached_dons
    trigger_on_play(st, me, opp, yamato, overlay)
    _drain(st)

    assert len(me.hand) == 2, f"【登場時】に2枚引けていない: hand={len(me.hand)}"
    assert len(me.deck) == deck_before - 2, "デッキが2枚減っていない"
    assert me.leader.attached_dons == leader_don_before + 1, \
        "自リーダーにレストドンが1枚付与されていない"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"


def test_op13_054_on_play_no_effect_when_life_over3():
    """負例: 自ライフが4枚 (>3) なら 条件不成立 → ドロー/ドン付与 は起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 4  # ライフ 4 (>3)
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 10
    me.don_rested = 2
    yamato = InPlay.of(repo.get("OP13-054"), sickness=True)
    me.characters = [yamato]

    deck_before = len(me.deck)
    leader_don_before = me.leader.attached_dons
    trigger_on_play(st, me, opp, yamato, overlay)
    _drain(st)

    assert len(me.hand) == 0, "ライフ4 (条件不成立) でドローが起きてはいけない"
    assert len(me.deck) == deck_before, "ライフ4 (条件不成立) でデッキは減ってはいけない"
    assert me.leader.attached_dons == leader_don_before, \
        "ライフ4 (条件不成立) でドン付与は起きてはいけない"


# --------------------------------------------------------------------------- #
#  OP13-055 ラクヨウ (CHARACTER 青 cost3 pow4000):
#    【アタック時】自分の手札が4枚以下の場合、自分の『白ひげ海賊団』を含む特徴を持つ
#      キャラすべてを、このターン中、パワー+1000。
# --------------------------------------------------------------------------- #
def test_op13_055_on_attack_pump_whitebeard_when_hand_le4_ai():
    """【アタック時】 自手札4以下 → 自 白ひげ キャラすべて +1000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    rakuyou = InPlay.of(repo.get("OP13-055"), sickness=False)  # 白ひげ海賊団
    haruta = InPlay.of(repo.get(_WB_C1), sickness=False)       # ハルタ 白ひげ海賊団
    me.characters = [rakuyou, haruta]
    me.hand = [repo.get(_FILLER)] * 2  # 手札 2 (≤4)

    haruta_before = haruta.power
    trigger_on_attack(st, me, opp, rakuyou, overlay)
    _drain(st)

    assert haruta.power == haruta_before + 1000, \
        f"白ひげキャラ (ハルタ) に +1000 が乗っていない: {haruta.power} (before {haruta_before})"


def test_op13_055_on_attack_no_pump_when_hand_over4():
    """負例: 自手札が5枚 (>4) なら 条件不成立 → +1000 は乗らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    rakuyou = InPlay.of(repo.get("OP13-055"), sickness=False)
    haruta = InPlay.of(repo.get(_WB_C1), sickness=False)
    me.characters = [rakuyou, haruta]
    me.hand = [repo.get(_FILLER)] * 5  # 手札 5 (>4)

    haruta_before = haruta.power
    trigger_on_attack(st, me, opp, rakuyou, overlay)
    _drain(st)

    assert haruta.power == haruta_before, \
        "手札5 (条件不成立) で +1000 が乗ってはいけない"


# --------------------------------------------------------------------------- #
#  OP13-056 リトルオーズJr. (CHARACTER 青 cost7 pow7000):
#    【アタック時】自分のリーダーが『白ひげ海賊団』を含む特徴を持つ場合、カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op13_056_on_attack_draw_when_leader_whitebeard_ai():
    """【アタック時】 自リーダーが 白ひげ → カード1枚を引く (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _WB_LEADER, overlay)  # 白ひげ leader → 条件成立
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 10
    oars = InPlay.of(repo.get("OP13-056"), sickness=False)
    me.characters = [oars]

    trigger_on_attack(st, me, opp, oars, overlay)
    _drain(st)

    assert len(me.hand) == 1, f"【アタック時】に1枚引けていない: hand={len(me.hand)}"


def test_op13_056_on_attack_no_draw_when_leader_not_whitebeard():
    """負例: 自リーダーが 白ひげ でなければ 条件不成立 → ドローは起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)  # ゾロ leader (白ひげ 無し)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 10
    oars = InPlay.of(repo.get("OP13-056"), sickness=False)
    me.characters = [oars]

    trigger_on_attack(st, me, opp, oars, overlay)
    _drain(st)

    assert len(me.hand) == 0, "条件不成立でドローが起きてはいけない"


# --------------------------------------------------------------------------- #
#  OP13-057 “力”に屈したら男に生まれた意味がねェだろう (EVENT 青 cost1):
#    【メイン】自分のドン‼1枚をレストにできる：自分のライフが1枚以下の場合、相手は、
#      このターン中、自分のリーダーがアタックする際【ブロッカー】を発動できない。
#    【カウンター】自分のリーダーを、このバトル中、パワー+3000。
# --------------------------------------------------------------------------- #
def test_op13_057_main_prevent_blocker_when_life_le1_ai():
    """【メイン】 ドン1レスト + 自ライフ1以下 → 自リーダーのアタックにブロッカー禁止 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 2
    me.don_rested = 0
    me.life = [repo.get(_FILLER)] * 1  # ライフ 1 (≤1、 条件成立)

    trigger_main_event(st, me, opp, repo.get("OP13-057"), overlay)
    _drain(st)

    assert me.leader.attacker_prevents_blocker_until_turn_end is True, \
        "自リーダーに『アタック時ブロッカー禁止』フラグが立っていない"
    assert me.don_rested == 1, "コストでドンが1枚レストされるべき"


def test_op13_057_counter_pump_leader():
    """【カウンター】 自リーダーを このバトル中 パワー+3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    trigger_counter_event(st, me, opp, repo.get("OP13-057"), overlay)
    _drain(st)

    assert me.leader.power == power_before + 3000, \
        f"カウンターの +3000 が自リーダーに反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  OP13-058 鳳梨礫 (EVENT 青 cost1):
#    【メイン】自分のドン‼1枚をレストにできる：相手のパワー3000以下のキャラ1枚までを、
#      持ち主のデッキの下に置く。
#    【カウンター】自分のリーダーを、このバトル中、パワー+3000。
# --------------------------------------------------------------------------- #
def test_op13_058_main_return_opp_power_le3000_to_deck_bottom_ai():
    """【メイン】 ドン1レスト → 相手のパワー3000以下キャラ1枚をデッキ下 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 2
    me.don_rested = 0
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # pow3000 (≤3000)
    opp.characters = [victim]
    opp_deck_before = len(opp.deck)

    trigger_main_event(st, me, opp, repo.get("OP13-058"), overlay)
    _drain(st)

    assert victim not in opp.characters, "相手のパワー3000以下キャラがデッキ下に戻っていない"
    assert len(opp.deck) == opp_deck_before + 1, "戻したキャラがデッキに加わっていない"
    assert me.don_rested == 1, "コストでドンが1枚レストされるべき"


def test_op13_058_main_return_human_pick():
    """人間 + 相手キャラ複数 → コスト確認 → 戻す対象を選ぶ target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _WB_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_active = 2
    a = InPlay.of(repo.get(_FILLER), sickness=False)   # pow3000
    b = InPlay.of(repo.get(_VICTIM), sickness=False)   # pow2000
    opp.characters = [a, b]

    trigger_main_event(st, me, opp, repo.get("OP13-058"), overlay)

    # まず 任意コスト (ドン1レスト) の確認 modal → 承諾
    assert st.pending_choice is not None, "コスト確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # コストを払う

    assert st.pending_choice is not None, "コスト後に対象選択 modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b not in opp.characters, "人間が選んだキャラがデッキ下に戻っていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP13-059 ブリリアント・パンク (EVENT 青 cost4):
#    【メイン】自分のキャラ1枚を持ち主の手札に戻すことができる：コスト6以下のキャラ1枚
#      までを、持ち主の手札に戻す。
#    【トリガー】カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op13_059_main_bounce_cost_then_bounce_opp_ai():
    """【メイン】 自キャラ1枚を手札に戻す (コスト) → 相手 cost6以下キャラ1枚を手札に戻す (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 4
    mine = InPlay.of(repo.get(_FILLER), sickness=False)  # コストで戻す自キャラ
    me.characters = [mine]
    victim = InPlay.of(repo.get(_VICTIM), sickness=False)  # 相手 cost1 (≤6)
    opp.characters = [victim]
    me_hand_before = len(me.hand)
    opp_hand_before = len(opp.hand)

    trigger_main_event(st, me, opp, repo.get("OP13-059"), overlay)
    _drain(st)

    assert mine not in me.characters, "コストで自キャラが手札に戻っていない"
    assert len(me.hand) == me_hand_before + 1, "戻した自キャラが手札に加わっていない"
    assert victim not in opp.characters, "相手の cost6以下キャラが手札に戻っていない"
    assert len(opp.hand) == opp_hand_before + 1, "戻した相手キャラが相手の手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP13-060 天月トキ (CHARACTER 紫 cost2 pow3000):
#    自分の『ロジャー海賊団』を含む特徴を持つキャラが相手の効果でKOされる場合、
#    代わりにこのキャラ (トキ) をトラッシュに置くことができる。 (= replace_ko / optional)
# --------------------------------------------------------------------------- #
def test_op13_060_replace_ko_protect_roger_ai():
    """AI: 自 ロジャー キャラが相手効果KO → 代わりに トキ をトラッシュ (victim 生存)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    toki = InPlay.of(repo.get("OP13-060"), sickness=False)     # holder
    victim = InPlay.of(repo.get(_ROGER_C1), sickness=False)    # シャンクス ロジャー (被KO対象)
    me.characters = [toki, victim]
    trash_before = len(me.trash)

    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "自 ロジャー キャラの相手効果KOが置換されていない"
    assert victim in me.characters, "置換成立時 被KO対象 (シャンクス) は場に残るべき"
    assert toki not in me.characters, "置換コストで トキ が場から取り除かれるべき"
    assert len(me.trash) == trash_before + 1, "トキ がトラッシュに置かれていない"


def test_op13_060_replace_ko_excludes_battle():
    """負例: バトルKO (by_opp_effect=False) は「相手の効果で」に該当しない → 置換しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    toki = InPlay.of(repo.get("OP13-060"), sickness=False)
    victim = InPlay.of(repo.get(_ROGER_C1), sickness=False)
    me.characters = [toki, victim]

    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=False, leave_kind="ko",
    )
    assert replaced is False, "相手効果以外 (バトル等) のKOを置換してはいけない"


def test_op13_060_replace_ko_human_confirm():
    """人間 actor: replace_ko は 任意 → replace_ko_optional modal が立ち、
    承諾すると トキ をトラッシュにして 被KO対象を守る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    toki = InPlay.of(repo.get("OP13-060"), sickness=False)
    victim = InPlay.of(repo.get(_ROGER_C1), sickness=False)
    me.characters = [toki, victim]

    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "人間 optional でも modal を立てて halt するべき (True)"
    assert st.pending_choice is not None, "replace_ko の 任意確認 modal が立たない"
    assert st.pending_choice.get("kind") == "replace_ko_optional", \
        f"kind が replace_ko_optional でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾 (= 置換する)
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [1])
        guard += 1
    assert victim in me.characters, "人間承諾後 被KO対象 (シャンクス) は場に残るべき"
    assert toki not in me.characters, "人間承諾後 トキ がトラッシュに置かれるべき"
