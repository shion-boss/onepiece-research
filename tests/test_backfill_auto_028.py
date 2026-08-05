# -*- coding: utf-8 -*-
"""OP02 弾 効果 回帰テスト バックフィル (自動生成 wave 028):
OP02-019 / OP02-021 / OP02-022 / OP02-023 / OP02-024 / OP02-027 /
OP02-029 / OP02-030 / OP02-031 / OP02-032 の 10 枚
(= 赤 白ひげ海賊団 常在/イベント系 + 緑 ワノ国/ミンク族 系)。

目的 (= test_backfill_auto_001〜027.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / サーチ / 任意コスト を 持つカードは 人間 actor で pending_choice が
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
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。
    デッキは効果の薄いバニラ気味カード (ST01-004、 cost2 赤) で埋める。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("ST01-004")] * 30
    p1.deck = [repo.get("ST01-004")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果の do 配列を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        # ⚠ 2026-08-05: コロン後の条件を conditional / optional_cost_then の中へ移したため、
        #   目的の primitive が入れ子になっている。 平坦化して探す。
        def _flat(arr):
            out = []
            for _p in arr or []:
                if not isinstance(_p, dict):
                    continue
                if "conditional" in _p:
                    out += _flat((_p["conditional"] or {}).get("do"))
                elif "optional_cost_then" in _p:
                    out += _flat((_p["optional_cost_then"] or {}).get("effect"))
                else:
                    out.append(_p)
            return out
        for e in matches:
            if any(needle in prim for prim in _flat(e["do"])):
                return e["do"], e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]["do"], matches[0]


def _drain_choices(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# WB = 白ひげ海賊団 を含む 赤 リーダー (= 条件節を成立させる用)
WB_LEADER = "OP02-001"  # エドワード・ニューゲート (四皇/白ひげ海賊団, 赤)


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op02_wave28_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP02-019", "OP02-021", "OP02-022", "OP02-023", "OP02-024",
           "OP02-027", "OP02-029", "OP02-030", "OP02-031", "OP02-032"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP02-019 ラクヨウ: 【ドン!!×1】【自分のターン中】自分の『白ひげ海賊団』を含む
#    特徴を持つキャラすべてを、パワー+1000。
# --------------------------------------------------------------------------- #
def test_op02_019_rakuyo_static_pump_whitebeard_chars():
    """常在 (on_attached_don n=1、 自ターン中): 自分の白ひげ海賊団キャラ すべて +1000。
    ラクヨウ自身 (白ひげ) は 印刷4000 + DON1(+1000) + 常在(+1000) = 6000、
    非白ひげ (ST01-004 麦わら) は 影響を受けない。"""
    repo = _repo()
    overlay = _overlay()
    p0 = Player(name="P0", leader=InPlay.of(repo.get(WB_LEADER), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    rakuyo_def = repo.get("OP02-019")  # power 4000, 白ひげ海賊団
    rakuyo = InPlay.of(rakuyo_def, sickness=False)
    rakuyo.attached_dons = 1  # 【ドン!!×1】ゲート成立
    other = InPlay.of(repo.get("ST01-004"), sickness=False)  # 麦わら (= 非対象)
    p0.characters = [rakuyo, other]
    st = GameState(players=[p0, p1], phase=Phase.MAIN, effects_overlay=overlay)
    st.turn_player_idx = 0  # 自分のターン (= self_turn 条件成立)
    st.human_player_idx = None

    other_before = other.power
    evaluate_static_effects(st, overlay)

    assert rakuyo.power == rakuyo_def.power + 1000 + 1000, \
        f"白ひげ自身の +1000 (DON含む) が反映されていない: {rakuyo.power}"
    assert other.power == other_before, \
        f"非白ひげキャラが影響を受けている: {other.power} (before {other_before})"


def test_op02_019_rakuyo_static_no_pump_off_turn():
    """相手ターン中は【自分のターン中】条件が不成立 → 常在 +0 (DON分のみ)。"""
    repo = _repo()
    overlay = _overlay()
    p0 = Player(name="P0", leader=InPlay.of(repo.get(WB_LEADER), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    rakuyo_def = repo.get("OP02-019")
    rakuyo = InPlay.of(rakuyo_def, sickness=False)
    rakuyo.attached_dons = 1
    p0.characters = [rakuyo]
    st = GameState(players=[p0, p1], phase=Phase.MAIN, effects_overlay=overlay)
    st.turn_player_idx = 1  # 相手のターン (= self_turn 不成立)
    st.human_player_idx = None

    evaluate_static_effects(st, overlay)
    # 【自分のターン中】常在 (+1000) は self_turn 不成立で 乗らない。
    # (DON+1000 は InPlay.of 既定 is_owners_turn=True のまま = +1000 のみ残る)
    assert rakuyo.power == rakuyo_def.power + 1000, \
        f"相手ターン中に【自分のターン中】常在が乗っている: {rakuyo.power}"


# --------------------------------------------------------------------------- #
#  OP02-021 海震 (EVENT): 【メイン】自リーダーが白ひげ海賊団の場合、相手のパワー
#    3000以下のキャラ1枚までを、KOする。 【トリガー】相手1枚を -3000。
# --------------------------------------------------------------------------- #
def test_op02_021_kaishin_main_ko_power_le3000_ai():
    """メイン (WB リーダー): 相手のパワー3000以下キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # power 2000 (<=3000)
    opp.characters = [victim]

    do, eff = _do(overlay, "OP02-021", "main")
    assert "白ひげ海賊団" in eff.get("if", {}).get("leader_features_any", []), \
        "overlay の リーダー特徴条件 (白ひげ海賊団) が無い"
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain_choices(st)

    assert victim not in opp.characters, "パワー3000以下キャラが KO されていない"


