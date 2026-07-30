# -*- coding: utf-8 -*-
"""OP13 / OP14 弾 効果 回帰テスト バックフィル (自動生成 wave 132):
OP13-118 / OP13-120 / OP14-002 / OP14-005 / OP14-006 / OP14-009 /
OP14-011 / OP14-012 / OP14-015 / OP14-016 の 10 枚。

目的 (= test_backfill_auto_001〜131.py と同一方針):
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
    eval_condition,
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
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。
    デッキは効果の薄いバニラ気味カード (ST01-004) で埋める (= サーチ/ドローの混入回避)。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("ST01-004")] * 30
    p1.deck = [repo.get("ST01-004")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _entries(overlay, cid, when):
    """指定 card_id の overlay から when 一致の効果 entry を全件返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    return matches


def _do(overlay, cid, when):
    """指定 card_id の overlay から when 一致の最初の効果の do を返す。"""
    return _entries(overlay, cid, when)[0]["do"]


# 定番 helper カード
_FILLER = "ST01-004"        # サンジ (cost2 pow4000 CHARACTER、 トリガー無し)
_NAMI = "OP01-016"          # ナミ (cost2 pow2000、 truly_original 2000 = KO対象/debuf対象)
_MULTI_LEADER = "ST12-001"  # ロロノア・ゾロ＆サンジ (LEADER 緑/青 = 多色)


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave132_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP13-118", "OP13-120", "OP14-002", "OP14-005", "OP14-006",
           "OP14-009", "OP14-011", "OP14-012", "OP14-015", "OP14-016"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP13-118 モンキー・Ｄ・ルフィ (CHARACTER 緑 cost6):
#    【ダブルアタック】【登場時】自分のリーダーが多色の場合、 自分のドン!!4枚までを、
#    アクティブにする。 その後、 このターン中 元々のコスト5以上のキャラを登場できない。
# --------------------------------------------------------------------------- #
def test_op13_118_luffy_on_play_untap_don_ai():
    """【登場時】多色リーダー → レストドン4枚をアクティブにする (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _MULTI_LEADER, overlay)  # 多色 leader → 条件成立
    me, opp = st.players[0], st.players[1]
    me.don_rested = 5
    me.don_active = 0

    assert eval_condition({"leader_multicolor": True}, st, me) is True, \
        "前提: 多色リーダーで leader_multicolor が成立していない"

    for prim in _do(overlay, "OP13-118", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP13-118"), sickness=True))

    assert me.don_active == 4, f"アクティブドンが4枚になっていない: {me.don_active}"
    assert me.don_rested == 1, f"レストドンが1枚残っていない: {me.don_rested}"


def test_op13_118_luffy_gate_off_when_monocolor():
    """負例: 単色リーダーでは leader_multicolor 条件が不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # 赤単色 leader
    me = st.players[0]
    assert eval_condition({"leader_multicolor": True}, st, me) is False, \
        "単色 leader で leader_multicolor が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP13-120 サボ (CHARACTER 黒 cost6):
