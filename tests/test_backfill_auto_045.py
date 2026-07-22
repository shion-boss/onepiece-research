# -*- coding: utf-8 -*-
"""OP04 (赤 アラバスタ王国 + 緑) 効果 回帰テスト バックフィル (自動生成 wave 045):
OP04-010 / OP04-011 / OP04-012 / OP04-015 / OP04-016 / OP04-017 /
OP04-018 / OP04-019 / OP04-020 / OP04-021 の 10 枚。

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


def _all_eff(overlay, cid, when):
    return [e for e in overlay.get(cid).effects if e["when"] == when]


def _drain(st, sel=None, guard=8):
    """pending_choice を sel (既定 [0]) で解決し続ける (人間チェーン用)。"""
    if sel is None:
        sel = [0]
    g = 0
    while st.pending_choice is not None and g < guard:
        resolve_pending_choice(st, sel)
        g += 1


def _arabasta_leader_id(repo):
    """特徴《アラバスタ王国》を持つ LEADER (パラレル除外) を1つ返す。"""
    for c in repo._by_id.values():
        if c.category.name == "LEADER" \
                and "アラバスタ王国" in (c.features or ()) \
                and "_p" not in c.card_id and "_r" not in c.card_id:
            return c.card_id
    raise AssertionError("アラバスタ王国 特徴リーダーが見つからない")


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave45_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP04-010", "OP04-011", "OP04-012", "OP04-015", "OP04-016",
           "OP04-017", "OP04-018", "OP04-019", "OP04-020", "OP04-021"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP04-010 トニートニー・チョッパー (CHARACTER 赤 cost3):
#    【登場時】自分の手札からパワー3000以下の特徴《動物》を持つキャラカード1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op04_010_on_play_play_animal_from_hand_ai():
    """【登場時】手札のパワー3000以下《動物》キャラ1枚を場に登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("ST01-006")]  # チョッパー 動物 power1000 (<=3000)
    chars_before = len(me.characters)

    on_play = _get_eff(overlay, "OP04-010", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-010"), sickness=True))
        _drain(st, [0])

    assert len(me.characters) == chars_before + 1, \
        "手札の《動物》キャラが場に登場していない"
    assert any(c.card.card_id == "ST01-006" for c in me.characters), \
        "登場したのが対象の《動物》キャラでない"
    assert len(me.hand) == 0, "登場させたカードが手札に残っている"


def test_op04_010_on_play_human_context_no_crash():
    """人間 actor 文脈でも 手札の《動物》キャラ登場が crash せず適用される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("ST01-006")]

    on_play = _get_eff(overlay, "OP04-010", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-010"), sickness=True))
        _drain(st, [0])

    assert any(c.card.card_id == "ST01-006" for c in me.characters), \
        "人間文脈で《動物》キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP04-011 ナミ (CHARACTER 赤 cost2):
#    【アタック時】自分のデッキの上から1枚を公開し、 公開したカードがパワー6000以上の
#      キャラカードだった場合、 このキャラは、 このターン中、 パワー+3000。
#      その後、 公開したカードをデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op04_011_on_attack_reveal_pump_when_power_ge6000_ai():
    """【アタック時】デッキ上がパワー6000+キャラ → 自身+3000、 公開札はデッキ下 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("OP04-011"), sickness=False)
    me.characters = [attacker]
    me.deck = [repo.get("EB01-012")] + [repo.get("OP01-013")] * 10  # top = power6000
    power_before = attacker.power

    on_attack = _get_eff(overlay, "OP04-011", "on_attack")
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp, attacker)
        _drain(st, [0])

    assert attacker.power == power_before + 3000, \
        f"パワー6000+公開時 自身+3000 が反映されていない: {attacker.power}"
    assert me.deck[-1].card_id == "EB01-012", \
        "公開したカードがデッキの下に置かれていない"


