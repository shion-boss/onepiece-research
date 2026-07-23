# -*- coding: utf-8 -*-
"""OP05 弾 効果 回帰テスト バックフィル (自動生成 wave 059):
OP05-063 / OP05-066 / OP05-067 / OP05-068 / OP05-069 / OP05-070 /
OP05-071 / OP05-072 / OP05-073 / OP05-074 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_058.py と同一方針):
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
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

# よく使うテスト用カード (テキストの前提固定)
_LEADER_NEUTRAL = "OP01-001"   # ロロノア・ゾロ (赤、 単色)
_NAMI = "OP01-016"             # ナミ cost1 power2000
_RED_C2 = "ST01-004"           # サンジ cost2 power4000
_RED_C3 = "EB02-003"           # トニートニー・チョッパー cost3 power3000
_ISSHO_C6 = "OP05-042"         # イッショウ cost6 power6000
_ZORO_JURO = "OP05-067"        # ゾロ十郎 紫 cost3 power4000 麦わらの一味 (untap 対象兼用)
_BEPO = "OP05-071"             # ベポ 紫 cost3 power5000 ハートの海賊団 (search 対象兼用)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(_RED_C2)] * 30
    p1.deck = [repo.get(_RED_C2)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _eff(overlay, cid, when):
    """when 一致の効果 dict (do + if を含む) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    return matches[0]


def _do(overlay, cid, when):
    """指定 card_id の overlay から when 一致の効果の do (list) を返す。"""
    return _eff(overlay, cid, when)["do"]


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave59_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP05-063", "OP05-066", "OP05-067", "OP05-068", "OP05-069",
           "OP05-070", "OP05-071", "OP05-072", "OP05-073", "OP05-074"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP05-063 おロビ (CHARACTER 紫 cost4 power5000 麦わらの一味):
#    【登場時】自分の場にドン!!が8枚以上ある場合、相手のコスト3以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op05_063_on_play_ko_cost_le_3_ai():
    """登場時 (AI): ドン8以上ゲート成立時、 相手のコスト3以下キャラ1体を KO する。
    コスト6のキャラは対象外 (= コスト3以下のみ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 8  # ドン8枚 → self_don_ge 8 成立
    victim = InPlay.of(repo.get(_RED_C3), sickness=False)   # cost3 → 対象
    safe = InPlay.of(repo.get(_ISSHO_C6), sickness=False)   # cost6 → 対象外
    opp.characters = [victim, safe]

    eff = _eff(overlay, "OP05-063", "on_play")
    assert eff.get("if", {}).get("self_don_ge") == 8, "overlay の ドン8ゲートが無い"
    assert eval_condition(eff.get("if", {}), st, me), "ドン8枚で条件成立のはず"

    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-063"), sickness=False))

    assert victim not in opp.characters, "コスト3のキャラが KO されていない"
    assert repo.get(_RED_C3).card_id in {c.card_id for c in opp.trash}, \
        "KO したキャラがトラッシュに無い"
    assert safe in opp.characters, "コスト6のキャラは対象外なのに KO された"


def test_op05_063_on_play_gate_not_met():
    """ドン7枚では self_don_ge 8 が不成立 (= 効果不発)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me = st.players[0]
    me.don_active = 7
    eff = _eff(overlay, "OP05-063", "on_play")
    assert not eval_condition(eff.get("if", {}), st, me), "ドン7枚では条件不成立のはず"


