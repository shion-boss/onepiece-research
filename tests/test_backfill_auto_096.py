# -*- coding: utf-8 -*-
"""OP09 弾 効果 回帰テスト バックフィル (自動生成 wave 096):
OP09-058 / OP09-059 / OP09-060 / OP09-064 / OP09-065 /
OP09-066 / OP09-068 / OP09-070 / OP09-072 / OP09-073 の 10 枚
(青 バウンス/カウンター/ステージ + 紫 ドン返却起動・KO・アクティブ化系)。

目的 (= test_backfill_auto_001〜095.py と同一方針):
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

# よく使うテスト用カード (テキストの前提固定)
_LEADER_CG = "OP09-042"   # バギー (leader、 四皇/クロスギルド)
_LEADER_KID = "ST02-001"  # ユースタス・キッド (leader、 超新星/キッド海賊団)
_FILLER = "ST01-004"      # サンジ cost2 power4000 (バニラ、 埋め用/相手キャラ)
_SMALL = "OP01-016"       # ナミ cost1 power2000 (バニラ)


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
def test_all_op09_wave096_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP09-058", "OP09-059", "OP09-060", "OP09-064", "OP09-065",
           "OP09-066", "OP09-068", "OP09-070", "OP09-072", "OP09-073"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP09-058 特製マギー玉 (EVENT): 【メイン】相手のコスト6以下のキャラ1枚を持ち主の
#          手札に戻す。 【トリガー】相手のコスト3以下のキャラ1枚までを持ち主の手札に戻す。
# --------------------------------------------------------------------------- #
def test_op09_058_main_bounce_opp_cost6_ai():
    """【メイン】相手のコスト6以下キャラ1枚を相手の手札に戻す (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (≤6)
    opp.characters = [victim]
    opp.hand = []

    prim = _eff(overlay, "OP09-058", "main")["do"][0]
    execute_effect(prim, st, me, opp, None)
    assert victim not in opp.characters, "相手キャラが場から消えていない"
    assert any(c.card_id == _FILLER for c in opp.hand), \
        "相手キャラが相手の手札に戻っていない"


def test_op09_058_main_bounce_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal が立ち、 選んだ1枚だけ戻る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_SMALL), sickness=False)
    opp.characters = [a, b]
    opp.hand = []

    prim = _eff(overlay, "OP09-058", "main")["do"][0]
    execute_effect(prim, st, me, opp, None)
    # ⚠ 公式 (cardqa_op_09): 「このカードを使用したプレイヤーの**対戦相手が**、 自身の場の
    #   コスト6以下のキャラの中から1枚を選び、 手札に戻します。」
    #   → 行動側 (= この人間) には modal は立たない。 相手 (= AI) が最も惜しくない 1 枚を戻す。
    assert st.pending_choice is None, (
        "相手が選ぶ効果なのに行動側に modal が立っている: "
        f"{st.pending_choice.get('kind') if st.pending_choice else None}"
    )
    assert len(opp.characters) == 1, "相手が 1 枚戻していない"
    assert len(opp.hand) == 1, "戻したキャラが相手の手札に無い"


