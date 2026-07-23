# -*- coding: utf-8 -*-
"""OP04 弾 効果 回帰テスト バックフィル (自動生成 wave 050):
OP04-068 / OP04-069 / OP04-070 / OP04-071 / OP04-073 / OP04-074 /
OP04-075 / OP04-076 / OP04-079 / OP04-080 の 10 枚。

目的 (= test_backfill_auto_001〜049.py と同一方針):
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

# B・W リーダー (= 『B・W』を含む特徴条件成立用)
LEADER_BW = "OP04-058"   # クロコダイル (王下七武海/B・W)
# ドレスローザ を含むデッキ用リーダー (条件は無いが文脈のため汎用リーダー)
LEADER_GEN = "OP01-001"  # ロロノア・ゾロ


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
    """指定 card_id の overlay から when 一致の効果の do 配列 + 効果 dict を返す。"""
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
def test_all_op04_wave50_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP04-068", "OP04-069", "OP04-070", "OP04-071", "OP04-073",
           "OP04-074", "OP04-075", "OP04-076", "OP04-079", "OP04-080"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP04-068 ヨコヅナ (CHARACTER):
#   【ブロッカー】/【相手のアタック時】ドン!!-1：相手コスト2以下キャラ1枚を持ち主の手札に戻す
# --------------------------------------------------------------------------- #
def test_op04_068_yokozuna_opp_attack_return_to_hand_ai():
    """AI: 相手アタック時 do → 相手のコスト2以下キャラ1枚を持ち主の手札に戻す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER_GEN, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost1 (<=2)
    opp.characters = [victim]
    opp_hand_before = len(opp.hand)

    do, _ = _do(overlay, "OP04-068", "opp_attack")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-068"), sickness=False))

    assert victim not in opp.characters, "相手コスト2以下キャラが場から離れていない"
    assert len(opp.hand) == opp_hand_before + 1, "相手手札に1枚戻っていない"


def test_op04_068_yokozuna_opp_attack_return_human_pick():
    """人間 + 相手コスト2以下キャラ複数 → return_to_hand の target_pick modal が立ち resolve。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER_GEN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP04-068", "opp_attack")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP04-068"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    assert b not in opp.characters, "人間が選んだキャラが手札に戻っていない"
    assert a in opp.characters, "選ばなかったキャラは場に残るべき"


# --------------------------------------------------------------------------- #
#  OP04-069 Mr.2・ボン・クレー(ベンサム) (CHARACTER):
#   【相手のアタック時】ドン!!-1：このキャラの元々のパワーは、このターン中、
#     相手のアタックしているリーダーかキャラと同じパワーになる
#   【トリガー】ドン!!-1：このカードを登場させる
# --------------------------------------------------------------------------- #
def test_op04_069_bonclay_opp_attack_copy_attacker_power_ai():
    """AI: 相手アタック時 do → 自身の元々のパワーを アタッカーと同じにする (power-copy)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER_GEN, overlay)
    me, opp = st.players[0], st.players[1]
    bonclay = InPlay.of(repo.get("OP04-069"), sickness=False)  # 元々 power 4000
    me.characters = [bonclay]
    # 相手のアタッカー = 相手リーダー (power 5000) を指定
    attacker = opp.leader
    st.current_attacker_iid = attacker.instance_id

    do, _ = _do(overlay, "OP04-069", "opp_attack", needle="set_base_power_copy")
    for prim in do:
        execute_effect(prim, st, me, opp, bonclay)

    assert bonclay.power == attacker.power, \
        f"ボン・クレーの元々パワーがアタッカーと同じになっていない: {bonclay.power} vs {attacker.power}"
    assert bonclay.power == 5000, \
        f"元々パワー 4000 → アタッカー 5000 への複写が効いていない: {bonclay.power}"


