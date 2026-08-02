# -*- coding: utf-8 -*-
"""ST09 / ST10 弾 効果 回帰テスト バックフィル (自動生成 wave 173):
ST09-009 / ST09-010 / ST09-012 / ST09-014 / ST09-015 / ST10-001 /
ST10-002 / ST10-004 / ST10-005 / ST10-007 の 10 枚。

目的 (= test_backfill_auto_001〜172.py と同一方針):
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
    eval_all_conditions,
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
    try_replace_ko,
)

ROOT = Path(__file__).resolve().parent.parent

# 汎用 埋めカード / 参照カード
_FILLER = "ST01-004"          # サンジ cost2 power4000 (バニラ気味)
_NEUTRAL_LEADER = "OP10-099"  # ユースタス・キッド (中立枠として利用、 黄)
_NAMI = "OP01-016"            # ナミ (cost1 power2000)
_BIG = "ST07-010"             # シャーロット・リンリン (CHARACTER cost7 power8000)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(_FILLER)] * 30
    p1.deck = [repo.get(_FILLER)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _eff(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果 dict を返す (needle で do 内絞り込み)。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave173_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["ST09-009", "ST09-010", "ST09-012", "ST09-014", "ST09-015",
           "ST10-001", "ST10-002", "ST10-004", "ST10-005", "ST10-007"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  ST09-009 風月おむすび (CHARACTER 黄 cost3):
#    【トリガー】相手のコスト1以下のキャラ1枚までを、 KOし、 このカードを手札に加える。
# --------------------------------------------------------------------------- #
def test_st09_009_trigger_ko_cost1_and_keep_in_hand_ai():
    """【トリガー】相手のコスト1以下キャラ1枚を KO + このカードを手札へ (keep flag) (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_NAMI), sickness=False)  # cost1 (<=1)
    opp.characters = [victim]

    for prim in _eff(overlay, "ST09-009", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])

    assert victim not in opp.characters, "相手のコスト1以下キャラが KO されていない"
    assert st.last_trigger_kept_in_hand is True, \
        "このカードを手札に加える (trigger keep) フラグが立っていない"


