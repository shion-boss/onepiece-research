# -*- coding: utf-8 -*-
"""OP01/OP02 弾 効果 回帰テスト バックフィル (自動生成 wave 026):
OP01-111 / OP01-112 / OP01-113 / OP01-114 / OP01-115 / OP01-117 /
OP01-118 / OP01-119 / OP01-120 / OP02-004 の 10 枚。

目的 (= test_backfill_auto_001〜025.py と同一方針):
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


def _do(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果の do 配列を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e["do"], e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]["do"], matches[0]


def _drain_choices(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op01_wave26_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP01-111", "OP01-112", "OP01-113", "OP01-114", "OP01-115",
           "OP01-117", "OP01-118", "OP01-119", "OP01-120", "OP02-004"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP01-111 ブラックマリア: 【ブロッカー】【ブロック時】ドン!!-1：
#    このターン中、このキャラはパワー+1000。
# --------------------------------------------------------------------------- #
def test_op01_111_black_maria_on_block_self_pump():
    """ブロック時 (ドン-1 コスト後の do): このキャラ (自身) は このターン中 パワー+1000。
    対象選択なし (target: self) の単純 pump。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay)  # 百獣海賊団 leader
    me, opp = st.players[0], st.players[1]
    blocker = InPlay.of(repo.get("OP01-111"), sickness=False)  # power 5000
    me.characters = [blocker]

    power_before = blocker.power
    do, eff = _do(overlay, "OP01-111", "on_block")
    assert eff.get("cost", {}).get("pay_don") == 1, \
        "overlay の ブロック時コスト pay_don=1 が無い"
    for prim in do:
        execute_effect(prim, st, me, opp, blocker)

    assert blocker.power == power_before + 1000, \
        f"ブロック時 自己 +1000 が反映されていない: {blocker.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  OP01-112 ページワン: 【起動メイン】【ターン1回】ドン!!-1：このキャラは、
