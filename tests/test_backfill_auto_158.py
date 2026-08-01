# -*- coding: utf-8 -*-
"""プロモ (P-*) 効果 回帰テスト バックフィル (自動生成 wave 158):
P-047 / P-048 / P-049 / P-050 / P-051 /
P-053 / P-054 / P-055 / P-056 / P-057 の 10 枚。

目的 (= test_backfill_auto_001〜157.py と同一方針):
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

# --------------------------------------------------------------------------- #
#  効果の薄い (= 素材用) カード。
# --------------------------------------------------------------------------- #
NAMI = "OP01-016"           # ナミ (cost1 power2000 attr特) フィラー / 相手キャラ
COST2 = "OP01-013"          # サンジ (cost2 power3000 attr打) フィラー
COST3 = "P-048"             # アーロン (cost3 power4000) 中コスト
COST4 = "OP11-015"          # モチャ (cost4 power6000 attr知) 中コスト
BIG = "OP02-004"            # エドワード・ニューゲート (cost9 power10000) 高コスト
NEUTRAL_LEADER = "OP01-001"  # ロロノア・ゾロ (LEADER)
UTA_LEADER = "ST11-001"      # ウタ (緑 LEADER) = P-057 の leader_name 条件用


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, turn=0,
           opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 MAIN / turn_number=3。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(COST2)] * 30
    p1.deck = [repo.get(COST2)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _eff(overlay, cid, when):
    """指定 card_id の overlay から when 一致の効果 (先頭) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    assert matches, f"{cid} に when={when} の効果がない"
    return matches[0]


def _drain(st, picks):
    """resolve 後続の連鎖 modal を流す (guard 付き)。"""
    guard = 0
    while st.pending_choice is not None and guard < 6:
        resolve_pending_choice(st, picks)
        guard += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave158_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["P-047", "P-048", "P-049", "P-050", "P-051",
           "P-053", "P-054", "P-055", "P-056", "P-057"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  P-047 モンキー・D・ルフィ (LEADER):
#    【ドン!!×1】【アタック時】自分の手札が3枚以下の場合、カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_p047_luffy_leader_on_attack_draw_ai():
    """【アタック時】(ドン×1 + 手札3以下) → 1 ドロー。 do を発火し hand+1 / deck-1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "P-047", overlay)  # P-047 自身が leader
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 1
    me.hand = [repo.get(COST2)] * 3  # 手札 3 枚 (= 条件成立)
    me.deck = [repo.get(NAMI)] * 10

    eff = _eff(overlay, "P-047", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    assert eff.get("if", {}).get("self_hand_count_le") == 3, \
        "overlay の 手札条件 self_hand_count_le=3 が無い"
    assert eval_condition(eff["if"], st, me, me.leader) is True, \
        "手札3枚 + ドン1 で条件が成立していない"

    hand_before = len(me.hand)
    deck_before = len(me.deck)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, me.leader)

    assert len(me.hand) == hand_before + 1, "アタック時の draw が起きていない"
    assert len(me.deck) == deck_before - 1, "ドローでデッキが1枚減っていない"


def test_p047_luffy_leader_condition_false_when_hand_high():
    """手札が4枚以上なら self_hand_count_le=3 不成立 → 条件 False。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "P-047", overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 1
    me.hand = [repo.get(COST2)] * 4  # 手札 4 枚 (= 条件不成立)

    eff = _eff(overlay, "P-047", "on_attack")
    assert eval_condition(eff["if"], st, me, me.leader) is False, \
        "手札4枚で条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  P-048 アーロン:
#    【ドン!!×1】【アタック時】自分のライフが4枚以上の場合、
#    相手は自身の手札1枚をデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_p048_arlong_on_attack_opp_hand_to_deck_ai():
    """【アタック時】(ドン×1 + ライフ4以上) → 相手手札1枚をデッキ下へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("P-048"), sickness=False)
    attacker.attached_dons = 1
    me.characters = [attacker]
    me.life = [repo.get(COST2)] * 4  # ライフ 4 (= 条件成立)
    opp.hand = [repo.get(NAMI), repo.get(COST2)]
    opp.deck = [repo.get(COST2)] * 10

    eff = _eff(overlay, "P-048", "on_attack")
    assert eff.get("if", {}).get("self_life_ge") == 4, \
        "overlay の ライフ条件 self_life_ge=4 が無い"
    assert eval_condition(eff["if"], st, me, attacker) is True, \
        "ライフ4 + ドン1 で条件が成立していない"

    opp_hand_before = len(opp.hand)
    opp_deck_before = len(opp.deck)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, attacker)

    assert len(opp.hand) == opp_hand_before - 1, "相手手札が1枚減っていない"
    assert len(opp.deck) == opp_deck_before + 1, "相手デッキ下に1枚加わっていない"


def test_p048_arlong_condition_false_when_life_low():
    """自分のライフが3枚以下なら self_life_ge=4 不成立 → 条件 False。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("P-048"), sickness=False)
    attacker.attached_dons = 1
    me.characters = [attacker]
    me.life = [repo.get(COST2)] * 3  # ライフ 3 (= 条件不成立)

    eff = _eff(overlay, "P-048", "on_attack")
    assert eval_condition(eff["if"], st, me, attacker) is False, \
        "ライフ3枚で条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  P-049 ウソップ:
#    【登場時】自分のデッキの上から5枚を見て、好きな順番に並び替え、デッキの上か下に置く。
#    (overlay: look_top_reorder depth5 to:choice = コスト昇順に並び替えて上へ)
# --------------------------------------------------------------------------- #
def test_p049_usopp_on_play_look_top_reorder_ai():
    """【登場時】 デッキ上5枚を コスト昇順に並び替えて上へ (デッキ枚数不変)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    # 上5枚を コスト バラバラ (9,1,4,2,3) に仕込む → 昇順 (1,2,3,4,9) を期待
    top5 = [repo.get(BIG), repo.get(NAMI), repo.get(COST4),
            repo.get(COST2), repo.get(COST3)]
    me.deck = list(top5) + [repo.get(COST2)] * 15
    deck_before = len(me.deck)

    for prim in _eff(overlay, "P-049", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-049"), sickness=True))

    assert len(me.deck) == deck_before, \
        "look_top_reorder はデッキ枚数を変えてはいけない (見て並べ替えるだけ)"
    costs = [c.cost for c in me.deck[:5]]
    assert costs == sorted(costs), \
        f"デッキ上5枚が コスト昇順に並び替わっていない: {costs}"
    assert costs[0] == 1, f"最小コスト (1) が上に来ていない: {costs}"


# --------------------------------------------------------------------------- #
#  P-050 サンジ:
#    【ブロッカー】【ドン!!×1】【自分のターン中】自分の手札が3枚以下の場合、
#    このキャラはパワー+4000。
# --------------------------------------------------------------------------- #
def test_p050_sanji_static_pump_when_hand_le_3():
    """静的 (on_attached_don n=1, 自ターン, 手札3以下): パワー+4000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, turn=0)  # 自ターン
    me, opp = st.players[0], st.players[1]
    sanji_def = repo.get("P-050")  # power 2000
    sanji = InPlay.of(sanji_def, sickness=False)
    sanji.attached_dons = 1  # ドン!!×1 ゲート成立
    me.characters = [sanji]
    me.hand = [repo.get(COST2)] * 3  # 手札 3 (= 条件成立)

    evaluate_static_effects(st, overlay)
    # 印刷 2000 + DON1枚(+1000) + 効果(+4000) = 7000
    assert sanji.power == sanji_def.power + 1000 + 4000, \
        f"手札3以下で +4000 が乗っていない: {sanji.power} (base {sanji_def.power})"


def test_p050_sanji_static_no_pump_when_hand_high():
    """手札が4枚以上なら 条件不成立 → 効果 pump なし (DON分のみ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, turn=0)
    me, opp = st.players[0], st.players[1]
    sanji_def = repo.get("P-050")
    sanji = InPlay.of(sanji_def, sickness=False)
    sanji.attached_dons = 1
    me.characters = [sanji]
    me.hand = [repo.get(COST2)] * 4  # 手札 4 (= 条件不成立)

    evaluate_static_effects(st, overlay)
    assert sanji.power == sanji_def.power + 1000, \
        f"手札4枚で効果 pump が乗ってはいけない: {sanji.power} (base {sanji_def.power})"


# --------------------------------------------------------------------------- #
#  P-051 シャンクス:
#    【アタック時】自分の手札を任意の枚数捨ててもよい。
#    捨てたカード1枚につき、このキャラは、このバトル中、パワー+1000。
# --------------------------------------------------------------------------- #
def test_p051_shanks_on_attack_optional_discard_buff_ai():
    """【アタック時】 AI: 手札 (最大3枚) を捨て 自身に +1000/枚。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("P-051"), sickness=False)  # power 9000
    me.characters = [attacker]
    me.hand = [repo.get(COST2)] * 3  # 3 枚 → AI は max3 捨て = +3000

    power_before = attacker.power
    hand_before = len(me.hand)
    for prim in _eff(overlay, "P-051", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, attacker)

    assert attacker.power == power_before + 3000, \
        f"3枚捨てで battle_buff +3000 が乗っていない: {attacker.power} (before {power_before})"
    assert len(me.hand) == hand_before - 3, "捨てたはずの手札が減っていない"