def test_op05_063_on_play_human_target_pick():
    """登場時 (人間): 相手コスト3以下キャラが複数 → target_pick modal → 選んだ1体を KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_active = 8
    a = InPlay.of(repo.get(_NAMI), sickness=False)   # cost1
    b = InPlay.of(repo.get(_RED_C3), sickness=False)  # cost3
    opp.characters = [a, b]

    for prim in _do(overlay, "OP05-063", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-063"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (コスト3以下2体) が 2 件でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラまで KO された"


# --------------------------------------------------------------------------- #
#  OP05-066 ジンベエ (CHARACTER 紫 cost5 power6000 魚人族/麦わらの一味):
#    【ブロッカー】【相手のターン中】自分の場にドン!!が10枚ある場合、このキャラはパワー+1000。
# --------------------------------------------------------------------------- #
def test_op05_066_opp_turn_don10_self_pump():
    """相手ターン中 + ドン10枚 → 自身 (静的) パワー+1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    st.turn_player_idx = 1  # 相手 (P1) のターン → me (P0) から見て opp_turn
    me, opp = st.players[0], st.players[1]
    me.don_active = 10  # ドン10枚
    jinbei = InPlay.of(repo.get("OP05-066"), sickness=False)  # power6000
    me.characters = [jinbei]

    eff = _eff(overlay, "OP05-066", "on_attached_don")
    assert eff.get("if", {}).get("opp_turn") is True, "overlay の opp_turn 条件が無い"
    assert eff.get("if", {}).get("self_don_ge") == 10, "overlay の ドン10条件が無い"
    assert eval_condition(eff.get("if", {}), st, me), "相手ターン+ドン10で条件成立のはず"

    power_before = jinbei.power
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, jinbei)

    assert jinbei.power == power_before + 1000, \
        f"パワー+1000 が反映されていない: {jinbei.power} (before {power_before})"


def test_op05_066_gate_not_met_don9():
    """ドン9枚では self_don_ge 10 が不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    st.turn_player_idx = 1
    me = st.players[0]
    me.don_active = 9
    eff = _eff(overlay, "OP05-066", "on_attached_don")
    assert not eval_condition(eff.get("if", {}), st, me), "ドン9枚では条件不成立のはず"


# --------------------------------------------------------------------------- #
#  OP05-067 ゾロ十郎 (CHARACTER 紫 cost3 power4000 麦わらの一味):
#    【アタック時】自分のライフが3枚以下の場合、ドン!!デッキからドン!!1枚までを、アクティブで追加する。
# --------------------------------------------------------------------------- #
def test_op05_067_on_attack_add_don_life_le3():
    """アタック時 (AI): ライフ3以下 → ドンデッキからドン1枚をアクティブで追加。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_RED_C2)] * 3  # ライフ3 (= 条件成立)
    zoro = InPlay.of(repo.get("OP05-067"), sickness=False)
    me.characters = [zoro]

    eff = _eff(overlay, "OP05-067", "on_attack")
    assert eff.get("if", {}).get("self_life_le") == 3, "overlay の self_life_le 3 が無い"
    assert eval_condition(eff.get("if", {}), st, me), "ライフ3で条件成立のはず"

    active_before = me.don_active
    remain_before = me.don_remaining_in_deck
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, zoro)

    assert me.don_active == active_before + 1, \
        f"アクティブドンが+1されていない: {me.don_active} (before {active_before})"
    assert me.don_remaining_in_deck == remain_before - 1, \
        "ドンデッキ残数が-1されていない"


def test_op05_067_gate_not_met_life4():
    """ライフ4枚では self_life_le 3 が不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me = st.players[0]
    me.life = [repo.get(_RED_C2)] * 4
    eff = _eff(overlay, "OP05-067", "on_attack")
    assert not eval_condition(eff.get("if", {}), st, me), "ライフ4では条件不成立のはず"


# --------------------------------------------------------------------------- #
#  OP05-068 チョパえもん (CHARACTER 紫 cost2 power3000 動物/麦わらの一味):
#    【登場時】自分の場にドン!!が8枚以上ある場合、自分のパワー6000以下の紫の特徴
#      《麦わらの一味》を持つキャラ1枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_op05_068_on_play_untap_ai():
    """登場時 (AI): ドン8以上 → 紫の麦わらの一味 (power≤6000) のレストキャラを1体アクティブに。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 8
    friend = InPlay.of(repo.get(_ZORO_JURO), sickness=False)  # 紫 麦わらの一味 power4000
    friend.rested = True
    me.characters = [friend]

    eff = _eff(overlay, "OP05-068", "on_play")
    assert eff.get("if", {}).get("self_don_ge") == 8, "overlay の ドン8ゲートが無い"
    assert eval_condition(eff.get("if", {}), st, me), "ドン8で条件成立のはず"

    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-068"), sickness=False))

    assert friend.rested is False, "紫麦わらキャラがアクティブになっていない"


