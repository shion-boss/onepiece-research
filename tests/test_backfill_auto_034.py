# -*- coding: utf-8 -*-
"""OP02 弾 (黒 海軍 / コスト-down 系) 効果 回帰テスト バックフィル (自動生成 wave 034):
OP02-105 / OP02-106 / OP02-110 / OP02-112 / OP02-113 / OP02-114 /
OP02-115 / OP02-117 / OP02-118 / OP02-119 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_001.py と同一方針):
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
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
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


def _get_eff(overlay, cid, when, needle=None):
    for e in overlay.get(cid).effects:
        if e["when"] == when and (needle is None or needle in str(e["do"])):
            return e
    raise KeyError(cid, when, needle)


def _drain(st, sel=None, guard=8):
    """pending_choice を sel (既定 [0]) で解決し続ける (人間チェーン用)。"""
    if sel is None:
        sel = [0]
    g = 0
    while st.pending_choice is not None and g < guard:
        resolve_pending_choice(st, sel)
        g += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op02_wave34_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP02-105", "OP02-106", "OP02-110", "OP02-112", "OP02-113",
           "OP02-114", "OP02-115", "OP02-117", "OP02-118", "OP02-119"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP02-105 たしぎ: 【ドン!!×1】【アタック時】相手のキャラ1枚までを コスト-3
# --------------------------------------------------------------------------- #
def test_op02_105_tashigi_on_attack_cost_down_ai():
    """【アタック時】(ドン×1 ゲート) 相手キャラ1枚を コスト-3 (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    opp.characters = [victim]

    on_attack = _get_eff(overlay, "OP02-105", "on_attack")
    assert on_attack.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-105"), sickness=False))
    assert victim.cost_minus_until_turn_end == 3, \
        f"相手キャラの コスト-3 が反映されていない: {victim.cost_minus_until_turn_end}"


def test_op02_105_tashigi_on_attack_cost_down_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal が立ち resolve で選んだ1体に -3。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [a, b]

    on_attack = _get_eff(overlay, "OP02-105", "on_attack")
    execute_effect(on_attack["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP02-105"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b.cost_minus_until_turn_end == 3, "人間が選んだ相手キャラに -3 が反映されていない"
    assert a.cost_minus_until_turn_end == 0, "選ばなかったキャラのコストは変わらないべき"


# --------------------------------------------------------------------------- #
#  OP02-106 つる: 【登場時】相手のキャラ1枚までを コスト-2
# --------------------------------------------------------------------------- #
def test_op02_106_tsuru_on_play_cost_down_ai():
    """【登場時】相手キャラ1枚を コスト-2 (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    opp.characters = [victim]

    on_play = _get_eff(overlay, "OP02-106", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-106"), sickness=True))
    assert victim.cost_minus_until_turn_end == 2, \
        f"登場時の コスト-2 が反映されていない: {victim.cost_minus_until_turn_end}"
    assert victim.base_cost == 0, \
        f"cost2 → -2 で 実効コスト0 になっていない: {victim.base_cost}"


def test_op02_106_tsuru_on_play_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal が立ち resolve で選んだ1体に -2。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)
    b = InPlay.of(repo.get("OP01-016"), sickness=False)
    opp.characters = [a, b]

    on_play = _get_eff(overlay, "OP02-106", "on_play")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP02-106"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    b_idx = next(i for i, c in enumerate(st.pending_choice["candidates"])
                 if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b.cost_minus_until_turn_end == 2, "人間が選んだ相手キャラに -2 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP02-110 ヒナ: 【ブロッカー】【ブロック時】相手のコスト6以下のキャラ1枚まで
#    → このターン中 アタックできない
# --------------------------------------------------------------------------- #
def test_op02_110_hina_on_block_set_cannot_attack_ai():
    """【ブロック時】相手のコスト6以下キャラ1枚を このターン中 アタック不可 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 <= 6
    opp.characters = [victim]

    on_block = _get_eff(overlay, "OP02-110", "on_block")
    for prim in on_block["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-110"), sickness=False))
    assert victim.cannot_attack_until_turn_end is True, \
        "相手のコスト6以下キャラに アタック不可 が付与されていない"


def test_op02_110_hina_on_block_human_pick():
    """人間 + 相手コスト6以下キャラ複数 → target_pick modal が立ち resolve で アタック不可。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [a, b]

    on_block = _get_eff(overlay, "OP02-110", "on_block")
    execute_effect(on_block["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP02-110"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    b_idx = next(i for i, c in enumerate(st.pending_choice["candidates"])
                 if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b.cannot_attack_until_turn_end is True, \
        "人間が選んだ相手キャラに アタック不可 が付与されていない"
    assert a.cannot_attack_until_turn_end is False, "選ばなかったキャラは影響を受けないべき"


# --------------------------------------------------------------------------- #
#  OP02-112 ベルメール: 【起動メイン】このキャラをレストにできる：
#    相手のキャラ1枚まで コスト-1。 その後、自分のリーダーかキャラ1枚まで +1000。
# --------------------------------------------------------------------------- #
def test_op02_112_bellemere_activate_main_cost_down_and_pump_ai():
    """起動メイン: 自レスト (コスト) → 相手キャラ -1 + 自リーダー/キャラ +1000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    bellemere = InPlay.of(repo.get("OP02-112"), sickness=False)  # power 1000
    me.characters = [bellemere]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    opp.characters = [victim]

    leader_power_before = me.leader.power  # リーダー (= 最高 power) が pump 対象
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP02-112"]
    assert len(opts) == 1, f"OP02-112 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert bellemere.rested is True, "起動メインコストで ベルメール がレストされるべき"
    assert victim.cost_minus_until_turn_end == 1, \
        f"相手キャラの コスト-1 が反映されていない: {victim.cost_minus_until_turn_end}"
    # power_pump target=self_inplay は AI が最高 power (= リーダー) を選ぶ
    assert me.leader.power == leader_power_before + 1000, \
        f"その後の 自リーダー/キャラ +1000 が反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  OP02-113 ヘルメッポ: 【アタック時】相手キャラ1枚 コスト-2。 その後 コスト0のキャラが
#    いる場合 このキャラは このバトル中 +2000。 【トリガー】このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op02_113_helmeppo_on_attack_cost_down_and_conditional_pump_ai():
    """コスト-2 + (コスト0キャラ存在時) 自身 +2000。 実効コスト0 の自キャラを用意して条件成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    helmeppo = InPlay.of(repo.get("OP02-113"), sickness=False)  # power 3000
    zero = InPlay.of(repo.get("OP01-016"), sickness=False)
    zero.cost_minus_until_turn_end = 1  # 実効コスト0 = 条件成立
    me.characters = [helmeppo, zero]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    opp.characters = [victim]

    power_before = helmeppo.power
    on_attack = _get_eff(overlay, "OP02-113", "on_attack")
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp, helmeppo)
    assert victim.cost_minus_until_turn_end == 2, \
        f"相手キャラの コスト-2 が反映されていない: {victim.cost_minus_until_turn_end}"
    assert helmeppo.power == power_before + 2000, \
        f"コスト0キャラ存在時の 自身 +2000 が反映されていない: {helmeppo.power} (before {power_before})"


def test_op02_113_helmeppo_conditional_pump_off_without_cost0():
    """コスト0のキャラがいなければ 自身 +2000 は乗らない (条件不成立)。
    victim は cost4 → コスト-2 後も cost2 のまま (= 実効コスト0 キャラ 不在)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    helmeppo = InPlay.of(repo.get("OP02-113"), sickness=False)  # cost3
    me.characters = [helmeppo]  # コスト0キャラ 無し
    victim = InPlay.of(repo.get("EB01-023"), sickness=False)  # cost4 → -2 で cost2
    opp.characters = [victim]

    power_before = helmeppo.power
    on_attack = _get_eff(overlay, "OP02-113", "on_attack")
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp, helmeppo)
    assert helmeppo.power == power_before, \
        f"コスト0キャラ不在なのに +2000 が乗ってはいけない: {helmeppo.power}"