def test_op09_058_trigger_bounce_opp_cost3_ai():
    """【トリガー】相手のコスト3以下キャラ1枚までを相手の手札に戻す (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_SMALL), sickness=False)  # cost1 (≤3)
    opp.characters = [victim]
    opp.hand = []

    prim = _eff(overlay, "OP09-058", "trigger")["do"][0]
    execute_effect(prim, st, me, opp, None)
    assert victim not in opp.characters, "トリガーで相手キャラが場から消えていない"
    assert any(c.card_id == _SMALL for c in opp.hand), \
        "トリガーで相手キャラが相手の手札に戻っていない"


# --------------------------------------------------------------------------- #
#  OP09-059 湯けむり殺人事件 (EVENT): 【カウンター】自リーダーかキャラ1枚まで +3000
#          (このバトル中)。 その後、 自分の手札2枚まで捨て、 捨てた枚数と同じ枚数を
#          デッキ上からトラッシュに置く。 【トリガー】カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op09_059_counter_pump_discard_mill_ai():
    """【カウンター】自リーダー +3000 (battle) → 手札2枚捨て → デッキ上2枚をトラッシュ (AI)。

    target "self_inplay" は 「自リーダーかキャラ1枚まで」 = AI は power 最大を自動選択。
    自キャラ不在なら自リーダーに乗る (= 防御中リーダーへの +3000 を模擬)。
    """
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = []
    me.hand = [repo.get(_FILLER)] * 3
    me.deck = [repo.get(_FILLER)] * 6

    hand_before, deck_before = len(me.hand), len(me.deck)
    trash_before = len(me.trash)
    do = _eff(overlay, "OP09-059", "counter")["do"]
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert me.leader.battle_buff == 3000, \
        f"バトル中 自リーダー +3000 が乗っていない: {me.leader.battle_buff}"
    assert len(me.hand) == hand_before - 2, \
        f"手札2枚が捨てられていない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 2, \
        f"デッキ上2枚がトラッシュに置かれていない: {len(me.deck)}"
    assert len(me.trash) == trash_before + 4, \
        f"トラッシュが (手札2 + デッキ2 =) 4 枚増えていない: {len(me.trash)}"


def test_op09_059_counter_pump_human_pick():
    """人間 + power_pump self_inplay → target_pick modal で自リーダーを選び +3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.characters = []

    do = _eff(overlay, "OP09-059", "counter")["do"]
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 自チーム対象で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    li = next(i for i, c in enumerate(cands) if c.get("is_leader"))
    resolve_pending_choice(st, [li])
    _drain(st, [li])
    assert me.leader.battle_buff == 3000, \
        f"人間が選んだ自リーダーに +3000 が乗っていない: {me.leader.battle_buff}"


def test_op09_059_counter_discard_human_pick():
    """人間 + 手札 > 2 → self_hand_discard_pick modal が立ち、 選んだ2枚が捨てられる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)] * 3
    me.deck = [repo.get(_FILLER)] * 6

    do = _eff(overlay, "OP09-059", "counter")["do"]
    # do[1] = trash_self_hand_random 2 (人間選択)
    execute_effect(do[1], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 手札>2 で discard modal が立たない"
    assert st.pending_choice.get("kind") == "self_hand_discard_pick", \
        f"kind が self_hand_discard_pick でない: {st.pending_choice.get('kind')}"
    hand_before = len(me.hand)
    resolve_pending_choice(st, [0, 1])
    _drain(st, [0])
    assert len(me.hand) == hand_before - 2, \
        f"人間が選んだ2枚が捨てられていない: {len(me.hand)}"


def test_op09_059_trigger_draw_ai():
    """【トリガー】カード1枚を引く → 手札 +1、 デッキ -1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 5

    prim = _eff(overlay, "OP09-059", "trigger")["do"][0]
    execute_effect(prim, st, me, opp, None)
    assert len(me.hand) == 1, f"トリガーで1枚引けていない: {len(me.hand)}"
    assert len(me.deck) == 4, f"デッキが1枚減っていない: {len(me.deck)}"