#    【ブロッカー】【起動メイン】【ターン1回】自分のキャラ1枚までを、次の相手のターン終了時まで、
#    コスト+2。 その後、 自分のリーダーにレストのドン!!1枚までを、付与する。
# --------------------------------------------------------------------------- #
def test_op13_120_sabo_activate_main_ai():
    """【起動メイン】自リーダーへレストドン1付与 + 自キャラ1体コスト+2 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2
    friend = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    me.characters = [friend]

    ld_don_before = me.leader.attached_dons
    for prim in _do(overlay, "OP13-120", "activate_main"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP13-120"), sickness=False))

    assert me.leader.attached_dons == ld_don_before + 1, \
        "起動メインで自リーダーへレストドンが付与されていない"
    # コスト+2 = cost_minus amount -2 (= effective_cost が +2)
    assert friend.cost_minus_through_opp_turn == -2, \
        f"自キャラのコスト修正が +2 になっていない: {friend.cost_minus_through_opp_turn}"
    assert friend.base_cost == friend.card.cost + 2, \
        "実効コストが元コスト+2 になっていない"


def test_op13_120_sabo_cost_target_human_pick():
    """人間 + 自キャラ複数 → cost+2 の対象選択 modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_NAMI), sickness=False)
    me.characters = [a, b]

    # cost_minus (= 2 番目の do) を発火 → target_pick modal
    cost_prim = _do(overlay, "OP13-120", "activate_main")[1]
    assert "cost_minus" in cost_prim, "2 番目の do が cost_minus でない"
    execute_effect(cost_prim, st, me, opp,
                   InPlay.of(repo.get("OP13-120"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert b.cost_minus_through_opp_turn == -2, \
        "人間が選んだキャラのコストが +2 されていない"


# --------------------------------------------------------------------------- #
#  OP14-002 ウルージ (CHARACTER 赤 cost3):
#    【アタック時】このキャラのパワーが5000以上の場合、 カード1枚を引き、 相手の元々のパワー
#    3000以下のキャラ1枚までを、 KOする。
# --------------------------------------------------------------------------- #
def test_op14_002_urouge_on_attack_draw_and_ko_ai():
    """【アタック時】1ドロー + 相手の元々パワー3000以下のキャラ1体をKO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 6
    me.hand = []
    victim = InPlay.of(repo.get(_NAMI), sickness=False)  # truly 2000 ≤ 3000
    opp.characters = [victim]

    # 条件 (self_power_ge 5000) を pump したアタッカーで確認
    attacker = InPlay.of(repo.get("OP14-002"), sickness=False)
    attacker.attached_dons = 3  # 2000 + 3000 = 5000
    assert eval_condition({"self_power_ge": 5000}, st, me, attacker) is True, \
        "前提: パワー5000以上の条件が成立していない"

    deck_before = len(me.deck)
    hand_before = len(me.hand)
    for prim in _do(overlay, "OP14-002", "on_attack"):
        execute_effect(prim, st, me, opp, attacker)

    assert len(me.hand) == hand_before + 1, "1ドローされていない"
    assert len(me.deck) == deck_before - 1, "デッキが1枚減っていない"
    assert victim not in opp.characters, "元々パワー3000以下のキャラがKOされていない"


def test_op14_002_urouge_ko_human_pick():
    """人間 + KO 対象複数 → target_pick modal が立ち resolve で 1 体 KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 6
    a = InPlay.of(repo.get(_NAMI), sickness=False)   # truly 2000
    b = InPlay.of(repo.get(_NAMI), sickness=False)   # truly 2000
    opp.characters = [a, b]

    ko_prim = _do(overlay, "OP14-002", "on_attack")[1]  # 2 番目が ko
    assert "ko" in ko_prim, "2 番目の do が ko でない"
    execute_effect(ko_prim, st, me, opp,
                   InPlay.of(repo.get("OP14-002"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"KO候補が2体でない: {len(cands)}"
    resolve_pending_choice(st, [0])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert len(opp.characters) == 1, "KO で相手キャラが1体に減っていない"


# --------------------------------------------------------------------------- #
#  OP14-005 キラー (CHARACTER 赤 cost1):
#    【起動メイン】【ターン1回】自分のリーダーかキャラ1枚にレストのドン!!1枚までを、付与する。
# --------------------------------------------------------------------------- #
def test_op14_005_killer_activate_main_attach_rested_don_ai():
    """【起動メイン】自リーダー(既定)にレストドン1枚を付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2

    ld_before = me.leader.attached_dons
    rested_before = me.don_rested
    for prim in _do(overlay, "OP14-005", "activate_main"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-005"), sickness=False))

    assert me.leader.attached_dons == ld_before + 1, \
        "起動メインで自リーダーへレストドンが付与されていない"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"


def test_op14_005_killer_target_human_pick():
    """人間 + 自リーダー/キャラ 複数候補 → target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2
    friend = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [friend]

    execute_effect(_do(overlay, "OP14-005", "activate_main")[0], st, me, opp,
                   InPlay.of(repo.get("OP14-005"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    resolve_pending_choice(st, [friend_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert friend.attached_dons == 1, "人間が選んだキャラにレストドンが付与されていない"


# --------------------------------------------------------------------------- #
#  OP14-006 シャチ＆ペンギン (CHARACTER 赤 cost2):
#    【アタック時】このキャラのパワーが5000以上の場合、 相手のキャラ1枚までを、
#    このターン中、 パワー-2000。
# --------------------------------------------------------------------------- #
def test_op14_006_shachi_penguin_attack_debuff_ai():
    """【アタック時】相手キャラ1体を このターン中 パワー-2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # power 4000
    opp.characters = [victim]

    power_before = victim.power
    for prim in _do(overlay, "OP14-006", "on_attack"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-006"), sickness=False))

    assert victim.power == power_before - 2000, \
        f"相手キャラ -2000 が反映されていない: {victim.power} (before {power_before})"


def test_op14_006_shachi_penguin_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal が立ち resolve で 1 体 -2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_NAMI), sickness=False)
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP14-006", "on_attack")[0], st, me, opp,
                   InPlay.of(repo.get("OP14-006"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    b_power_before = b.power
    cands = st.pending_choice.get("candidates", [])
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert b.power == b_power_before - 2000, "人間が選んだキャラに -2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP14-009 トラファルガー・ロー (CHARACTER 赤 cost9):
#    【速攻】【相手のアタック時】【ターン1回】自分の手札2枚を捨てることができる：
#    自分のリーダーとキャラ1枚を選ぶ。 選んだカードそれぞれの元々のパワーを、
#    このバトル中、 入れ替える。
# --------------------------------------------------------------------------- #
def test_op14_009_law_swap_base_power_effect():
    """swap: 自リーダーとキャラの元々パワーを入れ替える (effect 本体を直接検証)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # leader OP01-001 = power 5000
    me, opp = st.players[0], st.players[1]
    chara = InPlay.of(repo.get(_NAMI), sickness=False)  # power 2000
    me.characters = [chara]

    ld_base = me.leader.card.power
    ch_base = chara.card.power
    execute_effect({"swap_base_power_self_leader_chara": True}, st, me, opp,
                   InPlay.of(repo.get("OP14-009"), sickness=False))

    assert me.leader.turn_base_power_override == ch_base, \
        "リーダーの元々パワーがキャラ側に入れ替わっていない"
    assert chara.turn_base_power_override == ld_base, \
        "キャラの元々パワーがリーダー側に入れ替わっていない"


def test_op14_009_law_opp_attack_optional_cost_ai_no_crash():
    """【相手のアタック時】optional_cost_then (手札2捨て→swap) を AI 文脈で発火し crash しない。
    手札2枚 + キャラ在場 = 支払可能 → swap 発火。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER), repo.get(_FILLER)]
    chara = InPlay.of(repo.get(_NAMI), sickness=False)
    me.characters = [chara]

    hand_before = len(me.hand)
    for prim in _do(overlay, "OP14-009", "opp_attack"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-009"), sickness=False))

    # cost (手札2捨て) が払われ、 swap が発火 (元々パワー override が入る)
    assert len(me.hand) == hand_before - 2, "任意コストの手札2捨てが実行されていない"
    assert me.leader.turn_base_power_override is not None, \
        "コスト支払い後に swap 効果が発火していない"


# --------------------------------------------------------------------------- #
#  OP14-011 バルトロメオ (CHARACTER 赤 cost2):
#    【ドン!!×2】このキャラは【ブロッカー】を得る。
# --------------------------------------------------------------------------- #
def test_op14_011_bartolomeo_gain_blocker_ai():
    """【ドン!!×2】自身が【ブロッカー】を得る (on_attached_don n=2)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    barto = InPlay.of(repo.get("OP14-011"), sickness=False)
    me.characters = [barto]

    assert barto.is_blocker_now is False, "前提: 発動前は【ブロッカー】でない"
    entry = _entries(overlay, "OP14-011", "on_attached_don")[0]
    assert entry.get("n") == 2, "ドンゲート n=2 が overlay に無い"
    for prim in entry["do"]:
        execute_effect(prim, st, me, opp, barto)

    assert barto.is_blocker_now is True, "ドン2付与で【ブロッカー】を得ていない"


# --------------------------------------------------------------------------- #
#  OP14-012 ベポ (CHARACTER 赤 cost2):
#    【アタック時】このキャラのパワーが5000以上の場合、 自分のリーダーかキャラ1枚に
#    レストのドン!!2枚までを、付与する。
# --------------------------------------------------------------------------- #
def test_op14_012_bepo_attack_attach_rested_don_ai():
    """【アタック時】自リーダー(既定)にレストドン2枚を付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 3

    ld_before = me.leader.attached_dons
    rested_before = me.don_rested
    for prim in _do(overlay, "OP14-012", "on_attack"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-012"), sickness=False))

    assert me.leader.attached_dons == ld_before + 2, \
        "アタック時に自リーダーへレストドン2枚が付与されていない"
    assert me.don_rested == rested_before - 2, "レストドンが2枚消費されるべき"


def test_op14_012_bepo_target_human_pick():
    """人間 + 自リーダー/キャラ 複数候補 → target_pick modal が立ち resolve で キャラに 2 付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 3
    friend = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [friend]

    execute_effect(_do(overlay, "OP14-012", "on_attack")[0], st, me, opp,
                   InPlay.of(repo.get("OP14-012"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    resolve_pending_choice(st, [friend_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert friend.attached_dons == 2, "人間が選んだキャラにレストドン2枚が付与されていない"


# --------------------------------------------------------------------------- #
#  OP14-015 ロロノア・ゾロ (CHARACTER 赤 cost7):
#    【速攻】【アタック時】相手のキャラ1枚までを、 このターン中、 パワー-1000。
# --------------------------------------------------------------------------- #
def test_op14_015_zoro_attack_debuff_ai():
    """【アタック時】相手キャラ1体を このターン中 パワー-1000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # power 4000
    opp.characters = [victim]

    power_before = victim.power
    for prim in _do(overlay, "OP14-015", "on_attack"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-015"), sickness=False))

    assert victim.power == power_before - 1000, \
        f"相手キャラ -1000 が反映されていない: {victim.power} (before {power_before})"


def test_op14_015_zoro_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal が立ち resolve で 1 体 -1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_NAMI), sickness=False)
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP14-015", "on_attack")[0], st, me, opp,
                   InPlay.of(repo.get("OP14-015"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    b_power_before = b.power
    cands = st.pending_choice.get("candidates", [])
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert b.power == b_power_before - 1000, "人間が選んだキャラに -1000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP14-016 Ｘ・ドレーク (CHARACTER 赤 cost5):
#    【相手のターン中】【ターン1回】自分の特徴《超新星》を持つキャラが相手の効果で場を離れる場合、
#    代わりに自分のリーダーを、 このターン中、 パワー-2000できる。 (replace_leave)
#    【ドン!!×1】【アタック時】相手のキャラ1枚までを、 このターン中、 パワー-2000。
# --------------------------------------------------------------------------- #
def test_op14_016_drake_attack_debuff_ai():
    """【ドン!!×1】【アタック時】相手キャラ1体を このターン中 パワー-2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # power 4000
    opp.characters = [victim]

    on_attack = _entries(overlay, "OP14-016", "on_attack")[0]
    assert on_attack.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    power_before = victim.power
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-016"), sickness=False))

    assert victim.power == power_before - 2000, \
        f"相手キャラ -2000 が反映されていない: {victim.power} (before {power_before})"


def test_op14_016_drake_replace_leave_entry_structure():
    """replace_leave (超新星キャラの相手効果離脱を リーダー-2000 で代替) の overlay 構造検証。"""
    overlay = _overlay()
    rep = _entries(overlay, "OP14-016", "replace_leave")[0]
    cond = rep.get("if", {})
    assert cond.get("opp_turn") is True, "replace_leave の opp_turn 条件が無い"
    assert "超新星" in cond.get("victim_feature_in", []), \
        "replace_leave の victim_feature_in に 超新星 が無い"
    assert cond.get("by_opp_effect") is True, "replace_leave の by_opp_effect 条件が無い"
    # cost に once_per_turn + 自リーダー -2000 の power_pump
    cost = rep.get("cost", [])
    assert any(c.get("once_per_turn") for c in cost if isinstance(c, dict)), \
        "cost に once_per_turn が無い"
    pumps = [c["power_pump"] for c in cost if isinstance(c, dict) and "power_pump" in c]
    assert pumps and pumps[0].get("target") == "self_leader" and pumps[0].get("amount") == -2000, \
        "cost に 自リーダー -2000 の power_pump が無い"
