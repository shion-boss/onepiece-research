# -*- coding: utf-8 -*-
"""OP16 弾 (バギー / インペルダウンの囚人 / 海軍 ・ 青・紫) 効果 回帰テスト
バックフィル (自動生成 wave 150):
OP16-051 / OP16-053 / OP16-054 / OP16-055 / OP16-056 /
OP16-057 / OP16-058 / OP16-059 / OP16-064 / OP16-066 の 10 枚。

目的 (= test_backfill_auto_001〜149.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 任意コスト / 対象選択 を 持つカードは 人間 actor で pending_choice が
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
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)
from engine.deck import CardRepository

ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------- #
#  効果の薄い (= 副作用のない / 素材用) カード。
# --------------------------------------------------------------------------- #
RED1 = "OP01-016"          # ナミ 赤 cost1 power2000 (フィラー)
GREEN2 = "EB01-017"        # ブルーノ 緑 cost2 power2000 (cost≥2 素材)
IMPEL_LEADER = "OP16-022"  # モンキー・Ｄ・ルフィ (インペルダウン LEADER, 緑/青)
NAVY_LEADER = "OP16-060"   # センゴク (海軍 LEADER, 紫)
PRISONER = "OP16-042"      # インペルダウンの囚人 (青 cost6 power6000)
IMPEL_C1 = "EB02-038"      # マゼラン (インペルダウン cost3 power4000)
IMPEL_C2 = "EB01-026"      # プリンス・ベレット (インペルダウン cost2 power2000)
BAGGY_C = "EB02-018"       # バギー (青 cost4 power6000)
NAVY_C = "EB04-003"        # スモーカー＆たしぎ (海軍, コビー以外)
NAVY_C2 = "EB04-022"       # イッショウ (海軍, コビー以外)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001",
           turn_player=0):
    """P0 = テスト対象デッキ、 P1 = ダミー。 MAIN / turn_number=3。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(RED1)] * 30
    p1.deck = [repo.get(RED1)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn_player
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when):
    """指定 card_id の overlay から when 一致の効果の (do 配列, eff) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    return matches[0]["do"], matches[0]


def _drain(st, pick=None, guard=10):
    """残った pending_choice を安全に drain。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op16_wave150_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP16-051", "OP16-053", "OP16-054", "OP16-055", "OP16-056",
           "OP16-057", "OP16-058", "OP16-059", "OP16-064", "OP16-066"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP16-051 モージ＆カバジ (CHARACTER 青 cost6 power7000):
#    【登場時】自分の手札が5枚以下の場合、 カード2枚を引く。
# --------------------------------------------------------------------------- #
def test_op16_051_on_play_draw2_when_hand_le5_ai():
    """【登場時】手札5枚以下 → カード2枚を引く (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(RED1)] * 3   # 3 枚 (≤5 = 条件成立)
    me.deck = [repo.get(RED1)] * 10
    do, eff = _do(overlay, "OP16-051", "on_play")
    assert eff.get("if", {}).get("self_hand_count_le") == 5, \
        "on_play の self_hand_count_le=5 条件が overlay に無い"
    assert eval_condition(eff["if"], st, me, None) is True, \
        "手札3枚で条件が成立していない"
    hand_before = len(me.hand)
    deck_before = len(me.deck)
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-051"), sickness=True))
    _drain(st, [0])
    assert len(me.hand) == hand_before + 2, \
        f"カード2枚ドローが反映されていない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 2, "ドローでデッキが2枚減っていない"


def test_op16_051_condition_false_when_hand_gt5():
    """手札6枚 → 条件不成立 (ドローしない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, _ = st.players[0], st.players[1]
    me.hand = [repo.get(RED1)] * 6  # 6 枚 (> 5)
    _, eff = _do(overlay, "OP16-051", "on_play")
    assert eval_condition(eff["if"], st, me, None) is False, \
        "手札6枚で条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP16-053 ロロノア・ゾロ (CHARACTER 青 cost7 power9000):
#    【アタック時】自分の手札が6枚以下の場合、 カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op16_053_on_attack_draw1_when_hand_le6_ai():
    """【アタック時】手札6枚以下 → カード1枚を引く (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(RED1)] * 2
    me.deck = [repo.get(RED1)] * 10
    attacker = InPlay.of(repo.get("OP16-053"), sickness=False)
    me.characters = [attacker]
    do, eff = _do(overlay, "OP16-053", "on_attack")
    assert eff.get("if", {}).get("self_hand_count_le") == 6, \
        "on_attack の self_hand_count_le=6 条件が overlay に無い"
    hand_before = len(me.hand)
    for prim in do:
        execute_effect(prim, st, me, opp, attacker)
    _drain(st, [0])
    assert len(me.hand) == hand_before + 1, \
        f"アタック時 1ドローが反映されていない: {len(me.hand)}"


# --------------------------------------------------------------------------- #
#  OP16-054 Mr.1(ダズ・ボーネス) (CHARACTER 青 cost2 power2000):
#    【ドン!!×1】【自分のターン中】手札が5枚以上ある場合、 このキャラのパワー+3000。
#    【登場時】カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op16_054_static_power_pump_when_self_turn_and_hand_ge5():
    """静的効果: ドン1付与 + 自ターン + 手札5枚以上 → base +3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, turn_player=0)
    me, _ = st.players[0], st.players[1]
    card_def = repo.get("OP16-054")  # power 2000
    mr1 = InPlay.of(card_def, sickness=False)
    me.characters = [mr1]
    mr1.attached_dons = 1           # 【ドン!!×1】ゲート成立
    me.hand = [repo.get(RED1)] * 5  # 手札5枚以上 → 条件成立
    evaluate_static_effects(st, overlay)
    # 印刷 2000 + DON1枚(+1000) + 効果(+3000) = 6000
    assert mr1.power == card_def.power + 1000 + 3000, \
        f"自ターン・手札5枚で +3000 が反映されていない: {mr1.power} (base {card_def.power})"


