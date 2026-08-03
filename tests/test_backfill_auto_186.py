# -*- coding: utf-8 -*-
"""ST28 / ST29 弾 効果 回帰テスト バックフィル (自動生成 wave 186):
ST28-002 / ST28-003 / ST28-004 / ST28-005 / ST29-001 / ST29-002 /
ST29-003 / ST29-004 / ST29-005 / ST29-007 の 10 枚。

  ST28-002 イゾウ (CHARACTER 黄) = 【ドン‼×2】ブロッカー /【登場時】自リーダーが
     《ワノ国》なら このターン中【バニッシュ】を得る
     (on_play give_keyword self_leader バニッシュ if leader_feature ワノ国;
      on_attached_don n2 give_keyword self ブロッカー)
  ST28-003 錦えもん (CHARACTER 黄) = 【トリガー】自リーダー《ワノ国》かつ相手ライフ3以下なら
     このカードを登場させる (trigger play_self if leader_feature ワノ国 & opp_life_le 3)
  ST28-004 光月モモの助 (CHARACTER 黄) = 【自分のターン中】自ライフ2以下なら 自リーダー+1000 /
     【起動メイン】【ターン1回】付与ドン2枚をコストへレストで戻す：このキャラは【速攻】+1000
     (静的 power_pump self_leader if self_turn & self_life_le 2;
      activate_main optional_cost_then return_attached_don_to_cost_rested 2 → 速攻+power)
  ST28-005 ヤマト (CHARACTER 黄) = 【ドン‼×2】【自分のターン中】このキャラ+3000 /
     【登場時】デッキ上5枚を見てコスト2以上の《ワノ国》1枚を手札、残りをデッキ下
     (on_play search_top_n depth5 filter cost_ge2 feature ワノ国;
      on_attached_don n2 power_pump self 3000 if self_turn)
  ST29-001 モンキー・Ｄ・ルフィ (LEADER 黄) = 【アタック時】自ライフ2以下なら 1ドロー、
     手札1枚を捨てる (on_attack draw + trash_self_hand_random if self_life_le 2)
  ST29-002 ウソップ (CHARACTER 黄) = 【登場時】/【アタック時】相手ライフ枚数以下のコストを
     持つ相手キャラ1枚までをレスト
     (on_play / on_attack rest one_opponent_character_filtered cost_le_dynamic opp_life_count)
  ST29-003 カク (CHARACTER 黄) = 自ライフ枚数≤相手ライフ枚数なら このキャラ+1000 /
     【トリガー】相手のコスト3以下のキャラ1枚までをKO
     (静的 power_pump self if self_life_le_opp; trigger ko one_opponent_character_cost_le_3cost)
  ST29-004 サンジ (CHARACTER 黄) = 【登場時】デッキ上4枚を見て《麦わらの一味》1枚を手札 /
     【トリガー】自手札1枚を捨てる：このカードを登場させる
     (on_play search_top_n depth4 feature 麦わらの一味;
      trigger optional_cost_then trash_self_hand_random → play_self)
  ST29-005 ジンベエ (CHARACTER 黄) = 【トリガー】自リーダーが「モンキー・Ｄ・ルフィ」なら
     このカードを登場させる (trigger play_self if leader_name モンキー・Ｄ・ルフィ)
  ST29-007 トニートニー・チョッパー (CHARACTER 黄) = 【KO時】自ライフ上下1枚を手札に加える：
     自手札1枚までをライフの上に加える /【トリガー】自「モンキー・Ｄ・ルフィ」+2000
     (on_ko optional_cost_then life_top_or_bottom_to_hand → hand_to_self_life;
      trigger power_pump self_chara_or_leader_named モンキー・Ｄ・ルフィ 2000)

目的 (= test_backfill_auto_001〜185.py と同一方針):
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
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

_LEADER_WANO = "EB01-001"    # 光月おでん (ワノ国/光月家) — ワノ国 leader
_LEADER_LUFFY = "ST29-001"   # モンキー・Ｄ・ルフィ (LEADER 黄)
_LEADER_PLAIN = "OP01-001"   # ロロノア・ゾロ — 汎用 (ワノ国/ルフィ でない役)
_FILLER = "OP01-013"         # サンジ cost2 power3000 麦わらの一味
_NAMI = "OP01-016"           # ナミ cost1 power2000 麦わらの一味
_BIG = "PRB02-013"           # ゲッコー・モリア cost6 power7000
_WANO_C = "PRB02-016"        # お玉 cost2 ワノ国 (= コスト2以上の《ワノ国》)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id=_LEADER_PLAIN,
           turn_player=0):
    """P0 = テスト対象デッキ、 P1 = ダミー。 MAIN / turn_number=3。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(_FILLER)] * 30
    p1.deck = [repo.get(_FILLER)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn_player
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _eff(overlay, cid, when):
    """指定 card_id の overlay から when 一致の効果 (dict) を返す (先頭)。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    return matches[0]


def _effs(overlay, cid, when):
    return [e for e in overlay.get(cid).effects if e.get("when") == when]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [0])
        n += 1


def _resolve_search(st):
    """search_top_n modal → 候補 index 0 を選択 → 残る reorder modal を空順で drain。"""
    resolve_pending_choice(st, [0])
    guard = 0
    while st.pending_choice is not None and guard < 6:
        resolve_pending_choice(st, [])
        guard += 1


def _acts(st, me, overlay, cid):
    return [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == cid]


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave186_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["ST28-002", "ST28-003", "ST28-004", "ST28-005", "ST29-001",
           "ST29-002", "ST29-003", "ST29-004", "ST29-005", "ST29-007"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  ST28-002 イゾウ: 【登場時】ワノ国 leader なら 自リーダー【バニッシュ】/
#            【ドン‼×2】このキャラ【ブロッカー】
# --------------------------------------------------------------------------- #
def test_st28_002_on_play_leader_banish_when_wano():
    """登場時: ワノ国 leader → 自リーダーに【バニッシュ】が付与される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WANO, overlay)
    me, opp = st.players[0], st.players[1]
    eff = _eff(overlay, "ST28-002", "on_play")
    assert eff.get("if", {}).get("leader_feature") == "ワノ国", \
        "overlay の ワノ国 leader 条件が無い"
    assert eval_condition(eff.get("if", {}), st, me, opp) is True, \
        "ワノ国 leader で条件が成立していない"

    assert me.leader.is_banish_now is False
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST28-002"), sickness=True))
    _drain(st)
    assert me.leader.is_banish_now is True, \
        "登場時に自リーダーへ【バニッシュ】が付与されていない"