def test_op05_068_on_play_human_target_pick():
    """登場時 (人間): 対象候補が複数 → target_pick modal → 選んだ1体をアクティブに。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_active = 8
    a = InPlay.of(repo.get(_ZORO_JURO), sickness=False)  # 紫 麦わらの一味
    b = InPlay.of(repo.get(_ZORO_JURO), sickness=False)
    a.rested = True
    b.rested = True
    me.characters = [a, b]

    for prim in _do(overlay, "OP05-068", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-068"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert b.rested is False, "人間が選んだキャラがアクティブになっていない"


# --------------------------------------------------------------------------- #
#  OP05-069 トラファルガー・ロー (CHARACTER 紫 cost3 power5000 ハートの海賊団):
#    【アタック時】相手の場のドン!!の枚数が自分の場のドン!!の枚数より多い場合、
#      自分のデッキの上から5枚を見て、特徴《ハートの海賊団》を持つカード1枚までを
#      公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op05_069_on_attack_search_ai():
    """アタック時 (AI): ドン差条件成立 → 上5枚から ハートの海賊団 1枚を手札に加える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    opp.don_active = 2  # 相手ドン2 > 自ドン0 → don_diff_le -1 成立
    me.hand = []
    # デッキ上5枚に ハートの海賊団 (ベポ) を1枚仕込む
    me.deck = [repo.get(_RED_C2), repo.get(_BEPO), repo.get(_RED_C2),
               repo.get(_RED_C2), repo.get(_RED_C2)] + [repo.get(_RED_C2)] * 25
    deck_before = len(me.deck)

    eff = _eff(overlay, "OP05-069", "on_attack")
    assert eff.get("if", {}).get("don_diff_le") == -1, "overlay の don_diff_le -1 が無い"
    assert eval_condition(eff.get("if", {}), st, me), \
        "相手ドンが多い状況で条件成立のはず"

    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-069"), sickness=False))

    assert _BEPO in {c.card_id for c in me.hand}, \
        "ハートの海賊団カードが手札に加えられていない"
    assert len(me.deck) == deck_before - 1, \
        f"デッキが1枚 (手札へ) 減っていない: {len(me.deck)} (before {deck_before})"


def test_op05_069_on_attack_human_search_modal():
    """アタック時 (人間): 該当カードあり → search_top_n modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    opp.don_active = 2
    me.hand = []
    me.deck = [repo.get(_BEPO)] + [repo.get(_RED_C2)] * 29

    for prim in _do(overlay, "OP05-069", "on_attack"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-069"), sickness=False))

    assert st.pending_choice is not None, "人間 + 該当カードで search modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"


def test_op05_069_gate_not_met_don_equal():
    """自分と相手のドンが同数なら don_diff_le -1 は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 2
    opp.don_active = 2
    eff = _eff(overlay, "OP05-069", "on_attack")
    assert not eval_condition(eff.get("if", {}), st, me), \
        "ドン同数では条件不成立のはず"


# --------------------------------------------------------------------------- #
#  OP05-070 フラの介 (CHARACTER 紫 cost5 power4000 麦わらの一味):
#    【ドン!!×1】自分の場にドン!!が8枚以上ある場合、このキャラは【速攻】を得る。
# --------------------------------------------------------------------------- #
def test_op05_070_gives_rush_when_don8():
    """ドン8以上 → 自身が【速攻】を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 8
    flanosuke = InPlay.of(repo.get("OP05-070"), sickness=True)
    me.characters = [flanosuke]

    eff = _eff(overlay, "OP05-070", "on_attached_don")
    assert eff.get("if", {}).get("self_don_ge") == 8, "overlay の ドン8条件が無い"
    assert eval_condition(eff.get("if", {}), st, me), "ドン8で条件成立のはず"

    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, flanosuke)

    assert "速攻" in flanosuke.granted_keywords, "【速攻】が付与されていない"


def test_op05_070_gate_not_met_don7():
    """ドン7枚では self_don_ge 8 が不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me = st.players[0]
    me.don_active = 7
    eff = _eff(overlay, "OP05-070", "on_attached_don")
    assert not eval_condition(eff.get("if", {}), st, me), "ドン7枚では条件不成立のはず"