def test_st09_009_trigger_ko_cost2_not_target():
    """相手にコスト2以上のキャラしか居なければ KO 対象外。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    big = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (>1)
    opp.characters = [big]

    for prim in _eff(overlay, "ST09-009", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])

    assert big in opp.characters, "コスト2以上のキャラが KO されてはいけない (対象外)"


def test_st09_009_trigger_ko_human_pick():
    """人間 + 相手のコスト1以下キャラ複数 → target_pick modal が立ち resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_NAMI), sickness=False)   # cost1
    b = InPlay.of(repo.get(_NAMI), sickness=False)   # cost1
    opp.characters = [a, b]

    ko_prim = next(p for p in _eff(overlay, "ST09-009", "trigger")["do"] if "ko" in p)
    execute_effect(ko_prim, st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  ST09-010 ポートガス・D・エース (CHARACTER 黄 cost6):
#    【ターン1回】このキャラがKOされる場合、 代わりに自分のライフの上か下から
#      1枚をトラッシュに置くことができる。
# --------------------------------------------------------------------------- #
def test_st09_010_replace_ko_mill_life_ai():
    """KO 置換: ライフ上1枚をトラッシュに置いて KO を代替する (AI 自動承諾)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    ace = InPlay.of(repo.get("ST09-010"), sickness=False)
    me.characters = [ace]
    me.life = [repo.get(_FILLER)] * 2

    life_before = len(me.life)
    trash_before = len(me.trash)
    replaced = try_replace_ko(
        st, me, opp, ace, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "ライフを払えるのに KO が置換されていない"
    assert ace in me.characters, "置換成立時 エースは場に残るべき"
    assert len(me.life) == life_before - 1, "置換コストで自ライフ1枚が減るべき"
    assert len(me.trash) == trash_before + 1, "自ライフ1枚がトラッシュに置かれるべき"


def test_st09_010_replace_ko_no_life():
    """ライフが0枚なら 置換コストを払えず KO を代替できない (= 本来 False であるべき)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    ace = InPlay.of(repo.get("ST09-010"), sickness=False)
    me.characters = [ace]
    me.life = []  # ライフ 0 = コスト不能

    replaced = try_replace_ko(
        st, me, opp, ace, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is False, "ライフ0枚では置換が成立してはいけない"


def test_st09_010_replace_ko_human_confirm():
    """人間 actor: 任意 (できる) → replace_ko_optional modal が立ち、 承諾で置換する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    ace = InPlay.of(repo.get("ST09-010"), sickness=False)
    me.characters = [ace]
    me.life = [repo.get(_FILLER)] * 2

    life_before = len(me.life)
    replaced = try_replace_ko(
        st, me, opp, ace, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "人間 optional でも modal を立てて halt するべき (True)"
    assert st.pending_choice is not None, "replace_ko の 任意確認 modal が立たない"
    assert st.pending_choice.get("kind") == "replace_ko_optional", \
        f"kind が replace_ko_optional でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾 (= 置換する)
    _drain(st, [0])
    assert ace in me.characters, "人間承諾後 エースは場に残るべき"
    assert len(me.life) == life_before - 1, "承諾後 自ライフ1枚が減るべき"


# --------------------------------------------------------------------------- #
#  ST09-012 ヤマト (CHARACTER 黄 cost3):
#    【アタック時】自ライフ上下1→手札できる：このキャラは 次の自分のターン開始時まで +2000。
# --------------------------------------------------------------------------- #
def test_st09_012_on_attack_optional_cost_pump_ai():
    """【アタック時】任意コスト (自ライフ→手札) を払い、 自身 +2000 (次自ターン開始まで) (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    yamato = InPlay.of(repo.get("ST09-012"), sickness=False)  # power 3000
    me.characters = [yamato]
    me.life = [repo.get(_FILLER)] * 2
    me.hand = []

    power_before = yamato.power
    life_before = len(me.life)
    for prim in _eff(overlay, "ST09-012", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, yamato)
    _drain(st, [0])

    assert yamato.power == power_before + 2000, \
        f"アタック時の +2000 が反映されていない: {yamato.power} (before {power_before})"
    assert len(me.life) == life_before - 1, "任意コストで 自ライフ上下1枚が手札へ移るべき"
    assert len(me.hand) == 1, "自ライフ1枚が手札に加わっていない"


# --------------------------------------------------------------------------- #
#  ST09-014 鳴鏑 (EVENT 黄 cost1):
#    【カウンター】自ライフ2以下 → 相手リーダーかキャラ1枚まで このターン中 -3000。
#    【トリガー】自手札2枚を捨てられる：自デッキ上1枚までを ライフの上に加える。
# --------------------------------------------------------------------------- #
def test_st09_014_counter_debuff_when_life_le2_ai():
    """【カウンター】自ライフ2以下 → 相手キャラ1枚 -3000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2  # ライフ 2 (<=2) = 条件成立
    victim = InPlay.of(repo.get(_BIG), sickness=False)  # power 8000
    opp.characters = [victim]

    eff = _eff(overlay, "ST09-014", "counter")
    assert eval_all_conditions(eff, st, me) is True, \
        "自ライフ2以下なのに カウンター条件が成立しない"
    power_before = victim.power
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])

    assert victim.power == power_before - 3000, \
        f"相手キャラの -3000 が反映されていない: {victim.power} (before {power_before})"


def test_st09_014_counter_condition_false_when_life_ge3():
    """自ライフ3枚 (>2) なら カウンター条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me = st.players[0]
    me.life = [repo.get(_FILLER)] * 3  # ライフ 3 (>2)

    eff = _eff(overlay, "ST09-014", "counter")
    assert eval_all_conditions(eff, st, me) is False, \
        "自ライフ3枚なのに カウンター条件が成立してはいけない"


def test_st09_014_counter_debuff_human_pick():
    """人間 + 相手リーダー/キャラ 複数 → target_pick modal が立ち resolve で -3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2
    victim = InPlay.of(repo.get(_BIG), sickness=False)
    opp.characters = [victim]
    # 相手リーダー + キャラ で 候補 2 件 (one_opponent_inplay_any)

    debuff_prim = _eff(overlay, "ST09-014", "counter")["do"][0]
    execute_effect(debuff_prim, st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    v_idx = next(i for i, c in enumerate(cands) if c["iid"] == victim.instance_id)
    v_before = victim.power
    resolve_pending_choice(st, [v_idx])
    _drain(st, [v_idx])
    assert victim.power == v_before - 3000, \
        "人間が選んだ相手キャラに -3000 が反映されていない"


def test_st09_014_trigger_discard2_put_top_to_life_ai():
    """【トリガー】任意コスト (自手札2枚を捨てる) → 自デッキ上1枚を ライフの上へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER), repo.get(_NAMI)]  # 捨てる 2 枚
    me.deck = [repo.get(_FILLER)] * 5
    me.life = [repo.get(_FILLER)] * 1

    hand_before = len(me.hand)
    life_before = len(me.life)
    for prim in _eff(overlay, "ST09-014", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])

    assert len(me.hand) == hand_before - 2, "任意コストで手札2枚が捨てられるべき"
    assert len(me.life) == life_before + 1, "自デッキ上1枚が ライフの上に加わるべき"