def test_st28_002_condition_off_when_plain_leader():
    """ワノ国 でない leader なら 条件不成立 (= バニッシュ付与しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    eff = _eff(overlay, "ST28-002", "on_play")
    assert eval_condition(eff.get("if", {}), st, me, opp) is False, \
        "ワノ国 でない leader では条件が不成立であるべき"


def test_st28_002_don2_grants_blocker():
    """【ドン‼×2】このキャラは【ブロッカー】を得る (on_attached_don n=2)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WANO, overlay)
    me, opp = st.players[0], st.players[1]
    izou = InPlay.of(repo.get("ST28-002"), sickness=False)
    me.characters = [izou]
    eff = _eff(overlay, "ST28-002", "on_attached_don")
    assert eff.get("n") == 2, "ドン‼×2 の n=2 条件が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, izou)
    assert izou.is_blocker_now is True, "ドン‼×2 で【ブロッカー】が付与されていない"


# --------------------------------------------------------------------------- #
#  ST28-003 錦えもん: 【トリガー】ワノ国 leader かつ相手ライフ3以下なら 自身を登場
# --------------------------------------------------------------------------- #
def test_st28_003_trigger_play_self_when_wano_and_low_life_ai():
    """トリガー: ワノ国 leader + 相手ライフ3以下 → 自身を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WANO, overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_FILLER)] * 3  # 相手ライフ 3 (= opp_life_le 3 成立)
    me.trash = [repo.get("ST28-003")]
    st.current_source_card_id = "ST28-003"

    eff = _eff(overlay, "ST28-003", "trigger")
    assert eff.get("if", {}).get("leader_feature") == "ワノ国", \
        "overlay の ワノ国 leader 条件が無い"
    assert eff.get("if", {}).get("opp_life_le") == 3, \
        "overlay の 相手ライフ3以下条件が無い"
    assert eval_condition(eff.get("if", {}), st, me, opp) is True, \
        "ワノ国 leader + 相手ライフ3 で条件が成立していない"

    chars_before = len(me.characters)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    assert any(c.card.card_id == "ST28-003" for c in me.characters), \
        "トリガー play_self で 錦えもん が登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"


def test_st28_003_condition_off_when_life_high():
    """相手ライフが4枚 (> 3) なら 条件不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WANO, overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_FILLER)] * 4
    eff = _eff(overlay, "ST28-003", "trigger")
    assert eval_condition(eff.get("if", {}), st, me, opp) is False, \
        "相手ライフ4枚では条件が不成立であるべき"