def test_op04_011_on_attack_no_pump_when_power_lt6000():
    """デッキ上がパワー6000未満なら +3000 は乗らない (公開札はデッキ下)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("OP04-011"), sickness=False)
    me.characters = [attacker]
    me.deck = [repo.get("OP01-013")] + [repo.get("OP01-016")] * 10  # top = power2000
    power_before = attacker.power

    on_attack = _get_eff(overlay, "OP04-011", "on_attack")
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp, attacker)
        _drain(st, [0])

    assert attacker.power == power_before, \
        f"6000未満なのに +3000 が乗っている: {attacker.power}"


# --------------------------------------------------------------------------- #
#  OP04-012 ネフェルタリ・コブラ (CHARACTER 赤 cost2):
#    【自分のターン中】このキャラ以外の自分の特徴《アラバスタ王国》を持つキャラすべてを、
#      パワー+1000。
# --------------------------------------------------------------------------- #
def test_op04_012_static_buff_other_arabasta_on_turn():
    """自ターン中、 自身以外の《アラバスタ王国》キャラすべて +1000 (自身は対象外)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    cobra = InPlay.of(repo.get("OP04-012"), sickness=False)
    neko = InPlay.of(repo.get("OP15-004"), sickness=False)  # アラバスタ王国 base power0
    me.characters = [cobra, neko]
    neko_base = neko.card.power

    evaluate_static_effects(st, overlay)

    assert neko.power == neko_base + 1000, \
        f"他の《アラバスタ王国》キャラに +1000 が乗っていない: {neko.power}"
    assert cobra.power == cobra.card.power, \
        f"自身(コブラ)に +1000 が乗ってはいけない: {cobra.power}"


def test_op04_012_static_no_buff_off_turn():
    """相手ターン中は【自分のターン中】条件が不成立 → +1000 は乗らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    st.turn_player_idx = 1  # 相手ターン
    cobra = InPlay.of(repo.get("OP04-012"), sickness=False)
    neko = InPlay.of(repo.get("OP15-004"), sickness=False)
    me.characters = [cobra, neko]

    evaluate_static_effects(st, overlay)

    assert neko.power == neko.card.power, \
        f"相手ターンで +1000 が乗ってはいけない: {neko.power}"


# --------------------------------------------------------------------------- #
#  OP04-015 ロロノア・ゾロ (CHARACTER 赤 cost5):
#    【登場時】相手のキャラ1枚までを、 このターン中、 パワー-2000。
# --------------------------------------------------------------------------- #
def test_op04_015_on_play_debuff_opp_ai():
    """【登場時】相手キャラ1枚を このターン中 パワー-2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # power3000
    opp.characters = [victim]
    power_before = victim.power

    on_play = _get_eff(overlay, "OP04-015", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-015"), sickness=True))
        _drain(st, [0])

    assert victim.power == power_before - 2000, \
        f"相手キャラ -2000 が反映されていない: {victim.power}"


def test_op04_015_on_play_human_target_pick():
    """人間 actor: -2000 対象の target_pick modal が立ち、 解決で弱体化。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [victim]
    power_before = victim.power

    on_play = _get_eff(overlay, "OP04-015", "on_play")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP04-015"), sickness=True))

    assert st.pending_choice is not None, "人間 + 対象選択で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    assert victim.power == power_before - 2000, \
        "人間選択後 相手キャラ -2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP04-016 反行儀キックコース (EVENT 赤):
#    【カウンター】自分の手札1枚を捨てることができる：自分のリーダーかキャラ1枚までを、
#      このバトル中、 パワー+3000。
#    【トリガー】相手のリーダーかキャラ1枚までを、 このターン中、 パワー-3000。
# --------------------------------------------------------------------------- #
def test_op04_016_trigger_debuff_opp_ai():
    """【トリガー】相手キャラ1枚を このターン中 パワー-3000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # power3000
    opp.characters = [victim]
    power_before = victim.power

    on_trig = _get_eff(overlay, "OP04-016", "trigger")
    for prim in on_trig["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-016"), sickness=True))
        _drain(st, [0])

    assert victim.power == power_before - 3000, \
        f"トリガーで相手キャラ -3000 が反映されていない: {victim.power}"