def test_op16_054_static_no_pump_off_turn():
    """相手ターン中は【自分のターン中】条件が不成立 → 効果 pump は乗らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, turn_player=1)  # 相手ターン
    me, _ = st.players[0], st.players[1]
    card_def = repo.get("OP16-054")
    mr1 = InPlay.of(card_def, sickness=False)
    me.characters = [mr1]
    mr1.attached_dons = 1
    me.hand = [repo.get(RED1)] * 5
    evaluate_static_effects(st, overlay)
    # DON1枚(+1000) のみ、 効果 +3000 は乗らない
    assert mr1.power == card_def.power + 1000, \
        f"相手ターンで効果 pump が乗ってはいけない: {mr1.power} (base {card_def.power})"


def test_op16_054_on_play_draw1_ai():
    """【登場時】カード1枚を引く (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(RED1)] * 5
    do, _ = _do(overlay, "OP16-054", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-054"), sickness=True))
    _drain(st, [0])
    assert len(me.hand) == 1, "登場時の1ドローが起きていない"


# --------------------------------------------------------------------------- #
#  OP16-055 Mr.2・ボン・クレー(ベンサム) (CHARACTER 青 cost2 power1000):
#    【登場時】カード1枚を引く。
#    【ドン!!×1】【アタック時】このキャラの元々のパワーは、 このターン中、
#               相手のリーダーと同じパワーになる。
# --------------------------------------------------------------------------- #
def test_op16_055_on_play_draw1_ai():
    """【登場時】カード1枚を引く (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(RED1)] * 5
    do, _ = _do(overlay, "OP16-055", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-055"), sickness=True))
    _drain(st, [0])
    assert len(me.hand) == 1, "登場時の1ドローが起きていない"


def test_op16_055_on_attack_set_base_power_copy_opp_leader():
    """【アタック時】自身の元々のパワーが 相手リーダーと同じ (このターン中) になる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, opp_leader_id="OP01-001")
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("OP16-055"), sickness=False)  # base 1000
    # 【ドン!!×1】ゲートは overlay の if 条件。 execute_effect は gate を経由せず
    # 効果本体 (set_base_power_copy) を直接発火するので、 DON 付与なしで
    # 実効パワー = 相手リーダー値 と一致することを検証する (DON +1000 の混入を避ける)。
    me.characters = [attacker]
    opp_leader_power = opp.leader.power  # OP01-001 = 5000
    do, _ = _do(overlay, "OP16-055", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp, attacker)
    assert attacker.turn_base_power_override == opp_leader_power, \
        f"元々のパワーが 相手リーダー値に複写されていない: {attacker.turn_base_power_override}"
    assert attacker.power == opp_leader_power, \
        f"実効パワーが 相手リーダーと同じになっていない: {attacker.power} (leader {opp_leader_power})"