# --------------------------------------------------------------------------- #
#  ST28-004 光月モモの助: 静的 自リーダー+1000 (自ライフ2以下) /
#            起動メイン 付与ドン2枚返却 → 自身【速攻】+1000
# --------------------------------------------------------------------------- #
def test_st28_004_static_leader_pump_when_low_life():
    """【自分のターン中】自ライフ2以下 → 自リーダー パワー+1000 (静的)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)  # OP01-001 power5000
    me, _opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("ST28-004"), sickness=False)]
    me.life = [repo.get(_FILLER)] * 2  # 自ライフ 2 (= 条件成立)
    leader_base = me.leader.power

    evaluate_static_effects(st, overlay)
    assert me.leader.power == leader_base + 1000, \
        f"自ライフ2以下で 自リーダー+1000 が反映されていない: {me.leader.power}"


def test_st28_004_static_no_pump_when_high_life():
    """自ライフ3枚 (> 2) なら 自リーダーへの +1000 は乗らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, _opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("ST28-004"), sickness=False)]
    me.life = [repo.get(_FILLER)] * 3
    leader_base = me.leader.power

    evaluate_static_effects(st, overlay)
    assert me.leader.power == leader_base, \
        f"自ライフ3枚で +1000 が乗ってはいけない: {me.leader.power}"


def test_st28_004_activate_main_rush_and_pump_ai():
    """起動メイン: 付与ドン2枚を返却 → 自身【速攻】+1000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    mom = InPlay.of(repo.get("ST28-004"), sickness=True)  # base power7000
    mom.attached_dons = 2  # 返却コスト源
    me.characters = [mom]

    eff = _eff(overlay, "ST28-004", "activate_main")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, mom)
    _drain(st)

    assert mom.is_rush_now is True, "起動メインで【速攻】が付与されていない"
    assert mom.attached_dons == 0, "返却コストで 付与ドン2枚が消費されていない"
    assert me.don_rested >= 2, "返却された2枚が コストエリアにレストで戻っていない"
    # 付与ドン返却後 (= don+1000 なし) の 実効パワー = base7000 + 効果+1000
    assert mom.power == 7000 + 1000, \
        f"起動メインの +1000 が反映されていない: {mom.power}"


def test_st28_004_activate_main_human_optional_confirm():
    """人間: 起動メインの任意コストで optional_cost_confirm modal が立ち pay で解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    mom = InPlay.of(repo.get("ST28-004"), sickness=True)
    mom.attached_dons = 2
    me.characters = [mom]

    eff = _eff(overlay, "ST28-004", "activate_main")
    execute_effect(eff["do"][0], st, me, opp, mom)
    assert st.pending_choice is not None, "人間で任意コスト確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # pay
    _drain(st)
    assert mom.is_rush_now is True, "人間が支払った後に【速攻】が付与されていない"
    assert mom.attached_dons == 0, "人間の支払いで 付与ドンが返却されていない"