def test_op04_016_counter_discard_cost_ai():
    """【カウンター】任意コストの手札1枚捨てが払われる (AI 自動、 crash しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]
    hand_before = len(me.hand)

    on_counter = _get_eff(overlay, "OP04-016", "counter")
    for prim in on_counter["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-016"), sickness=True))
        _drain(st, [1])  # 任意コストは AI が承諾

    assert len(me.hand) == hand_before - 1, \
        f"任意コストの手札1枚捨てが払われていない: {len(me.hand)}"


def test_op04_016_counter_human_optional_confirm():
    """人間 actor: カウンター任意コスト → optional_cost_confirm modal が立ち、 承諾で手札-1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]
    hand_before = len(me.hand)

    on_counter = _get_eff(overlay, "OP04-016", "counter")
    execute_effect(on_counter["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP04-016"), sickness=True))

    assert st.pending_choice is not None, "人間 + 任意コストで確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert len(me.hand) == hand_before - 1, "人間承諾後 手札1枚が捨てられていない"


# --------------------------------------------------------------------------- #
#  OP04-017 幸せパンチ (EVENT 赤 cost1):
#    【カウンター】相手のリーダーかキャラ1枚までを、 このターン中、 パワー-2000。
#      その後、 自分のリーダーがアクティブの場合、 相手のリーダーかキャラ1枚までを、
#      このターン中、 パワー-1000。
# --------------------------------------------------------------------------- #
def test_op04_017_counter_debuff_2000_ai():
    """【カウンター】1つ目: 相手キャラ -2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # power3000
    opp.characters = [victim]
    power_before = victim.power

    first = _all_eff(overlay, "OP04-017", "counter")[0]
    for prim in first["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-017"), sickness=True))
        _drain(st, [0])

    assert victim.power == power_before - 2000, \
        f"1つ目のカウンターで相手 -2000 が反映されていない: {victim.power}"


def test_op04_017_second_debuff_condition_leader_active():
    """2つ目の -1000 は 自リーダーがアクティブの場合のみ条件成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    second = _all_eff(overlay, "OP04-017", "counter")[1]
    assert second.get("if", {}).get("self_leader_active") is True, \
        "overlay の 自リーダーアクティブ 条件が無い"

    me.leader.rested = False
    assert eval_condition(second["if"], st, me) is True, \
        "リーダーアクティブで 2つ目の条件が成立しない"

    me.leader.rested = True
    assert eval_condition(second["if"], st, me) is False, \
        "リーダーレストなのに 2つ目の条件が成立している"


def test_op04_017_second_debuff_applies_when_active_ai():
    """自リーダーアクティブ時、 2つ目の 相手 -1000 が適用される (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.rested = False
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [victim]
    power_before = victim.power

    second = _all_eff(overlay, "OP04-017", "counter")[1]
    assert eval_condition(second["if"], st, me) is True
    for prim in second["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-017"), sickness=True))
        _drain(st, [0])

    assert victim.power == power_before - 1000, \
        f"リーダーアクティブ時 2つ目の -1000 が反映されていない: {victim.power}"


# --------------------------------------------------------------------------- #
#  OP04-018 魅惑のメマーイダンス (EVENT 赤 cost3):
#    【メイン】自分のリーダーが特徴《アラバスタ王国》を持つ場合、 相手のキャラ2枚までを、
#      このターン中、 パワー-2000。
#    【トリガー】このカードの【メイン】効果を発動する。
# --------------------------------------------------------------------------- #
def test_op04_018_main_debuff_two_when_arabasta_leader_ai():
    """【メイン】(自リーダー アラバスタ王国) 相手キャラ2枚 -2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    leader = _arabasta_leader_id(repo)
    st = _state(repo, leader, overlay)
    me, opp = st.players[0], st.players[1]
    v1 = InPlay.of(repo.get("OP01-013"), sickness=False)  # power3000
    v2 = InPlay.of(repo.get("OP01-016"), sickness=False)  # power2000
    opp.characters = [v1, v2]
    p1b, p2b = v1.power, v2.power

    on_main = _get_eff(overlay, "OP04-018", "main")
    assert eval_condition(on_main["if"], st, me) is True, \
        "テスト前提: 自リーダー アラバスタ王国 で条件成立していない"
    for prim in on_main["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-018"), sickness=True))
        _drain(st, [0])

    assert v1.power == p1b - 2000 and v2.power == p2b - 2000, \
        f"相手2枚 -2000 が反映されていない: {v1.power}, {v2.power}"