# --------------------------------------------------------------------------- #
#  OP16-056 Mr.3(ギャルディーノ) (CHARACTER 青 cost4 power5000):
#    【起動メイン】このキャラをトラッシュに置くことができる：カード2枚を引き、
#                 相手のコスト9以下のキャラ1枚までは、 次の相手のエンドフェイズ終了時まで、
#                 アタックできない。
# --------------------------------------------------------------------------- #
def test_op16_056_activate_main_trash_draw2_and_cannot_attack_ai():
    """【起動メイン】自身をトラッシュ + カード2枚引き + 相手コスト9以下1枚をアタック不可 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    mr3 = InPlay.of(repo.get("OP16-056"), sickness=False)
    me.characters = [mr3]
    me.hand = []
    me.deck = [repo.get(RED1)] * 10
    victim = InPlay.of(repo.get(RED1), sickness=False)  # cost1 (≤9)
    opp.characters = [victim]
    options = list_activate_main_effects(st, me, overlay)
    mr3_opts = [(src, e) for (src, e) in options
                if src.card.card_id == "OP16-056"]
    assert len(mr3_opts) == 1, \
        f"OP16-056 の起動メインが legal に出ない: {len(mr3_opts)}"
    fire_activate_main(st, me, opp, *mr3_opts[0])
    _drain(st, [0])
    assert mr3 not in me.characters, "コストで Mr.3 がトラッシュに置かれるべき"
    assert len(me.hand) == 2, f"カード2枚ドローが反映されていない: {len(me.hand)}"
    assert victim.cannot_attack_through_opp_turn is True, \
        "相手キャラが 次の相手エンド終了時まで アタック不可になっていない"


def test_op16_056_activate_main_human_target_pick():
    """人間 + 相手コスト9以下キャラ 複数 → アタック不可対象の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    mr3 = InPlay.of(repo.get("OP16-056"), sickness=False)
    me.characters = [mr3]
    me.deck = [repo.get(RED1)] * 10
    opp.characters = [
        InPlay.of(repo.get(RED1), sickness=False),
        InPlay.of(repo.get(GREEN2), sickness=False),
    ]
    options = list_activate_main_effects(st, me, overlay)
    mr3_opts = [(src, e) for (src, e) in options
                if src.card.card_id == "OP16-056"]
    assert len(mr3_opts) == 1
    fire_activate_main(st, me, opp, *mr3_opts[0])
    # draw2 の後、 アタック不可対象を人間が選ぶ modal が立つ
    _drain_guard = 0
    while st.pending_choice is not None and \
            st.pending_choice.get("kind") != "target_pick" and _drain_guard < 4:
        resolve_pending_choice(st, [0])
        _drain_guard += 1
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "target_pick", \
        f"人間で target_pick modal が立たない: {st.pending_choice}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"


# --------------------------------------------------------------------------- #
#  OP16-057 おれ達の救世主!!!キャプテン・バギー!!!! (EVENT 青 cost1):
#    【カウンター】自分の「インペルダウンの囚人」が2枚以上いる場合、
#                 自分のリーダーかキャラ1枚までを、 このバトル中、 パワー+4000。
#    【トリガー】カード2枚を引き、 自分の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op16_057_counter_pump_when_two_prisoners_ai():
    """【カウンター】「インペルダウンの囚人」2枚以上 → 自リーダー/キャラ1枚 +4000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    p1 = InPlay.of(repo.get(PRISONER), sickness=False)  # power 6000
    p2 = InPlay.of(repo.get(PRISONER), sickness=False)
    me.characters = [p1, p2]
    do, eff = _do(overlay, "OP16-057", "counter")
    assert eval_condition(eff.get("if", {}), st, me, None) is True, \
        "「インペルダウンの囚人」2枚で counter 条件が成立していない"
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    # AI は キャラ (囚人) を +4000 対象に選ぶ (leader は据え置き)
    pumped = [c for c in me.characters if c.power == 6000 + 4000]
    assert len(pumped) == 1, \
        f"自キャラ1枚に +4000 が反映されていない: {[c.power for c in me.characters]}"


def test_op16_057_counter_condition_false_with_one_prisoner():
    """「インペルダウンの囚人」1枚のみ → counter 条件が成立しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, _ = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(PRISONER), sickness=False)]  # 1 枚
    _, eff = _do(overlay, "OP16-057", "counter")
    assert eval_condition(eff.get("if", {}), st, me, None) is False, \
        "囚人1枚で counter 条件が成立してはいけない"


