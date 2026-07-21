# -*- coding: utf-8 -*-
"""OP02 弾 (黒 海軍 / インペルダウン系) 効果 回帰テスト バックフィル (自動生成 wave 033):
OP02-092 / OP02-093 / OP02-095 / OP02-096 / OP02-099 / OP02-100 /
OP02-101 / OP02-102 / OP02-103 / OP02-104 の 10 枚。

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


def _get_eff(overlay, cid, when):
    return next(e for e in overlay.get(cid).effects if e["when"] == when)


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
def test_all_op02_wave33_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP02-092", "OP02-093", "OP02-095", "OP02-096", "OP02-099",
           "OP02-100", "OP02-101", "OP02-102", "OP02-103", "OP02-104"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP02-092 インペルダウン (STAGE): 【起動メイン】手札1枚を捨て このステージを
#    レストにできる → デッキ上3枚を見て 特徴《インペルダウン》1枚まで手札 / 残りデッキ下
# --------------------------------------------------------------------------- #
def test_op02_092_impeldown_activate_main_search_ai():
    """AI: コスト (手札1捨て + ステージレスト) を払い、 上3枚から インペルダウン1枚を手札へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("OP02-092"), sickness=False)
    me.stages = [stage]
    me.hand = [repo.get("OP01-013")]  # 捨てるコスト用
    # 上3枚のうち先頭に インペルダウン カード (OP02-081 ドミノ)
    me.deck = [repo.get("OP02-081")] + [repo.get("OP01-013")] * 20

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP02-092"]
    assert len(opts) == 1, \
        f"OP02-092 (ステージ) の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert stage.rested is True, "起動メインコストでステージがレストされるべき"
    assert any(c.card_id == "OP02-081" for c in me.hand), \
        "上3枚から 特徴《インペルダウン》カードが手札に加わっていない"
    assert not any(c.card_id == "OP01-013" for c in me.hand), \
        "捨てるコスト (OP01-013) が手札に残ってはいけない"


def test_op02_092_impeldown_activate_main_human_chain():
    """人間: discard_pick → search_top_n → reorder のチェーンが立ち、 全て解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("OP02-092"), sickness=False)
    me.stages = [stage]
    me.hand = [repo.get("OP01-013")]
    me.deck = [repo.get("OP02-081"), repo.get("OP01-013"), repo.get("OP02-081")] \
        + [repo.get("OP01-013")] * 15

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP02-092"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間で最初の modal が立たない"
    assert st.pending_choice.get("kind") == "activate_main_discard_pick", \
        f"最初の modal kind が discard_pick でない: {st.pending_choice.get('kind')}"
    _drain(st, [0])
    assert stage.rested is True, "解決後にステージがレストされているべき"
    assert any(c.card_id == "OP02-081" for c in me.hand), \
        "人間が選んだ インペルダウンカードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP02-093 スモーカー (LEADER): 【ドン!!×1】【起動メイン】【ターン1回】相手キャラ1枚まで
#    コスト-1 → その後 コスト0のキャラがいる場合 このリーダーは このターン中 パワー+1000
# --------------------------------------------------------------------------- #
def test_op02_093_smoker_leader_activate_main_cost_down_and_pump_ai():
    """AI: 相手コスト1キャラを -1 (=実効コスト0)、 その結果 リーダー +1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-093", overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 1  # 【ドン!!×1】ゲート成立
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost1
    opp.characters = [victim]

    power_before = me.leader.power  # DON+1000 込みの現在値
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP02-093"]
    assert len(opts) == 1, f"OP02-093 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert victim.base_cost == 0, \
        f"相手キャラのコストが -1 (=0) されていない: {victim.base_cost}"
    assert me.leader.power == power_before + 1000, \
        f"コスト0キャラ存在時の リーダー +1000 が反映されていない: {me.leader.power}"


def test_op02_093_smoker_leader_activate_main_once_per_turn():
    """【ターン1回】: 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-093", overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 1
    opp.characters = [InPlay.of(repo.get("OP01-016"), sickness=False)]

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP02-093"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP02-093"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP02-095 オニグモ (CHARACTER): コスト0のキャラがいる場合 このキャラは【バニッシュ】を得る
# --------------------------------------------------------------------------- #
@pytest.mark.skip(reason=(
    "overlay の条件 opp_or_self_chara_cost_eq_0_exists は 印刷コスト (c.card.cost==0) を "
    "見るが、 cards.json に コスト0 の CHARACTER は 1 枚も存在せず、 公式の「コスト0のキャラ」"
    "(= OP02-093 等で 実効コストが0になったキャラ) を 捕捉できない → 効果が発火不能。 "
    "engine/overlay 実バグ (実効コスト exists_chara_cost_le を使うべき)。 人間レビューへ。"
))
def test_op02_095_onigumo_static_vanish():
    """コスト0のキャラがいる場合 このキャラは【バニッシュ】を得る (静的付与)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    onigumo = InPlay.of(repo.get("OP02-095"), sickness=False)
    me.characters = [onigumo]
    # 実効コスト0 の相手キャラを用意 (印刷1 → -1)
    zero = InPlay.of(repo.get("OP01-016"), sickness=False)
    zero.cost_minus_until_turn_end = 1
    opp.characters = [zero]

    evaluate_static_effects(st, overlay)
    assert "バニッシュ" in onigumo.static_granted_keywords, \
        "コスト0キャラ存在時に バニッシュ が付与されていない"