def test_op02_021_kaishin_ko_human_pick():
    """人間 + 相手パワー3000以下キャラ 複数 → KO の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # power 2000
    b = InPlay.of(repo.get("OP02-010"), sickness=False)  # power 2000
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP02-021", "main")
    ko_prim = next(p for p in do if "ko" in p)
    execute_effect(ko_prim, st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain_choices(st)
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは場に残るべき"


def test_op02_021_kaishin_trigger_debuff_ai():
    """【トリガー】相手のリーダーかキャラ1枚までを -3000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # power 2000
    opp.characters = [victim]

    power_before = victim.power
    do, _ = _do(overlay, "OP02-021", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain_choices(st)

    # 相手リーダー or キャラ のどちらかが -3000 されている
    debuffed = victim.power == power_before - 3000 or \
        opp.leader.power == repo.get("OP01-001").power - 3000
    assert debuffed, \
        f"トリガーの -3000 がどこにも反映されていない (victim={victim.power})"


# --------------------------------------------------------------------------- #
#  OP02-022 白ひげ海賊団 (EVENT): 【メイン】デッキ上5枚を見て、白ひげ海賊団の
#    キャラ1枚までを公開し手札に加える。残りをデッキの下へ。
# --------------------------------------------------------------------------- #
def test_op02_022_wb_event_main_search_ai():
    """メイン: デッキ上5枚から 白ひげ海賊団キャラ を手札に加える (AI 自動)。
    デッキ先頭に ラクヨウ (OP02-019, 白ひげ) を仕込み、 残りは非該当で埋める。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("OP02-019")] + [repo.get("ST01-004")] * 29

    hand_before = len(me.hand)
    do, _ = _do(overlay, "OP02-022", "main")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-022"), sickness=True))
    _drain_choices(st)

    assert len(me.hand) == hand_before + 1, \
        f"サーチで手札が1枚増えていない: {len(me.hand)}"
    assert any(c.card_id == "OP02-019" for c in me.hand), \
        "白ひげ海賊団キャラ (ラクヨウ) が手札に加わっていない"


def test_op02_022_wb_event_search_human_pick():
    """人間 + デッキ上5枚に 白ひげ海賊団キャラ → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("OP02-019"), repo.get("ST01-004"), repo.get("ST01-004"),
               repo.get("ST01-004"), repo.get("ST01-004")] + [repo.get("ST01-004")] * 25

    do, _ = _do(overlay, "OP02-022", "main")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-022"), sickness=True))

    assert st.pending_choice is not None, "人間 + 候補ありで search_top_n modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    cards = st.pending_choice.get("cards", [])
    rakuyo_idx = next(c["idx"] for c in cards if c["card_id"] == "OP02-019")
    resolve_pending_choice(st, [rakuyo_idx])
    _drain_choices(st)
    assert any(c.card_id == "OP02-019" for c in me.hand), \
        "人間が選んだ白ひげキャラが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP02-023 バカな息子をそれでも愛そう… (EVENT): 【メイン】自ライフ3以下の場合、