def test_op16_057_trigger_draw2_discard1_ai():
    """【トリガー】カード2枚を引き、 自分の手札1枚を捨てる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(RED1)] * 10
    trash_before = len(me.trash)
    do, _ = _do(overlay, "OP16-057", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    # net 手札: +2 ドロー -1 捨て = +1
    assert len(me.hand) == 1, f"トリガー net (+2ドロー -1捨て) が合わない: {len(me.hand)}"
    assert len(me.trash) == trash_before + 1, "手札1枚捨てでトラッシュが1枚増えていない"


def test_op16_057_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +4000 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    p1 = InPlay.of(repo.get(PRISONER), sickness=False)
    p2 = InPlay.of(repo.get(PRISONER), sickness=False)
    me.characters = [p1, p2]
    do, _ = _do(overlay, "OP16-057", "counter")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "target_pick", \
        f"人間で target_pick modal が立たない: {st.pending_choice}"
    # 候補 = リーダー + 囚人2体 = 3 件
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 3, f"候補 (リーダー+キャラ2) が 3 件でない: {len(cands)}"


# --------------------------------------------------------------------------- #
#  OP16-058 囚人達が暴れ出したァ～～～!!! (EVENT 青 cost1):
#    【メイン】自分の場のドン!!が10枚ある場合、 自分の「インペルダウンの囚人」すべてを、
#             このターン中、 元々のパワー7000にする。
#    【カウンター】自分の「バギー」1枚までを、 このバトル中、 パワー+4000。
# --------------------------------------------------------------------------- #
def test_op16_058_main_set_prisoners_base_7000_when_don10_ai():
    """【メイン】場のドン!!10枚 → 「インペルダウンの囚人」すべての 元々パワー7000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 10  # 場のドン10枚 (= 条件成立)
    p1 = InPlay.of(repo.get(PRISONER), sickness=False)  # base 6000
    me.characters = [p1]
    do, eff = _do(overlay, "OP16-058", "main")
    assert eff.get("if", {}).get("self_don_count_eq") == 10, \
        "main の self_don_count_eq=10 条件が overlay に無い"
    assert eval_condition(eff["if"], st, me, None) is True, \
        "ドン10枚で main 条件が成立していない"
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert p1.turn_base_power_override == 7000, \
        f"「インペルダウンの囚人」の 元々パワーが 7000 になっていない: {p1.turn_base_power_override}"
    assert p1.power == 7000, f"実効パワーが 7000 でない: {p1.power}"


