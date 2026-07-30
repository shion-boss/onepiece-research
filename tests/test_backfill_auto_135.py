# -*- coding: utf-8 -*-
"""OP14 弾 効果 回帰テスト バックフィル (自動生成 wave 135):
OP14-049 / OP14-050 / OP14-052 / OP14-054 / OP14-056 / OP14-057 /
OP14-058 / OP14-059 / OP14-062 / OP14-064 の 10 枚。

目的 (= test_backfill_auto_001〜134.py と同一方針):
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
)

ROOT = Path(__file__).resolve().parent.parent


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
    """指定 card_id の overlay から when 一致の効果の (do, effect) を返す。"""
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
def test_all_op14_wave135_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP14-049", "OP14-050", "OP14-052", "OP14-054", "OP14-056",
           "OP14-057", "OP14-058", "OP14-059", "OP14-062", "OP14-064"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP14-049 ジンベエ (CHARACTER 青 cost8):
#    【登場時】(自ドン2レスト) カード2枚を引き、 コスト7以下のキャラ1枚まで 手札に戻す
#    効果で自分の手札が捨てられた時 このターン中【速攻】を得る
# --------------------------------------------------------------------------- #
def test_op14_049_on_play_draw_and_bounce_ai():
    """【登場時】2ドロー + 相手のコスト7以下キャラを手札に戻す (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 (<=7)
    opp.characters = [victim]
    opp.hand = []

    do, _ = _do(overlay, "OP14-049", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-049"), sickness=True))
    assert len(me.hand) == 2, f"登場時の2ドローが反映されていない: {len(me.hand)}"
    assert victim not in opp.characters, "コスト7以下キャラが手札に戻っていない"
    assert any(c.card_id == "OP01-016" for c in opp.hand), \
        "戻されたキャラが持ち主の手札に加わっていない"


def test_op14_049_on_play_bounce_human_pick():
    """人間 + 相手キャラ複数 → return_to_hand の target_pick modal が立ち解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    opp.characters = [a, b]
    opp.hand = []

    do, _ = _do(overlay, "OP14-049", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-049"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"相手キャラ候補が 2 件でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b not in opp.characters, "人間が選んだ相手キャラが手札に戻っていない"


def test_op14_049_hand_discarded_grants_rush_ai():
    """効果で自分の手札が捨てられた時、 このキャラは このターン中【速攻】を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    jinbe = InPlay.of(repo.get("OP14-049"), sickness=True)
    me.characters = [jinbe]

    assert "速攻" not in jinbe.granted_keywords, "初期状態で速攻を持っていてはいけない"
    do, _ = _do(overlay, "OP14-049", "on_self_hand_discarded")
    for prim in do:
        execute_effect(prim, st, me, opp, jinbe)
    assert "速攻" in jinbe.granted_keywords, \
        "手札が捨てられた時に【速攻】が付与されていない"


# --------------------------------------------------------------------------- #
#  OP14-050 チュウ (CHARACTER 青 cost1):
#    【登場時】自リーダーが特徴《魚人族》を持つ場合、 カード1枚を引く
# --------------------------------------------------------------------------- #
def test_op14_050_on_play_draw_when_fishman_ai():
    """【登場時】魚人族リーダーで 1ドロー (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP14-040", overlay)  # ジンベエ (魚人族 leader)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    assert eval_condition({"leader_feature": "魚人族"}, st, me) is True, \
        "魚人族リーダーで leader_feature 条件が成立していない"

    do, _ = _do(overlay, "OP14-050", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-050"), sickness=True))
    assert len(me.hand) == 1, "登場時 1ドローが反映されていない"


def test_op14_050_condition_false_for_non_fishman():
    """非魚人族リーダーでは leader_feature 条件が不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ロロノア・ゾロ (非魚人族)
    me = st.players[0]
    assert eval_condition({"leader_feature": "魚人族"}, st, me) is False, \
        "非魚人族リーダーで leader_feature 条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP14-052 ハンニャバル (CHARACTER 青 cost5 ブロッカー):
#    【登場時】自手札3枚を捨てられる：手札からコスト6以下の《インペルダウン》キャラ1枚まで 登場
# --------------------------------------------------------------------------- #
def test_op14_052_on_play_deploy_impel_ai():
    """【登場時】手札3枚を捨てて 手札のコスト6以下《インペルダウン》キャラを登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    # ランダム捨て 3 枚後にも 必ず インペル が残るよう ドミノ 4 枚 + fodder 3 枚
    domino = "OP02-081"  # ドミノ (vanilla インペルダウン cost2)
    me.hand = [repo.get(domino) for _ in range(4)] + [repo.get("ST01-004") for _ in range(3)]

    chars_before = len(me.characters)
    do, _ = _do(overlay, "OP14-052", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-052"), sickness=True))
    _drain(st, [0])
    assert any(c.card.card_id == domino for c in me.characters), \
        "手札のコスト6以下《インペルダウン》キャラが登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"


# --------------------------------------------------------------------------- #
#  OP14-054 フィッシャー・タイガー (CHARACTER 青 cost6):
#    【登場時】魚人族リーダーで 3ドロー / 【自ターン終了時】手札が5枚になるよう捨てる
# --------------------------------------------------------------------------- #
def test_op14_054_on_play_draw3_when_fishman_ai():
    """【登場時】魚人族リーダーで 3ドロー (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP14-040", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    assert eval_condition({"leader_feature": "魚人族"}, st, me) is True

    do, _ = _do(overlay, "OP14-054", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-054"), sickness=True))
    assert len(me.hand) == 3, f"登場時 3ドローが反映されていない: {len(me.hand)}"


def test_op14_054_end_of_turn_discard_to_5_ai():
    """【自ターン終了時】手札が5枚になるように捨てる (AI 自動、 最悪札から)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP14-040", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-016") for _ in range(7)]  # 7 枚 → 5 枚に

    do, _ = _do(overlay, "OP14-054", "end_of_turn")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-054"), sickness=False))
    assert len(me.hand) == 5, f"ターン終了時に手札が5枚に整理されていない: {len(me.hand)}"


# --------------------------------------------------------------------------- #
#  OP14-056 ワダツミ (CHARACTER 青 cost3):
#    このキャラはアタックできない (常在) / 効果で自手札が捨てられた時 このターン中 効果無効
# --------------------------------------------------------------------------- #
def test_op14_056_static_cannot_attack():
    """常在: このキャラはアタックできない (evaluate_static_effects で cannot_attack_static)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    wadatsumi = InPlay.of(repo.get("OP14-056"), sickness=False)
    me.characters = [wadatsumi]

    assert wadatsumi.cannot_attack_static is False, "初期状態で cannot_attack_static であってはいけない"
    evaluate_static_effects(st, overlay)
    assert wadatsumi.cannot_attack_static is True, \
        "常在『このキャラはアタックできない』が反映されていない"


def test_op14_056_hand_discarded_grants_negate_ai():
    """効果で自手札が捨てられた時、 このキャラは このターン中 効果が無効になる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    wadatsumi = InPlay.of(repo.get("OP14-056"), sickness=False)
    me.characters = [wadatsumi]

    do, _ = _do(overlay, "OP14-056", "on_self_hand_discarded")
    for prim in do:
        execute_effect(prim, st, me, opp, wadatsumi)
    assert "効果無効" in wadatsumi.granted_keywords, \
        "手札が捨てられた時に【効果無効】が付与されていない"


# --------------------------------------------------------------------------- #
#  OP14-057 安心せい!!わしがおる!!! (EVENT 青 cost2):
#    【メイン】自《魚人族》/《人魚族》リーダー・キャラすべて このターン中 +1000
#    【トリガー】2ドロー
# --------------------------------------------------------------------------- #
def test_op14_057_main_pump_fishman_team_ai():
    """【メイン】自《魚人族》/《人魚族》のリーダー/キャラ全体を +1000 (非該当キャラは +0)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP14-040", overlay)  # ジンベエ (魚人族 leader)
    me, opp = st.players[0], st.players[1]
    fishman = InPlay.of(repo.get("OP14-050"), sickness=False)  # チュウ 魚人族
    other = InPlay.of(repo.get("OP01-013"), sickness=False)    # サンジ (非魚人族/人魚族)
    me.characters = [fishman, other]

    leader_before = me.leader.power
    fishman_before = fishman.power
    other_before = other.power
    do, _ = _do(overlay, "OP14-057", "main")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-057"), sickness=True))
    assert me.leader.power == leader_before + 1000, \
        f"魚人族リーダーに +1000 が乗っていない: {me.leader.power}"
    assert fishman.power == fishman_before + 1000, \
        f"魚人族キャラに +1000 が乗っていない: {fishman.power}"
    assert other.power == other_before, \
        f"非該当キャラに +1000 が乗ってはいけない: {other.power}"


def test_op14_057_trigger_draw_ai():
    """【トリガー】2ドロー (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP14-040", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []

    do, _ = _do(overlay, "OP14-057", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert len(me.hand) == 2, f"トリガーの2ドローが反映されていない: {len(me.hand)}"


# --------------------------------------------------------------------------- #
#  OP14-058 海流一本背負い (EVENT 青 cost2):
#    【メイン】(自ドン3レスト) 手札からコスト3以下《魚人族》キャラ1枚まで登場、
#              その後 元々P6000キャラ1枚まで 手札に戻す
#    【カウンター】1ドロー + 自リーダー このバトル +3000
# --------------------------------------------------------------------------- #
def test_op14_058_main_deploy_and_bounce_ai():
    """【メイン】手札の《魚人族》を登場 + 相手の元々P6000キャラを手札に戻す (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # 非魚人族 leader (アーロン on_play を不発化)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("EB02-011")]  # アーロン cost3 魚人族
    victim = InPlay.of(repo.get("PRB02-008"), sickness=False)  # マルコ 元々P6000
    opp.characters = [victim]
    opp.hand = []

    do, _ = _do(overlay, "OP14-058", "main")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-058"), sickness=True))
    _drain(st, [0])
    assert any(c.card.card_id == "EB02-011" for c in me.characters), \
        "手札のコスト3以下《魚人族》キャラが登場していない"
    assert victim not in opp.characters, "元々P6000キャラが手札に戻っていない"
    assert any(c.card_id == "PRB02-008" for c in opp.hand), \
        "戻された元々P6000キャラが持ち主の手札に加わっていない"


def test_op14_058_counter_draw_and_pump_ai():
    """【カウンター】1ドロー + 自リーダー このバトル中 +3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []

    power_before = me.leader.power
    do, _ = _do(overlay, "OP14-058", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert len(me.hand) == 1, "カウンターの1ドローが反映されていない"
    assert me.leader.power == power_before + 3000, \
        f"カウンター +3000 が自リーダーに反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  OP14-059 わしも連れて行ってくれ!!!必ず役に立つ!!! (EVENT 青 cost1):
#    【メイン】自リーダーが「ジンベエ」で手札2枚以下なら 2ドロー
#    【トリガー】相手のコスト4以下キャラ1枚まで 手札に戻す
# --------------------------------------------------------------------------- #
def test_op14_059_main_draw_when_conditions_ai():
    """【メイン】ジンベエリーダー + 手札2枚以下で 2ドロー (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP14-040", overlay)  # ジンベエ leader
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-016")]  # 1 枚 (<=2)
    assert eval_condition({"leader_name": "ジンベエ"}, st, me) is True, \
        "ジンベエリーダーで leader_name 条件が成立していない"
    assert eval_condition({"self_hand_count_le": 2}, st, me) is True, \
        "手札2枚以下 条件が成立していない"

    hand_before = len(me.hand)
    do, _ = _do(overlay, "OP14-059", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert len(me.hand) == hand_before + 2, \
        f"メインの2ドローが反映されていない: {len(me.hand)}"


def test_op14_059_trigger_bounce_ai():
    """【トリガー】相手のコスト4以下キャラを手札に戻す (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 (<=4)
    opp.characters = [victim]
    opp.hand = []

    do, _ = _do(overlay, "OP14-059", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert victim not in opp.characters, "トリガーで相手のコスト4以下キャラが手札に戻っていない"
    assert any(c.card_id == "OP01-016" for c in opp.hand), \
        "戻されたキャラが持ち主の手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP14-062 グラディウス (CHARACTER 紫 cost3):
#    【KO時】(ドン-1) 相手の元々P6000以下キャラ1枚まで KO するか レストにする
# --------------------------------------------------------------------------- #
def test_op14_062_on_ko_choice_ko_ai():
    """【KO時】choice: AI (life_count heuristic、 ライフ3以上→idx0=KO) で
    相手の元々P6000以下キャラを KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-016")] * 3  # ライフ3以上 → choice heuristic が idx0(KO)を選ぶ
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # power2000 (<=6000)
    opp.characters = [victim]

    do, _ = _do(overlay, "OP14-062", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-062"), sickness=False))
    _drain(st, [0])
    assert victim not in opp.characters, \
        "KO時 choice(KO) で相手の元々P6000以下キャラが KO されていない"


def test_op14_062_on_ko_choice_human_option_pick():
    """人間: choice が option_pick modal (2択) で立ち、 KO を選ぶと相手キャラが KO される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)
    opp.characters = [victim]

    do, _ = _do(overlay, "OP14-062", "on_ko")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP14-062"), sickness=False))
    assert st.pending_choice is not None, "人間で choice modal が立たない"
    assert st.pending_choice.get("kind") == "option_pick", \
        f"kind が option_pick でない: {st.pending_choice.get('kind')}"
    opts = st.pending_choice.get("options", [])
    assert len(opts) == 2, f"選択肢 (KO/レスト) が 2 件でない: {len(opts)}"
    resolve_pending_choice(st, [0])  # KO を選択
    _drain(st, [0])
    assert victim not in opp.characters, "人間が選んだ KO が相手キャラに反映されていない"


# --------------------------------------------------------------------------- #
#  OP14-064 ジョーラ (CHARACTER 紫 cost3 power1000):
#    【KO時】ドンデッキからドン1枚までレストで追加。 その後 相手の元々P0キャラ1枚まで KO
# --------------------------------------------------------------------------- #
def test_op14_064_on_ko_add_don_and_ko_power0_ai():
    """【KO時】レストドン+1 + 相手の元々P0キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_remaining_in_deck = 10
    victim = InPlay.of(repo.get("PRB02-016"), sickness=False)  # お玉 (power '-' = 元々P0)
    opp.characters = [victim]

    rested_before = me.don_rested
    do, _ = _do(overlay, "OP14-064", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-064"), sickness=False))
    _drain(st, [0])
    assert me.don_rested == rested_before + 1, \
        f"KO時のレストドン+1が反映されていない: {me.don_rested}"
    assert victim not in opp.characters, "元々P0キャラが KO されていない"


def test_op14_064_ko_ignores_nonzero_power():
    """相手キャラの元々パワーが 0 でなければ KO 対象にならない (= 場に残る)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_remaining_in_deck = 10
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # power2000 (元々P!=0)
    opp.characters = [victim]

    do, _ = _do(overlay, "OP14-064", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-064"), sickness=False))
    _drain(st, [0])
    assert victim in opp.characters, \
        "元々パワーが0でない相手キャラが KO されてはいけない"