# --------------------------------------------------------------------------- #
#  OP09-060 カライ・バリ島 (STAGE): 【起動メイン】手札2枚を好きな順番でデッキの下に置き、
#          このステージをレストにできる：自リーダーが《クロスギルド》なら、 カード2枚を引く。
# --------------------------------------------------------------------------- #
def test_op09_060_activate_main_draw2_ai():
    """クロスギルド leader + 任意コスト → 手札2枚をデッキ下 → ステージレスト → 2枚引く (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_CG, overlay)
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("OP09-060"), sickness=False)
    stage.rested = False
    me.stages = [stage]
    me.hand = [repo.get(_FILLER)] * 3
    # デッキ上に一意カード (= draw で手札へ来る) を置く。 hand_to_deck_bottom は下に積む
    # ため 上 2 枚 (= _SMALL) は draw で確実に引ける。
    me.deck = [repo.get(_SMALL), repo.get(_SMALL)] + [repo.get(_FILLER)] * 10

    prim = _eff(overlay, "OP09-060", "activate_main")["do"][0]
    execute_effect(prim, st, me, opp, stage)
    assert stage.rested is True, "起動コストでステージがレストになっていない"
    assert sum(1 for c in me.hand if c.card_id == _SMALL) == 2, \
        "クロスギルド leader で デッキ上2枚 (ナミ) を引けていない"


def test_op09_060_activate_main_human_confirm():
    """人間 + 任意コスト → optional_cost_confirm modal が立ち、 承諾で発動できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_CG, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("OP09-060"), sickness=False)
    me.stages = [stage]
    # 手札 == 2 (= コスト枚数) にして hand_to_deck_bottom の 追加 pick modal を回避し、
    # optional_cost_confirm の accept パスに集中する。
    me.hand = [repo.get(_FILLER)] * 2
    me.deck = [repo.get(_SMALL), repo.get(_SMALL)] + [repo.get(_FILLER)] * 10

    prim = _eff(overlay, "OP09-060", "activate_main")["do"][0]
    execute_effect(prim, st, me, opp, stage)
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾 (= コストを払う)
    _drain(st, [0])
    assert stage.rested is True, "承諾後ステージがレストになっていない"
    assert sum(1 for c in me.hand if c.card_id == _SMALL) == 2, \
        "承諾後 2枚引けていない"


# --------------------------------------------------------------------------- #
#  OP09-064 キラー (CHARACTER): 【登場時】ドン!!-1：自リーダーが《キッド海賊団》なら
#          自リーダー1枚までをアクティブにする。
# --------------------------------------------------------------------------- #
def test_op09_064_on_play_untap_leader_ai():
    """【登場時】(ドン-1 + キッド海賊団 gate): レスト中の自リーダーをアクティブ化 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_KID, overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.rested = True  # アタック後を模擬

    eff = _eff(overlay, "OP09-064", "on_play")
    assert eff.get("cost", {}).get("pay_don") == 1, "overlay の ドン-1 コストが無い"
    assert eff.get("if", {}).get("leader_feature") == "キッド海賊団", \
        "overlay の リーダー条件 (キッド海賊団) が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-064"), sickness=True))
    assert me.leader.rested is False, "自リーダーがアクティブになっていない"


# --------------------------------------------------------------------------- #
#  OP09-065 サンジ (CHARACTER): 【登場時】ドン!!を1枚以上返却できる：このキャラは速攻を
#          得る。 その後、 相手のコスト6以下のキャラ1枚までをレストにする。
# --------------------------------------------------------------------------- #
def test_op09_065_on_play_rush_and_rest_ai():
    """【登場時】(任意コスト): 自身が速攻を得る + 相手コスト6以下キャラをレスト (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    sanji = InPlay.of(repo.get("OP09-065"), sickness=True)
    me.characters = [sanji]
    me.don_active = 2  # 返却コスト用
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (≤6)
    victim.rested = False
    opp.characters = [victim]

    prim = _eff(overlay, "OP09-065", "on_play")["do"][0]
    execute_effect(prim, st, me, opp, sanji)
    assert "速攻" in sanji.granted_keywords, \
        f"自身が速攻を得ていない: {sanji.granted_keywords}"
    assert victim.rested is True, "相手キャラがレストになっていない"


def test_op09_065_on_play_human_confirm():
    """人間 + 任意コスト → optional_cost_confirm → 承諾で速攻付与 + 相手レストまで解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    sanji = InPlay.of(repo.get("OP09-065"), sickness=True)
    me.characters = [sanji]
    me.don_active = 2
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]

    prim = _eff(overlay, "OP09-065", "on_play")["do"][0]
    execute_effect(prim, st, me, opp, sanji)
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert "速攻" in sanji.granted_keywords, "承諾後 自身が速攻を得ていない"
    assert victim.rested is True, "承諾後 相手キャラがレストになっていない"


# --------------------------------------------------------------------------- #
#  OP09-066 ジャンバール (CHARACTER): 【登場時】相手の場のドン!!が自分より多い場合、
#          相手のコスト3以下のキャラ1枚までを KO する。
# --------------------------------------------------------------------------- #
def test_op09_066_on_play_ko_opp_cost3_ai():
    """【登場時】(相手ドン優勢 gate): 相手コスト3以下キャラを KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_SMALL), sickness=False)  # cost1 (≤3)
    opp.characters = [victim]

    eff = _eff(overlay, "OP09-066", "on_play")
    assert eff.get("if", {}).get("don_diff_le") == -1, \
        "overlay の 相手ドン優勢 条件 (don_diff_le=-1) が無い"
    trash_before = len(opp.trash)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-066"), sickness=True))
    assert victim not in opp.characters, "相手コスト3以下キャラが KO されていない"
    assert len(opp.trash) == trash_before + 1, "KO キャラがトラッシュに置かれていない"