# --------------------------------------------------------------------------- #
#  ST28-005 ヤマト: 【登場時】デッキ上5枚 → コスト2以上《ワノ国》1枚を手札 /
#            【ドン‼×2】【自分のターン中】このキャラ+3000
# --------------------------------------------------------------------------- #
def test_st28_005_on_play_search_wano_ai():
    """登場時: デッキ上5枚から コスト2以上の《ワノ国》を手札に加える (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WANO, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_WANO_C)] + [repo.get(_FILLER)] * 20  # 先頭に お玉(ワノ国 cost2)
    me.hand = []

    execute_effect(_eff(overlay, "ST28-005", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST28-005"), sickness=True))
    _drain(st, [])
    assert any(c.card_id == _WANO_C for c in me.hand), \
        "デッキ上5枚から コスト2以上の《ワノ国》が手札に加わっていない"


def test_st28_005_on_play_search_human_pick():
    """人間: search_top_n modal が立ち、 選択で《ワノ国》が手札に加わる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WANO, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_WANO_C)] + [repo.get(_FILLER)] * 20
    me.hand = []

    execute_effect(_eff(overlay, "ST28-005", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST28-005"), sickness=True))
    assert st.pending_choice is not None, "人間で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    _resolve_search(st)
    assert any(c.card_id == _WANO_C for c in me.hand), \
        "人間が選んだ《ワノ国》カードが手札に加わっていない"


def test_st28_005_don2_self_pump():
    """【ドン‼×2】【自分のターン中】このキャラ パワー+3000 (on_attached_don n=2)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WANO, overlay)
    me, opp = st.players[0], st.players[1]
    yamato = InPlay.of(repo.get("ST28-005"), sickness=False)
    me.characters = [yamato]
    eff = _eff(overlay, "ST28-005", "on_attached_don")
    assert eff.get("n") == 2, "ドン‼×2 の n=2 条件が無い"
    power_before = yamato.power
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, yamato)
    assert yamato.power == power_before + 3000, \
        f"ドン‼×2 の +3000 が反映されていない: {yamato.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  ST29-001 モンキー・Ｄ・ルフィ (LEADER): 【アタック時】自ライフ2以下なら
#            1ドロー + 手札1枚を捨てる
# --------------------------------------------------------------------------- #
def test_st29_001_on_attack_draw_discard_ai():
    """アタック時: 自ライフ2以下 → 1ドロー + 手札1枚捨てる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_LUFFY, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2  # 自ライフ 2 (= 条件成立)
    me.hand = [repo.get(_FILLER), repo.get(_NAMI)]
    eff = _eff(overlay, "ST29-001", "on_attack")
    assert eff.get("if", {}).get("self_life_le") == 2, \
        "overlay の 自ライフ2以下条件が無い"
    assert eval_condition(eff.get("if", {}), st, me, opp) is True

    deck_before = len(me.deck)
    trash_before = len(me.trash)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, me.leader)
    _drain(st)
    assert len(me.deck) == deck_before - 1, "1ドローでデッキが1枚減っていない"
    assert len(me.trash) == trash_before + 1, "手札1枚がトラッシュに捨てられていない"


def test_st29_001_condition_off_when_life_high():
    """自ライフ3枚 (> 2) なら 条件不成立 (= ドロー/捨て 発動しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_LUFFY, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    eff = _eff(overlay, "ST29-001", "on_attack")
    assert eval_condition(eff.get("if", {}), st, me, opp) is False, \
        "自ライフ3枚では条件が不成立であるべき"


# --------------------------------------------------------------------------- #
#  ST29-002 ウソップ: 【登場時】/【アタック時】相手ライフ枚数以下のコストを持つ
#            相手キャラ1枚までをレスト
# --------------------------------------------------------------------------- #
def test_st29_002_on_play_rest_within_life_count_ai():
    """登場時: 相手ライフ3枚 → コスト3以下の相手キャラ (cost2) をレストにする (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_FILLER)] * 3
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 ≤ 3
    victim.rested = False
    opp.characters = [victim]

    for prim in _eff(overlay, "ST29-002", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST29-002"), sickness=True))
    _drain(st, [0])
    assert victim.rested is True, \
        "相手ライフ枚数以下のコストを持つ相手キャラがレストにされていない"


def test_st29_002_on_play_no_rest_when_cost_above_life_count():
    """相手ライフ1枚 → コスト2の相手キャラは対象外 (レストされない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_FILLER)] * 1  # ライフ1 → cost≤1 のみ対象
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 > 1
    victim.rested = False
    opp.characters = [victim]

    for prim in _eff(overlay, "ST29-002", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST29-002"), sickness=True))
    _drain(st, [0])
    assert victim.rested is False, \
        "ライフ枚数を超えるコストのキャラがレストされてはいけない (対象外)"


def test_st29_002_on_attack_rest_human_pick():
    """人間 + アタック時 対象複数 → target_pick modal → resolve で1枚レスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_FILLER)] * 3
    a = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    b = InPlay.of(repo.get(_NAMI), sickness=False)    # cost1
    a.rested = False
    b.rested = False
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "ST29-002", "on_attack")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST29-002"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b.rested is True, "人間が選んだ相手キャラがレストにされていない"
    assert a.rested is False, "選ばなかったキャラはアクティブのままであるべき"


