# -*- coding: utf-8 -*-
"""OP15 弾 効果 回帰テスト バックフィル (自動生成 wave 145):
OP15-095 / OP15-096 / OP15-097 / OP15-099 / OP15-102 /
OP15-103 / OP15-104 / OP15-105 / OP15-106 / OP15-109 の 10 枚。

目的 (= test_backfill_auto_001〜144.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 を 持つカードは 人間 actor で pending_choice が
      正しい kind + 候補で立ち、 resolve_pending_choice で解決できる (= 人間が選べる)
  (3) 同じ効果を AI 文脈 (human_player_idx=None) で回しても crash せず自動解決する
      (= AI が選べる)
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.effects import (
    eval_condition,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
    try_replace_ko,
)
from engine.deck import CardRepository
from engine.game import _compute_in_hand_cost_minus

ROOT = Path(__file__).resolve().parent.parent


def _cond_of(eff: dict) -> dict:
    """効果の発動条件を取り出す (top-level `if` / `conditional` の両対応)。

    ⚠ 2026-08-05: 公式は 「〜できる：<条件>の場合、<効果>」 のコロン後の条件を **効果のみ** の
    gate とする (cardqa_op_02 / cardqa_st_04)。 top-level `if` に置くと **任意コストの支払いごと
    消える** ので、 overlay ではこの形の条件を `conditional` の中に移した。
    条件そのものは変わっていないので、 テストはどちらの位置でも読めればよい。
    """
    if isinstance(eff.get("if"), dict):
        return eff["if"]
    for _prim in eff.get("do") or []:
        if isinstance(_prim, dict) and "conditional" in _prim:
            return (_prim.get("conditional") or {}).get("if") or {}
    return {}


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001",
           turn_player=0):
    """P0 = テスト対象デッキ、 P1 = ダミー。 MAIN / turn_number=3。
    デッキは効果の薄いカード (OP01-016 ナミ) で埋める。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("OP01-016")] * 30
    p1.deck = [repo.get("OP01-016")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn_player
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果の (do 配列, eff) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e["do"], e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]["do"], matches[0]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op15_wave145_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP15-095", "OP15-096", "OP15-097", "OP15-099", "OP15-102",
           "OP15-103", "OP15-104", "OP15-105", "OP15-106", "OP15-109"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP15-095 ゴムゴムの暴風雨 (EVENT 黒 cost1):