def test_p051_shanks_on_attack_human_optional_discard_pick():
    """人間: 【アタック時】 → optional_discard_buff_pick modal → 1 枚選択で +1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("P-051"), sickness=False)
    me.characters = [attacker]
    me.hand = [repo.get(COST2), repo.get(NAMI)]

    power_before = attacker.power
    for prim in _eff(overlay, "P-051", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, attacker)
        if st.pending_choice is not None:
            break

    assert st.pending_choice is not None, "人間 任意捨ての modal が立たない"
    assert st.pending_choice.get("kind") == "optional_discard_buff_pick", \
        f"kind が optional_discard_buff_pick でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 候補 1 枚を選んで捨てる
    assert attacker.power == power_before + 1000, \
        "人間が1枚捨てた後 +1000 が反映されていない"
    assert len(me.hand) == 1, "人間が選んだ1枚が捨てられていない"


# --------------------------------------------------------------------------- #
#  P-053 ナミ:
#    【登場時】自分の手札が3枚以下の場合、
#    相手のコスト3以下のキャラ1枚までを、持ち主の手札に戻す。
# --------------------------------------------------------------------------- #
def test_p053_nami_on_play_return_cost_le_3_ai():
    """【登場時】(手札3以下) AI: 相手のコスト3以下キャラを 持ち主 (相手) の手札へ戻す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(COST2)] * 3  # 手札 3 (= 条件成立)
    victim = InPlay.of(repo.get(COST3), sickness=False)  # cost3 (= 対象)
    opp.characters = [victim]
    opp.hand = []

    eff = _eff(overlay, "P-053", "on_play")
    assert eff.get("if", {}).get("self_hand_count_le") == 3, \
        "overlay の 手札条件 self_hand_count_le=3 が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-053"), sickness=True))
    _drain(st, [0])

    assert victim not in opp.characters, "相手のコスト3以下キャラが手札に戻っていない"
    assert any(c.card_id == COST3 for c in opp.hand), \
        "戻したキャラが持ち主 (相手) の手札に加わっていない"