def test_op02_113_helmeppo_trigger_play_self_ai():
    """【トリガー】このカードを登場させる (play_self)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP02-113")]
    st.current_source_card_id = "OP02-113"

    trig = _get_eff(overlay, "OP02-113", "trigger")
    for prim in trig["do"]:
        execute_effect(prim, st, me, opp, None)
    assert any(c.card.card_id == "OP02-113" for c in me.characters), \
        "トリガーで 自身が登場していない"
    assert not any(c.card_id == "OP02-113" for c in me.hand), \
        "登場した自身が手札から取り除かれていない"


# --------------------------------------------------------------------------- #
#  OP02-114 ボルサリーノ: 【相手のターン中】このキャラは効果でKOされず、パワー+1000。
# --------------------------------------------------------------------------- #
def test_op02_114_borsalino_static_opp_turn_immune_and_pump():
    """相手ターン中: 効果KO耐性 (static_ko_immune) + パワー+1000 (static)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1  # 相手ターン (= opp_turn 条件成立)
    borsalino = InPlay.of(repo.get("OP02-114"), sickness=False)  # power 5000
    me.characters = [borsalino]

    evaluate_static_effects(st, overlay)
    assert borsalino.static_ko_immune is True, \
        "相手ターン中に 効果KO耐性 が付いていない"
    assert borsalino.power == borsalino.card.power + 1000, \
        f"相手ターン中の +1000 が反映されていない: {borsalino.power} (base {borsalino.card.power})"


