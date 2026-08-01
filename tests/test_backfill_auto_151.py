# -*- coding: utf-8 -*-
"""OP16 弾 (ドンキホーテ海賊団 / 海軍 / インペルダウン / 大将 ・ 紫) 効果 回帰テスト
バックフィル (自動生成 wave 151):
OP16-067 / OP16-068 / OP16-069 / OP16-070 / OP16-071 /
OP16-072 / OP16-074 / OP16-075 / OP16-076 / OP16-077 の 10 枚。

目的 (= test_backfill_auto_001〜150.py と同一方針):
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
    load_effect_overlay,
    resolve_pending_choice,
)
from engine.deck import CardRepository

ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------- #
#  効果の薄い (= 副作用のない / 素材用) カード + テスト用 leader/feature 素材。
# --------------------------------------------------------------------------- #
RED1 = "OP01-016"          # ナミ 赤 cost1 power2000 (フィラー)
NAVY_C = "EB04-003"        # スモーカー＆たしぎ (海軍, cost8 power8000)
NAVY_C2 = "EB04-022"       # イッショウ (海軍, cost5 power7000)
IMPEL_C = "EB02-038"       # マゼラン (インペルダウン, cost3 power4000)
TAISHO_C = "OP16-063"      # クザン (大将/海軍, cost7 power8000)
DONQ_LEADER = "OP04-019"   # ドンキホーテ・ドフラミンゴ (ドンキホーテ海賊団 LEADER)
IMPEL_LEADER = "OP02-071"  # マゼラン (インペルダウン LEADER, 紫)
NAVY_LEADER = "OP16-060"   # センゴク (海軍 LEADER, 紫)
NEUTRAL_LEADER = "OP01-001"  # ロロノア・ゾロ (超新星/麦わらの一味 = 非海軍/非インペルダウン/非ドンキ)


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
def test_all_op16_wave151_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP16-067", "OP16-068", "OP16-069", "OP16-070", "OP16-071",
           "OP16-072", "OP16-074", "OP16-075", "OP16-076", "OP16-077"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP16-067 つる (CHARACTER 紫 cost1 power2000):
#    【登場時】デッキ上5枚を見て《海軍》1枚までを公開・手札へ、 残りをデッキ下。
#             その後、 自分の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op16_067_on_play_search_navy_then_discard_ai():
    """【登場時】デッキ上5から《海軍》1枚を手札へ + その後手札1枚捨て (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NAVY_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(NAVY_C)] + [repo.get(RED1)] * 20  # 上5に 海軍 を1枚
    me.hand = [repo.get(RED1), repo.get(RED1)]
    do, _ = _do(overlay, "OP16-067", "on_play")
    src = InPlay.of(repo.get("OP16-067"), sickness=True)
    # (1) search_top_n で 海軍 が手札へ
    execute_effect(do[0], st, me, opp, src)
    _drain(st, [0])
    assert any(c.card_id == NAVY_C for c in me.hand), \
        "デッキ上5枚から《海軍》キャラが手札に加わっていない"
    # (2) その後 手札1枚捨て
    trash_before = len(me.trash)
    execute_effect(do[1], st, me, opp, src)
    _drain(st, [0])
    assert len(me.trash) == trash_before + 1, \
        f"その後の手札1枚捨てが反映されていない: trash={len(me.trash)}"