#    自分は このターン中 自分の効果でライフを手札に加えられない。 【トリガー】自リーダー +1000。
# --------------------------------------------------------------------------- #
def test_op02_023_main_prevent_self_life_to_hand_ai():
    """メイン (ライフ3以下): このターン中 自効果ライフ→手札 が禁止される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("ST01-004")] * 3  # ライフ 3 (= 条件成立)

    assert getattr(me, "prevent_self_life_to_hand_until_turn_end", False) is False
    do, eff = _do(overlay, "OP02-023", "main")
    assert eff.get("if", {}).get("self_life_le") == 3, \
        "overlay の ライフ3以下条件が無い"
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.prevent_self_life_to_hand_until_turn_end is True, \
        "このターン中の 自効果ライフ→手札 禁止フラグが立っていない"


def test_op02_023_trigger_leader_pump_ai():
    """【トリガー】自分のリーダー1枚までを このターン中 パワー+1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    do, _ = _do(overlay, "OP02-023", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain_choices(st)

    assert me.leader.power == power_before + 1000, \
        f"トリガーの 自リーダー +1000 が反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  OP02-024 モビー・ディック号 (STAGE): 【自分のターン中】自ライフ1枚以下の場合、
#    「エドワード・ニューゲート」と『白ひげ海賊団』キャラ すべてを パワー+2000。
# --------------------------------------------------------------------------- #
def test_op02_024_moby_static_pump_when_life_le1():
    """常在 (自ターン + ライフ1以下): 白ひげ海賊団キャラ すべて +2000。"""
    repo = _repo()
    overlay = _overlay()
    p0 = Player(name="P0", leader=InPlay.of(repo.get(WB_LEADER), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    moby = InPlay.of(repo.get("OP02-024"), sickness=False)  # STAGE
    wb_def = repo.get("OP02-019")  # 白ひげ, power 4000
    wb = InPlay.of(wb_def, sickness=False)
    other = InPlay.of(repo.get("ST01-004"), sickness=False)  # 麦わら (= 非対象)
    p0.stages = [moby]
    p0.characters = [wb, other]
    p0.life = [repo.get("ST01-004")] * 1  # ライフ 1 (= 条件成立)
    st = GameState(players=[p0, p1], phase=Phase.MAIN, effects_overlay=overlay)
    st.turn_player_idx = 0  # 自分のターン
    st.human_player_idx = None

    other_before = other.power
    evaluate_static_effects(st, overlay)

    assert wb.power == wb_def.power + 2000, \
        f"白ひげキャラへの +2000 が反映されていない: {wb.power} (base {wb_def.power})"
    assert other.power == other_before, \
        f"非白ひげキャラが影響を受けている: {other.power}"


def test_op02_024_moby_static_no_pump_when_life_ge2():
    """自ライフが2枚以上なら 常在条件 不成立 → +0。"""
    repo = _repo()
    overlay = _overlay()
    p0 = Player(name="P0", leader=InPlay.of(repo.get(WB_LEADER), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    moby = InPlay.of(repo.get("OP02-024"), sickness=False)
    wb_def = repo.get("OP02-019")
    wb = InPlay.of(wb_def, sickness=False)
    p0.stages = [moby]
    p0.characters = [wb]
    p0.life = [repo.get("ST01-004")] * 2  # ライフ 2 (= 不成立)
    st = GameState(players=[p0, p1], phase=Phase.MAIN, effects_overlay=overlay)
    st.turn_player_idx = 0
    st.human_player_idx = None

    evaluate_static_effects(st, overlay)
    assert wb.power == wb_def.power, \
        f"ライフ2以上で常在が乗ってしまっている: {wb.power}"


# --------------------------------------------------------------------------- #
#  OP02-027 イヌアラシ: 自分のドン!!すべてがレストの場合、このキャラは相手の効果で
#    場を離れない (= self_don_active_eq 0 で protect_from_opp_effect)。
# --------------------------------------------------------------------------- #
def test_op02_027_inuarashi_protect_when_all_don_rested():
    """常在: 自ドンがすべてレスト (= active 0) の場合、 自身が相手効果離脱耐性を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    inu = InPlay.of(repo.get("OP02-027"), sickness=False)
    me.characters = [inu]
    me.don_active = 0
    me.don_rested = 4  # すべてレスト (= active 0)

    evaluate_static_effects(st, overlay)
    assert inu.protect_from_opp_effect is True, \
        "自ドン全レスト時に protect_from_opp_effect が立っていない"


def test_op02_027_inuarashi_no_protect_when_don_active():
    """アクティブドンが1枚でもあれば 条件不成立 → 耐性なし。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    inu = InPlay.of(repo.get("OP02-027"), sickness=False)
    me.characters = [inu]
    me.don_active = 1  # アクティブが残る (= 不成立)
    me.don_rested = 3

    evaluate_static_effects(st, overlay)
    assert inu.protect_from_opp_effect is False, \
        "アクティブドンありなのに耐性が立っている"


# --------------------------------------------------------------------------- #
#  OP02-029 キャロット: 【自分のターン終了時】自分のドン!!1枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_op02_029_carrot_end_of_turn_untap_don_ai():
    """ターン終了時: レストドン1枚をアクティブにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    carrot = InPlay.of(repo.get("OP02-029"), sickness=False)
    me.characters = [carrot]
    me.don_active = 0
    me.don_rested = 2

    do, _ = _do(overlay, "OP02-029", "end_of_turn")
    for prim in do:
        execute_effect(prim, st, me, opp, carrot)

    assert me.don_active == 1, f"ドン1枚がアクティブになっていない: active={me.don_active}"
    assert me.don_rested == 1, f"レストドンが1枚消費されていない: rested={me.don_rested}"


# --------------------------------------------------------------------------- #
#  OP02-030 光月おでん: 【起動メイン】③：このキャラをアクティブにする。
#    【KO時】デッキからコスト3の緑《ワノ国》キャラ1枚までを登場 → シャッフル。
# --------------------------------------------------------------------------- #
def test_op02_030_oden_activate_main_untap_self_ai():
    """起動メイン (ドン3レストコスト): 自身 (レスト中) をアクティブにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    oden = InPlay.of(repo.get("OP02-030"), sickness=False)
    oden.rested = True  # アタック済 想定 → 起動メインで復帰
    me.characters = [oden]
    me.don_active = 3  # ③ コスト用
    me.don_rested = 0

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP02-030"]
    assert len(opts) == 1, f"OP02-030 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain_choices(st)

    assert oden.rested is False, "起動メインで自身がアクティブになっていない"
    assert me.don_active == 0 and me.don_rested == 3, \
        f"③ コストで ドン3枚がレストされていない: active={me.don_active} rested={me.don_rested}"


def test_op02_030_oden_on_ko_summon_wano_ai():
    """KO時: デッキから コスト3緑《ワノ国》キャラ1枚を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    # デッキ先頭に コスト3緑ワノ国 (OP01-033 イゾウ)、 残りは非該当
    me.deck = [repo.get("OP01-033")] + [repo.get("ST01-004")] * 29

    chars_before = len(me.characters)
    do, _ = _do(overlay, "OP02-030", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-030"), sickness=False))
    _drain_choices(st)

    assert len(me.characters) == chars_before + 1, \
        "デッキから コスト3緑ワノ国キャラが登場していない"
    assert any(c.card.card_id == "OP01-033" for c in me.characters), \
        "登場したキャラが 想定 (OP01-033) でない"


def test_op02_030_oden_on_ko_summon_human_pick():
    """人間 + デッキに コスト3緑ワノ国キャラ 複数 → summon_from_deck_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    # 2 枚の コスト3緑ワノ国 (OP01-033 イゾウ / OP01-052 雷ぞう) → limit=1 超過
    me.deck = [repo.get("OP01-033"), repo.get("OP01-052")] + [repo.get("ST01-004")] * 28

    do, _ = _do(overlay, "OP02-030", "on_ko")
    summon_prim = next(p for p in do if "summon_from_deck" in p)
    execute_effect(summon_prim, st, me, opp,
                   InPlay.of(repo.get("OP02-030"), sickness=False))

    assert st.pending_choice is not None, "人間 + 候補超過で summon_from_deck_pick modal が立たない"
    assert st.pending_choice.get("kind") == "summon_from_deck_pick", \
        f"kind が summon_from_deck_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"コスト3緑ワノ国候補が2枚でない: {len(cands)}"

    raizo_idx = next(i for i, c in enumerate(cands) if c["card_id"] == "OP01-052")
    resolve_pending_choice(st, [raizo_idx])
    _drain_choices(st)
    assert any(c.card.card_id == "OP01-052" for c in me.characters), \
        "人間が選んだキャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP02-031 光月トキ: 自分のキャラの「光月おでん」がいる場合、このキャラは
#    【ブロッカー】を得る。
# --------------------------------------------------------------------------- #
def test_op02_031_toki_grants_blocker_when_oden_present():
    """常在: 場に「光月おでん」がいる場合、 トキ自身が【ブロッカー】を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    toki = InPlay.of(repo.get("OP02-031"), sickness=False)
    oden = InPlay.of(repo.get("OP02-030"), sickness=False)  # 光月おでん
    me.characters = [toki, oden]

    evaluate_static_effects(st, overlay)
    assert "ブロッカー" in toki.static_granted_keywords, \
        "光月おでん在場時に【ブロッカー】が付与されていない"


def test_op02_031_toki_no_blocker_without_oden():
    """場に「光月おでん」がいなければ 条件不成立 → ブロッカーなし。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    toki = InPlay.of(repo.get("OP02-031"), sickness=False)
    me.characters = [toki]  # おでん 不在

    evaluate_static_effects(st, overlay)
    assert "ブロッカー" not in toki.static_granted_keywords, \
        "光月おでん不在なのに【ブロッカー】が付与されている"


# --------------------------------------------------------------------------- #
#  OP02-032 シシリアン: 【登場時】②：自分のコスト5以下の《ミンク族》キャラ1枚までを、
#    アクティブにする。
# --------------------------------------------------------------------------- #
def test_op02_032_sicilian_on_play_untap_mink_ai():
    """登場時 (ドン2レスト任意コスト): 自分の コスト5以下ミンク族キャラをアクティブに (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    mink = InPlay.of(repo.get("OP02-029"), sickness=False)  # キャロット ミンク族 cost5
    mink.rested = True  # レスト中 → 起こす対象
    me.characters = [mink]
    me.don_active = 2  # ② コスト用
    me.don_rested = 0

    do, _ = _do(overlay, "OP02-032", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-032"), sickness=True))
    _drain_choices(st)

    assert mink.rested is False, "コスト5以下ミンク族キャラがアクティブになっていない"


def test_op02_032_sicilian_on_play_human_optional_cost_confirm():
    """人間: 任意コスト (②) の pay/skip 確認 modal (optional_cost_confirm) が立ち、
    承諾すると ミンク族キャラをアクティブにできる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    mink = InPlay.of(repo.get("OP02-029"), sickness=False)  # キャロット ミンク族 cost5
    mink.rested = True
    me.characters = [mink]
    me.don_active = 2
    me.don_rested = 0

    do, _ = _do(overlay, "OP02-032", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-032"), sickness=True))

    assert st.pending_choice is not None, "人間で 任意コスト確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    # 承諾 (= 任意コストを払って効果発動) → 後続の untap 対象選択を先頭候補で解決
    resolve_pending_choice(st, [1])
    _drain_choices(st, pick=[0])
    assert mink.rested is False, \
        "人間承諾後 ミンク族キャラがアクティブになっていない"