def test_op02_114_borsalino_static_off_on_self_turn():
    """自分のターン中は【相手のターン中】条件が不成立 → 耐性 も +1000 も 無し。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 0  # 自分のターン
    borsalino = InPlay.of(repo.get("OP02-114"), sickness=False)
    me.characters = [borsalino]

    evaluate_static_effects(st, overlay)
    assert borsalino.static_ko_immune is False, \
        "自分のターン中に 効果KO耐性 が付いてはいけない"
    assert borsalino.power == borsalino.card.power, \
        f"自分のターン中に +1000 が乗ってはいけない: {borsalino.power}"


# --------------------------------------------------------------------------- #
#  OP02-115 モンキー・D・ガープ: 【ドン!!×2】【アタック時】相手のコスト0のキャラ1枚KO
# --------------------------------------------------------------------------- #
def test_op02_115_garp_overlay_don_gate_and_ko():
    """overlay 構造 sanity: ドン×2 ゲート + 相手コスト0キャラ KO (= 公式テキスト整合)。"""
    overlay = _overlay()
    on_attack = _get_eff(overlay, "OP02-115", "on_attack")
    assert on_attack.get("if", {}).get("self_attached_don_ge") == 2, \
        "overlay の ドンゲート self_attached_don_ge=2 が無い"
    assert on_attack["do"][0].get("ko") == "one_opponent_character_cost_eq_0", \
        "overlay の KO 対象 (相手コスト0キャラ) が無い"


@pytest.mark.skip(reason=(
    "engine bug (人間レビュー行き): KO 対象 selector 'one_opponent_character_cost_eq_0' が "
    "実効コスト (base_cost) でなく 印刷コスト (card.cost) で照合する。 海軍アーキタイプは "
    "相手キャラのコストを 0 まで下げてから KO するが、 印刷コスト0のキャラは DB に存在せず "
    "実効コスト0キャラでは KO が不発になる。 OP02-095 オニグモ (commit 8212a29 で "
    "exists_chara_cost_le:0 へ修正済) と同型の selector バグ。 engine/overlay 修正は "
    "このバックフィルタスクの範囲外 (engine 非編集) のため skip。"))
def test_op02_115_garp_ko_effective_cost0():
    """相手の 実効コスト0 キャラを KO する (現状 engine は印刷コストで照合し不発)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    victim.cost_minus_until_turn_end = 1  # 実効コスト0
    opp.characters = [victim]

    on_attack = _get_eff(overlay, "OP02-115", "on_attack")
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-115"), sickness=False))
    assert victim not in opp.characters, "相手の実効コスト0キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP02-117 氷河時代 (EVENT): 【メイン】相手キャラ1枚 コスト-5