def test_op16_067_on_play_search_human_modal():
    """人間 + デッキ上5に《海軍》複数 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NAVY_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(NAVY_C), repo.get(NAVY_C2)] + [repo.get(RED1)] * 20
    me.hand = []
    do, _ = _do(overlay, "OP16-067", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP16-067"), sickness=True))
    assert st.pending_choice is not None and \
        "search_top_n" in st.pending_choice.get("kind", ""), \
        f"人間で search_top_n modal が立たない: {st.pending_choice}"
    resolve_pending_choice(st, [0])  # 先頭 (海軍) を選択
    _drain(st, [])
    assert any(c.card_id in (NAVY_C, NAVY_C2) for c in me.hand), \
        "人間が選んだ《海軍》キャラが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP16-068 トラファルガー・ロー (CHARACTER 紫 cost4 power3000):
#    【登場時】ドン!!デッキからドン!!1枚までをアクティブで追加。
#    【アタック時】リーダーが《ドンキホーテ海賊団》の場合、 このキャラは +3000。
# --------------------------------------------------------------------------- #
def test_op16_068_on_play_add_active_don_ai():
    """【登場時】ドン!!1枚をアクティブで追加 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, DONQ_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    active_before = me.don_active
    remain_before = me.don_remaining_in_deck
    do, _ = _do(overlay, "OP16-068", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-068"), sickness=True))
    assert me.don_active == active_before + 1, \
        f"登場時 アクティブドン+1 が反映されていない: {me.don_active}"
    assert me.don_remaining_in_deck == remain_before - 1, \
        "ドンデッキが1枚減っていない"


def test_op16_068_on_attack_pump_when_donquixote_leader():
    """【アタック時】リーダーが《ドンキホーテ海賊団》 → 自身 +3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, DONQ_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("OP16-068"), sickness=False)  # base 3000
    me.characters = [attacker]
    do, eff = _do(overlay, "OP16-068", "on_attack")
    assert eff.get("if", {}).get("leader_feature") == "ドンキホーテ海賊団", \
        "on_attack の leader_feature 条件が overlay に無い"
    assert eval_condition(eff["if"], st, me, None) is True, \
        "ドンキホーテ海賊団リーダーで条件が成立していない"
    power_before = attacker.power
    for prim in do:
        execute_effect(prim, st, me, opp, attacker)
    assert attacker.power == power_before + 3000, \
        f"アタック時 自己 +3000 が反映されていない: {attacker.power} (before {power_before})"


def test_op16_068_on_attack_condition_false_when_not_donquixote():
    """非《ドンキホーテ海賊団》リーダー → on_attack の条件が成立しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, _ = st.players[0], st.players[1]
    _, eff = _do(overlay, "OP16-068", "on_attack")
    assert eval_condition(eff["if"], st, me, None) is False, \
        "非ドンキホーテ海賊団リーダーで条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP16-069 ドンキホーテ・ドフラミンゴ (CHARACTER 紫 cost7 power8000):
#    【登場時】/【アタック時】ドン!!デッキからドン!!1枚までをアクティブで追加。
# --------------------------------------------------------------------------- #
def test_op16_069_on_play_add_active_don_ai():
    """【登場時】ドン!!1枚をアクティブで追加 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    active_before = me.don_active
    remain_before = me.don_remaining_in_deck
    do, _ = _do(overlay, "OP16-069", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-069"), sickness=True))
    assert me.don_active == active_before + 1, \
        f"登場時 アクティブドン+1 が反映されていない: {me.don_active}"
    assert me.don_remaining_in_deck == remain_before - 1, \
        "ドンデッキが1枚減っていない"


def test_op16_069_on_attack_add_active_don_ai():
    """【アタック時】ドン!!1枚をアクティブで追加 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("OP16-069"), sickness=False)
    me.characters = [attacker]
    active_before = me.don_active
    remain_before = me.don_remaining_in_deck
    do, _ = _do(overlay, "OP16-069", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp, attacker)
    assert me.don_active == active_before + 1, \
        f"アタック時 アクティブドン+1 が反映されていない: {me.don_active}"
    assert me.don_remaining_in_deck == remain_before - 1, \
        "ドンデッキが1枚減っていない"


