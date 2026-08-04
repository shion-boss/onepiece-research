# -*- coding: utf-8 -*-
"""OP16 弾 (ワノ国 / 海軍 / 王下七武海 ・ 紫/黒) 効果 回帰テスト
バックフィル (自動生成 wave 152):
OP16-078 / OP16-081 / OP16-082 / OP16-083 / OP16-085 /
OP16-089 / OP16-090 / OP16-091 / OP16-092 / OP16-093 の 10 枚。

目的 (= test_backfill_auto_001〜151.py と同一方針):
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
from engine.game import _compute_in_hand_cost_minus
from engine.deck import CardRepository

ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------- #
#  効果の薄い (= 素材用) カード + テスト用 leader/feature 素材。
# --------------------------------------------------------------------------- #
RED1 = "OP01-016"          # ナミ 麦わらの一味 cost1 power2000 (フィラー / cost1 相手キャラ)
NAVY_C = "EB04-003"        # スモーカー＆たしぎ (海軍, cost8 power8000)
NAVY_C2 = "EB04-022"       # イッショウ (海軍, cost5 power7000)
WANO_C = "PRB02-008"       # マルコ (ワノ国, cost4 power6000, 名前 != ナミ)
WANO_C2 = "EB01-016"       # びん豪 (ワノ国, cost1, 名前 != ナミ)
WANO_LEADER = "EB01-001"   # 光月おでん (ワノ国/光月家 LEADER)
NAVY_LEADER = "OP16-060"   # センゴク (海軍 LEADER, 紫)
NEUTRAL_LEADER = "OP01-001"  # ロロノア・ゾロ (超新星/麦わらの一味 = 非ワノ国/非海軍)


def _cond_of(eff: dict) -> dict:
    """効果の発動条件を取り出す (top-level `if` / `conditional` の両対応)。

    ⚠ 2026-08-05: 公式は 「〜できる：<条件>の場合、<効果>」 のコロン後の条件を **効果のみ** の
    gate とする (cardqa_op_02 / cardqa_st_04)。 top-level `if` に置くと **任意コストの支払いごと
    消える** ので、 overlay ではこの形の条件を `conditional` の中に移した。
    条件そのものは変わっていないので、 テストはどちらの位置でも読めればよい。
    """
    if isinstance(eff.get("if"), dict):
        return eff["if"]
    for _prim in eff.get("do") or []:
        if isinstance(_prim, dict) and "conditional" in _prim:
            return (_prim.get("conditional") or {}).get("if") or {}
    return {}


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


def _am(st, me, overlay, cid):
    """指定 card_id の起動メイン (src, eff) を legal から取り出す。"""
    return [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == cid]


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op16_wave152_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP16-078", "OP16-081", "OP16-082", "OP16-083", "OP16-085",
           "OP16-089", "OP16-090", "OP16-091", "OP16-092", "OP16-093"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP16-078 マリンフォード (STAGE 紫 cost1):
#    【登場時】デッキ上5枚を見て《海軍》1枚までを公開・手札へ、 残りをデッキ下。
#    【起動メイン】ドン!!-1, このステージをレスト：カード1枚を引き、 自分の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op16_078_on_play_search_navy_to_hand_ai():
    """【登場時】デッキ上5から《海軍》1枚を手札へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NAVY_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(NAVY_C)] + [repo.get(RED1)] * 20  # 上5に 海軍 を1枚
    me.hand = []
    do, _ = _do(overlay, "OP16-078", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-078"), sickness=True))
    _drain(st, [0])
    assert any(c.card_id == NAVY_C for c in me.hand), \
        "デッキ上5枚から《海軍》キャラが手札に加わっていない"


def test_op16_078_on_play_search_human_modal():
    """人間 + デッキ上5に《海軍》複数 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NAVY_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(NAVY_C), repo.get(NAVY_C2)] + [repo.get(RED1)] * 20
    me.hand = []
    do, _ = _do(overlay, "OP16-078", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP16-078"), sickness=True))
    assert st.pending_choice is not None and \
        "search_top_n" in st.pending_choice.get("kind", ""), \
        f"人間で search_top_n modal が立たない: {st.pending_choice}"
    resolve_pending_choice(st, [0])  # 先頭 (海軍) を選択
    _drain(st, [])
    assert any(c.card_id in (NAVY_C, NAVY_C2) for c in me.hand), \
        "人間が選んだ《海軍》キャラが手札に加わっていない"


def test_op16_078_activate_main_draw_then_discard_ai():
    """【起動メイン】ドン!!-1 + ステージレスト → 1ドロー + 手札1枚捨て (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NAVY_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("OP16-078"), sickness=False)  # STAGE
    me.stages = [stage]
    me.don_active = 1        # ドン!!-1 コスト用
    me.hand = [repo.get(RED1)]  # 捨てコスト用の手札 1 枚
    me.deck = [repo.get(RED1)] * 10

    opts = _am(st, me, overlay, "OP16-078")
    assert len(opts) == 1, \
        f"OP16-078 (ステージ) の起動メインが legal に出ない: {len(opts)}"
    src, eff = opts[0]
    fire_activate_main(st, me, opp, src, eff)
    _drain(st, [0])
    # コスト: ドン1消費 (active→deck)、 ステージレスト。 効果: 1 ドロー + 手札1枚捨て。
    assert me.don_active == 0, f"ドン!!-1 が消費されていない: {me.don_active}"
    assert stage.rested is True, "起動メインコストでステージがレストされるべき"
    # 手札 net: 1 (初期) + 1 (draw) - 1 (捨て) = 1
    assert len(me.hand) == 1, f"draw + 手札1枚捨ての net が合わない: {len(me.hand)}"
    assert len(me.trash) == 1, f"捨てた手札1枚がトラッシュに無い: {len(me.trash)}"


def test_op16_078_activate_main_not_legal_without_don():
    """ドン!!が0枚 → ドン!!-1 コストが払えず起動メインは legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NAVY_LEADER, overlay)
    me, _ = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("OP16-078"), sickness=False)
    me.stages = [stage]
    me.don_active = 0  # ドン!!無し
    assert len(_am(st, me, overlay, "OP16-078")) == 0, \
        "ドン!!0枚で起動メインが legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP16-081 お玉 (CHARACTER 黒 cost2):
#    【起動メイン】このキャラをレストにできる：コスト8以上のキャラがいる場合、
#                 相手のキャラ1枚までを、 このターン中、 パワー-2000。
# --------------------------------------------------------------------------- #
def test_op16_081_activate_main_debuff_when_cost8_present_ai():
    """【起動メイン】自レスト → 場にコスト8+キャラがいる → 相手キャラ1枚 -2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    otama = InPlay.of(repo.get("OP16-081"), sickness=False)
    big = InPlay.of(repo.get(NAVY_C), sickness=False)  # cost8 (= 条件成立源)
    me.characters = [otama, big]
    victim = InPlay.of(repo.get(RED1), sickness=False)  # power 2000
    opp.characters = [victim]

    opts = _am(st, me, overlay, "OP16-081")
    assert len(opts) == 1, \
        f"OP16-081 の起動メイン (コスト8+キャラ在場) が legal に出ない: {len(opts)}"
    power_before = victim.power
    src, eff = opts[0]
    fire_activate_main(st, me, opp, src, eff)
    _drain(st, [0])
    assert otama.rested is True, "起動メインコストで お玉 がレストされるべき"
    assert victim.power == power_before - 2000, \
        f"相手キャラ -2000 が反映されていない: {victim.power} (before {power_before})"


def test_op16_081_activate_main_not_legal_without_cost8():
    """コスト8以上のキャラが場にいない → if 条件不成立で起動メインは legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, _ = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP16-081"), sickness=False)]  # お玉 (cost2) のみ

    # ⚠ 2026-08-05: コロン後の条件は効果のみを gate する (cardqa_op_02 / cardqa_st_04)。
    #   任意コストは条件不成立でも払えるので legal には残る。
    assert len(_am(st, me, overlay, "OP16-081")) == 1, \
        "任意コストは条件不成立でも払えるので legal に残るべき (cardqa_op_02)"


def test_op16_081_activate_main_debuff_human_pick():
    """人間 + 相手キャラ複数 → -2000 の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    otama = InPlay.of(repo.get("OP16-081"), sickness=False)
    big = InPlay.of(repo.get(NAVY_C), sickness=False)
    me.characters = [otama, big]
    a = InPlay.of(repo.get(RED1), sickness=False)   # power 2000
    b = InPlay.of(repo.get(NAVY_C2), sickness=False)  # power 7000
    opp.characters = [a, b]

    src, eff = _am(st, me, overlay, "OP16-081")[0]
    fire_activate_main(st, me, opp, src, eff)
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "target_pick", \
        f"人間で target_pick modal が立たない: {st.pending_choice}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が相手キャラ2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    _drain(st, [])
    assert b.power == b_before - 2000, "人間が選んだ相手キャラに -2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP16-082 錦えもん (CHARACTER 黒 cost4 power6000):
#    このキャラのコスト+3 (手札時)。
#    【登場時】リーダーが《ワノ国》なら、 デッキ上5枚を見て《ワノ国》1枚までを手札へ、
#             残りをトラッシュ。
# --------------------------------------------------------------------------- #
def test_op16_082_in_hand_cost_plus_3():
    """手札時 コスト+3 (= in_hand_cost_plus) が計算に反映される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WANO_LEADER, overlay)
    me, _ = st.players[0], st.players[1]
    # _compute_in_hand_cost_minus は cost_plus を「負の軽減」で返す (= -3)。
    delta = _compute_in_hand_cost_minus(st, me, repo.get("OP16-082"))
    assert delta == -3, f"手札時 コスト+3 が反映されていない: delta={delta}"


def test_op16_082_on_play_search_wano_when_wano_leader_ai():
    """【登場時】ワノ国リーダー → デッキ上5から《ワノ国》1枚を手札へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WANO_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    _, eff = _do(overlay, "OP16-082", "on_play")
    assert _cond_of(eff).get("leader_feature") == "ワノ国", \
        "on_play の leader_feature 条件 (ワノ国) が overlay に無い"
    assert eval_condition(_cond_of(eff), st, me, None) is True, \
        "ワノ国リーダーで条件が成立していない"
    me.deck = [repo.get(WANO_C)] + [repo.get(RED1)] * 20  # 上5に ワノ国 を1枚
    me.hand = []
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-082"), sickness=True))
    _drain(st, [0])
    assert any(c.card_id == WANO_C for c in me.hand), \
        "デッキ上5枚から《ワノ国》キャラが手札に加わっていない"


def test_op16_082_on_play_condition_false_when_not_wano():
    """非《ワノ国》リーダー → on_play の条件が成立しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, _ = st.players[0], st.players[1]
    _, eff = _do(overlay, "OP16-082", "on_play")
    assert eval_condition(_cond_of(eff), st, me, None) is False, \
        "非ワノ国リーダーで条件が成立してはいけない"


def test_op16_082_on_play_search_human_modal():
    """人間 + デッキ上5に《ワノ国》複数 → search_top_n modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WANO_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(WANO_C), repo.get(WANO_C2)] + [repo.get(RED1)] * 20
    me.hand = []
    do, _ = _do(overlay, "OP16-082", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP16-082"), sickness=True))
    assert st.pending_choice is not None and \
        "search_top_n" in st.pending_choice.get("kind", ""), \
        f"人間で search_top_n modal が立たない: {st.pending_choice}"
    resolve_pending_choice(st, [0])
    _drain(st, [])
    assert any(c.card_id in (WANO_C, WANO_C2) for c in me.hand), \
        "人間が選んだ《ワノ国》キャラが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP16-083 光月おでん (CHARACTER 黒 cost5 power6000):
#    【ブロッカー】【登場時】自分の手札からコスト8以上のキャラ1枚を捨てることができる：
#                 カード2枚を引く。
# --------------------------------------------------------------------------- #
def test_op16_083_on_play_discard_cost8_then_draw2_ai():
    """【登場時】手札のコスト8+キャラ1枚を捨て → 2ドロー (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(NAVY_C), repo.get(RED1), repo.get(RED1)]  # cost8 + フィラー2
    me.deck = [repo.get(RED1)] * 10
    do, _ = _do(overlay, "OP16-083", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-083"), sickness=True))
    _drain(st, [0])
    # 手札 net: 3 (初期) - 1 (捨て) + 2 (draw) = 4
    assert len(me.hand) == 4, f"discard1 + draw2 の net が合わない: {len(me.hand)}"
    assert any(c.card_id == NAVY_C for c in me.trash), \
        "捨てたコスト8キャラがトラッシュに無い"


def test_op16_083_on_play_no_fire_without_cost8_in_hand():
    """手札にコスト8+キャラが無い → 任意コスト不能で不発 (ドローしない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(RED1), repo.get(RED1)]  # cost8 キャラ無し
    me.deck = [repo.get(RED1)] * 10
    do, _ = _do(overlay, "OP16-083", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-083"), sickness=True))
    _drain(st, [0])
    assert len(me.hand) == 2, \
        f"コスト8キャラが無いのにドローが起きている: {len(me.hand)}"


def test_op16_083_on_play_human_optional_confirm():
    """人間: 任意コスト → optional_cost_confirm modal が立ち、 承諾で 2ドローまで解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(NAVY_C)]
    me.deck = [repo.get(RED1)] * 10
    do, _ = _do(overlay, "OP16-083", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP16-083"), sickness=True))
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"人間で optional_cost_confirm modal が立たない: {st.pending_choice}"
    resolve_pending_choice(st, [1])  # 承諾 (= コストを払う)
    _drain(st, [0])
    # 手札 net: 1 (初期) - 1 (捨て) + 2 (draw) = 2
    assert len(me.hand) == 2, f"人間承諾後 discard1 + draw2 の net が合わない: {len(me.hand)}"


# --------------------------------------------------------------------------- #
#  OP16-085 光月モモの助 (CHARACTER 黒 cost9 power6000):
#    【ブロッカー】【登場時】自分のトラッシュから「光月モモの助」以外のコスト6以下の
#                 《ワノ国》キャラ1枚までを、 登場させる。
# --------------------------------------------------------------------------- #
def test_op16_085_on_play_play_wano_from_trash_ai():
    """【登場時】トラッシュから《ワノ国》コスト6以下キャラ1枚を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WANO_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(WANO_C)]  # マルコ ワノ国 cost4
    do, _ = _do(overlay, "OP16-085", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-085"), sickness=True))
    _drain(st, [0])
    assert any(c.card.card_id == WANO_C for c in me.characters), \
        "トラッシュから《ワノ国》コスト6以下キャラが登場していない"


def test_op16_085_on_play_no_target_when_excluded_only():
    """トラッシュに「光月モモの助」しかいない → 除外名で対象なし (登場しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WANO_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP16-085")]  # 光月モモの助 = 除外名 (+ cost9 > 6)
    do, _ = _do(overlay, "OP16-085", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-085"), sickness=True))
    _drain(st, [0])
    assert len(me.characters) == 0, \
        "除外名/コスト超過のみのトラッシュから登場してはいけない"


def test_op16_085_on_play_play_human_pick():
    """人間 + トラッシュに《ワノ国》コスト6以下 複数 → play_from_trash_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WANO_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(WANO_C), repo.get(WANO_C2)]  # マルコ / びん豪 (両方ワノ国 cost6以下)
    do, _ = _do(overlay, "OP16-085", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP16-085"), sickness=True))
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "play_from_trash_pick", \
        f"人間で play_from_trash_pick modal が立たない: {st.pending_choice}"
    resolve_pending_choice(st, [0])  # 先頭候補を登場
    _drain(st, [0])
    assert any(c.card.card_id in (WANO_C, WANO_C2) for c in me.characters), \
        "人間が選んだ《ワノ国》キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP16-089 ジュラキュール・ミホーク (CHARACTER 黒 cost6 power8000):
#    【速攻：キャラ】【登場時】カード2枚を引き、 自分の手札2枚を捨てる。 その後、
#                   相手のキャラ1枚までを、 このターン中、 コスト-4。
# --------------------------------------------------------------------------- #
def test_op16_089_on_play_draw_discard_cost_minus_ai():
    """【登場時】2ドロー + 手札2枚捨て + 相手キャラ1枚 コスト-4 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(RED1), repo.get(RED1)]
    me.deck = [repo.get(RED1)] * 10
    victim = InPlay.of(repo.get(NAVY_C), sickness=False)  # cost8
    opp.characters = [victim]

    cost_before = victim.base_cost
    do, _ = _do(overlay, "OP16-089", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-089"), sickness=True))
    _drain(st, [0])
    # 手札 net: 2 (初期) + 2 (draw) - 2 (捨て) = 2
    assert len(me.hand) == 2, f"draw2 + 手札2枚捨ての net が合わない: {len(me.hand)}"
    assert victim.base_cost == cost_before - 4, \
        f"相手キャラ コスト-4 が反映されていない: {victim.base_cost} (before {cost_before})"


def test_op16_089_on_play_cost_minus_human_pick():
    """人間 + 相手キャラ複数 → コスト-4 の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(NAVY_C), sickness=False)   # cost8
    b = InPlay.of(repo.get(NAVY_C2), sickness=False)  # cost5
    opp.characters = [a, b]
    do, _ = _do(overlay, "OP16-089", "on_play")
    # 対象選択を持つ末尾 cost_minus を直接発火 (draw/discard は対象なし)
    execute_effect(do[-1], st, me, opp,
                   InPlay.of(repo.get("OP16-089"), sickness=True))
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "target_pick", \
        f"人間で target_pick modal が立たない: {st.pending_choice}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が相手キャラ2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.base_cost
    resolve_pending_choice(st, [b_idx])
    _drain(st, [])
    assert b.base_cost == b_before - 4, "人間が選んだ相手キャラに コスト-4 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP16-090 トニートニー・チョッパー (CHARACTER 黒 cost3 power4000):
#    【登場時】カード2枚を引き、 自分の手札2枚を捨てる。 その後、
#             相手のコスト1以下のキャラ1枚までを、 KOする。
# --------------------------------------------------------------------------- #
def test_op16_090_on_play_draw_discard_ko_cost1_ai():
    """【登場時】2ドロー + 手札2枚捨て + 相手コスト1以下キャラ1枚 KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(RED1), repo.get(RED1)]
    me.deck = [repo.get(RED1)] * 10
    victim = InPlay.of(repo.get(RED1), sickness=False)  # cost1
    opp.characters = [victim]

    do, _ = _do(overlay, "OP16-090", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-090"), sickness=True))
    _drain(st, [0])
    assert len(me.hand) == 2, f"draw2 + 手札2枚捨ての net が合わない: {len(me.hand)}"
    assert victim not in opp.characters, "相手コスト1以下キャラが KO されていない"


def test_op16_090_on_play_no_ko_cost2():
    """相手のキャラがコスト2 → コスト1以下でないので KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(RED1), repo.get(RED1)]
    me.deck = [repo.get(RED1)] * 10
    victim = InPlay.of(repo.get("OP16-081"), sickness=False)  # お玉 cost2
    opp.characters = [victim]
    do, _ = _do(overlay, "OP16-090", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-090"), sickness=True))
    _drain(st, [0])
    assert victim in opp.characters, "コスト2のキャラが KO されてはいけない"


def test_op16_090_on_play_ko_human_pick():
    """人間 + 相手のコスト1以下キャラ複数 → KO の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(RED1), sickness=False)      # cost1
    b = InPlay.of(repo.get(WANO_C2), sickness=False)   # びん豪 cost1
    opp.characters = [a, b]
    do, _ = _do(overlay, "OP16-090", "on_play")
    execute_effect(do[-1], st, me, opp,
                   InPlay.of(repo.get("OP16-090"), sickness=True))
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "target_pick", \
        f"人間で target_pick modal が立たない: {st.pending_choice}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b not in opp.characters, "人間が選んだ相手キャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP16-091 ナミ (CHARACTER 黒 cost1 power2000):
#    【登場時】リーダーが《ワノ国》なら、 デッキ上4枚を見て「ナミ」以外の《ワノ国》1枚を
#             手札へ、 残りをトラッシュ。
# --------------------------------------------------------------------------- #
def test_op16_091_on_play_search_wano_when_wano_leader_ai():
    """【登場時】ワノ国リーダー → デッキ上4から「ナミ」以外の《ワノ国》1枚を手札へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WANO_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    _, eff = _do(overlay, "OP16-091", "on_play")
    assert eval_condition(_cond_of(eff), st, me, None) is True, \
        "ワノ国リーダーで条件が成立していない"
    me.deck = [repo.get(WANO_C)] + [repo.get(RED1)] * 20  # 上4に ワノ国 (マルコ) を1枚
    me.hand = []
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-091"), sickness=True))
    _drain(st, [0])
    assert any(c.card_id == WANO_C for c in me.hand), \
        "デッキ上4枚から「ナミ」以外の《ワノ国》キャラが手札に加わっていない"


def test_op16_091_on_play_condition_false_when_not_wano():
    """非《ワノ国》リーダー → on_play の条件が成立しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, _ = st.players[0], st.players[1]
    _, eff = _do(overlay, "OP16-091", "on_play")
    assert eval_condition(_cond_of(eff), st, me, None) is False, \
        "非ワノ国リーダーで条件が成立してはいけない"


def test_op16_091_on_play_excludes_nami_by_name():
    """デッキ上4が「ナミ」だけ (除外名) → 対象なしで手札に加わらない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WANO_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    # OP16-091 自体が ワノ国 かつ 名前「ナミ」 = 除外対象
    me.deck = [repo.get("OP16-091")] + [repo.get(RED1)] * 20
    me.hand = []
    do, _ = _do(overlay, "OP16-091", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP16-091"), sickness=True))
    _drain(st, [0])
    assert not any(c.card_id == "OP16-091" for c in me.hand), \
        "除外名「ナミ」が手札に加わってはいけない"


def test_op16_091_on_play_search_human_modal():
    """人間 + デッキ上4に「ナミ」以外の《ワノ国》複数 → search_top_n modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WANO_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(WANO_C), repo.get(WANO_C2)] + [repo.get(RED1)] * 20
    me.hand = []
    do, _ = _do(overlay, "OP16-091", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP16-091"), sickness=True))
    assert st.pending_choice is not None and \
        "search_top_n" in st.pending_choice.get("kind", ""), \
        f"人間で search_top_n modal が立たない: {st.pending_choice}"
    resolve_pending_choice(st, [0])
    _drain(st, [])
    assert any(c.card_id in (WANO_C, WANO_C2) for c in me.hand), \
        "人間が選んだ《ワノ国》キャラが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP16-092 ニコ・ロビン (CHARACTER 黒 cost1 power2000):
#    【登場時】自分の手札からコスト8以上のキャラ1枚を捨てることができる：カード2枚を引く。
# --------------------------------------------------------------------------- #
def test_op16_092_on_play_discard_cost8_then_draw2_ai():
    """【登場時】手札のコスト8+キャラ1枚を捨て → 2ドロー (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(NAVY_C), repo.get(RED1), repo.get(RED1)]
    me.deck = [repo.get(RED1)] * 10
    do, _ = _do(overlay, "OP16-092", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-092"), sickness=True))
    _drain(st, [0])
    assert len(me.hand) == 4, f"discard1 + draw2 の net が合わない: {len(me.hand)}"
    assert any(c.card_id == NAVY_C for c in me.trash), \
        "捨てたコスト8キャラがトラッシュに無い"


def test_op16_092_on_play_no_fire_without_cost8():
    """手札にコスト8+キャラが無い → 任意コスト不能で不発 (ドローしない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(RED1), repo.get(RED1)]
    me.deck = [repo.get(RED1)] * 10
    do, _ = _do(overlay, "OP16-092", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-092"), sickness=True))
    _drain(st, [0])
    assert len(me.hand) == 2, \
        f"コスト8キャラが無いのにドローが起きている: {len(me.hand)}"


def test_op16_092_on_play_human_optional_confirm():
    """人間: 任意コスト → optional_cost_confirm modal が立ち、 承諾で 2ドローまで解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(NAVY_C)]
    me.deck = [repo.get(RED1)] * 10
    do, _ = _do(overlay, "OP16-092", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP16-092"), sickness=True))
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"人間で optional_cost_confirm modal が立たない: {st.pending_choice}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert len(me.hand) == 2, f"人間承諾後 discard1 + draw2 の net が合わない: {len(me.hand)}"


# --------------------------------------------------------------------------- #
#  OP16-093 バーソロミュー・くま (CHARACTER 黒 cost3 power4000):
#    【登場時】カード2枚を引き、 自分の手札2枚を捨てる。 その後、
#             自分のリーダーかキャラ1枚にレストのドン!!1枚までを、 付与する。
# --------------------------------------------------------------------------- #
def test_op16_093_on_play_draw_discard_attach_don_ai():
    """【登場時】2ドロー + 手札2枚捨て + 自リーダーにレストドン1枚付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(RED1), repo.get(RED1)]
    me.deck = [repo.get(RED1)] * 10
    me.don_rested = 1  # 付与元 レストドン

    don_before = me.leader.attached_dons
    do, _ = _do(overlay, "OP16-093", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-093"), sickness=True))
    _drain(st, [0])
    assert len(me.hand) == 2, f"draw2 + 手札2枚捨ての net が合わない: {len(me.hand)}"
    assert me.leader.attached_dons == don_before + 1, \
        "自リーダーにレストドンが付与されていない"
    assert me.don_rested == 0, "レストドンが1枚消費されるべき"


def test_op16_093_on_play_attach_don_human_pick():
    """人間 + 自リーダー/キャラ複数 → レストドン付与先の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 1
    friend = InPlay.of(repo.get(RED1), sickness=False)
    me.characters = [friend]
    do, _ = _do(overlay, "OP16-093", "on_play")
    # 対象選択を持つ末尾 attach_rested_don を直接発火
    execute_effect(do[-1], st, me, opp,
                   InPlay.of(repo.get("OP16-093"), sickness=True))
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "target_pick", \
        f"人間で target_pick modal が立たない: {st.pending_choice}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    resolve_pending_choice(st, [friend_idx])
    _drain(st, [])
    assert friend.attached_dons == 1, \
        "人間が選んだキャラにレストドンが付与されていない"