# --------------------------------------------------------------------------- #
#  ST29-003 カク: 静的 自ライフ≤相手ライフ で このキャラ+1000 /
#            【トリガー】相手のコスト3以下のキャラ1枚までをKO
# --------------------------------------------------------------------------- #
def test_st29_003_static_self_pump_when_life_le_opp():
    """静的: 自ライフ ≤ 相手ライフ → このキャラ パワー+1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    kaku = InPlay.of(repo.get("ST29-003"), sickness=False)  # base power5000
    me.characters = [kaku]
    me.life = [repo.get(_FILLER)] * 1   # 自ライフ 1
    opp.life = [repo.get(_FILLER)] * 3  # 相手ライフ 3 → self_life_le_opp 成立

    evaluate_static_effects(st, overlay)
    assert kaku.power == 5000 + 1000, \
        f"自ライフ≤相手ライフで +1000 が反映されていない: {kaku.power}"


def test_st29_003_static_no_pump_when_life_gt_opp():
    """自ライフ > 相手ライフ なら +1000 は乗らない (= 条件を省略しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    kaku = InPlay.of(repo.get("ST29-003"), sickness=False)
    me.characters = [kaku]
    me.life = [repo.get(_FILLER)] * 3   # 自ライフ 3
    opp.life = [repo.get(_FILLER)] * 1  # 相手ライフ 1 → 不成立

    evaluate_static_effects(st, overlay)
    assert kaku.power == 5000, \
        f"自ライフ>相手ライフで +1000 が乗ってはいけない: {kaku.power}"


def test_st29_003_trigger_ko_cost3_ai():
    """トリガー: 相手のコスト3以下のキャラを KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 ≤ 3
    opp.characters = [victim]

    for prim in _eff(overlay, "ST29-003", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert victim not in opp.characters, "コスト3以下の相手キャラが KO されていない"


def test_st29_003_trigger_ko_human_pick():
    """人間 + コスト3以下の相手キャラ複数 → target_pick modal → resolve で1体KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    b = InPlay.of(repo.get(_NAMI), sickness=False)    # cost1
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "ST29-003", "trigger")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で KO 選択 modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  ST29-004 サンジ: 【登場時】デッキ上4枚 → 《麦わらの一味》1枚を手札 /
#            【トリガー】自手札1枚を捨てる：このカードを登場させる
# --------------------------------------------------------------------------- #
def test_st29_004_on_play_search_mugiwara_ai():
    """登場時: デッキ上4枚から《麦わらの一味》を手札に加える (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    # _FILLER (OP01-013 サンジ) は 麦わらの一味 → 上4枚に必ず含まれる
    me.deck = [repo.get(_FILLER)] * 20
    me.hand = []

    execute_effect(_eff(overlay, "ST29-004", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST29-004"), sickness=True))
    _drain(st, [])
    assert any(c.card_id == _FILLER for c in me.hand), \
        "デッキ上4枚から《麦わらの一味》が手札に加わっていない"


def test_st29_004_on_play_search_human_pick():
    """人間: search_top_n modal が立ち、 選択で《麦わらの一味》が手札に加わる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 20
    me.hand = []

    execute_effect(_eff(overlay, "ST29-004", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST29-004"), sickness=True))
    assert st.pending_choice is not None, "人間で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    _resolve_search(st)
    assert any(c.card_id == _FILLER for c in me.hand), \
        "人間が選んだ《麦わらの一味》が手札に加わっていない"


def test_st29_004_trigger_discard_then_play_self_ai():
    """トリガー: 手札1枚を捨てる (コスト) → 自身を登場させる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_NAMI), repo.get(_BIG)]  # 捨て札源 (ナミ / モリア)
    me.trash = [repo.get("ST29-004")]
    st.current_source_card_id = "ST29-004"

    chars_before = len(me.characters)
    for prim in _eff(overlay, "ST29-004", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    # play_self で サンジ 登場 (= trash から場へ移動)。 登場時 search が発火し手札は補充されうるため
    # 枚数ではなく「コストで捨てた札がトラッシュに落ちたか」で捨てコストを検証する。
    assert any(c.card.card_id == "ST29-004" for c in me.characters), \
        "トリガーの optional_cost_then → play_self で サンジ が登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"
    assert not any(c.card_id == "ST29-004" for c in me.trash), \
        "登場した サンジ がトラッシュから場へ移動していない"
    assert any(c.card_id in (_NAMI, _BIG) for c in me.trash), \
        "コストで捨てた手札1枚がトラッシュに置かれていない"


# --------------------------------------------------------------------------- #
#  ST29-005 ジンベエ: 【トリガー】自リーダーが「モンキー・Ｄ・ルフィ」なら 自身を登場
# --------------------------------------------------------------------------- #
def test_st29_005_trigger_play_self_when_luffy_leader_ai():
    """トリガー: リーダーが「モンキー・Ｄ・ルフィ」→ 自身を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_LUFFY, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("ST29-005")]
    st.current_source_card_id = "ST29-005"

    eff = _eff(overlay, "ST29-005", "trigger")
    assert eff.get("if", {}).get("leader_name") == "モンキー・Ｄ・ルフィ", \
        "overlay の リーダー名 条件が無い"
    assert eval_condition(eff.get("if", {}), st, me, opp) is True, \
        "ルフィ leader で条件が成立していない"

    chars_before = len(me.characters)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    assert any(c.card.card_id == "ST29-005" for c in me.characters), \
        "トリガー play_self で ジンベエ が登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"


def test_st29_005_condition_off_when_plain_leader():
    """リーダーが「モンキー・Ｄ・ルフィ」でなければ 条件不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    eff = _eff(overlay, "ST29-005", "trigger")
    assert eval_condition(eff.get("if", {}), st, me, opp) is False, \
        "ルフィ でない leader では条件が不成立であるべき"


# --------------------------------------------------------------------------- #
#  ST29-007 トニートニー・チョッパー: 【KO時】自ライフ上下1枚を手札：自手札1枚をライフ上 /
#            【トリガー】自「モンキー・Ｄ・ルフィ」+2000
# --------------------------------------------------------------------------- #
def test_st29_007_on_ko_life_hand_swap_ai():
    """KO時: 自ライフ1枚を手札へ (コスト) → 自手札1枚をライフ上へ (効果) (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_NAMI)]   # ライフ = ナミ
    me.hand = [repo.get(_BIG)]    # 手札 = モリア

    for prim in _eff(overlay, "ST29-007", "on_ko")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST29-007"), sickness=False))
    _drain(st)
    # cost: ナミ(ライフ) → 手札 / 効果: 手札先頭(モリア) → ライフ上
    assert len(me.life) == 1 and len(me.hand) == 1, \
        f"ライフ/手札の枚数が変わってはいけない: life={len(me.life)} hand={len(me.hand)}"
    assert any(c.card_id == _BIG for c in me.life), \
        "効果で 手札のカードが ライフの上に加わっていない"
    assert any(c.card_id == _NAMI for c in me.hand), \
        "コストで ライフのカードが 手札に加わっていない"


def test_st29_007_on_ko_human_optional_confirm():
    """人間: KO時の任意コストで optional_cost_confirm modal が立ち pay で解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_NAMI)]
    me.hand = [repo.get(_BIG)]

    execute_effect(_eff(overlay, "ST29-007", "on_ko")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST29-007"), sickness=False))
    assert st.pending_choice is not None, "人間で任意コスト確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # pay
    _drain(st)
    assert any(c.card_id == _BIG for c in me.life), \
        "人間が支払った後に 手札→ライフ が起きていない"


def test_st29_007_trigger_pump_named_luffy():
    """トリガー: 自「モンキー・Ｄ・ルフィ」(= リーダー) を このターン中 パワー+2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_LUFFY, overlay)
    me, opp = st.players[0], st.players[1]
    leader_base = me.leader.power

    for prim in _eff(overlay, "ST29-007", "trigger")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST29-007"), sickness=False))
    _drain(st)
    assert me.leader.power == leader_base + 2000, \
        f"トリガーで 自「モンキー・Ｄ・ルフィ」に +2000 が乗っていない: {me.leader.power}"