def test_op04_018_main_condition_false_non_arabasta_leader():
    """自リーダーが《アラバスタ王国》でなければ【メイン】条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ルフィ (アラバスタ王国 でない)
    me = st.players[0]
    on_main = _get_eff(overlay, "OP04-018", "main")
    assert eval_condition(on_main["if"], st, me) is False, \
        "非アラバスタ王国 リーダーで条件が成立している"


def test_op04_018_trigger_fires_main_ai():
    """【トリガー】自身の【メイン】効果を再発火 (アラバスタ王国 リーダーで相手 -2000)。"""
    repo = _repo()
    overlay = _overlay()
    leader = _arabasta_leader_id(repo)
    st = _state(repo, leader, overlay)
    me, opp = st.players[0], st.players[1]
    st.current_source_card_id = "OP04-018"
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [victim]
    power_before = victim.power

    on_trig = _get_eff(overlay, "OP04-018", "trigger")
    for prim in on_trig["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-018"), sickness=True))
        _drain(st, [0])

    assert victim.power == power_before - 2000, \
        f"トリガーで【メイン】が再発火し相手 -2000 が反映されていない: {victim.power}"


# --------------------------------------------------------------------------- #
#  OP04-019 ドンキホーテ・ドフラミンゴ (LEADER 緑/紫):
#    【自分のターン終了時】自分のドン!!2枚までを、 アクティブにする。
# --------------------------------------------------------------------------- #
def test_op04_019_end_of_turn_untap_don_ai():
    """【自分のターン終了時】レストのドン!!2枚をアクティブにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP04-019", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 5
    me.don_active = 0
    rested_before = me.don_rested

    on_eot = _get_eff(overlay, "OP04-019", "end_of_turn")
    for prim in on_eot["do"]:
        execute_effect(prim, st, me, opp, me.leader)
        _drain(st, [0])

    assert me.don_rested == rested_before - 2, \
        f"レストのドン!!2枚がアクティブにされていない: rested={me.don_rested}"
    assert me.don_active == 2, \
        f"アクティブのドン!!が+2でない: active={me.don_active}"


# --------------------------------------------------------------------------- #
#  OP04-020 イッショウ (LEADER 緑/黒):
#    【ドン!!×1】【自分のターン中】相手のキャラすべてを、 コスト-1。
#    【自分のターン終了時】➀：自分のコスト5以下のキャラ1枚までを、 アクティブにする。
# --------------------------------------------------------------------------- #
def test_op04_020_static_opp_cost_minus_on_turn():
    """【ドン!!×1】【自分のターン中】相手キャラすべて コスト-1 (静的)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP04-020", overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 1  # ドン!!×1 ゲート成立
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # base cost2
    opp.characters = [victim]
    base_cost = victim.card.cost

    evaluate_static_effects(st, overlay)

    assert victim.base_cost == base_cost - 1, \
        f"相手キャラ コスト-1 が反映されていない: {victim.base_cost} (base {base_cost})"


def test_op04_020_static_no_cost_minus_off_turn():
    """相手ターン中は【自分のターン中】条件が不成立 → コスト-1 は乗らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP04-020", overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1  # 相手ターン
    me.leader.attached_dons = 1
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [victim]

    evaluate_static_effects(st, overlay)

    assert victim.base_cost == victim.card.cost, \
        f"相手ターンで コスト-1 が乗ってはいけない: {victim.base_cost}"