#    【メイン】ドン1レスト：自トラッシュ15枚以上で、自《麦わらの一味》リーダー/キャラ1枚まで
#      このターン中 パワー+3000。
#    【カウンター】自トラッシュ15枚以上で、自リーダー/キャラ1枚まで このバトル中 パワー+4000。
# --------------------------------------------------------------------------- #
def test_op15_095_main_pump_strawhat_ai():
    """【メイン】自《麦わらの一味》リーダーに +3000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ (麦わらの一味 leader)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP01-016")] * 15  # 条件 (トラッシュ15以上) 成立
    power_before = me.leader.power
    do, _ = _do(overlay, "OP15-095", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert me.leader.power == power_before + 3000, \
        f"《麦わらの一味》リーダーに +3000 が反映されていない: {me.leader.power}"


def test_op15_095_main_condition_trash_ge_15():
    """メイン条件: 自トラッシュ15枚以上で成立、 14枚では不成立。"""
    repo = _repo()
    overlay = _overlay()
    _, eff = _do(overlay, "OP15-095", "main")
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    me.trash = [repo.get("OP01-016")] * 14
    assert eval_condition(_cond_of(eff), st, me) is False, \
        "トラッシュ14枚でメイン条件が成立してはいけない"
    me.trash = [repo.get("OP01-016")] * 15
    assert eval_condition(_cond_of(eff), st, me) is True, \
        "トラッシュ15枚でメイン条件が成立していない"


def test_op15_095_counter_pump_self_inplay_ai():
    """【カウンター】自リーダー1枚に +4000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    power_before = me.leader.power
    do, _ = _do(overlay, "OP15-095", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert me.leader.power == power_before + 4000, \
        f"カウンターの +4000 が自リーダーに反映されていない: {me.leader.power}"


def test_op15_095_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → target_pick modal → 選んだ 1 枚に +4000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP01-016"), sickness=False)
    me.characters = [friend]
    do, _ = _do(overlay, "OP15-095", "counter")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    _drain(st, [friend_idx])
    assert friend.power == friend_before + 4000, \
        "人間が選んだキャラに +4000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP15-096 飛燕ボンナバン (EVENT 黒):
#    【メイン】ドン1レスト：自リーダーが《麦わらの一味》なら、自デッキ上5枚をトラッシュに置く。
#    【カウンター】手札1枚を捨てることができる：自リーダー/キャラ1枚まで このバトル中 +3000。
# --------------------------------------------------------------------------- #
def test_op15_096_main_mill_top_5_ai():
    """【メイン】自デッキ上5枚をトラッシュへ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # 麦わらの一味 leader
    me, opp = st.players[0], st.players[1]
    deck_before = len(me.deck)
    trash_before = len(me.trash)
    do, _ = _do(overlay, "OP15-096", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert len(me.deck) == deck_before - 5, \
        f"デッキ上5枚がトラッシュに置かれていない: deck={len(me.deck)}"
    assert len(me.trash) == trash_before + 5, \
        f"トラッシュが5枚増えていない: trash={len(me.trash)}"


def test_op15_096_main_condition_leader_strawhat():
    """メイン条件: 《麦わらの一味》リーダーで成立、 非該当で不成立。"""
    repo = _repo()
    overlay = _overlay()
    _, eff = _do(overlay, "OP15-096", "main")
    st_ok = _state(repo, "OP01-001", overlay)   # ゾロ (麦わらの一味)
    st_ng = _state(repo, "OP15-039", overlay)   # レベッカ (ドレスローザ)
    assert eval_condition(_cond_of(eff), st_ok, st_ok.players[0]) is True, \
        "《麦わらの一味》リーダーでメイン条件が成立していない"
    assert eval_condition(_cond_of(eff), st_ng, st_ng.players[0]) is False, \
        "非《麦わらの一味》リーダーで条件が成立してはいけない"


def test_op15_096_counter_optional_discard_pump_ai():
    """【カウンター】手札1枚を捨てて → 自リーダーに +3000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-016")]  # 捨てるコスト用
    hand_before = len(me.hand)
    power_before = me.leader.power
    do, _ = _do(overlay, "OP15-096", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert me.leader.power == power_before + 3000, \
        f"カウンターの +3000 が自リーダーに反映されていない: {me.leader.power}"
    assert len(me.hand) == hand_before - 1, \
        "任意コストで手札1枚が捨てられていない"


# --------------------------------------------------------------------------- #
#  OP15-097 人として恥ずかしいわ (EVENT 黒 cost1):
#    【メイン】自トラッシュ10枚以上で、相手の元々コスト5以下キャラ1枚まで、
#      次の相手のエンドフェイズ終了時まで、アタックできない。
#    【トリガー】このカードの【メイン】効果を発動する。
# --------------------------------------------------------------------------- #
def test_op15_097_main_set_cannot_attack_ai():
    """【メイン】相手コスト5以下キャラ1枚を アタック不可 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP01-016")] * 10  # 条件成立
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2 (≤5)
    opp.characters = [victim]
    do, _ = _do(overlay, "OP15-097", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim.cannot_attack_through_opp_turn is True, \
        "相手コスト5以下キャラがアタック不可になっていない"


def test_op15_097_main_condition_trash_ge_10():
    """メイン条件: 自トラッシュ10枚以上で成立、 9枚では不成立。"""
    repo = _repo()
    overlay = _overlay()
    _, eff = _do(overlay, "OP15-097", "main")
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    me.trash = [repo.get("OP01-016")] * 9
    assert eval_condition(_cond_of(eff), st, me) is False, \
        "トラッシュ9枚でメイン条件が成立してはいけない"
    me.trash = [repo.get("OP01-016")] * 10
    assert eval_condition(_cond_of(eff), st, me) is True, \
        "トラッシュ10枚でメイン条件が成立していない"


def test_op15_097_main_human_pick():
    """人間 + 相手コスト5以下 複数 → target_pick modal → 選んだ 1 枚のみアタック不可。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP01-016")] * 10
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost1
    opp.characters = [a, b]
    do, _ = _do(overlay, "OP15-097", "main")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b.cannot_attack_through_opp_turn is True, \
        "人間が選んだ相手キャラがアタック不可になっていない"
    assert a.cannot_attack_through_opp_turn is False, \
        "選ばなかったキャラはアタック不可になってはいけない"


def test_op15_097_trigger_fires_main_ai():
    """【トリガー】fire_self_effect で【メイン】効果 (アタック不可) が発動する (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP01-016")] * 10  # メイン条件成立
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 (≤5)
    opp.characters = [victim]
    st.current_source_card_id = "OP15-097"
    do, _ = _do(overlay, "OP15-097", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim.cannot_attack_through_opp_turn is True, \
        "トリガーからメイン効果 (アタック不可) が発動していない"


# --------------------------------------------------------------------------- #
#  OP15-099 ウルージ (CHARACTER 黄 cost6 power7000):
#    【登場時】手札から《超新星》1枚を捨てることができる：このキャラは このターン中【速攻】。
#    【起動メイン】自ライフ上1枚を裏向きにできる：自リーダー/キャラ1枚にレストドン1まで付与。
# --------------------------------------------------------------------------- #
def test_op15_099_on_play_give_rush_ai():
    """【登場時】自身に【速攻】を付与 (AI、 do のみ発火)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    urouge = InPlay.of(repo.get("OP15-099"), sickness=True)
    me.characters = [urouge]
    do, _ = _do(overlay, "OP15-099", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp, urouge)
    _drain(st, [0])
    assert "速攻" in urouge.granted_keywords, \
        f"登場時に【速攻】が付与されていない: {urouge.granted_keywords}"


def test_op15_099_activate_main_flip_life_attach_rested_don_ai():
    """【起動メイン】自ライフ1枚裏向き (コスト) → 自リーダーにレストドン1付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    urouge = InPlay.of(repo.get("OP15-099"), sickness=False)
    me.characters = [urouge]
    me.life = [repo.get("OP01-016")] * 2
    me.face_up_life_count = 2
    me.don_rested = 2  # レストドン供給源
    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    faceup_before = me.face_up_life_count

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP15-099"]
    assert len(opts) == 1, f"OP15-099 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert me.leader.attached_dons == don_before + 1, \
        "自リーダーにレストドンが付与されていない"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"
    assert me.face_up_life_count == faceup_before - 1, \
        "コストで自ライフ1枚が裏向きになっていない"


# --------------------------------------------------------------------------- #
#  OP15-102 ガン・フォール (CHARACTER 黄 cost4 power4000):
#    手札のこのカードは、自パワー7000以上の《空島》キャラがいる場合、コスト-3。
#    【登場時】相手のライフの枚数以下のコストを持つ相手のキャラ1枚まで、レストにする。
# --------------------------------------------------------------------------- #
def test_op15_102_in_hand_cost_minus_with_skyisland_7000():
    """自場に《空島》パワー7000以上のキャラがいると 手札のこのカードは コスト-3。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    me.characters = [InPlay.of(repo.get("OP12-114"), sickness=False)]  # ワイパー 空島 pow7000
    assert _compute_in_hand_cost_minus(st, me, repo.get("OP15-102")) == 3, \
        "《空島》パワー7000以上のキャラがいるのに 手札コスト -3 が計算されていない"


def test_op15_102_in_hand_no_reduction_without_skyisland():
    """条件を満たす《空島》キャラがいなければ コスト軽減は無い。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    me.characters = [InPlay.of(repo.get("OP01-016"), sickness=False)]  # ナミ (非空島)
    assert _compute_in_hand_cost_minus(st, me, repo.get("OP15-102")) == 0, \
        "条件を満たさないのにコスト軽減が発生してはいけない"


def test_op15_102_on_play_rest_opp_cost_le_life_ai():
    """【登場時】相手ライフ枚数以下コストの相手キャラ1枚をレスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get("OP01-016")] * 3  # ライフ3枚 → コスト3以下が対象
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2 (≤3)
    opp.characters = [victim]
    do, _ = _do(overlay, "OP15-102", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-102"), sickness=True))
    _drain(st, [0])
    assert victim.rested is True, \
        "相手ライフ枚数以下コストの相手キャラがレストされていない"


def test_op15_102_on_play_over_life_cost_not_target():
    """相手ライフ枚数を超えるコストの相手キャラは 対象外 → レストされない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get("OP01-016")] * 1  # ライフ1枚 → コスト1以下のみ対象
    big = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2 (>1)
    opp.characters = [big]
    do, _ = _do(overlay, "OP15-102", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-102"), sickness=True))
    _drain(st, [0])
    assert big.rested is False, \
        "ライフ枚数を超えるコストのキャラがレストされてはいけない (対象外)"


def test_op15_102_on_play_rest_human_pick():
    """人間 + 対象の相手キャラ 複数 → target_pick modal → 選んだ 1 枚のみレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get("OP01-016")] * 3
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost1
    opp.characters = [a, b]
    do, _ = _do(overlay, "OP15-102", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP15-102"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b.rested is True, "人間が選んだ相手キャラがレストされていない"
    assert a.rested is False, "選ばなかったキャラはレストされないべき"


# --------------------------------------------------------------------------- #
#  OP15-103 ゲンボウ (CHARACTER 黄 cost3 power4000):
#    【トリガー】カード1枚を引く。その後、自分のライフが2枚以下の場合、このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op15_103_trigger_draw_and_play_self_when_life_le_2_ai():
    """【トリガー】1ドロー → 自ライフ2枚以下なら 自身を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.life = [repo.get("OP01-016")] * 2  # ライフ2枚 (= 条件成立)
    me.trash = [repo.get("OP15-103")]     # トリガーめくれ元 (trash 相当)
    st.current_source_card_id = "OP15-103"
    deck_before = len(me.deck)
    do, _ = _do(overlay, "OP15-103", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert len(me.deck) == deck_before - 1, "トリガーの 1ドローが起きていない"
    assert any(c.card.card_id == "OP15-103" for c in me.characters), \
        "自ライフ2枚以下なのに ゲンボウ が登場していない"


def test_op15_103_trigger_no_play_self_when_life_gt_2():
    """自ライフ3枚 (>2) では 登場しない (ドローのみ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.life = [repo.get("OP01-016")] * 3  # ライフ3枚 (= 条件不成立)
    me.trash = [repo.get("OP15-103")]
    st.current_source_card_id = "OP15-103"
    do, _ = _do(overlay, "OP15-103", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert not any(c.card.card_id == "OP15-103" for c in me.characters), \
        "自ライフ3枚 (>2) なのに ゲンボウ が登場している"


# --------------------------------------------------------------------------- #
#  OP15-104 コニス (CHARACTER 黄 cost1):
#    【登場時】自分のライフの枚数が相手より少ない場合、カード2枚を引き、自分の手札2枚を捨てる。
#    【トリガー】カード2枚を引き、自分の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op15_104_on_play_draw2_discard2_ai():
    """【登場時】2ドロー → 手札2枚を捨てる (AI 自動)。 net 手札 ±0 / デッキ -2 / トラッシュ +2。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    deck_before = len(me.deck)
    trash_before = len(me.trash)
    do, _ = _do(overlay, "OP15-104", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-104"), sickness=True))
    _drain(st, [0])
    assert len(me.deck) == deck_before - 2, f"2ドローが起きていない: deck={len(me.deck)}"
    assert len(me.hand) == 0, f"引いた2枚を捨てて手札±0 のはず: {len(me.hand)}"
    assert len(me.trash) == trash_before + 2, \
        f"捨てた2枚がトラッシュに行っていない: trash={len(me.trash)}"


def test_op15_104_on_play_condition_self_life_lt_opp():
    """登場時条件: 自ライフが相手より少ない場合に成立。"""
    repo = _repo()
    overlay = _overlay()
    _, eff = _do(overlay, "OP15-104", "on_play")
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-016")] * 1
    opp.life = [repo.get("OP01-016")] * 3
    assert eval_condition(_cond_of(eff), st, me) is True, \
        "自ライフ<相手 で条件が成立していない"
    me.life = [repo.get("OP01-016")] * 3
    opp.life = [repo.get("OP01-016")] * 3
    assert eval_condition(_cond_of(eff), st, me) is False, \
        "自ライフ==相手 で条件が成立してはいけない"


def test_op15_104_trigger_draw2_discard1_ai():
    """【トリガー】2ドロー → 手札1枚を捨てる (AI 自動)。 net 手札 +1 / デッキ -2。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    deck_before = len(me.deck)
    trash_before = len(me.trash)
    do, _ = _do(overlay, "OP15-104", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert len(me.deck) == deck_before - 2, f"2ドローが起きていない: deck={len(me.deck)}"
    assert len(me.hand) == 1, f"2引き1捨てで手札 +1 のはず: {len(me.hand)}"
    assert len(me.trash) == trash_before + 1, \
        f"捨てた1枚がトラッシュに行っていない: trash={len(me.trash)}"


# --------------------------------------------------------------------------- #
#  OP15-105 ジュエリー・ボニー (CHARACTER 黄 cost1 power2000):
#    自分の元々のパワー7000以下のキャラが相手の効果で場を離れる場合、代わりに
#      自分のライフの上から1枚を手札に加えることができる。 (replace_leave / 任意)
# --------------------------------------------------------------------------- #
def test_op15_105_replace_leave_life_to_hand_ai():
    """元々P7000以下の自キャラが相手効果で離脱 → 代わりに自ライフ1枚を手札へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    bonney = InPlay.of(repo.get("OP15-105"), sickness=False)
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ power2000 ≤7000
    me.characters = [bonney, victim]
    me.hand = []
    me.life = [repo.get("OP01-016")] * 2
    life_before = len(me.life)

    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "元々P7000以下の自キャラ離脱が置換されていない"
    assert victim in me.characters, "置換成立時 victim は場に残るべき"
    assert len(me.hand) == 1, "置換でライフ1枚が手札に加わっていない"
    assert len(me.life) == life_before - 1, "置換でライフが1枚減っていない"


def test_op15_105_replace_leave_power_over_7000_no_replace():
    """元々パワー7000超の自キャラは 対象外 → 置換されない (False)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    bonney = InPlay.of(repo.get("OP15-105"), sickness=False)
    big = InPlay.of(repo.get("OP15-008"), sickness=False)  # power9000 (> 7000)
    me.characters = [bonney, big]
    me.life = [repo.get("OP01-016")] * 2

    replaced = try_replace_ko(
        st, me, opp, big, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is False, "元々パワー7000超のキャラに置換が成立してはいけない (対象外)"


# --------------------------------------------------------------------------- #
#  OP15-106 タコバルーン (CHARACTER 黄 cost2):
#    【トリガー】カード1枚を引く。その後、自分の手札からコスト2以下の黄の、キャラカードか
#      ステージカード1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op15_106_trigger_draw_and_play_from_hand_ai():
    """【トリガー】1ドロー → 手札のコスト2以下・黄のキャラ1枚を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    target = repo.get("OP10-111")  # モンキー・D・ルフィ 黄 cost1 (≤2)
    me.hand = [target]
    chars_before = len(me.characters)
    do, _ = _do(overlay, "OP15-106", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert any(c.card.card_id == "OP10-111" for c in me.characters), \
        "手札のコスト2以下・黄のキャラが登場していない"
    assert len(me.characters) == chars_before + 1, "キャラが1体増えていない"


def test_op15_106_trigger_human_play_pick():
    """人間 + 手札に対象 複数 → play_from_hand modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    # 2 種の 黄 cost≤2 キャラ を手札に
    me.hand = [repo.get("OP10-111"), repo.get("EB04-056")]  # ルフィ cost1 / パシフィスタ cost1
    do, _ = _do(overlay, "OP15-106", "trigger")
    # まず draw を消化 (対象選択に影響しないよう)
    execute_effect(do[0], st, me, opp, None)
    _drain(st, [0])
    execute_effect(do[1], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert any(c.card.card_id == "OP10-111" for c in me.characters), \
        "人間が選んだ 黄 cost≤2 キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP15-109 ニコ・ロビン (CHARACTER 黄 cost7 power7000):
#    【登場時】自ライフ上1枚を手札に加えることができる：自リーダーが《麦わらの一味》なら、
#      自デッキ上1枚までをライフの上に加える。その後、手札からコスト5以下の《空島》キャラ
#      1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op15_109_on_play_life_and_play_skyisland_ai():
    """【登場時】手札のコスト5以下《空島》キャラを登場させる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # 麦わらの一味 leader
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-016")] * 2
    me.deck = [repo.get("OP01-016")] * 10
    skyisland = repo.get("EB01-054")  # ガン・フォール 空島 cost3 (≤5)
    me.hand = [skyisland]
    chars_before = len(me.characters)
    do, _ = _do(overlay, "OP15-109", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-109"), sickness=True))
    _drain(st, [0])
    assert any(c.card.card_id == "EB01-054" for c in me.characters), \
        "手札のコスト5以下《空島》キャラ (ガン・フォール) が登場していない"
    assert len(me.characters) == chars_before + 1, "キャラが1体増えていない"


def test_op15_109_on_play_human_play_pick():
    """人間 + 手札にコスト5以下《空島》 複数 → play_from_hand modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-016")] * 2
    me.deck = [repo.get("OP01-016")] * 10
    me.hand = [repo.get("EB01-054"), repo.get("OP05-108")]  # ガン・フォール / ノラ (両方 空島 cost≤5)
    do, _ = _do(overlay, "OP15-109", "on_play")
    # life_to_hand (cost) → put_top_to_life → play_from_hand の順に drain して modal を立てる
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-109"), sickness=True))
        if st.pending_choice is not None and \
                "play_from_hand" in st.pending_choice.get("kind", ""):
            break
        _drain(st, [0])
    assert st.pending_choice is not None, "人間文脈で pending_choice が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert any(c.card.card_id in ("EB01-054", "OP05-108") for c in me.characters), \
        "人間が選んだ《空島》キャラが登場していない"