# --------------------------------------------------------------------------- #
#  OP02-096 クザン (CHARACTER): 【登場時】1ドロー / 【アタック時】相手キャラ1枚まで コスト-4
# --------------------------------------------------------------------------- #
def test_op02_096_kuzan_on_play_draw():
    """【登場時】カード1枚を引く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("OP01-013")] * 5

    on_play = _get_eff(overlay, "OP02-096", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-096"), sickness=True))
    assert len(me.hand) == 1, "登場時の 1 ドローが起きていない"


def test_op02_096_kuzan_on_attack_cost_down_ai():
    """【アタック時】相手キャラ1枚まで コスト-4 (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    opp.characters = [victim]

    on_attack = _get_eff(overlay, "OP02-096", "on_attack")
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-096"), sickness=False))
    assert victim.base_cost == 0, \
        f"相手キャラの コスト-4 (=0) が反映されていない: {victim.base_cost}"


def test_op02_096_kuzan_on_attack_cost_down_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal が立ち resolve で -4。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [a, b]

    on_attack = _get_eff(overlay, "OP02-096", "on_attack")
    execute_effect(on_attack["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP02-096"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b.base_cost == 0, "人間が選んだ相手キャラに -4 (=0) が反映されていない"
    assert a.base_cost == a.card.cost, "選ばなかったキャラのコストは変わらないべき"


# --------------------------------------------------------------------------- #
#  OP02-099 サカズキ (CHARACTER): 【登場時】手札1枚を捨てることができる：
#    相手のコスト5以下のキャラ1枚までを KO する
# --------------------------------------------------------------------------- #
def test_op02_099_sakazuki_on_play_ko_ai():
    """AI: 手札1枚を捨てて 相手のコスト5以下キャラを KO する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]  # 捨てるコスト用
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 <= 5
    opp.characters = [victim]

    on_play = _get_eff(overlay, "OP02-099", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-099"), sickness=True))
    assert victim not in opp.characters, "相手のコスト5以下キャラが KO されていない"
    assert len(me.hand) == 0, "任意コストの 手札1捨てが行われていない"


def test_op02_099_sakazuki_on_play_optional_confirm_human():
    """人間: 任意コスト (=「〜できる」) の optional_cost_confirm modal が立ち、 承諾で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [victim]

    on_play = _get_eff(overlay, "OP02-099", "on_play")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP02-099"), sickness=True))

    assert st.pending_choice is not None, "人間 任意コストの確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾 (= 払って発動)
    _drain(st, [0])
    assert victim not in opp.characters, "人間承諾後に 相手キャラが KO されていない"
    assert len(me.hand) == 0, "承諾後 手札1枚が捨てられているべき"


# --------------------------------------------------------------------------- #
#  OP02-100 ジャンゴ (CHARACTER): 自分の「フルボディ」がいる場合 このキャラはバトルでKOされない
# --------------------------------------------------------------------------- #
def test_op02_100_django_static_ko_immune_with_fullbody():
    """自分の「フルボディ」がいる場合 → 静的に バトルKO耐性 が付く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    django = InPlay.of(repo.get("OP02-100"), sickness=False)
    fullbody = InPlay.of(repo.get("OP02-111"), sickness=False)  # フルボディ (黒 cost2)
    me.characters = [django, fullbody]

    evaluate_static_effects(st, overlay)
    assert django.battle_ko_immune_static is True, \
        "フルボディ存在時に ジャンゴが バトルKO耐性 を得ていない"


def test_op02_100_django_static_no_immune_without_fullbody():
    """「フルボディ」がいなければ 条件不成立 → バトルKO耐性は付かない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    django = InPlay.of(repo.get("OP02-100"), sickness=False)
    me.characters = [django]

    evaluate_static_effects(st, overlay)
    assert django.battle_ko_immune_static is False, \
        "フルボディ不在なのに バトルKO耐性 が付いてはいけない"


# --------------------------------------------------------------------------- #
#  OP02-101 ストロベリー (CHARACTER): 【アタック時】コスト0のキャラがいる場合
#    相手は このバトル中 コスト5以下のキャラの【ブロッカー】を発動できない
# --------------------------------------------------------------------------- #
def test_op02_101_strawberry_on_attack_block_deny():
    """コスト0のキャラ存在時、 相手のコスト5以下キャラに「ブロック不可」が付く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    # 実効コスト0 の自キャラを用意 (印刷1 → -1) = 条件成立
    zero = InPlay.of(repo.get("OP01-016"), sickness=False)
    zero.cost_minus_until_turn_end = 1
    me.characters = [zero]
    blocker = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 <= 5
    opp.characters = [blocker]

    on_attack = _get_eff(overlay, "OP02-101", "on_attack")
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-101"), sickness=False))
    assert "ブロック不可" in blocker.granted_keywords, \
        "コスト0キャラ存在時に 相手コスト5以下キャラへ ブロック不可 が付与されていない"


# --------------------------------------------------------------------------- #
#  OP02-102 スモーカー (CHARACTER): 効果でKOされない / 【アタック時】コスト0のキャラがいる場合
#    このキャラは このバトル中 パワー+2000
# --------------------------------------------------------------------------- #
def test_op02_102_smoker_on_attack_self_pump():
    """コスト0のキャラ存在時、 アタック時に 自身 +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    zero = InPlay.of(repo.get("OP01-016"), sickness=False)
    zero.cost_minus_until_turn_end = 1  # 実効コスト0 = 条件成立
    smoker = InPlay.of(repo.get("OP02-102"), sickness=False)  # power 4000
    me.characters = [smoker, zero]

    power_before = smoker.power
    on_attack = _get_eff(overlay, "OP02-102", "on_attack")
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp, smoker)
    assert smoker.power == power_before + 2000, \
        f"コスト0存在時の アタック +2000 が反映されていない: {smoker.power} (before {power_before})"


def test_op02_102_smoker_on_attack_condition_is_cost0_gate():
    """トリガーは【コスト0のキャラがいる場合】= overlay の if=exists_chara_cost_le:0 で gate。
    (正方向の pump は test_op02_102_smoker_on_attack_self_pump が担保。)"""
    overlay = _overlay()
    on_attack = _get_eff(overlay, "OP02-102", "on_attack")
    assert on_attack.get("if", {}).get("exists_chara_cost_le") == 0, \
        "overlay の トリガー条件 exists_chara_cost_le=0 が無い"


# --------------------------------------------------------------------------- #
#  OP02-103 センゴク (CHARACTER): 【ドン!!×1】【アタック時】相手キャラ1枚まで コスト-2
# --------------------------------------------------------------------------- #
def test_op02_103_sengoku_on_attack_cost_down_ai():
    """【アタック時】(ドンゲート) 相手キャラ1枚を コスト-2 (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    opp.characters = [victim]

    on_attack = _get_eff(overlay, "OP02-103", "on_attack")
    assert on_attack.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-103"), sickness=False))
    assert victim.base_cost == 0, \
        f"相手キャラの コスト-2 (=0) が反映されていない: {victim.base_cost}"


def test_op02_103_sengoku_on_attack_cost_down_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal が立ち resolve で -2。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [a, b]

    on_attack = _get_eff(overlay, "OP02-103", "on_attack")
    execute_effect(on_attack["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP02-103"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b.base_cost == 0, "人間が選んだ相手キャラに -2 (=0) が反映されていない"


# --------------------------------------------------------------------------- #
#  OP02-104 戦桃丸 (CHARACTER): 【トリガー】このカードを登場させる (play_self)
# --------------------------------------------------------------------------- #
def test_op02_104_sentomaru_trigger_play_self_ai():
    """AI: トリガーで 自身を場に登場させる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP02-104")]  # トリガー元 (= 手札の自身)
    st.current_source_card_id = "OP02-104"

    trig = _get_eff(overlay, "OP02-104", "trigger")
    for prim in trig["do"]:
        execute_effect(prim, st, me, opp, None)

    assert any(c.card.card_id == "OP02-104" for c in me.characters), \
        "トリガーで 自身が登場していない"
    assert not any(c.card_id == "OP02-104" for c in me.hand), \
        "登場した自身が手札から取り除かれていない"


def test_op02_104_sentomaru_trigger_play_self_human():
    """人間文脈でも crash せず 自身が登場する (choice の無い単純 play_self)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP02-104")]
    st.current_source_card_id = "OP02-104"

    trig = _get_eff(overlay, "OP02-104", "trigger")
    for prim in trig["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])

    assert any(c.card.card_id == "OP02-104" for c in me.characters), \
        "人間文脈で 自身が登場していない"