def test_p053_nami_on_play_high_cost_survives():
    """相手キャラが コスト3超のみなら 対象外 → 戻らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(COST2)] * 3
    tough = InPlay.of(repo.get(COST4), sickness=False)  # cost4 (= 対象外)
    opp.characters = [tough]

    for prim in _eff(overlay, "P-053", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-053"), sickness=True))
    _drain(st, [0])

    assert tough in opp.characters, "コスト3超のキャラが戻ってはいけない (対象外)"


def test_p053_nami_on_play_return_human_pick():
    """人間 + 相手のコスト3以下キャラ 複数 → target_pick modal が立ち resolve で 1 体を戻す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(COST2)] * 3
    a = InPlay.of(repo.get(NAMI), sickness=False)   # cost1
    b = InPlay.of(repo.get(COST3), sickness=False)  # cost3
    opp.characters = [a, b]
    opp.hand = []

    execute_effect(_eff(overlay, "P-053", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("P-053"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b not in opp.characters, "人間が選んだキャラが手札に戻っていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  P-054 モンキー・D・ガープ:
#    【ドン!!×1】このキャラは属性(打)を持つカードとのバトルでKOされない。
# --------------------------------------------------------------------------- #
def test_p054_garp_static_immune_attribute_with_don():
    """静的 (on_attached_don n=1): 属性「打」とのバトルで KO されない = 免疫属性に「打」が登録。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    garp = InPlay.of(repo.get("P-054"), sickness=False)
    garp.attached_dons = 1  # ドン!!×1 ゲート成立
    me.characters = [garp]

    evaluate_static_effects(st, overlay)
    assert "打" in garp.ko_immune_battle_attributes_in, \
        f"属性「打」の KO 免疫が登録されていない: {garp.ko_immune_battle_attributes_in}"


def test_p054_garp_static_no_immune_without_don():
    """ドンが付いていなければ n=1 ゲート不成立 → 免疫属性は空。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    garp = InPlay.of(repo.get("P-054"), sickness=False)
    garp.attached_dons = 0  # ゲート不成立
    me.characters = [garp]

    evaluate_static_effects(st, overlay)
    assert "打" not in garp.ko_immune_battle_attributes_in, \
        "ドン無しで KO 免疫が乗ってはいけない"


# --------------------------------------------------------------------------- #
#  P-055 モンキー・D・ルフィ:
#    【登場時】自分の手札2枚を捨てることができる：
#    相手は自身のキャラ1枚を、持ち主のデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_p055_luffy_on_play_discard2_return_deck_bottom_ai():
    """【登場時】 AI: 手札2枚を捨て 相手キャラ1枚を持ち主 (相手) のデッキ下へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(COST2), repo.get(NAMI)]  # 捨てるコスト 2 枚
    victim = InPlay.of(repo.get(COST4), sickness=False)
    opp.characters = [victim]
    opp.deck = [repo.get(COST2)] * 10

    hand_before = len(me.hand)
    opp_deck_before = len(opp.deck)
    for prim in _eff(overlay, "P-055", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-055"), sickness=True))
    _drain(st, [0])

    assert victim not in opp.characters, "相手キャラが場から消えていない"
    assert len(opp.deck) == opp_deck_before + 1, "相手デッキ下に1枚加わっていない"
    assert len(me.hand) == hand_before - 2, "任意コストで手札2枚が捨てられていない"


def test_p055_luffy_on_play_cannot_pay_noop():
    """手札が1枚 (< 2) なら コスト不能 → 効果不発 (相手キャラは残る)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(COST2)]  # 1 枚 (= 2枚捨て不能)
    victim = InPlay.of(repo.get(COST4), sickness=False)
    opp.characters = [victim]

    for prim in _eff(overlay, "P-055", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-055"), sickness=True))
    _drain(st, [0])

    assert victim in opp.characters, "コスト不能なのに相手キャラが消えてはいけない"
    assert len(me.hand) == 1, "コスト不能なのに手札が減ってはいけない"


def test_p055_luffy_on_play_human_optional_cost():
    """人間: 【登場時】 → optional_cost_confirm modal → pay ([1]) で 捨て + デッキ下解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(COST2), repo.get(NAMI)]
    victim = InPlay.of(repo.get(COST4), sickness=False)
    opp.characters = [victim]
    opp.deck = [repo.get(COST2)] * 10

    for prim in _eff(overlay, "P-055", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-055"), sickness=True))
        if st.pending_choice is not None:
            break

    assert st.pending_choice is not None, "人間 任意コストの modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 任意コストを払う
    _drain(st, [0])
    assert victim not in opp.characters, "承認後に 相手キャラがデッキ下へ戻っていない"
    assert len(me.hand) == 0, "承認後に 手札2枚が捨てられていない"


# --------------------------------------------------------------------------- #
#  P-056 ロロノア・ゾロ:
#    【登場時】➁(コストエリアのドン!!を指定の数レストにできる)：
#    コスト5以下のキャラ1枚までを、持ち主の手札に戻す。
# --------------------------------------------------------------------------- #
def test_p056_zoro_on_play_rest_don2_return_hand_ai():
    """【登場時】 AI: ドン2枚をレスト → 相手のコスト5以下キャラを 持ち主 (相手) の手札へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3  # コスト2 支払い可
    me.don_rested = 0
    victim = InPlay.of(repo.get(COST4), sickness=False)  # cost4 (= 対象)
    opp.characters = [victim]
    opp.hand = []

    for prim in _eff(overlay, "P-056", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-056"), sickness=True))
    _drain(st, [0])

    assert victim not in opp.characters, "相手のコスト5以下キャラが手札に戻っていない"
    assert any(c.card_id == COST4 for c in opp.hand), \
        "戻したキャラが持ち主 (相手) の手札に加わっていない"
    assert me.don_active == 1 and me.don_rested == 2, \
        f"コストでドン2枚がレストされていない: active={me.don_active} rested={me.don_rested}"


def test_p056_zoro_on_play_cannot_pay_noop():
    """アクティブドンが1枚 (< 2) なら コスト不能 → 効果不発。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 1  # コスト2 支払い不能
    victim = InPlay.of(repo.get(COST4), sickness=False)
    opp.characters = [victim]

    for prim in _eff(overlay, "P-056", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-056"), sickness=True))
    _drain(st, [0])

    assert victim in opp.characters, "コスト不能なのに相手キャラが戻ってはいけない"


def test_p056_zoro_on_play_human_optional_cost():
    """人間: 【登場時】 → optional_cost_confirm modal → pay ([1]) で ドンレスト + 手札戻し。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    victim = InPlay.of(repo.get(COST4), sickness=False)
    opp.characters = [victim]
    opp.hand = []

    for prim in _eff(overlay, "P-056", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-056"), sickness=True))
        if st.pending_choice is not None:
            break

    assert st.pending_choice is not None, "人間 任意コストの modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 任意コストを払う
    _drain(st, [0])
    assert victim not in opp.characters, "承認後に 相手キャラが手札へ戻っていない"


# --------------------------------------------------------------------------- #
#  P-057 ウタカタララバイ (EVENT):
#    【メイン】自分のリーダーが「ウタ」の場合、相手のレストのコスト4以下のキャラ2枚までは、
#    次の相手のリフレッシュフェイズでアクティブにならない。
#    【トリガー】このカードの【メイン】効果を発動する。
# --------------------------------------------------------------------------- #
def test_p057_utakata_main_stay_rested_ai():
    """【メイン】(leader=ウタ) AI: 相手レストのコスト4以下キャラ2枚に「次リフレッシュ非アクティブ」。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, UTA_LEADER, overlay)  # 緑 ウタ leader (= 条件成立)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(COST2), sickness=False)  # cost2 レスト
    b = InPlay.of(repo.get(COST4), sickness=False)  # cost4 レスト
    a.rested = True
    b.rested = True
    opp.characters = [a, b]

    eff = _eff(overlay, "P-057", "main")
    assert eff.get("if", {}).get("leader_name") == "ウタ", \
        "overlay の leader_name=ウタ 条件が無い"
    assert eval_condition(eff["if"], st, me, None) is True, \
        "リーダー ウタ で条件が成立していない"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])

    assert a.stay_rested_next_refresh is True, "レストキャラ a が非アクティブ化されていない"
    assert b.stay_rested_next_refresh is True, "レストキャラ b が非アクティブ化されていない"


def test_p057_utakata_main_condition_false_non_uta_leader():
    """リーダーが「ウタ」でなければ leader_name 条件 不成立 → 条件 False。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)  # ゾロ leader (= ウタでない)
    me, opp = st.players[0], st.players[1]

    eff = _eff(overlay, "P-057", "main")
    assert eval_condition(eff["if"], st, me, None) is False, \
        "ウタ以外の leader で条件が成立してはいけない"


def test_p057_utakata_main_human_pick():
    """人間 + 相手のレストコスト4以下キャラ 3体 → target_pick modal が立ち resolve で 2 体を選ぶ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, UTA_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    chars = [InPlay.of(repo.get(NAMI), sickness=False) for _ in range(3)]
    for c in chars:
        c.rested = True
    opp.characters = chars

    execute_effect(_eff(overlay, "P-057", "main")["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 3候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 3, f"候補が3体でない: {len(cands)}"

    resolve_pending_choice(st, [0, 1])  # 2 体を選択
    _drain(st, [0, 1])
    marked = [c for c in opp.characters if c.stay_rested_next_refresh]
    assert len(marked) == 2, f"人間が選んだ2体が非アクティブ化されていない: {len(marked)}"


def test_p057_utakata_trigger_fires_main_ai():
    """【トリガー】 fire_self_effect(main) → メイン効果 (leader=ウタ) が発動する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, UTA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(COST4), sickness=False)
    victim.rested = True
    opp.characters = [victim]
    st.current_source_card_id = "P-057"  # EVENT トリガー: self_inplay 無し → source を明示

    for prim in _eff(overlay, "P-057", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])

    assert victim.stay_rested_next_refresh is True, \
        "トリガーからメイン効果が発動して非アクティブ化していない"