#    このターン中、相手のアクティブのキャラにもアタックできる。
# --------------------------------------------------------------------------- #
def test_op01_112_page_one_activate_main_grants_active_attack_ai():
    """起動メイン: このキャラに「アクティブアタック可」キーワードが付与される (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay)
    me, opp = st.players[0], st.players[1]
    page_one = InPlay.of(repo.get("OP01-112"), sickness=False)
    me.characters = [page_one]
    me.don_active = 3  # ドン-1 コスト支払い用

    assert "アクティブアタック可" not in page_one.granted_keywords
    options = list_activate_main_effects(st, me, overlay)
    p1_opts = [(src, eff) for (src, eff) in options
               if src.card.card_id == "OP01-112"]
    assert len(p1_opts) == 1, \
        f"OP01-112 の起動メインが legal に出ない: {len(p1_opts)}"
    src, eff = p1_opts[0]
    fire_activate_main(st, me, opp, src, eff)

    assert "アクティブアタック可" in page_one.granted_keywords, \
        "起動メインで「アクティブアタック可」が付与されていない"


def test_op01_112_page_one_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay)
    me, opp = st.players[0], st.players[1]
    page_one = InPlay.of(repo.get("OP01-112"), sickness=False)
    me.characters = [page_one]
    me.don_active = 5

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP01-112"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP01-112"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP01-113 ホールデム: 【KO時】ドン!!デッキからドン!!1枚までをレストで追加する。
# --------------------------------------------------------------------------- #
def test_op01_113_holdem_on_ko_add_rested_don_ai():
    """KO時: ドンデッキからレストドン1枚をコストエリアに追加 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay)
    me, opp = st.players[0], st.players[1]

    rested_before = me.don_rested
    remaining_before = me.don_remaining_in_deck
    assert remaining_before >= 1, "テスト前提: ドンデッキに残りがある"
    do, _ = _do(overlay, "OP01-113", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-113"), sickness=False))

    assert me.don_rested == rested_before + 1, "KO時 レストドンが1枚追加されていない"
    assert me.don_remaining_in_deck == remaining_before - 1, \
        "ドンデッキの残りが1枚減っていない"


# --------------------------------------------------------------------------- #
#  OP01-114 X・ドレーク: 【登場時】ドン!!-1：相手は自身の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op01_114_drake_on_play_opp_discard_ai():
    """登場時 (ドン-1 コスト後の do): 相手は自身の手札を1枚捨てる → 相手手札 -1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.hand = [repo.get("ST01-004"), repo.get("OP01-013")]

    opp_hand_before = len(opp.hand)
    trash_before = len(opp.trash)
    do, eff = _do(overlay, "OP01-114", "on_play")
    assert eff.get("cost", {}).get("pay_don") == 1, \
        "overlay の 登場時コスト pay_don=1 が無い"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-114"), sickness=True))

    assert len(opp.hand) == opp_hand_before - 1, \
        f"相手手札が1枚捨てられていない: {len(opp.hand)} (before {opp_hand_before})"
    assert len(opp.trash) == trash_before + 1, "捨てた手札がトラッシュに置かれていない"


# --------------------------------------------------------------------------- #
#  OP01-115 象の鼻息 (EVENT): 【メイン】相手のコスト2以下のキャラ1枚までを、KOし、
#    ドン!!デッキからドン!!1枚までをアクティブで追加する。
#    【トリガー】このカードの【メイン】効果を発動する。
# --------------------------------------------------------------------------- #
def test_op01_115_zou_no_hanaiki_main_ko_and_add_don_ai():
    """メイン: 相手のコスト2以下キャラを KO + ドン1枚をアクティブで追加 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 (<=2)
    assert victim.card.cost <= 2
    opp.characters = [victim]

    active_before = me.don_active
    remaining_before = me.don_remaining_in_deck
    do, _ = _do(overlay, "OP01-115", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert victim not in opp.characters, "コスト2以下キャラが KO されていない"
    assert me.don_active == active_before + 1, "ドンが1枚アクティブで追加されていない"
    assert me.don_remaining_in_deck == remaining_before - 1, \
        "ドンデッキの残りが1枚減っていない"


def test_op01_115_zou_no_hanaiki_main_ko_human_pick():
    """人間 + 相手コスト2以下キャラ 複数 → KO の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP01-115", "main", needle="ko")
    ko_prim = next(p for p in do if "ko" in p)
    execute_effect(ko_prim, st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain_choices(st)
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは場に残るべき"


def test_op01_115_zou_no_hanaiki_trigger_fires_main_ai():
    """【トリガー】このカードの【メイン】効果 (KO + ドン追加) を発動する (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 (<=2)
    opp.characters = [victim]
    st.current_source_card_id = "OP01-115"  # event 起点 (self_inplay=None)

    active_before = me.don_active
    do, _ = _do(overlay, "OP01-115", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert victim not in opp.characters, "トリガー経由の メイン効果で KO されていない"
    assert me.don_active == active_before + 1, \
        "トリガー経由の メイン効果で ドンが追加されていない"


# --------------------------------------------------------------------------- #
#  OP01-117 シープスホーン (EVENT): 【メイン】ドン!!-1：相手のコスト6以下のキャラ
#    1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_op01_117_sheeps_horn_main_rest_ai():
    """メイン (ドン-1 コスト後の do): 相手のコスト6以下キャラを レストにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-025"), sickness=False)  # ゾロ cost3 (<=6)
    assert victim.card.cost <= 6
    victim.rested = False
    opp.characters = [victim]

    do, eff = _do(overlay, "OP01-117", "main")
    assert eff.get("cost", {}).get("pay_don") == 1, \
        "overlay の メインコスト pay_don=1 が無い"
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert victim.rested is True, "コスト6以下キャラが レストにされていない"


def test_op01_117_sheeps_horn_main_rest_human_pick():
    """人間 + 相手コスト6以下キャラ 複数 → rest の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-025"), sickness=False)  # cost3
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    a.rested = False
    b.rested = False
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP01-117", "main")
    rest_prim = next(p for p in do if "rest" in p)
    execute_effect(rest_prim, st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain_choices(st)
    assert b.rested is True, "人間が選んだキャラが レストにされていない"
    assert a.rested is False, "選ばなかったキャラは アクティブのままであるべき"


# --------------------------------------------------------------------------- #
#  OP01-118 ウル頭銃 (EVENT): 【カウンター】ドン!!-2：自分のリーダーかキャラ1枚までを、
#    このバトル中、パワー+2000。その後、カード1枚を引く。
#    【トリガー】ドン!!デッキからドン!!1枚までをアクティブで追加する。
# --------------------------------------------------------------------------- #
def test_op01_118_uru_zugin_counter_pump_and_draw_ai():
    """カウンター (ドン-2 コスト後の do): 自リーダー(既定) +2000 + 1ドロー (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("ST01-004")] * 10

    power_before = me.leader.power
    hand_before = len(me.hand)
    do, eff = _do(overlay, "OP01-118", "counter")
    assert eff.get("cost", {}).get("pay_don") == 2, \
        "overlay の カウンターコスト pay_don=2 が無い"
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 2000, \
        f"カウンターの +2000 が自リーダーに反映されていない: {me.leader.power}"
    assert len(me.hand) == hand_before + 1, "その後の1ドローが起きていない"


def test_op01_118_uru_zugin_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +2000 の対象選択 target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [friend]
    me.deck = [repo.get("ST01-004")] * 10

    do, _ = _do(overlay, "OP01-118", "counter")
    pump_prim = next(p for p in do if "power_pump" in p)
    execute_effect(pump_prim, st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert friend.power == friend_before + 2000, \
        "人間が選んだキャラに +2000 が反映されていない"


def test_op01_118_uru_zugin_trigger_add_don_ai():
    """【トリガー】ドンデッキからドン1枚をアクティブで追加する (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay)
    me, opp = st.players[0], st.players[1]

    active_before = me.don_active
    remaining_before = me.don_remaining_in_deck
    do, _ = _do(overlay, "OP01-118", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.don_active == active_before + 1, "トリガーで ドンが追加されていない"
    assert me.don_remaining_in_deck == remaining_before - 1, \
        "ドンデッキの残りが1枚減っていない"


# --------------------------------------------------------------------------- #
#  OP01-119 雷鳴八卦 (EVENT): 【カウンター】自分のリーダーかキャラ1枚までを、
#    このバトル中、パワー+4000。その後、自分のライフが2枚以下の場合、
#    ドン!!デッキからドン!!1枚までをレストで追加する。
#    【トリガー】ドン!!デッキからドン!!1枚までをアクティブで追加する。
# --------------------------------------------------------------------------- #
def test_op01_119_raimei_hakke_counter_pump_and_ramp_ai():
    """カウンター: 自リーダー(既定) +4000 → ライフ2枚以下なら レストドン1枚追加 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("ST01-004")] * 2  # ライフ 2 (= 条件成立)

    power_before = me.leader.power
    rested_before = me.don_rested
    do, _ = _do(overlay, "OP01-119", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 4000, \
        f"カウンターの +4000 が自リーダーに反映されていない: {me.leader.power}"
    assert me.don_rested == rested_before + 1, \
        "ライフ2枚以下の条件成立で レストドンが追加されていない"


def test_op01_119_raimei_hakke_counter_no_ramp_when_life_high():
    """自ライフが3枚以上なら【その後】の条件が不成立 → レストドンは追加されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("ST01-004")] * 4  # ライフ 4 (= 条件不成立)

    rested_before = me.don_rested
    do, _ = _do(overlay, "OP01-119", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.don_rested == rested_before, \
        "ライフ2枚超なのに レストドンが追加されている (条件節を省略している)"


# --------------------------------------------------------------------------- #
#  OP01-120 シャンクス: 【速攻】【アタック時】相手は、このバトル中、
#    パワー2000以下のキャラの【ブロッカー】を発動できない。
# --------------------------------------------------------------------------- #
def test_op01_120_shanks_attack_prevent_low_blocker():
    """アタック時: このアタッカーに「パワー2000以下ブロッカー禁止」フラグが立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    shanks = InPlay.of(repo.get("OP01-120"), sickness=False)
    me.characters = [shanks]

    assert shanks.attacker_prevents_blocker_power_le != 2000
    do, _ = _do(overlay, "OP01-120", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp, shanks)

    assert shanks.attacker_prevents_blocker_power_le == 2000, \
        "アタック時 パワー2000以下ブロッカー禁止 のフラグが立っていない"


# --------------------------------------------------------------------------- #
#  OP02-004 エドワード・ニューゲート: 【登場時】自分のリーダー1枚までを、次の自分の
#    ターン開始時まで、パワー+2000。その後、自分は、このターン中、自分の効果でライフを
#    手札に加えられない。【ドン!!×2】【アタック時】相手のパワー3000以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op02_004_newgate_on_play_leader_pump_and_lock_ai():
    """登場時: 自リーダー +2000 (次の自分のターン開始時まで) + 自効果ライフ→手札 禁止。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    assert me.prevent_self_life_to_hand_until_turn_end is False
    do, _ = _do(overlay, "OP02-004", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-004"), sickness=True))

    assert me.leader.power == power_before + 2000, \
        f"登場時 自リーダー +2000 が反映されていない: {me.leader.power}"
    assert me.prevent_self_life_to_hand_until_turn_end is True, \
        "その後の「自効果でライフを手札に加えられない」フラグが立っていない"


def test_op02_004_newgate_attack_ko_power_le3000_ai():
    """アタック時 (ドン×2 ゲート): 相手のパワー3000以下キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("OP02-004"), sickness=False)
    attacker.attached_dons = 2  # 【ドン!!×2】ゲート成立
    me.characters = [attacker]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # power 3000 (<=3000)
    assert victim.power <= 3000
    opp.characters = [victim]

    do, eff = _do(overlay, "OP02-004", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 2, \
        "overlay の ドンゲート self_attached_don_ge=2 が無い"
    for prim in do:
        execute_effect(prim, st, me, opp, attacker)

    assert victim not in opp.characters, "パワー3000以下キャラが KO されていない"


def test_op02_004_newgate_attack_ko_human_pick():
    """人間 + 相手パワー3000以下キャラ 複数 → KO の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("OP02-004"), sickness=False)
    attacker.attached_dons = 2
    me.characters = [attacker]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # power 3000
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # power 2000
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP02-004", "on_attack")
    ko_prim = next(p for p in do if "ko" in p)
    execute_effect(ko_prim, st, me, opp, attacker)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain_choices(st)
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは場に残るべき"