def test_op04_069_bonclay_trigger_play_self_ai():
    """AI: トリガー do → 自身を登場させる (play_self)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER_GEN, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP04-069")]
    st.current_source_card_id = "OP04-069"
    me.don_active = 3  # ドン-1 コスト支払い可
    chars_before = len(me.characters)

    do, _ = _do(overlay, "OP04-069", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert any(c.card.card_id == "OP04-069" for c in me.characters), \
        "トリガー play_self で ボン・クレー が登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"


# --------------------------------------------------------------------------- #
#  OP04-070 Mr.3(ギャルディーノ) (CHARACTER):
#   【相手のアタック時】【ターン1回】ドン!!-1：相手キャラ1枚を このターン中 パワー-1000
# --------------------------------------------------------------------------- #
def test_op04_070_mr3_opp_attack_debuff_ai():
    """AI: 相手アタック時 do → 相手キャラ1枚を このターン中 パワー-1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER_GEN, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ power 2000
    opp.characters = [victim]
    power_before = victim.power

    do, _ = _do(overlay, "OP04-070", "opp_attack")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-070"), sickness=False))

    assert victim.power == power_before - 1000, \
        f"相手キャラ -1000 が反映されていない: {victim.power} (before {power_before})"


def test_op04_070_mr3_opp_attack_debuff_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal が立ち resolve で1枚に -1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER_GEN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # power 2000
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # power 3000
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP04-070", "opp_attack")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP04-070"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    assert b.power == b_before - 1000, "人間が選んだ相手キャラに -1000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP04-071 Mr.4(ベーブ) (CHARACTER):
#   【相手のアタック時】ドン!!-1：このキャラは このバトル中【ブロッカー】を得て パワー+1000
# --------------------------------------------------------------------------- #
def test_op04_071_mr4_opp_attack_gain_blocker_and_pump_ai():
    """AI: 相手アタック時 do → 自身が【ブロッカー】を得て パワー+1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER_GEN, overlay)
    me, opp = st.players[0], st.players[1]
    mr4 = InPlay.of(repo.get("OP04-071"), sickness=False)  # 元々 power 6000
    me.characters = [mr4]
    assert "ブロッカー" not in mr4.granted_keywords
    power_before = mr4.power

    do, _ = _do(overlay, "OP04-071", "opp_attack")
    for prim in do:
        execute_effect(prim, st, me, opp, mr4)

    assert "ブロッカー" in mr4.granted_keywords, \
        "相手アタック時に【ブロッカー】が付与されていない"
    assert mr4.power == power_before + 1000, \
        f"自己 +1000 が反映されていない: {mr4.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  OP04-073 Mr.13&ミス・フライデー (CHARACTER):
#   【起動メイン】このキャラと自分の『B・W』を含む特徴を持つキャラ1枚をトラッシュに置く：
#     ドン!!デッキからドン!!1枚までをアクティブで追加する (optional_cost_then)
# --------------------------------------------------------------------------- #
def test_op04_073_mr13_activate_main_trash_bw_add_don_ai():
    """AI: 起動メイン → 自身 + 別の『B・W』キャラをトラッシュ (コスト) し、 ドン1枚を追加。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER_GEN, overlay)
    me, opp = st.players[0], st.players[1]
    mr13 = InPlay.of(repo.get("OP04-073"), sickness=False)  # 動物/B・W
    partner = InPlay.of(repo.get("OP14-085"), sickness=False)  # B・W (別キャラ)
    me.characters = [mr13, partner]
    me.don_active = 0
    me.don_remaining_in_deck = 8

    options = list_activate_main_effects(st, me, overlay)
    mr13_opts = [(src, eff) for (src, eff) in options
                 if src.card.card_id == "OP04-073"]
    assert len(mr13_opts) == 1, \
        f"OP04-073 の起動メインが legal に出ない: {len(mr13_opts)}"
    src, eff = mr13_opts[0]
    fire_activate_main(st, me, opp, src, eff)

    assert me.don_active == 1, f"ドン1枚がアクティブで追加されていない: {me.don_active}"
    assert me.don_remaining_in_deck == 7, "ドンデッキから1枚供給されていない"
    assert mr13 not in me.characters, "コストで Mr.13 がトラッシュに置かれていない"
    assert partner not in me.characters, "コストで『B・W』相棒がトラッシュに置かれていない"