def test_op16_058_main_condition_false_when_don_not10():
    """場のドン!!が10枚未満 → main 条件が成立しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, _ = st.players[0], st.players[1]
    me.don_active = 8  # 8 枚 (≠10)
    _, eff = _do(overlay, "OP16-058", "main")
    assert eval_condition(eff["if"], st, me, None) is False, \
        "ドン8枚で main 条件が成立してはいけない"


def test_op16_058_counter_pump_baggy_ai():
    """【カウンター】自分の「バギー」1枚までを、 このバトル中、 パワー+4000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    baggy = InPlay.of(repo.get(BAGGY_C), sickness=False)  # バギー power 6000
    me.characters = [baggy]
    power_before = baggy.power
    do, _ = _do(overlay, "OP16-058", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert baggy.power == power_before + 4000, \
        f"「バギー」に +4000 が反映されていない: {baggy.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  OP16-059 ド派手大作戦に変更じゃァ～～～!!! (EVENT 青 cost1):
#    【メイン】自分のドン!!7枚をレストにできる：自分のデッキの上から5枚を見て、
#             パワー6000以下の特徴《インペルダウン》を持つキャラカード2枚までを登場させる。
#             その後、 残りを好きな順番でデッキの下に置く。
#    【カウンター】自分のリーダーを、 このバトル中、 パワー+3000。
# --------------------------------------------------------------------------- #
def test_op16_059_main_rest7_don_then_play_two_impel_ai():
    """【メイン】ドン!!7枚レスト → デッキ上5からインペルダウン(パワー6000以下)2枚を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, IMPEL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 7  # レストコスト用
    me.deck = [repo.get(IMPEL_C1), repo.get(IMPEL_C2)] + [repo.get(RED1)] * 20
    chars_before = len(me.characters)
    do, _ = _do(overlay, "OP16-059", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert me.don_active == 0 and me.don_rested == 7, \
        f"ドン!!7枚がレストされていない: active={me.don_active} rested={me.don_rested}"
    played = [c.card.card_id for c in me.characters]
    assert IMPEL_C1 in played and IMPEL_C2 in played, \
        f"インペルダウンキャラ2枚が登場していない: {played}"
    assert len(me.characters) == chars_before + 2, "2枚登場していない"


def test_op16_059_counter_pump_leader_ai():
    """【カウンター】自リーダーを このバトル中 +3000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, IMPEL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    power_before = me.leader.power
    do, _ = _do(overlay, "OP16-059", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert me.leader.power == power_before + 3000, \
        f"カウンターの自リーダー +3000 が反映されていない: {me.leader.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  OP16-064 コビー (CHARACTER 紫 cost1 power2000):
#    【登場時】自分のデッキの上から5枚を見て、 「コビー」以外の特徴《海軍》を持つカード1枚までを
#             公開し、 手札に加える。 その後、 残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op16_064_on_play_search_navy_to_hand_ai():
    """【登場時】デッキ上5から「コビー」以外の《海軍》1枚を手札へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(NAVY_C)] + [repo.get(RED1)] * 20  # 上5に 海軍 を1枚
    me.hand = []
    do, _ = _do(overlay, "OP16-064", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-064"), sickness=True))
    _drain(st, [0])
    assert any(c.card_id == NAVY_C for c in me.hand), \
        "デッキ上5枚から《海軍》キャラが手札に加わっていない"


def test_op16_064_on_play_search_human_modal():
    """人間 + デッキ上5に《海軍》複数 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(NAVY_C), repo.get(NAVY_C2)] + [repo.get(RED1)] * 20
    me.hand = []
    do, _ = _do(overlay, "OP16-064", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP16-064"), sickness=True))
    assert st.pending_choice is not None and \
        "search_top_n" in st.pending_choice.get("kind", ""), \
        f"人間で search_top_n modal が立たない: {st.pending_choice}"
    resolve_pending_choice(st, [0])  # 先頭 (海軍) を選択
    _drain(st, [])
    assert any(c.card_id in (NAVY_C, NAVY_C2) for c in me.hand), \
        "人間が選んだ《海軍》キャラが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP16-066 センゴク (CHARACTER 紫 cost5 power5000):
#    【登場時】自分のリーダーが特徴《海軍》を持つ場合、 ドン!!デッキからドン!!2枚までを、
#             レストで追加する。 その後、 カード2枚を引き、 自分の手札2枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op16_066_on_play_add_don_draw2_discard2_when_navy_ai():
    """【登場時】海軍リーダー → レストドン2追加 + カード2枚引き + 手札2枚捨てる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NAVY_LEADER, overlay)  # センゴク (海軍 leader)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(RED1)] * 3
    me.deck = [repo.get(RED1)] * 5
    do, eff = _do(overlay, "OP16-066", "on_play")
    assert eff.get("if", {}).get("leader_feature") == "海軍", \
        "on_play の leader_feature 条件 (海軍) が overlay に無い"
    assert eval_condition(eff["if"], st, me, None) is True, \
        "海軍リーダーで条件が成立していない"
    don_rested_before = me.don_rested
    don_remain_before = me.don_remaining_in_deck
    trash_before = len(me.trash)
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-066"), sickness=True))
    _drain(st, [0])
    assert me.don_rested == don_rested_before + 2, \
        f"ドン!!2枚がレストで追加されていない: {me.don_rested}"
    assert me.don_remaining_in_deck == don_remain_before - 2, \
        "ドンデッキが2枚減っていない"
    assert len(me.trash) == trash_before + 2, \
        f"手札2枚捨てでトラッシュが2枚増えていない: {len(me.trash)}"
    # net 手札: 開始3 + ドロー2 - 捨て2 = 3
    assert len(me.hand) == 3, f"手札 net (+2ドロー -2捨て) が合わない: {len(me.hand)}"


def test_op16_066_on_play_condition_false_when_not_navy():
    """非《海軍》リーダー → on_play の条件が成立しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # 麦わらの一味 leader
    me, _ = st.players[0], st.players[1]
    _, eff = _do(overlay, "OP16-066", "on_play")
    assert eval_condition(eff["if"], st, me, None) is False, \
        "非海軍リーダーで条件が成立してはいけない"