# --------------------------------------------------------------------------- #
#  OP16-070 ドンキホーテ・ロシナンテ (CHARACTER 紫 cost2 power1000):
#    【ブロッカー】【登場時】自分のドン!!2枚をレストにできる：リーダーが《海軍》なら
#                 ドン!!デッキからドン!!1枚までをレストで追加。
# --------------------------------------------------------------------------- #
def test_op16_070_on_play_rest2_don_then_add_rested_when_navy_ai():
    """【登場時】海軍リーダー: ドン!!2枚レスト → ドン!!1枚レストで追加 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NAVY_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 2  # レストコスト用
    rested_before = me.don_rested
    remain_before = me.don_remaining_in_deck
    do, _ = _do(overlay, "OP16-070", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-070"), sickness=True))
    _drain(st, [0])
    # コスト: アクティブ2 → レスト2。 効果: 海軍なので レストドン+1 (デッキから)。
    assert me.don_active == 0, f"アクティブドン2枚がレストされていない: {me.don_active}"
    assert me.don_rested == rested_before + 2 + 1, \
        f"レスト2 + 海軍で追加1 が反映されていない: {me.don_rested}"
    assert me.don_remaining_in_deck == remain_before - 1, \
        "ドンデッキからの1枚追加が反映されていない"


def test_op16_070_on_play_no_add_when_not_navy():
    """非《海軍》リーダー → コストは払えるが 追加ドンは デッキから引かれない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 2
    remain_before = me.don_remaining_in_deck
    do, _ = _do(overlay, "OP16-070", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-070"), sickness=True))
    _drain(st, [0])
    assert me.don_remaining_in_deck == remain_before, \
        "非海軍リーダーで ドンデッキから追加されてはいけない"


def test_op16_070_on_play_optional_cost_human_modal():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NAVY_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_active = 2
    do, _ = _do(overlay, "OP16-070", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP16-070"), sickness=True))
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"人間で optional_cost_confirm modal が立たない: {st.pending_choice}"
    resolve_pending_choice(st, [1])  # 承諾 (= コストを払う)
    _drain(st, [0])
    assert me.don_active == 0, "承諾後 アクティブドン2枚がレストされるべき"


# --------------------------------------------------------------------------- #
#  OP16-071 波頭の仁王 (CHARACTER 紫 cost3 power5000):
#    【登場時】手札1枚を捨てることができる：ドン!!デッキからドン!!1枚までをレストで追加。
#    【KO時】ドン!!デッキからドン!!1枚までをレストで追加。
# --------------------------------------------------------------------------- #
def test_op16_071_on_play_discard_then_add_rested_don_ai():
    """【登場時】手札1枚捨て → ドン!!1枚レストで追加 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(RED1)]  # 捨てコスト用 1 枚
    rested_before = me.don_rested
    remain_before = me.don_remaining_in_deck
    trash_before = len(me.trash)
    do, _ = _do(overlay, "OP16-071", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-071"), sickness=True))
    _drain(st, [0])
    assert len(me.trash) == trash_before + 1, "手札1枚捨てがトラッシュに反映されていない"
    assert me.don_rested == rested_before + 1, \
        f"レストドン+1 が反映されていない: {me.don_rested}"
    assert me.don_remaining_in_deck == remain_before - 1, \
        "ドンデッキが1枚減っていない"


def test_op16_071_on_play_no_fire_when_hand_empty():
    """手札0枚 → 捨てコストが払えず 追加ドンも発火しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    remain_before = me.don_remaining_in_deck
    do, _ = _do(overlay, "OP16-071", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-071"), sickness=True))
    _drain(st, [0])
    assert me.don_remaining_in_deck == remain_before, \
        "手札0枚で ドンデッキから追加されてはいけない"


def test_op16_071_on_ko_add_rested_don_ai():
    """【KO時】ドン!!1枚をレストで追加 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    rested_before = me.don_rested
    remain_before = me.don_remaining_in_deck
    do, _ = _do(overlay, "OP16-071", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-071"), sickness=False))
    assert me.don_rested == rested_before + 1, \
        f"KO時 レストドン+1 が反映されていない: {me.don_rested}"
    assert me.don_remaining_in_deck == remain_before - 1, \
        "ドンデッキが1枚減っていない"


# --------------------------------------------------------------------------- #
#  OP16-072 ハンニャバル (CHARACTER 紫 cost2 power3000):
#    【登場時】デッキ上5枚を見て《インペルダウン》1枚までを公開・手札へ、 残りをデッキ下。
# --------------------------------------------------------------------------- #
def test_op16_072_on_play_search_impel_to_hand_ai():
    """【登場時】デッキ上5から《インペルダウン》1枚を手札へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(IMPEL_C)] + [repo.get(RED1)] * 20  # 上5に インペルダウン を1枚
    me.hand = []
    do, _ = _do(overlay, "OP16-072", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-072"), sickness=True))
    _drain(st, [0])
    assert any(c.card_id == IMPEL_C for c in me.hand), \
        "デッキ上5枚から《インペルダウン》キャラが手札に加わっていない"


def test_op16_072_on_play_search_human_modal():
    """人間 + デッキ上5に《インペルダウン》複数 → search_top_n modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(IMPEL_C), repo.get("OP16-042")] + [repo.get(RED1)] * 20
    me.hand = []
    do, _ = _do(overlay, "OP16-072", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP16-072"), sickness=True))
    assert st.pending_choice is not None and \
        "search_top_n" in st.pending_choice.get("kind", ""), \
        f"人間で search_top_n modal が立たない: {st.pending_choice}"
    resolve_pending_choice(st, [0])
    _drain(st, [])
    assert any(c.card_id in (IMPEL_C, "OP16-042") for c in me.hand), \
        "人間が選んだ《インペルダウン》キャラが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP16-074 マゼラン (CHARACTER 紫 cost8 power10000):
#    【登場時】リーダーが《インペルダウン》の場合、 相手は自身の場のドン!!1枚をドンデッキに戻す。
#    【KO時】相手は自身の場のドン!!4枚をドンデッキに戻す。
# --------------------------------------------------------------------------- #
def test_op16_074_on_play_don_minus_opp_when_impel_leader_ai():
    """【登場時】インペルダウンリーダー → 相手ドン!!1枚をドンデッキへ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, IMPEL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.don_active = 5
    opp_remain_before = opp.don_remaining_in_deck
    do, eff = _do(overlay, "OP16-074", "on_play")
    assert eff.get("if", {}).get("leader_feature") == "インペルダウン", \
        "on_play の leader_feature 条件が overlay に無い"
    assert eval_condition(eff["if"], st, me, None) is True, \
        "インペルダウンリーダーで条件が成立していない"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-074"), sickness=True))
    assert opp.don_active == 4, f"相手ドン!!1枚が戻されていない: {opp.don_active}"
    assert opp.don_remaining_in_deck == opp_remain_before + 1, \
        "相手ドンデッキが1枚増えていない"


def test_op16_074_on_play_condition_false_when_not_impel():
    """非《インペルダウン》リーダー → on_play の条件が成立しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, _ = st.players[0], st.players[1]
    _, eff = _do(overlay, "OP16-074", "on_play")
    assert eval_condition(eff["if"], st, me, None) is False, \
        "非インペルダウンリーダーで条件が成立してはいけない"


def test_op16_074_on_ko_don_minus_opp4_ai():
    """【KO時】相手は自身の場のドン!!4枚をドンデッキに戻す (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.don_active = 6
    opp_remain_before = opp.don_remaining_in_deck
    do, _ = _do(overlay, "OP16-074", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-074"), sickness=False))
    assert opp.don_active == 2, f"相手ドン!!4枚が戻されていない: {opp.don_active}"
    assert opp.don_remaining_in_deck == opp_remain_before + 4, \
        "相手ドンデッキが4枚増えていない"


# --------------------------------------------------------------------------- #
#  OP16-075 モンキー・Ｄ・ガープ (CHARACTER 紫 cost5 power6000):
#    【登場時】リーダーが《海軍》の場合、 ドン!!1枚アクティブ + 1枚レストで追加。
# --------------------------------------------------------------------------- #
def test_op16_075_on_play_add_active_and_rested_don_when_navy_ai():
    """【登場時】海軍リーダー → ドン!!1枚アクティブ + 1枚レストで追加 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NAVY_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    active_before = me.don_active
    rested_before = me.don_rested
    remain_before = me.don_remaining_in_deck
    do, eff = _do(overlay, "OP16-075", "on_play")
    assert eff.get("if", {}).get("leader_feature") == "海軍", \
        "on_play の leader_feature 条件 (海軍) が overlay に無い"
    assert eval_condition(eff["if"], st, me, None) is True, \
        "海軍リーダーで条件が成立していない"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-075"), sickness=True))
    assert me.don_active == active_before + 1, \
        f"アクティブドン+1 が反映されていない: {me.don_active}"
    assert me.don_rested == rested_before + 1, \
        f"レストドン+1 が反映されていない: {me.don_rested}"
    assert me.don_remaining_in_deck == remain_before - 2, \
        "ドンデッキが2枚 (アクティブ1+レスト1) 減っていない"


def test_op16_075_on_play_condition_false_when_not_navy():
    """非《海軍》リーダー → on_play の条件が成立しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, _ = st.players[0], st.players[1]
    _, eff = _do(overlay, "OP16-075", "on_play")
    assert eval_condition(eff["if"], st, me, None) is False, \
        "非海軍リーダーで条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP16-076 「三大将」!!! (EVENT 紫 cost1):
#    【メイン】自分のドン!!3枚をレスト：自分の《大将》キャラ3枚までを このターン中 +2000。
#    【カウンター】《大将》キャラがいる場合、 自リーダー/キャラ1枚まで このバトル中 +4000。
# --------------------------------------------------------------------------- #
def test_op16_076_main_rest3_don_pump_taisho_ai():
    """【メイン】ドン!!3枚レスト → 《大将》キャラ (最大3体) +2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NAVY_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3  # レストコスト用
    t1 = InPlay.of(repo.get(TAISHO_C), sickness=False)  # 大将 base 8000
    t2 = InPlay.of(repo.get(TAISHO_C), sickness=False)
    me.characters = [t1, t2]
    do, _ = _do(overlay, "OP16-076", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert me.don_active == 0 and me.don_rested == 3, \
        f"ドン!!3枚がレストされていない: active={me.don_active} rested={me.don_rested}"
    assert t1.power == 8000 + 2000 and t2.power == 8000 + 2000, \
        f"《大将》キャラに +2000 が反映されていない: {t1.power}/{t2.power}"


def test_op16_076_counter_pump_when_taisho_present_ai():
    """【カウンター】《大将》キャラがいる → 自リーダー/キャラ1枚 +4000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NAVY_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    taisho = InPlay.of(repo.get(TAISHO_C), sickness=False)  # 大将 base 8000
    me.characters = [taisho]  # 大将 在場 = 条件成立
    do, eff = _do(overlay, "OP16-076", "counter")
    assert eval_condition(eff.get("if", {}), st, me, None) is True, \
        "《大将》キャラ在場で counter 条件が成立していない"
    leader_before = me.leader.power
    taisho_before = taisho.power
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    # target は「自リーダーかキャラ1枚まで」。 AI は自リーダー or 自キャラ の いずれか 1 体を +4000。
    pumped = (me.leader.power == leader_before + 4000) ^ \
        (taisho.power == taisho_before + 4000)
    assert pumped, \
        f"カウンターの +4000 が自リーダー/キャラ の どちらにも 単独反映されていない: " \
        f"leader={me.leader.power} taisho={taisho.power}"


def test_op16_076_counter_condition_false_without_taisho():
    """《大将》キャラが1枚もいない → counter 条件が成立しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NAVY_LEADER, overlay)
    me, _ = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(RED1), sickness=False)]  # 非大将
    _, eff = _do(overlay, "OP16-076", "counter")
    assert eval_condition(eff.get("if", {}), st, me, None) is False, \
        "《大将》キャラ不在で counter 条件が成立してはいけない"


def test_op16_076_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +4000 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NAVY_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    taisho = InPlay.of(repo.get(TAISHO_C), sickness=False)
    me.characters = [taisho]
    do, _ = _do(overlay, "OP16-076", "counter")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "target_pick", \
        f"人間で target_pick modal が立たない: {st.pending_choice}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    t_idx = next(i for i, c in enumerate(cands) if c["iid"] == taisho.instance_id)
    t_before = taisho.power
    resolve_pending_choice(st, [t_idx])
    assert taisho.power == t_before + 4000, \
        "人間が選んだキャラに +4000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP16-077 智将“仏のセンゴク” (EVENT 紫 cost1):
#    【メイン】デッキ上5枚を見て《海軍》2枚までを公開・手札へ、 残りをデッキ下。
#             その後、 自分の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op16_077_main_search_two_navy_then_discard_ai():
    """【メイン】デッキ上5から《海軍》2枚を手札へ + その後手札1枚捨て (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NAVY_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(NAVY_C), repo.get(NAVY_C2)] + [repo.get(RED1)] * 20
    me.hand = []
    do, _ = _do(overlay, "OP16-077", "main")
    # (1) search_top_n で 海軍 2枚が手札へ
    execute_effect(do[0], st, me, opp, None)
    _drain(st, [0])
    navy_in_hand = [c for c in me.hand if c.card_id in (NAVY_C, NAVY_C2)]
    assert len(navy_in_hand) == 2, \
        f"デッキ上5枚から《海軍》2枚が手札に加わっていない: {[c.card_id for c in me.hand]}"
    # (2) その後 手札1枚捨て
    trash_before = len(me.trash)
    execute_effect(do[1], st, me, opp, None)
    _drain(st, [0])
    assert len(me.trash) == trash_before + 1, \
        f"その後の手札1枚捨てが反映されていない: trash={len(me.trash)}"


def test_op16_077_main_search_human_modal():
    """人間 + デッキ上5に《海軍》複数 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NAVY_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(NAVY_C), repo.get(NAVY_C2)] + [repo.get(RED1)] * 20
    me.hand = []
    do, _ = _do(overlay, "OP16-077", "main")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None and \
        "search_top_n" in st.pending_choice.get("kind", ""), \
        f"人間で search_top_n modal が立たない: {st.pending_choice}"
    resolve_pending_choice(st, [0])  # 先頭を選択
    _drain(st, [0])
    assert any(c.card_id in (NAVY_C, NAVY_C2) for c in me.hand), \
        "人間が選んだ《海軍》キャラが手札に加わっていない"
