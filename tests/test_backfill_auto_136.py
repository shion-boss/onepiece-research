# -*- coding: utf-8 -*-
"""OP14 弾 効果 回帰テスト バックフィル (自動生成 wave 136):
OP14-065 / OP14-067 / OP14-070 / OP14-071 / OP14-072 / OP14-076 /
OP14-077 / OP14-078 / OP14-081 / OP14-086 の 10 枚。

目的 (= test_backfill_auto_001〜135.py と同一方針):
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
    evaluate_static_effects,
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
    trigger_on_self_rested,
)

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


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。
    デッキは効果の薄いカード (OP01-016 ナミ) で埋める。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("OP01-016")] * 30
    p1.deck = [repo.get("OP01-016")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果の do 配列を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        # ⚠ 2026-08-05: コロン後の条件を conditional / optional_cost_then の中へ移したため、
        #   目的の primitive が入れ子になっている。 平坦化して探す。
        def _flat(arr):
            out = []
            for _p in arr or []:
                if not isinstance(_p, dict):
                    continue
                if "conditional" in _p:
                    out += _flat((_p["conditional"] or {}).get("do"))
                elif "optional_cost_then" in _p:
                    out += _flat((_p["optional_cost_then"] or {}).get("effect"))
                else:
                    out.append(_p)
            return out
        for e in matches:
            if any(needle in prim for prim in _flat(e["do"])):
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
def test_all_op14_wave136_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP14-065", "OP14-067", "OP14-070", "OP14-071", "OP14-072",
           "OP14-076", "OP14-077", "OP14-078", "OP14-081", "OP14-086"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP14-065 セニョール・ピンク (CHARACTER 紫 cost4):
#    【KO時】相手は自身の場のドン‼1枚をドン‼デッキに戻す。 (return_opp_don 1)
# --------------------------------------------------------------------------- #
def test_op14_065_on_ko_return_opp_don_ai():
    """【KO時】相手の場のドン1枚がドンデッキに戻る (active 優先)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-060", overlay)  # ドフラミンゴ (ドンキホーテ海賊団)
    me, opp = st.players[0], st.players[1]
    opp.don_active = 3
    opp.don_remaining_in_deck = 5

    do, _ = _do(overlay, "OP14-065", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-065"), sickness=False))
    assert opp.don_active == 2, \
        f"相手のアクティブドンが1枚戻っていない: {opp.don_active}"
    assert opp.don_remaining_in_deck == 6, \
        f"戻したドンがドンデッキに加わっていない: {opp.don_remaining_in_deck}"


# --------------------------------------------------------------------------- #
#  OP14-067 デリンジャー (CHARACTER 紫 cost1):
#    【KO時】ドン‼デッキからドン‼1枚までをレストで追加し、 デッキ上5枚を見て
#            《ドンキホーテ海賊団》1枚までを手札に加え、 残りをデッキ下に置く。
# --------------------------------------------------------------------------- #
def test_op14_067_on_ko_add_rested_don_and_search_ai():
    """【KO時】レストドン+1 + デッキ上5枚から《ドンキホーテ海賊団》を手札 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-060", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_remaining_in_deck = 10
    sugar = repo.get("EB03-005")  # シュガー ドンキホーテ海賊団
    me.deck = [sugar] + [repo.get("OP01-016")] * 20
    me.hand = []

    rested_before = me.don_rested
    do, _ = _do(overlay, "OP14-067", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-067"), sickness=False))
    _drain(st, [0])
    assert me.don_rested == rested_before + 1, \
        f"KO時のレストドン+1が反映されていない: {me.don_rested}"
    assert any(c.card_id == "EB03-005" for c in me.hand), \
        "デッキ上5枚から《ドンキホーテ海賊団》キャラが手札に加わっていない"


def test_op14_067_on_ko_search_human_pick():
    """人間 + デッキ上5枚に《ドンキホーテ海賊団》→ search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-060", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_remaining_in_deck = 10
    sugar = repo.get("EB03-005")
    me.deck = [sugar, repo.get("OP01-016"), sugar] + [repo.get("OP01-016")] * 15
    me.hand = []

    do, _ = _do(overlay, "OP14-067", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-067"), sickness=False))
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (シュガー) を選択
    _drain(st, [])
    assert any(c.card_id == "EB03-005" for c in me.hand), \
        "人間が選んだ《ドンキホーテ海賊団》キャラが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP14-070 バッファロー (CHARACTER 紫 cost2 ブロッカー):
#    このキャラが相手のキャラの効果でレストになった時、 自分の場のドン‼1枚を
#    ドン‼デッキに戻してもよい。 そうした場合、 このキャラをアクティブにする。
# --------------------------------------------------------------------------- #
def test_op14_070_on_self_rested_untap_ai():
    """on_self_rested: レストされた自身がアクティブに戻る (do = untap_chara self)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-060", overlay)
    me, opp = st.players[0], st.players[1]
    buffalo = InPlay.of(repo.get("OP14-070"), sickness=False)
    buffalo.rested = True
    me.characters = [buffalo]
    me.don_active = 2

    trigger_on_self_rested(st, me, opp, buffalo, overlay)
    assert buffalo.rested is False, \
        "on_self_rested の untap_chara で自身がアクティブに戻っていない"


def test_op14_070_cost_return_self_don_to_deck():
    """コスト『自分の場のドン‼1枚をドン‼デッキに戻す』が active ドンを返却する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-060", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 2
    me.don_remaining_in_deck = 5

    _, eff = _do(overlay, "OP14-070", "on_self_rested")
    cost = eff.get("cost", {})
    assert cost.get("return_self_don_to_deck") == 1, \
        "overlay の コスト return_self_don_to_deck=1 が無い"
    execute_effect({"return_self_don_to_deck": 1}, st, me, opp, None)
    assert me.don_active == 1, f"コストでアクティブドンが1枚返却されていない: {me.don_active}"
    assert me.don_remaining_in_deck == 6, \
        f"返却したドンがドンデッキに加わっていない: {me.don_remaining_in_deck}"


# --------------------------------------------------------------------------- #
#  OP14-071 ピーカ (CHARACTER 紫 cost5):
#    【自分のターン終了時】自リーダーが《ドンキホーテ海賊団》なら
#    ドン‼デッキからドン‼1枚までをアクティブで追加する。
# --------------------------------------------------------------------------- #
def test_op14_071_end_of_turn_add_don_ai():
    """【自ターン終了時】ドンキホーテ海賊団リーダーで アクティブドン+1 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-060", overlay)  # ドンキホーテ海賊団 leader
    me, opp = st.players[0], st.players[1]
    me.don_remaining_in_deck = 10
    assert eval_condition({"leader_feature": "ドンキホーテ海賊団"}, st, me) is True, \
        "ドンキホーテ海賊団リーダーで leader_feature 条件が成立していない"

    don_before = me.don_active
    do, _ = _do(overlay, "OP14-071", "end_of_turn")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-071"), sickness=False))
    assert me.don_active == don_before + 1, \
        f"ターン終了時のアクティブドン+1が反映されていない: {me.don_active}"


def test_op14_071_condition_false_for_non_doflamingo():
    """非《ドンキホーテ海賊団》リーダーでは leader_feature 条件が不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ (非ドンキホーテ)
    me = st.players[0]
    assert eval_condition({"leader_feature": "ドンキホーテ海賊団"}, st, me) is False, \
        "非ドンキホーテ海賊団リーダーで leader_feature 条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP14-072 ベビー５ (CHARACTER 紫 cost4):
#    【登場時】ドン‼デッキからドン‼1枚までをアクティブで追加する。
#    【KO時】ドン‼-1：自分のデッキの上から1枚までを、 ライフの上に加える。
# --------------------------------------------------------------------------- #
def test_op14_072_on_play_add_don_ai():
    """【登場時】アクティブドン+1 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-060", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_remaining_in_deck = 10

    don_before = me.don_active
    do, _ = _do(overlay, "OP14-072", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-072"), sickness=True))
    assert me.don_active == don_before + 1, \
        f"登場時のアクティブドン+1が反映されていない: {me.don_active}"


def test_op14_072_on_ko_put_top_to_life_ai():
    """【KO時】(ドン-1) デッキ上1枚をライフの上に加える (do = put_top_to_life 1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-060", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP01-016")] * 10
    me.life = [repo.get("OP01-016")] * 2

    life_before = len(me.life)
    deck_before = len(me.deck)
    do, _ = _do(overlay, "OP14-072", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-072"), sickness=False))
    assert len(me.life) == life_before + 1, \
        f"KO時にデッキ上1枚がライフへ加わっていない: {len(me.life)}"
    assert len(me.deck) == deck_before - 1, \
        f"ライフに加えた分デッキが1枚減っていない: {len(me.deck)}"


# --------------------------------------------------------------------------- #
#  OP14-076 海原白波 (EVENT 紫 cost1):
#    【メイン】(自ドン2レスト) 自リーダーが《ドンキホーテ海賊団》なら
#             ドン‼デッキからドン‼1枚までをレストで追加する。
#    【カウンター】自分のリーダーを、 このバトル中、 パワー+3000。
# --------------------------------------------------------------------------- #
def test_op14_076_main_add_rested_don_ai():
    """【メイン】ドンキホーテ海賊団リーダーで レストドン+1 (do = add_rested_don 1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-060", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_remaining_in_deck = 10
    do, eff = _do(overlay, "OP14-076", "main")
    assert _cond_of(eff).get("leader_feature") == "ドンキホーテ海賊団", \
        "overlay の leader_feature ゲートが無い"

    rested_before = me.don_rested
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-076"), sickness=True))
    assert me.don_rested == rested_before + 1, \
        f"メインのレストドン+1が反映されていない: {me.don_rested}"


def test_op14_076_counter_pump_leader_ai():
    """【カウンター】自リーダー このバトル中 +3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-060", overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    do, _ = _do(overlay, "OP14-076", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert me.leader.power == power_before + 3000, \
        f"カウンター +3000 が自リーダーに反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  OP14-077 五色糸 (EVENT 紫 cost2):
#    【カウンター】自分のリーダーかキャラ1枚まで このバトル中 +4000。
#    その後、 相手のパワー6000以上のキャラがいる場合、
#    ドン‼デッキからドン‼1枚までをレストで追加する。
# --------------------------------------------------------------------------- #
def test_op14_077_counter_pump_ai():
    """【カウンター】自リーダー(既定 = leader のみ)を +4000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-060", overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    do, _ = _do(overlay, "OP14-077", "counter", needle="power_pump")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert me.leader.power == power_before + 4000, \
        f"カウンター +4000 が自リーダーに反映されていない: {me.leader.power}"


def test_op14_077_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +4000 の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-060", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [friend]

    do, _ = _do(overlay, "OP14-077", "counter", needle="power_pump")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert friend.power == friend_before + 4000, \
        "人間が選んだキャラに +4000 が反映されていない"


def test_op14_077_counter_add_don_when_opp_big_chara_ai():
    """【カウンター(2)】相手にパワー6000以上のキャラがいる場合 レストドン+1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-060", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_remaining_in_deck = 10
    big = InPlay.of(repo.get("PRB02-011"), sickness=False)  # power 6000
    opp.characters = [big]
    assert eval_condition({"exists_opp_chara_power_ge": 6000}, st, me) is True, \
        "相手にパワー6000以上のキャラがいる条件が成立していない"

    rested_before = me.don_rested
    do, eff = _do(overlay, "OP14-077", "counter", needle="add_rested_don")
    assert _cond_of(eff).get("exists_opp_chara_power_ge") == 6000, \
        "overlay の exists_opp_chara_power_ge=6000 ゲートが無い"
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert me.don_rested == rested_before + 1, \
        f"相手大型キャラ存在時のレストドン+1が反映されていない: {me.don_rested}"


# --------------------------------------------------------------------------- #
#  OP14-078 弾糸 (EVENT 紫 cost2):
#    【カウンター】ドン‼-1：自リーダーが《ドンキホーテ海賊団》なら
#    自分のリーダーかキャラ1枚まで、 このバトル中 +2000。 (その後 このターン中 +2000)
# --------------------------------------------------------------------------- #
def test_op14_078_counter_pump_ai():
    """【カウンター】自リーダー(既定)を +2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-060", overlay)
    me, opp = st.players[0], st.players[1]
    do, eff = _do(overlay, "OP14-078", "counter")
    assert _cond_of(eff).get("leader_feature") == "ドンキホーテ海賊団", \
        "overlay の leader_feature ゲートが無い"

    power_before = me.leader.power
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert me.leader.power == power_before + 2000, \
        f"カウンター +2000 が自リーダーに反映されていない: {me.leader.power}"


def test_op14_078_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +2000 の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-060", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [friend]

    do, _ = _do(overlay, "OP14-078", "counter")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert friend.power == friend_before + 2000, \
        "人間が選んだキャラに +2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP14-081 スパイダーマウス (CHARACTER 黒 cost1):
#    【登場時】自分のデッキの上から3枚をトラッシュに置く。
#    【KO時】相手の元々のコスト1のキャラ1枚までを、 KOする。
# --------------------------------------------------------------------------- #
def test_op14_081_on_play_mill_top3_ai():
    """【登場時】デッキ上3枚をトラッシュ (mill_self_top 3)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP01-016")] * 10
    me.trash = []

    deck_before = len(me.deck)
    do, _ = _do(overlay, "OP14-081", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-081"), sickness=True))
    assert len(me.trash) == 3, f"登場時にデッキ上3枚がトラッシュされていない: {len(me.trash)}"
    assert len(me.deck) == deck_before - 3, \
        f"トラッシュした分デッキが3枚減っていない: {len(me.deck)}"


def test_op14_081_on_ko_ko_cost1_ai():
    """【KO時】相手の元々コスト1キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [victim]

    do, _ = _do(overlay, "OP14-081", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-081"), sickness=False))
    _drain(st, [0])
    assert victim not in opp.characters, \
        "KO時に相手の元々コスト1キャラが KO されていない"


def test_op14_081_on_ko_ignores_non_cost1():
    """相手キャラの元々コストが1でなければ KO 対象にならない (= 場に残る)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    opp.characters = [victim]

    do, _ = _do(overlay, "OP14-081", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-081"), sickness=False))
    _drain(st, [0])
    assert victim in opp.characters, \
        "元々コストが1でない相手キャラが KO されてはいけない"


def test_op14_081_on_ko_human_pick():
    """人間 + 相手の元々コスト1キャラ 複数 → target_pick modal が立ち resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    b = InPlay.of(repo.get("EB04-002"), sickness=False)  # cost1
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP14-081", "on_ko")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP14-081"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP14-086 ミス・ダブルフィンガー(ザラ) (CHARACTER 黒 cost5 power6000):
#    自分のトラッシュが7枚以上ある場合、 このキャラのパワー+1000し、
#    自分の《B・W》を含む特徴を持つキャラすべてを、 コスト+2。 (常在 static)
# --------------------------------------------------------------------------- #
def test_op14_086_static_when_trash_ge7():
    """トラッシュ7枚以上: 自身 +1000 + 自《B・W》キャラすべてコスト+2 (evaluate_static_effects)。"""
    repo = _repo()
    overlay = _overlay()
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    zara_def = repo.get("OP14-086")  # power 6000, cost 5, B・W
    zara = InPlay.of(zara_def, sickness=False)
    other_bw_def = repo.get("EB03-047")  # ミス・バレンタイン B・W cost2
    other_bw = InPlay.of(other_bw_def, sickness=False)
    p0.characters = [zara, other_bw]
    p0.trash = [repo.get("OP01-016")] * 7  # トラッシュ7枚 (= 条件成立)
    st = GameState(players=[p0, p1], phase=Phase.MAIN, effects_overlay=overlay)
    st.turn_player_idx = 0
    st.human_player_idx = None

    evaluate_static_effects(st, overlay)
    assert zara.power == zara_def.power + 1000, \
        f"トラッシュ7枚で自身 +1000 が反映されていない: {zara.power} (base {zara_def.power})"
    assert zara.base_cost_override == zara_def.cost + 2, \
        f"自身の《B・W》コスト+2 が反映されていない: {zara.base_cost_override}"
    assert other_bw.base_cost_override == other_bw_def.cost + 2, \
        f"別の《B・W》キャラのコスト+2 が反映されていない: {other_bw.base_cost_override}"


def test_op14_086_static_no_effect_when_trash_lt7():
    """トラッシュ7枚未満: 効果不成立 → power +0 / コスト変更なし。"""
    repo = _repo()
    overlay = _overlay()
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    zara_def = repo.get("OP14-086")
    zara = InPlay.of(zara_def, sickness=False)
    p0.characters = [zara]
    p0.trash = [repo.get("OP01-016")] * 6  # 6 枚 (< 7 = 条件不成立)
    st = GameState(players=[p0, p1], phase=Phase.MAIN, effects_overlay=overlay)
    st.turn_player_idx = 0
    st.human_player_idx = None

    evaluate_static_effects(st, overlay)
    assert zara.power == zara_def.power, \
        f"トラッシュ7枚未満で power pump が乗ってはいけない: {zara.power}"
    assert zara.base_cost_override is None, \
        f"トラッシュ7枚未満でコスト変更が起きてはいけない: {zara.base_cost_override}"