# --------------------------------------------------------------------------- #
#  ST09-015 雷鳴八卦 (EVENT 黄 cost2):
#    【カウンター】自リーダーかキャラ1枚まで +4000。 その後 自ライフ2以下 →
#      相手のコスト3以下キャラ1枚までを 持ち主のライフの上か下へ。
#    【トリガー】カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_st09_015_counter_pump_and_chara_to_life_ai():
    """【カウンター】自リーダー +4000 (バトル中) → 自ライフ2以下なら相手cost3以下を相手ライフへ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2  # ライフ 2 (<=2)
    victim = InPlay.of(repo.get(_NAMI), sickness=False)  # cost1 (<=3)
    opp.characters = [victim]

    leader_power_before = me.leader.power
    opp_life_before = len(opp.life)
    for prim in _eff(overlay, "ST09-015", "counter")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])

    assert me.leader.power == leader_power_before + 4000, \
        f"カウンターの +4000 が自リーダーに反映されていない: {me.leader.power}"
    assert victim not in opp.characters, \
        "自ライフ2以下なら 相手コスト3以下キャラが場から除かれるべき"
    assert len(opp.life) == opp_life_before + 1, \
        "除かれた相手キャラが 持ち主 (相手) のライフに加わるべき"


def test_st09_015_counter_no_chara_move_when_life_ge3():
    """自ライフ3枚 (>2) なら「その後」の条件不成立 → 相手キャラは場に残る (+4000 のみ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3  # ライフ 3 (>2)
    victim = InPlay.of(repo.get(_NAMI), sickness=False)
    opp.characters = [victim]

    for prim in _eff(overlay, "ST09-015", "counter")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])

    assert victim in opp.characters, \
        "自ライフ3枚では 相手キャラを ライフに送ってはいけない (条件外)"


def test_st09_015_trigger_draw_ai():
    """【トリガー】カード1枚を引く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 5

    for prim in _eff(overlay, "ST09-015", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    assert len(me.hand) == 1, "トリガーの 1 ドローが起きていない"


# --------------------------------------------------------------------------- #
#  ST10-001 トラファルガー・ロー (LEADER 赤/紫):
#    【起動メイン】【ターン1回】ドン!!-3：相手のパワー3000以下キャラ1枚までを 持ち主デッキ下へ、
#      自手札からコスト4以下キャラ1枚までを 登場させる。
# --------------------------------------------------------------------------- #
def test_st10_001_activate_main_bounce_and_play_ai():
    """起動メイン (ドン-3): 相手P3000以下を デッキ下 + 手札 cost4以下を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST10-001", overlay)  # ロー leader
    me, opp = st.players[0], st.players[1]
    me.don_active = 5  # ドン-3 支払い用
    victim = InPlay.of(repo.get(_NAMI), sickness=False)  # power 2000 (<=3000)
    opp.characters = [victim]
    opp.deck = [repo.get(_FILLER)] * 10
    me.hand = [repo.get(_FILLER)]  # cost2 CHARACTER (<=4)

    opp_deck_before = len(opp.deck)
    options = list_activate_main_effects(st, me, overlay)
    law_opts = [(src, eff) for (src, eff) in options
                if src.card.card_id == "ST10-001"]
    assert len(law_opts) == 1, \
        f"ST10-001 の起動メインが legal に出ない: {len(law_opts)}"
    src, eff = law_opts[0]
    fire_activate_main(st, me, opp, src, eff)
    _drain(st, [0])

    assert victim not in opp.characters, "相手のパワー3000以下キャラが場から除かれていない"
    assert len(opp.deck) == opp_deck_before + 1, "除かれた相手キャラが持ち主デッキ下へ戻るべき"
    assert any(c.card.card_id == _FILLER for c in me.characters), \
        "手札から コスト4以下キャラが登場していない"
    assert me.don_active == 2, "ドン-3 (5→2) が支払われていない"