def test_op09_066_on_play_ko_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal が立ち、 選んだ1枚だけ KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_SMALL), sickness=False)   # cost1
    b = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (両方 ≤3)
    opp.characters = [a, b]

    prim = _eff(overlay, "OP09-066", "on_play")["do"][0]
    execute_effect(prim, st, me, opp,
                   InPlay.of(repo.get("OP09-066"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    bi = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [bi])
    _drain(st, [bi])
    assert b not in opp.characters, "人間が選んだ相手キャラが KO されていない"
    assert a in opp.characters, "選ばなかった相手キャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP09-068 トニートニー・チョッパー (CHARACTER): 【自分のターン終了時】ドン!!を1枚以上
#          返却できる：このキャラをアクティブにし、 次の相手ターン終了時まで【ブロッカー】を得る。
# --------------------------------------------------------------------------- #
def test_op09_068_end_of_turn_untap_and_blocker_ai():
    """【自分のターン終了時】(任意コスト): 自身をアクティブ化 + ブロッカー付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    chopper = InPlay.of(repo.get("OP09-068"), sickness=False)
    chopper.rested = True  # アタックでレスト済を模擬
    me.characters = [chopper]

    eff = _eff(overlay, "OP09-068", "end_of_turn")
    assert eff.get("cost", {}).get("pay_don") == 1, "overlay の ドン-1 コストが無い"
    assert eff.get("if", {}).get("self_turn") is True, \
        "overlay の 自ターン条件 (self_turn) が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, chopper)
    assert chopper.rested is False, "チョッパーがアクティブになっていない"
    assert "ブロッカー" in chopper.granted_keywords_through_opp_turn, \
        f"次の相手ターン終了時までのブロッカーが付与されていない: " \
        f"{chopper.granted_keywords_through_opp_turn}"


# --------------------------------------------------------------------------- #
#  OP09-070 ナミ (CHARACTER): 【登場時】ドン!!を1枚以上返却できる：自リーダーかキャラ1枚に
#          レストのドン!!2枚までを付与する。
# --------------------------------------------------------------------------- #
def test_op09_070_on_play_attach_rested_don_ai():
    """【登場時】(ドン1返却コスト): 自リーダーにレストドン2枚を付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    nami = InPlay.of(repo.get("OP09-070"), sickness=True)
    me.characters = [nami]
    me.don_active = 1   # 返却コスト用 (active から優先返却)
    me.don_rested = 2   # attach_rested_don の付与元

    prim = _eff(overlay, "OP09-070", "on_play")["do"][0]
    execute_effect(prim, st, me, opp, nami)
    assert me.leader.attached_dons == 2, \
        f"自リーダーにレストドン2枚が付与されていない: {me.leader.attached_dons}"
    assert me.don_rested == 0, \
        f"付与元のレストドンが消費されていない: {me.don_rested}"


def test_op09_070_on_play_human_confirm():
    """人間 + 任意コスト → optional_cost_confirm → 承諾 → 付与先 target_pick まで解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    nami = InPlay.of(repo.get("OP09-070"), sickness=True)
    me.characters = [nami]
    me.don_active = 1
    me.don_rested = 2

    prim = _eff(overlay, "OP09-070", "on_play")["do"][0]
    execute_effect(prim, st, me, opp, nami)
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    # 承諾後 付与先 (自リーダー or キャラ) の target_pick が立つ → リーダー (idx 0) を選ぶ
    assert st.pending_choice is not None, "承諾後 付与先の modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"付与先 kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    li = next(i for i, c in enumerate(cands) if c.get("is_leader"))
    resolve_pending_choice(st, [li])
    _drain(st, [li])
    assert me.leader.attached_dons == 2, "承諾後 自リーダーにレストドンが付与されていない"


# --------------------------------------------------------------------------- #
#  OP09-072 フランキー (CHARACTER): 【ブロッカー】【登場時】ドン!!-2, 自分の手札1枚を
#          捨てられる：カード2枚を引く。
# --------------------------------------------------------------------------- #
def test_op09_072_on_play_draw2_ai():
    """【登場時】(ドン-2 + 手札1捨てコスト): カード2枚を引く (AI、 do 本体)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 6

    eff = _eff(overlay, "OP09-072", "on_play")
    assert eff.get("cost", {}).get("pay_don") == 2, "overlay の ドン-2 コストが無い"
    assert eff.get("cost", {}).get("discard_hand") == 1, \
        "overlay の 手札1捨てコストが無い"
    deck_before = len(me.deck)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-072"), sickness=True))
    assert len(me.hand) == 2, f"カード2枚を引けていない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 2, f"デッキが2枚減っていない: {len(me.deck)}"


# --------------------------------------------------------------------------- #
#  OP09-073 ブルック (CHARACTER): 【アタック時】ドン!!を1枚以上返却できる：相手のキャラ
#          2枚までを、 このターン中、 パワー-2000。
# --------------------------------------------------------------------------- #
def test_op09_073_on_attack_power_down_ai():
    """【アタック時】(ドン1返却コスト): 相手キャラ2枚を このターン中 パワー-2000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    brook = InPlay.of(repo.get("OP09-073"), sickness=False)
    me.characters = [brook]
    me.don_active = 1  # 返却コスト用
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [a, b]

    prim = _eff(overlay, "OP09-073", "on_attack")["do"][0]
    execute_effect(prim, st, me, opp, brook)
    assert a.turn_buff == -2000, f"相手キャラ a に -2000 が乗っていない: {a.turn_buff}"
    assert b.turn_buff == -2000, f"相手キャラ b に -2000 が乗っていない: {b.turn_buff}"


def test_op09_073_on_attack_human_pick():
    """人間 + 相手キャラ3体 → 承諾後 パワー-2000 対象を2枚まで target_pick で選ぶ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    brook = InPlay.of(repo.get("OP09-073"), sickness=False)
    me.characters = [brook]
    me.don_active = 1
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_FILLER), sickness=False)
    c = InPlay.of(repo.get(_SMALL), sickness=False)
    opp.characters = [a, b, c]

    prim = _eff(overlay, "OP09-073", "on_attack")["do"][0]
    execute_effect(prim, st, me, opp, brook)
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    # 承諾後 相手キャラ 3 体 > 2 枚制限 → target_pick modal が立つ
    assert st.pending_choice is not None, "承諾後 パワー-対象の modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"対象選択 kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    ai = next(i for i, x in enumerate(cands) if x["iid"] == a.instance_id)
    bi = next(i for i, x in enumerate(cands) if x["iid"] == b.instance_id)
    resolve_pending_choice(st, [ai, bi])
    _drain(st, [ai, bi])
    assert a.turn_buff == -2000, "選んだ相手キャラ a に -2000 が乗っていない"
    assert b.turn_buff == -2000, "選んだ相手キャラ b に -2000 が乗っていない"
    assert c.turn_buff == 0, "選ばなかった相手キャラ c は変化しないべき"