def test_op04_020_end_of_turn_untap_chara_ai():
    """【自分のターン終了時】コスト5以下のキャラ1枚をアクティブにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP04-020", overlay)
    me, opp = st.players[0], st.players[1]
    myc = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost低め (<=5)
    myc.rested = True
    me.characters = [myc]

    on_eot = _get_eff(overlay, "OP04-020", "end_of_turn")
    for prim in on_eot["do"]:
        execute_effect(prim, st, me, opp, me.leader)
        _drain(st, [0])

    assert myc.rested is False, \
        "コスト5以下のキャラがアクティブにされていない"


def test_op04_020_end_of_turn_untap_human_target_pick():
    """人間 actor: アクティブ対象の target_pick modal が立ち、 解決でアクティブ化。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP04-020", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    myc = InPlay.of(repo.get("OP01-016"), sickness=False)
    myc.rested = True
    me.characters = [myc]

    on_eot = _get_eff(overlay, "OP04-020", "end_of_turn")
    execute_effect(on_eot["do"][0], st, me, opp, me.leader)

    assert st.pending_choice is not None, "人間 + 対象選択で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    assert myc.rested is False, "人間選択後 キャラがアクティブにされていない"


# --------------------------------------------------------------------------- #
#  OP04-021 ヴィオラ (CHARACTER 緑 cost3):
#    【相手のアタック時】➁：相手のドン!!1枚までを、 レストにする。
# --------------------------------------------------------------------------- #
def test_op04_021_opp_attack_optcost_rest_opp_don_ai():
    """【相手のアタック時】(任意コスト ➁) 自ドン2レスト → 相手ドン1レスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    viola = InPlay.of(repo.get("OP04-021"), sickness=False)
    me.characters = [viola]
    me.don_active = 3
    me.don_rested = 0
    opp.don_active = 3
    opp.don_rested = 0

    on_oa = _get_eff(overlay, "OP04-021", "opp_attack")
    for prim in on_oa["do"]:
        execute_effect(prim, st, me, opp, viola)
        _drain(st, [1])  # 任意コストは AI が承諾

    assert me.don_rested == 2, \
        f"コストで自ドン!!2枚がレストになっていない: {me.don_rested}"
    assert opp.don_rested == 1, \
        f"相手ドン!!1枚がレストにされていない: {opp.don_rested}"


def test_op04_021_opp_attack_no_effect_when_insufficient_don():
    """自ドン!!が2枚未満なら 任意コスト不能 → 相手ドン!!レストは起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    viola = InPlay.of(repo.get("OP04-021"), sickness=False)
    me.characters = [viola]
    me.don_active = 1  # 2枚未満
    me.don_rested = 0
    opp.don_active = 3
    opp.don_rested = 0

    on_oa = _get_eff(overlay, "OP04-021", "opp_attack")
    for prim in on_oa["do"]:
        execute_effect(prim, st, me, opp, viola)
        _drain(st, [1])

    assert opp.don_rested == 0, \
        "自ドン!!不足なのに 相手ドン!!がレストにされている (コスト未払いで発火してはならない)"


def test_op04_021_opp_attack_human_optional_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、 承諾で相手ドン!!レスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    viola = InPlay.of(repo.get("OP04-021"), sickness=False)
    me.characters = [viola]
    me.don_active = 3
    me.don_rested = 0
    opp.don_active = 3
    opp.don_rested = 0

    on_oa = _get_eff(overlay, "OP04-021", "opp_attack")
    execute_effect(on_oa["do"][0], st, me, opp, viola)

    assert st.pending_choice is not None, "人間 + 任意コストで確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert opp.don_rested == 1, "人間承諾後 相手ドン!!1枚がレストにされていない"