def test_st10_001_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST10-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 8
    opp.characters = [InPlay.of(repo.get(_NAMI), sickness=False)]
    opp.deck = [repo.get(_FILLER)] * 10
    me.hand = [repo.get(_FILLER)]

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST10-001"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST10-001"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  ST10-002 モンキー・D・ルフィ (LEADER 赤/紫):
#    【起動メイン】【ターン1回】自分の場のドン!!が0枚 または 8枚以上 → ドンデッキから1枚アクティブ追加。
# --------------------------------------------------------------------------- #
def test_st10_002_activate_main_add_don_when_don_zero_ai():
    """場のドン0枚 → 起動メインが legal + ドン1枚アクティブ追加。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST10-002", overlay)  # ルフィ leader
    me, opp = st.players[0], st.players[1]
    me.don_active = 0
    me.don_rested = 0
    me.don_remaining_in_deck = 10

    active_before = me.don_active
    deck_before = me.don_remaining_in_deck
    options = list_activate_main_effects(st, me, overlay)
    luffy_opts = [(src, eff) for (src, eff) in options
                  if src.card.card_id == "ST10-002"]
    assert len(luffy_opts) == 1, \
        f"場のドン0枚で起動メインが legal に出ない: {len(luffy_opts)}"
    fire_activate_main(st, me, opp, *luffy_opts[0])
    _drain(st, [0])

    assert me.don_active == active_before + 1, "ドンデッキからアクティブで1枚追加されていない"
    assert me.don_remaining_in_deck == deck_before - 1, "ドンデッキから1枚減るべき"


def test_st10_002_activate_main_not_legal_when_don_between():
    """場のドンが 0 でも 8以上でもない (= 4枚) なら 起動メインは legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST10-002", overlay)
    me = st.players[0]
    me.don_active = 4
    me.don_rested = 0
    me.don_remaining_in_deck = 6

    luffy_opts = [o for o in list_activate_main_effects(st, me, overlay)
                  if o[0].card.card_id == "ST10-002"]
    assert len(luffy_opts) == 0, \
        "場のドン4枚 (0でも8以上でもない) では起動メインが legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  ST10-004 サンジ (CHARACTER 赤 cost6):
#    【登場時】相手のパワー5000以上のキャラがいる場合、 このキャラは このターン中【速攻】を得る。
# --------------------------------------------------------------------------- #
def test_st10_004_on_play_grant_rush_when_opp_power_ge5000_ai():
    """相手にパワー5000以上キャラがいる → 登場時 自身が【速攻】を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.characters = [InPlay.of(repo.get(_BIG), sickness=False)]  # power 8000 (>=5000)
    sanji = InPlay.of(repo.get("ST10-004"), sickness=True)
    me.characters = [sanji]

    eff = _eff(overlay, "ST10-004", "on_play")
    assert eval_all_conditions(eff, st, me) is True, \
        "相手にパワー5000以上キャラが居るのに 登場時条件が成立しない"
    assert sanji.is_rush_now is False, "前提: 付与前は【速攻】を持たない"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, sanji)
    assert sanji.is_rush_now is True, "登場時に【速攻】が付与されていない"


def test_st10_004_on_play_condition_false_without_big_opp():
    """相手にパワー5000以上キャラが居なければ 登場時条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.characters = [InPlay.of(repo.get(_NAMI), sickness=False)]  # power 2000 (<5000)

    eff = _eff(overlay, "ST10-004", "on_play")
    assert eval_all_conditions(eff, st, me) is False, \
        "パワー5000以上キャラが居ないのに 条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  ST10-005 ジンベエ (CHARACTER 赤 cost2):