#    【トリガー】相手のコスト3以下のキャラ1枚まで KO
# --------------------------------------------------------------------------- #
def test_op02_117_ice_age_main_cost_down_ai():
    """【メイン】相手キャラ1枚を コスト-5 (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    opp.characters = [victim]

    main = _get_eff(overlay, "OP02-117", "main")
    for prim in main["do"]:
        execute_effect(prim, st, me, opp, None)
    assert victim.cost_minus_until_turn_end == 5, \
        f"メインの コスト-5 が反映されていない: {victim.cost_minus_until_turn_end}"


def test_op02_117_ice_age_trigger_ko_cost_le_3_ai():
    """【トリガー】相手のコスト3以下キャラ1枚を KO (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 <= 3
    opp.characters = [victim]

    trig = _get_eff(overlay, "OP02-117", "trigger")
    for prim in trig["do"]:
        execute_effect(prim, st, me, opp, None)
    assert victim not in opp.characters, "トリガーで相手のコスト3以下キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP02-118 八尺瓊勾玉 (EVENT): 【カウンター】手札1枚を捨てられる：自分のキャラ1枚まで
#    → このバトル中 KOされない。 【トリガー】相手のコスト3以下のステージ1枚まで KO
# --------------------------------------------------------------------------- #
def test_op02_118_magatama_counter_prevent_ko_ai():
    """【カウンター】自分のキャラ1枚を このバトル中 KO耐性 (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [friend]

    counter = _get_eff(overlay, "OP02-118", "counter")
    for prim in counter["do"]:
        execute_effect(prim, st, me, opp, None)
    assert friend.ko_immune_until_turn_end is True, \
        "カウンターで 自キャラに KO耐性 が付与されていない"


def test_op02_118_magatama_counter_prevent_ko_human_pick():
    """人間 + 自キャラ複数 → target_pick modal が立ち resolve で選んだ1体に KO耐性。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)
    b = InPlay.of(repo.get("OP01-016"), sickness=False)
    me.characters = [a, b]

    counter = _get_eff(overlay, "OP02-118", "counter")
    execute_effect(counter["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    b_idx = next(i for i, c in enumerate(st.pending_choice["candidates"])
                 if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b.ko_immune_until_turn_end is True, \
        "人間が選んだ 自キャラに KO耐性 が付与されていない"
    assert a.ko_immune_until_turn_end is False, "選ばなかったキャラは影響を受けないべき"


def test_op02_118_magatama_trigger_ko_opp_stage_ai():
    """【トリガー】相手のコスト3以下ステージ1枚を KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("OP02-092"), sickness=False)  # STAGE cost1 <= 3
    opp.stages = [stage]

    trig = _get_eff(overlay, "OP02-118", "trigger")
    for prim in trig["do"]:
        execute_effect(prim, st, me, opp, None)
    assert stage not in opp.stages, "トリガーで相手のコスト3以下ステージが KO されていない"
    assert repo.get("OP02-092") in opp.trash, "KO したステージが相手トラッシュにない"


# --------------------------------------------------------------------------- #
#  OP02-119 流星火山 (EVENT): 【メイン】相手のコスト1以下のキャラ1枚まで KO
#    【トリガー】カード2枚を引き、自分の手札1枚を捨てる
# --------------------------------------------------------------------------- #
def test_op02_119_meteor_volcano_main_ko_cost_le_1_ai():
    """【メイン】相手のコスト1以下キャラ1枚を KO (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [victim]

    main = _get_eff(overlay, "OP02-119", "main")
    for prim in main["do"]:
        execute_effect(prim, st, me, opp, None)
    assert victim not in opp.characters, "メインで相手のコスト1以下キャラが KO されていない"


def test_op02_119_meteor_volcano_main_no_ko_cost_2():
    """コスト2キャラは対象外 (コスト1以下限定) → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 > 1
    opp.characters = [victim]

    main = _get_eff(overlay, "OP02-119", "main")
    for prim in main["do"]:
        execute_effect(prim, st, me, opp, None)
    assert victim in opp.characters, "コスト2キャラが KO されてはいけない (対象外)"


def test_op02_119_meteor_volcano_trigger_draw2_discard1_ai():
    """【トリガー】2枚引いて 手札1枚を捨てる → 手札 net +1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("OP01-013")] * 10

    trig = _get_eff(overlay, "OP02-119", "trigger")
    for prim in trig["do"]:
        execute_effect(prim, st, me, opp, None)
    assert len(me.hand) == 1, \
        f"トリガー (2枚引き→1枚捨て) の手札 net が +1 でない: {len(me.hand)}"