# --------------------------------------------------------------------------- #
#  OP04-074 カラーズトラップ (EVENT):
#   【カウンター】ドン!!-1：自リーダー/キャラ1枚 +1000 → その後 相手コスト4以下キャラ1枚をレスト
#   【トリガー】ドン!!デッキからドン!!1枚をアクティブで追加
# --------------------------------------------------------------------------- #
def test_op04_074_colorstrap_counter_pump_and_rest_ai():
    """AI: カウンター do → 自リーダー(最大パワー) +1000、 相手コスト4以下キャラをレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER_GEN, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 (<=4)、 アクティブ
    opp.characters = [victim]
    leader_power_before = me.leader.power

    do, _ = _do(overlay, "OP04-074", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == leader_power_before + 1000, \
        f"カウンターの +1000 が自リーダーに乗っていない: {me.leader.power}"
    assert victim.rested is True, "相手コスト4以下キャラがレストされていない"


def test_op04_074_colorstrap_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ複数 → power_pump の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER_GEN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP01-016"), sickness=False)
    me.characters = [friend]

    do, _ = _do(overlay, "OP04-074", "counter")
    execute_effect(do[0], st, me, opp, None)  # power_pump self_inplay

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    power_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert friend.power == power_before + 1000, "人間が選んだキャラに +1000 が乗っていない"


def test_op04_074_colorstrap_trigger_add_don_ai():
    """トリガー do: ドンデッキからドン1枚をアクティブで追加する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER_GEN, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 0
    me.don_remaining_in_deck = 8

    do, _ = _do(overlay, "OP04-074", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.don_active == 1, f"トリガーで ドン+1 されていない: {me.don_active}"
    assert me.don_remaining_in_deck == 7, "ドンデッキから1枚供給されていない"


# --------------------------------------------------------------------------- #
#  OP04-075 鼻空想砲 (EVENT):
#   【カウンター】自リーダー/キャラ1枚 +6000 → その後 自ライフ2枚以下なら ドン1枚をレストで追加
# --------------------------------------------------------------------------- #
def test_op04_075_hanakusou_counter_pump_and_life_le2_add_rested_don_ai():
    """AI: カウンター do → 自リーダー +6000、 自ライフ2枚以下で レストドン1枚を追加。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER_GEN, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("ST01-004")] * 2  # ライフ 2 (= self_life_le 2 成立)
    me.don_rested = 0
    me.don_remaining_in_deck = 8
    leader_power_before = me.leader.power

    do, _ = _do(overlay, "OP04-075", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == leader_power_before + 6000, \
        f"カウンターの +6000 が自リーダーに乗っていない: {me.leader.power}"
    assert me.don_rested == 1, "ライフ2枚以下なのに レストドンが追加されていない"


def test_op04_075_hanakusou_counter_no_don_over_2_life():
    """自ライフ3枚以上なら レストドン追加は起きない (条件不成立)。 +6000 は無条件。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER_GEN, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("ST01-004")] * 4  # ライフ 4 (> 2)
    me.don_rested = 0
    me.don_remaining_in_deck = 8
    leader_power_before = me.leader.power

    do, _ = _do(overlay, "OP04-075", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == leader_power_before + 6000, "+6000 は無条件で乗るべき"
    assert me.don_rested == 0, "ライフ3枚以上なのに レストドンが追加されている"


# --------------------------------------------------------------------------- #
#  OP04-076 弱ェってのは…罪なもんだ… (EVENT):
#   【カウンター】ドン!!-1：自リーダー/キャラ1枚 このターン中 パワー+1000
# --------------------------------------------------------------------------- #
def test_op04_076_yowaettenoha_counter_pump_ai():
    """AI: カウンター do → 自リーダー(最大パワー)を このターン中 +1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER_GEN, overlay)
    me, opp = st.players[0], st.players[1]
    leader_power_before = me.leader.power

    do, _ = _do(overlay, "OP04-076", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == leader_power_before + 1000, \
        f"カウンターの +1000 が自リーダーに乗っていない: {me.leader.power}"


def test_op04_076_yowaettenoha_trigger_add_don_ai():
    """トリガー do: ドンデッキからドン1枚をアクティブで追加する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER_GEN, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 0
    me.don_remaining_in_deck = 8

    do, _ = _do(overlay, "OP04-076", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.don_active == 1, f"トリガーで ドン+1 されていない: {me.don_active}"


# --------------------------------------------------------------------------- #
#  OP04-079 オオロンブス (CHARACTER):
#   【起動メイン】【ターン1回】相手キャラ1枚を このターン中 コスト-4し、 自デッキ上2枚をトラッシュ。
#     その後 自分の《ドレスローザ》キャラ1枚を KO する
# --------------------------------------------------------------------------- #
def test_op04_079_oorombus_activate_main_costdown_mill_ko_ai():
    """AI: 起動メイン → 相手キャラ コスト-4、 デッキ上2枚をトラッシュ、《ドレスローザ》1枚 KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER_GEN, overlay)
    me, opp = st.players[0], st.players[1]
    oorombus = InPlay.of(repo.get("OP04-079"), sickness=False)  # ドレスローザ
    gatz = InPlay.of(repo.get("OP04-080"), sickness=False)      # ドレスローザ
    me.characters = [oorombus, gatz]
    victim = InPlay.of(repo.get("OP04-071"), sickness=False)  # cost 5
    opp.characters = [victim]
    me.deck = [repo.get("ST01-004")] * 10

    cost_before = victim.base_cost
    deck_before = len(me.deck)
    trash_before = len(me.trash)
    dressrosa_before = sum(
        1 for c in me.characters if "ドレスローザ" in (c.card.features or ""))

    options = list_activate_main_effects(st, me, overlay)
    oorombus_opts = [(src, eff) for (src, eff) in options
                     if src.card.card_id == "OP04-079"]
    assert len(oorombus_opts) == 1, \
        f"OP04-079 の起動メインが legal に出ない: {len(oorombus_opts)}"
    src, eff = oorombus_opts[0]
    fire_activate_main(st, me, opp, src, eff)

    assert victim.base_cost == max(0, cost_before - 4), \
        f"相手キャラの コスト-4 が反映されていない: {victim.base_cost} (before {cost_before})"
    assert len(me.deck) == deck_before - 2, \
        f"デッキ上2枚のトラッシュが起きていない: {len(me.deck)}"
    assert len(me.trash) >= trash_before + 2, "トラッシュに2枚以上積まれていない (mill)"
    dressrosa_after = sum(
        1 for c in me.characters if "ドレスローザ" in (c.card.features or ""))
    assert dressrosa_after == dressrosa_before - 1, \
        f"《ドレスローザ》キャラが1枚 KO されていない: {dressrosa_after} (before {dressrosa_before})"


# --------------------------------------------------------------------------- #
#  OP04-080 ギャッツ (CHARACTER):
#   【登場時】自分の《ドレスローザ》キャラ1枚は このターン中 アクティブのキャラにもアタックできる
# --------------------------------------------------------------------------- #
def test_op04_080_gatz_on_play_give_attack_active_chara_ai():
    """AI: 登場時 do → 自分の《ドレスローザ》キャラが アクティブキャラにもアタック可 になる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER_GEN, overlay)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP04-079"), sickness=False)  # オオロンブス ドレスローザ
    me.characters = [friend]
    assert "アクティブアタック可" not in friend.granted_keywords

    do, _ = _do(overlay, "OP04-080", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-080"), sickness=True))

    assert "アクティブアタック可" in friend.granted_keywords, \
        "《ドレスローザ》キャラに アクティブアタック可 が付与されていない"


def test_op04_080_gatz_on_play_human_pick():
    """人間 + 自《ドレスローザ》キャラ複数 → target_pick modal が立ち resolve で1枚に付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER_GEN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP04-079"), sickness=False)  # オオロンブス ドレスローザ
    b = InPlay.of(repo.get("OP04-080"), sickness=False)  # ギャッツ ドレスローザ
    me.characters = [a, b]

    do, _ = _do(overlay, "OP04-080", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP04-080"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    assert "アクティブアタック可" in b.granted_keywords, \
        "人間が選んだ《ドレスローザ》キャラに アクティブアタック可 が付与されていない"