#    【ドン!!×1】【アタック時】相手のキャラ1枚までを、 このターン中、 パワー-2000。
# --------------------------------------------------------------------------- #
def test_st10_005_on_attack_debuff_ai():
    """【アタック時】(ドン!!×1 ゲート) 相手キャラ1枚を -2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    jinbe = InPlay.of(repo.get("ST10-005"), sickness=False)
    jinbe.attached_dons = 1  # ドン!!×1 ゲート
    me.characters = [jinbe]
    victim = InPlay.of(repo.get(_BIG), sickness=False)  # power 8000
    opp.characters = [victim]

    eff = _eff(overlay, "ST10-005", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    power_before = victim.power
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, jinbe)
    _drain(st, [0])

    assert victim.power == power_before - 2000, \
        f"相手キャラ -2000 が反映されていない: {victim.power} (before {power_before})"


def test_st10_005_on_attack_debuff_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal が立ち resolve で 1 体に -2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    jinbe = InPlay.of(repo.get("ST10-005"), sickness=False)
    jinbe.attached_dons = 1
    me.characters = [jinbe]
    a = InPlay.of(repo.get(_BIG), sickness=False)    # power 8000
    b = InPlay.of(repo.get(_NAMI), sickness=False)   # power 2000
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "ST10-005", "on_attack")["do"][0], st, me, opp, jinbe)
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    a_before = a.power
    resolve_pending_choice(st, [a_idx])
    _drain(st, [a_idx])
    assert a.power == a_before - 2000, "人間が選んだ相手キャラに -2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  ST10-007 キラー (CHARACTER 紫 cost5):
#    【自分のターン中】【ターン1回】自分の場のドン!!がドンデッキに戻された時、
#      相手のレストのコスト3以下キャラ1枚までを KO する。
# --------------------------------------------------------------------------- #
def test_st10_007_on_don_returned_ko_rested_cost3_ai():
    """自ドンがデッキに戻った時: 相手のレストのコスト3以下キャラ1枚を KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    killer = InPlay.of(repo.get("ST10-007"), sickness=False)
    me.characters = [killer]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (<=3)
    victim.rested = True  # レスト = 対象
    opp.characters = [victim]

    for prim in _eff(overlay, "ST10-007", "on_self_don_returned_to_deck")["do"]:
        execute_effect(prim, st, me, opp, killer)
    _drain(st, [0])

    assert victim not in opp.characters, "相手のレストのコスト3以下キャラが KO されていない"


def test_st10_007_on_don_returned_no_ko_when_active():
    """相手のコスト3以下キャラが アクティブ (非レスト) なら 対象外 → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    killer = InPlay.of(repo.get("ST10-007"), sickness=False)
    me.characters = [killer]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    victim.rested = False  # アクティブ = 対象外
    opp.characters = [victim]

    for prim in _eff(overlay, "ST10-007", "on_self_don_returned_to_deck")["do"]:
        execute_effect(prim, st, me, opp, killer)
    _drain(st, [0])

    assert victim in opp.characters, "アクティブなキャラが KO されてはいけない (対象外)"


def test_st10_007_on_don_returned_ko_human_pick():
    """人間 + 相手のレストのコスト3以下キャラ複数 → target_pick modal が立ち resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    killer = InPlay.of(repo.get("ST10-007"), sickness=False)
    me.characters = [killer]
    a = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    b = InPlay.of(repo.get(_NAMI), sickness=False)    # cost1
    a.rested = True
    b.rested = True
    opp.characters = [a, b]

    ko_prim = _eff(overlay, "ST10-007", "on_self_don_returned_to_deck")["do"][0]
    execute_effect(ko_prim, st, me, opp, killer)
    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"
