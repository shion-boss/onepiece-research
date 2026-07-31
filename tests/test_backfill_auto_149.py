# -*- coding: utf-8 -*-
"""OP16 弾 (インペルダウン / 麦わらの一味 / 緑・青) 効果 回帰テスト バックフィル (自動生成 wave 149):
OP16-035 / OP16-036 / OP16-037 / OP16-039 / OP16-040 /
OP16-045 / OP16-047 / OP16-048 / OP16-049 / OP16-050 の 10 枚。

目的 (= test_backfill_auto_001〜148.py と同一方針):
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
RED1 = "OP01-016"        # ナミ 赤 cost1 power2000 (非インペルダウン フィラー)
GREEN2 = "EB01-017"      # ブルーノ 緑 cost2 power2000 (cost≥2 return コスト素材)
IMPEL_LEADER = "OP16-022"  # モンキー・Ｄ・ルフィ (インペルダウン LEADER, 緑/青)
IMPEL2 = "EB01-026"      # プリンス・ベレット (インペルダウン cost2 play_from_hand 素材)
LUFFY_C = "OP16-052"     # モンキー・Ｄ・ルフィ (CHARACTER インペルダウン cost2 power3000)
MR3 = "OP16-037"         # Mr.3(ギャルディーノ) (cost2 power3000)
PRISONER = "OP16-042"    # インペルダウンの囚人 (cost6 power6000)


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
def test_all_op16_wave149_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP16-035", "OP16-036", "OP16-037", "OP16-039", "OP16-040",
           "OP16-045", "OP16-047", "OP16-048", "OP16-049", "OP16-050"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP16-035 ロロノア・ゾロ (CHARACTER 緑 cost7 power9000):
#    【登場時】相手のカード1枚までをレスト。 その後、手札1枚を捨ててもよい：
#             自リーダーにレストのドン!!3枚までを付与。
# --------------------------------------------------------------------------- #
def test_op16_035_on_play_rest_then_attach_rested_don_ai():
    """【登場時】相手キャラ1枚をレスト + (任意)手札1捨てて自リーダーにレストドン3付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, IMPEL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(RED1), sickness=False)  # 相手キャラ
    opp.characters = [victim]
    me.hand = [repo.get(RED1)]   # 捨てるコスト用
    me.don_rested = 3            # 付与するレストドン供給源
    don_before = me.leader.attached_dons
    hand_before = len(me.hand)
    do, _ = _do(overlay, "OP16-035", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-035"), sickness=True))
    _drain(st, [0])
    assert victim.rested is True, "登場時に相手キャラがレストされていない"
    assert me.leader.attached_dons == don_before + 3, \
        f"自リーダーにレストドン3枚が付与されていない: {me.leader.attached_dons}"
    assert me.don_rested == 0, "付与コストでレストドン3枚が消費されるべき"
    assert len(me.hand) == hand_before - 1, "任意コストで手札1枚が捨てられるべき"


def test_op16_035_on_play_rest_human_pick():
    """人間 + 相手リーダー/キャラ 複数 → rest の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, IMPEL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    opp.characters = [InPlay.of(repo.get(RED1), sickness=False)]
    do, _ = _do(overlay, "OP16-035", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP16-035"), sickness=True))
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "target_pick", \
        f"人間で rest の target_pick modal が立たない: {st.pending_choice}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (相手リーダー+キャラ) が 2 件でない: {len(cands)}"


# --------------------------------------------------------------------------- #
#  OP16-036 Mr.2・ボン・クレー (CHARACTER 緑 cost4 power1000):
#    【登場時】相手のコスト4以下のキャラ1枚までをレスト。
#    【アタック時】このキャラの元々のパワーは、 このターン中、 相手のリーダーと同じパワーになる。
# --------------------------------------------------------------------------- #
def test_op16_036_on_play_rest_cost_le4_ai():
    """【登場時】相手コスト4以下キャラ1枚をレスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(GREEN2), sickness=False)  # cost2 (≤4)
    opp.characters = [victim]
    do, _ = _do(overlay, "OP16-036", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-036"), sickness=True))
    _drain(st, [0])
    assert victim.rested is True, "相手コスト4以下キャラがレストされていない"


def test_op16_036_on_attack_set_base_power_copy_leader():
    """【アタック時】自身の元々のパワーが 相手リーダーと同じ (このターン中) になる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, opp_leader_id="OP01-001")
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("OP16-036"), sickness=False)  # base 1000
    me.characters = [attacker]
    opp_leader_power = opp.leader.power  # OP01-001 = 5000
    do, _ = _do(overlay, "OP16-036", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp, attacker)
    assert attacker.turn_base_power_override == opp_leader_power, \
        f"自身の元々のパワーが 相手リーダー値に複写されていない: {attacker.turn_base_power_override}"
    assert attacker.power == opp_leader_power, \
        f"実効パワーが 相手リーダーと同じになっていない: {attacker.power} (leader {opp_leader_power})"


def test_op16_036_on_play_rest_human_pick():
    """人間 + 相手コスト4以下キャラ 複数 → target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    opp.characters = [
        InPlay.of(repo.get(RED1), sickness=False),   # cost1
        InPlay.of(repo.get(GREEN2), sickness=False),  # cost2
    ]
    do, _ = _do(overlay, "OP16-036", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP16-036"), sickness=True))
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "target_pick", \
        f"人間で target_pick modal が立たない: {st.pending_choice}"


# --------------------------------------------------------------------------- #
#  OP16-037 Mr.3(ギャルディーノ) (CHARACTER 緑 cost2 power3000):
#    【登場時】自分のリーダーが《インペルダウン》を持つ場合、 相手のコスト5以下のキャラ1枚をレスト。
# --------------------------------------------------------------------------- #
def test_op16_037_on_play_condition_and_rest_ai():
    """【登場時】インペルダウンリーダーで条件成立 → 相手コスト5以下キャラ1枚レスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, IMPEL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(GREEN2), sickness=False)  # cost2 (≤5)
    opp.characters = [victim]
    do, eff = _do(overlay, "OP16-037", "on_play")
    assert eff.get("if", {}).get("leader_feature") == "インペルダウン", \
        "on_play の leader_feature 条件 (インペルダウン) が overlay に無い"
    assert eval_condition(eff["if"], st, me, None) is True, \
        "インペルダウンリーダーで条件が成立していない"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-037"), sickness=True))
    _drain(st, [0])
    assert victim.rested is True, "条件成立時に相手コスト5以下キャラがレストされていない"


def test_op16_037_on_play_condition_false_when_not_impel():
    """非《インペルダウン》リーダー → on_play の条件が成立しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ (麦わらの一味)
    me, _ = st.players[0], st.players[1]
    _, eff = _do(overlay, "OP16-037", "on_play")
    assert eval_condition(eff["if"], st, me, None) is False, \
        "非インペルダウンリーダーで条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP16-039 ゴムゴムのツインJET銃 (EVENT 緑 cost1):
#    【メイン】自分の「モンキー・Ｄ・ルフィ」1枚までにダブルアタック(turn)。 その後、
#             リーダーが《インペルダウン》なら相手コスト3以下キャラ2枚までをレスト。
#    【トリガー】相手のリーダーをレストにする。
# --------------------------------------------------------------------------- #
def test_op16_039_main_double_attack_and_rest_two_ai():
    """【メイン】自ルフィにダブルアタック + (インペルダウン条件) 相手コスト3以下2枚レスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, IMPEL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get(LUFFY_C), sickness=False)  # モンキー・Ｄ・ルフィ
    me.characters = [luffy]
    v1 = InPlay.of(repo.get(RED1), sickness=False)   # cost1
    v2 = InPlay.of(repo.get(GREEN2), sickness=False)  # cost2
    opp.characters = [v1, v2]
    do, _ = _do(overlay, "OP16-039", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert "ダブルアタック" in luffy.granted_keywords, \
        "自ルフィにダブルアタックが付与されていない"
    assert v1.rested and v2.rested, \
        f"インペルダウン条件下で相手コスト3以下2枚がレストされていない: v1={v1.rested} v2={v2.rested}"


def test_op16_039_main_rest_skipped_when_not_impel():
    """非インペルダウンリーダー → その後のレストは発生しない (conditional 不成立)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # 非インペルダウン
    me, opp = st.players[0], st.players[1]
    v1 = InPlay.of(repo.get(RED1), sickness=False)
    opp.characters = [v1]
    do, _ = _do(overlay, "OP16-039", "main")
    # do[1] = conditional { if leader_feature インペルダウン → rest_multi }
    conditional = next(p for p in do if "conditional" in p)
    execute_effect(conditional, st, me, opp, None)
    _drain(st, [0])
    assert v1.rested is False, "非インペルダウンリーダーで相手キャラがレストされてはいけない"


def test_op16_039_trigger_rest_opponent_leader_ai():
    """【トリガー】相手のリーダーをレストにする。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, IMPEL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    assert opp.leader.rested is False
    do, _ = _do(overlay, "OP16-039", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert opp.leader.rested is True, "トリガーで相手リーダーがレストされていない"


# --------------------------------------------------------------------------- #
#  OP16-040 ゴムゴムのトンカチ回転銃 (EVENT 緑 cost1):
#    【メイン】「ルフィ」と「Mr.3(ギャルディーノ)」がいる場合、 相手のレストのコスト6以下キャラ1枚は
#             次の相手リフレッシュでアクティブにならない。
#    【カウンター】自リーダーをこのバトル中パワー+3000。
# --------------------------------------------------------------------------- #
def test_op16_040_main_keep_opp_rested_when_both_present_ai():
    """【メイン】ルフィ+Mr.3 在場 → 相手レストコスト6以下キャラに stay_rested (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, IMPEL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [
        InPlay.of(repo.get(LUFFY_C), sickness=False),  # モンキー・Ｄ・ルフィ
        InPlay.of(repo.get(MR3), sickness=False),       # Mr.3(ギャルディーノ)
    ]
    victim = InPlay.of(repo.get(GREEN2), sickness=False)  # cost2 (≤6)
    victim.rested = True
    opp.characters = [victim]
    do, eff = _do(overlay, "OP16-040", "main")
    assert eval_condition(eff["if"], st, me, None) is True, \
        "ルフィ+Mr.3 在場で main 条件が成立していない"
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim.stay_rested_next_refresh is True, \
        "相手レストキャラに stay_rested_next_refresh が付いていない"


def test_op16_040_main_condition_false_without_both():
    """ルフィ or Mr.3 のどちらか不在 → main 条件が成立しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, IMPEL_LEADER, overlay)
    me, _ = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(LUFFY_C), sickness=False)]  # Mr.3 不在
    _, eff = _do(overlay, "OP16-040", "main")
    assert eval_condition(eff["if"], st, me, None) is False, \
        "Mr.3 不在で main 条件が成立してはいけない"


def test_op16_040_counter_pump_leader_ai():
    """【カウンター】自リーダーをこのバトル中 +3000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, IMPEL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    power_before = me.leader.power
    do, _ = _do(overlay, "OP16-040", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert me.leader.power == power_before + 3000, \
        f"カウンターの自リーダー +3000 が反映されていない: {me.leader.power} (before {power_before})"


def test_op16_040_main_keep_opp_human_pick():
    """人間 + 相手レストコスト6以下キャラ 複数 → target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, IMPEL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.characters = [
        InPlay.of(repo.get(LUFFY_C), sickness=False),
        InPlay.of(repo.get(MR3), sickness=False),
    ]
    v1 = InPlay.of(repo.get(RED1), sickness=False)
    v2 = InPlay.of(repo.get(GREEN2), sickness=False)
    v1.rested = True
    v2.rested = True
    opp.characters = [v1, v2]
    do, _ = _do(overlay, "OP16-040", "main")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "target_pick", \
        f"人間で target_pick modal が立たない: {st.pending_choice}"


# --------------------------------------------------------------------------- #
#  OP16-045 クロコダイル (CHARACTER 青 cost4 power6000, ブロッカー):
#    【登場時】自分のコスト2以上のキャラ1枚を手札に戻す：
#             手札からコスト2以下の《インペルダウン》キャラ1枚までを登場。
# --------------------------------------------------------------------------- #
def test_op16_045_on_play_bounce_then_play_impel_ai():
    """【登場時】自コスト2以上キャラを手札に戻す + 手札のインペルダウンcost2以下を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    bounce = InPlay.of(repo.get(GREEN2), sickness=False)  # cost2 (≥2 = 戻す対象)
    me.characters = [bounce]
    me.hand = [repo.get(IMPEL2)]  # インペルダウン cost2 (= 登場対象)
    do, _ = _do(overlay, "OP16-045", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-045"), sickness=True))
    _drain(st, [0])
    assert bounce not in me.characters, "コスト2以上のキャラが手札に戻されていない"
    assert any(c.card.card_id == IMPEL2 for c in me.characters), \
        "手札からインペルダウン cost2以下キャラが登場していない"
    assert any(c.card_id == GREEN2 for c in me.hand), \
        "戻したキャラが手札に加わっていない"


def test_op16_045_on_play_human_optional_cost_confirm():
    """人間 → optional_cost_confirm modal が立つ (任意コストの pay/skip を委ねる)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(GREEN2), sickness=False)]
    me.hand = [repo.get(IMPEL2)]
    do, _ = _do(overlay, "OP16-045", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP16-045"), sickness=True))
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"人間で optional_cost_confirm modal が立たない: {st.pending_choice}"


# --------------------------------------------------------------------------- #
#  OP16-047 ドンキホーテ・ドフラミンゴ (CHARACTER 青 cost3):
#    【起動メイン】このキャラをレストにできる：相手の手札が8枚以上ある場合、
#                 相手は手札2枚をデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op16_047_activate_main_hand_to_deck_when_ge8_ai():
    """【起動メイン】相手手札8枚以上 → 自レスト + 相手手札2枚をデッキ下 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    doffy = InPlay.of(repo.get("OP16-047"), sickness=False)
    me.characters = [doffy]
    opp.hand = [repo.get(RED1)] * 8  # 8 枚 (= 条件成立)
    opp.deck = [repo.get(RED1)] * 10
    opp_hand_before = len(opp.hand)
    opp_deck_before = len(opp.deck)
    options = list_activate_main_effects(st, me, overlay)
    doffy_opts = [(src, e) for (src, e) in options
                  if src.card.card_id == "OP16-047"]
    assert len(doffy_opts) == 1, \
        f"OP16-047 の起動メインが legal に出ない: {len(doffy_opts)}"
    fire_activate_main(st, me, opp, *doffy_opts[0])
    _drain(st, [0])
    assert doffy.rested is True, "起動メインコストで自身がレストされるべき"
    assert len(opp.hand) == opp_hand_before - 2, \
        f"相手手札2枚がデッキ下へ移っていない: {len(opp.hand)}"
    assert len(opp.deck) == opp_deck_before + 2, \
        f"相手デッキが2枚増えていない: {len(opp.deck)}"


def test_op16_047_activate_main_absent_when_hand_lt8():
    """相手手札8枚未満 → 条件不成立で起動メインが legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP16-047"), sickness=False)]
    opp.hand = [repo.get(RED1)] * 5  # 5 枚 (< 8)
    options = list_activate_main_effects(st, me, overlay)
    doffy_opts = [(src, e) for (src, e) in options
                  if src.card.card_id == "OP16-047"]
    assert len(doffy_opts) == 0, \
        "相手手札8枚未満で起動メインが legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP16-048 バギー (CHARACTER 青 cost5 power6000):
#    【登場時】リーダーが《インペルダウン》なら、 カード1枚を引き、
#             手札から「インペルダウンの囚人」1枚までを登場。
#    【ターン1回】相手がアタックした時：自分の「インペルダウンの囚人」1枚は【ブロッカー】を得る(turn)。
# --------------------------------------------------------------------------- #
def test_op16_048_on_play_draw_and_play_prisoner_ai():
    """【登場時】インペルダウンリーダー → 1ドロー + 手札の「インペルダウンの囚人」を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, IMPEL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(PRISONER)]  # インペルダウンの囚人
    me.deck = [repo.get(RED1)] * 5
    chars_before = len(me.characters)
    deck_before = len(me.deck)
    do, eff = _do(overlay, "OP16-048", "on_play")
    assert eff.get("if", {}).get("leader_feature") == "インペルダウン", \
        "on_play の leader_feature 条件 (インペルダウン) が overlay に無い"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-048"), sickness=True))
    _drain(st, [0])
    assert len(me.deck) == deck_before - 1, "1ドローでデッキが1枚減っていない"
    assert any(c.card.name == "インペルダウンの囚人" for c in me.characters), \
        "手札の「インペルダウンの囚人」が登場していない"
    assert len(me.characters) == chars_before + 1, "囚人が1体登場していない"


def test_op16_048_opp_attack_give_blocker_to_prisoner_ai():
    """【相手アタック時】自分の「インペルダウンの囚人」に【ブロッカー】(turn) を付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, IMPEL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    prisoner = InPlay.of(repo.get(PRISONER), sickness=False)
    me.characters = [prisoner]
    do, _ = _do(overlay, "OP16-048", "opp_attack")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-048"), sickness=False))
    _drain(st, [0])
    assert "ブロッカー" in prisoner.granted_keywords, \
        "「インペルダウンの囚人」にブロッカーが付与されていない"


# --------------------------------------------------------------------------- #
#  OP16-049 ポートガス・Ｄ・エース (CHARACTER 青 cost3):
#    【起動メイン】このキャラをレストにできる：カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op16_049_activate_main_rest_then_draw_ai():
    """【起動メイン】自レスト → 1ドロー (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    ace = InPlay.of(repo.get("OP16-049"), sickness=False)
    me.characters = [ace]
    me.hand = []
    me.deck = [repo.get(RED1)] * 5
    deck_before = len(me.deck)
    options = list_activate_main_effects(st, me, overlay)
    ace_opts = [(src, e) for (src, e) in options
                if src.card.card_id == "OP16-049"]
    assert len(ace_opts) == 1, \
        f"OP16-049 の起動メインが legal に出ない: {len(ace_opts)}"
    fire_activate_main(st, me, opp, *ace_opts[0])
    _drain(st, [0])
    assert ace.rested is True, "起動メインコストで自身がレストされるべき"
    assert len(me.hand) == 1, "起動メインの1ドローが起きていない"
    assert len(me.deck) == deck_before - 1, "1ドローでデッキが1枚減っていない"


def test_op16_049_activate_main_once_per_turn():
    """起動メインは【ターン1回】相当 (= 一度発動したら再び legal に出ない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    ace = InPlay.of(repo.get("OP16-049"), sickness=False)
    me.characters = [ace]
    me.deck = [repo.get(RED1)] * 5
    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP16-049"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])
    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP16-049"]
    assert len(opts2) == 0, \
        "起動メインを一度発動した後 (レスト済) は再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP16-050 ミス・オリーブ (CHARACTER 青 cost5 power6000, ブロッカー):
#    【登場時】自分のコスト2以上のキャラ1枚を手札に戻す：カード2枚を引き、 自分の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op16_050_on_play_bounce_then_draw2_discard1_ai():
    """【登場時】自コスト2以上キャラを手札に戻す + カード2枚引き 手札1枚捨てる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    bounce = InPlay.of(repo.get(GREEN2), sickness=False)  # cost2 (≥2 = 戻す対象)
    me.characters = [bounce]
    me.hand = []
    me.deck = [repo.get(RED1)] * 5
    deck_before = len(me.deck)
    trash_before = len(me.trash)
    do, _ = _do(overlay, "OP16-050", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-050"), sickness=True))
    _drain(st, [0])
    assert bounce not in me.characters, "コスト2以上のキャラが手札に戻されていない"
    assert len(me.deck) == deck_before - 2, \
        f"カード2枚ドローでデッキが2枚減っていない: {len(me.deck)}"
    assert len(me.trash) == trash_before + 1, \
        f"手札1枚捨てでトラッシュが1枚増えていない: {len(me.trash)}"
    # net 手札: 戻す +1、 ドロー +2、 捨て -1 = +2
    assert len(me.hand) == 2, f"手札 net (+1戻す +2ドロー -1捨て) が合わない: {len(me.hand)}"


def test_op16_050_on_play_human_optional_cost_confirm():
    """人間 → optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(GREEN2), sickness=False)]
    me.hand = []
    me.deck = [repo.get(RED1)] * 5
    do, _ = _do(overlay, "OP16-050", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP16-050"), sickness=True))
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"人間で optional_cost_confirm modal が立たない: {st.pending_choice}"