# --------------------------------------------------------------------------- #
#  OP05-071 ベポ (CHARACTER 紫 cost3 power5000 ミンク族/ハートの海賊団):
#    【アタック時】相手の場のドン!!の枚数が自分の場のドン!!の枚数より多い場合、
#      相手のキャラ1枚までを、このターン中、パワー-2000。
# --------------------------------------------------------------------------- #
def test_op05_071_on_attack_debuff_ai():
    """アタック時 (AI): ドン差成立 → 相手キャラ1体を このターン中 パワー-2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    opp.don_active = 2  # 相手ドン多い
    victim = InPlay.of(repo.get(_RED_C2), sickness=False)  # power4000
    opp.characters = [victim]

    eff = _eff(overlay, "OP05-071", "on_attack")
    assert eff.get("if", {}).get("don_diff_le") == -1, "overlay の don_diff_le -1 が無い"
    assert eval_condition(eff.get("if", {}), st, me), "ドン差で条件成立のはず"

    power_before = victim.power
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-071"), sickness=False))

    assert victim.power == power_before - 2000, \
        f"相手キャラ -2000 が反映されていない: {victim.power} (before {power_before})"


def test_op05_071_on_attack_human_pick():
    """アタック時 (人間): 相手キャラ複数 → target_pick modal → 選んだ1体に -2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    opp.don_active = 2
    a = InPlay.of(repo.get(_NAMI), sickness=False)   # power2000
    b = InPlay.of(repo.get(_RED_C2), sickness=False)  # power4000
    opp.characters = [a, b]

    for prim in _do(overlay, "OP05-071", "on_attack"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-071"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert b.power == b_before - 2000, "人間が選んだ相手キャラに -2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP05-072 ホネ吉 (CHARACTER 紫 cost4 power6000 麦わらの一味):
#    【登場時】自分の場にドン!!が8枚以上ある場合、相手のキャラ2枚までを、
#      このターン中、パワー-2000。
# --------------------------------------------------------------------------- #
def test_op05_072_on_play_debuff2_ai():
    """登場時 (AI): ドン8以上 → 相手キャラ2体に このターン中 パワー-2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 8
    a = InPlay.of(repo.get(_RED_C2), sickness=False)  # power4000
    b = InPlay.of(repo.get(_RED_C3), sickness=False)  # power3000
    opp.characters = [a, b]

    eff = _eff(overlay, "OP05-072", "on_play")
    assert eff.get("if", {}).get("self_don_ge") == 8, "overlay の ドン8ゲートが無い"
    assert eval_condition(eff.get("if", {}), st, me), "ドン8で条件成立のはず"

    a_before, b_before = a.power, b.power
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-072"), sickness=False))

    assert a.power == a_before - 2000, "相手キャラ a に -2000 が反映されていない"
    assert b.power == b_before - 2000, "相手キャラ b に -2000 が反映されていない"


def test_op05_072_on_play_human_pick():
    """登場時 (人間): 相手キャラ3体 (> 上限2) → target_pick modal (limit 2) → 2体に -2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_active = 8
    a = InPlay.of(repo.get(_NAMI), sickness=False)
    b = InPlay.of(repo.get(_RED_C2), sickness=False)
    c = InPlay.of(repo.get(_RED_C3), sickness=False)
    opp.characters = [a, b, c]

    for prim in _do(overlay, "OP05-072", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-072"), sickness=False))

    assert st.pending_choice is not None, "人間 + 候補超過で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 3, f"候補が3体でない: {len(cands)}"

    b_idx = next(i for i, x in enumerate(cands) if x["iid"] == b.instance_id)
    c_idx = next(i for i, x in enumerate(cands) if x["iid"] == c.instance_id)
    b_before, c_before, a_before = b.power, c.power, a.power
    resolve_pending_choice(st, [b_idx, c_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert b.power == b_before - 2000, "選んだ b に -2000 が反映されていない"
    assert c.power == c_before - 2000, "選んだ c に -2000 が反映されていない"
    assert a.power == a_before, "選ばなかった a まで -2000 された"


# --------------------------------------------------------------------------- #
#  OP05-073 ミス・ダブルフィンガー(ザラ) (CHARACTER 紫 cost4 power4000 B・W):
#    【登場時】自分の手札1枚を捨てることができる：ドン!!デッキからドン!!1枚までを、
#      レストで追加する。
# --------------------------------------------------------------------------- #
def test_op05_073_on_play_optional_cost_ai():
    """登場時 (AI): 手札1枚を捨て → レストドン1枚を追加 (自動発動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_RED_C2)]  # 捨てるコスト用
    hand_before = len(me.hand)
    rested_before = me.don_rested
    remain_before = me.don_remaining_in_deck

    for prim in _do(overlay, "OP05-073", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-073"), sickness=False))

    assert len(me.hand) == hand_before - 1, "手札1枚が捨てられていない"
    assert me.don_rested == rested_before + 1, "レストドンが+1されていない"
    assert me.don_remaining_in_deck == remain_before - 1, "ドンデッキ残数が-1されていない"


def test_op05_073_on_play_human_confirm():
    """登場時 (人間): optional_cost_confirm modal → pay ([1]) で コスト+効果を実行。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_RED_C2)]
    rested_before = me.don_rested

    for prim in _do(overlay, "OP05-073", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-073"), sickness=False))

    assert st.pending_choice is not None, "人間で任意コスト確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # pay
    assert st.pending_choice is None, "解決後も modal が残る"
    assert len(me.hand) == 0, "支払い後に手札が捨てられていない"
    assert me.don_rested == rested_before + 1, "支払い後にレストドンが+1されていない"


# --------------------------------------------------------------------------- #
#  OP05-074 ユースタス・キッド (CHARACTER 紫 cost5 power6000 キッド海賊団):
#    【ブロッカー】【自分のターン中】【ターン1回】自分の場のドン!!がドン!!デッキに戻された時、
#      ドン!!デッキからドン!!1枚までを、アクティブで追加する。
# --------------------------------------------------------------------------- #
def test_op05_074_on_don_returned_add_don_self_turn():
    """自分のターン中 (AI): ドン返却トリガー → ドンデッキからドン1枚をアクティブで追加。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)  # turn_player=0 = me → self_turn
    me, opp = st.players[0], st.players[1]
    kid = InPlay.of(repo.get("OP05-074"), sickness=False)
    me.characters = [kid]

    eff = _eff(overlay, "OP05-074", "on_self_don_returned_to_deck")
    assert eff.get("if", {}).get("self_turn") is True, "overlay の self_turn 条件が無い"
    assert eval_condition(eff.get("if", {}), st, me), "自分のターンで条件成立のはず"

    active_before = me.don_active
    remain_before = me.don_remaining_in_deck
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, kid)

    assert me.don_active == active_before + 1, "アクティブドンが+1されていない"
    assert me.don_remaining_in_deck == remain_before - 1, "ドンデッキ残数が-1されていない"


def test_op05_074_gate_not_met_opp_turn():
    """相手ターン中は self_turn が不成立 (= 発動しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    st.turn_player_idx = 1  # 相手ターン
    me = st.players[0]
    eff = _eff(overlay, "OP05-074", "on_self_don_returned_to_deck")
    assert not eval_condition(eff.get("if", {}), st, me), \
        "相手ターン中は self_turn 不成立のはず"
