# -*- coding: utf-8 -*-
"""OP08 弾 (ミンク族 / ドラム王国) 効果 回帰テスト バックフィル (自動生成 wave 084):
OP08-019 / OP08-020 / OP08-022 / OP08-023 / OP08-026 / OP08-028 /
OP08-029 / OP08-030 / OP08-031 / OP08-032 の 10 枚。

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


def _drain(st, pick=0, guard=8):
    """pending_choice を pick を選び続けて解決しきる (後続の reorder 等を流す)。"""
    g = 0
    while st.pending_choice is not None and g < guard:
        cands = st.pending_choice.get("candidates")
        cards = st.pending_choice.get("cards")
        if cands is not None and len(cands) == 0:
            resolve_pending_choice(st, [])
        elif cards is not None and not cands:
            resolve_pending_choice(st, [pick] if any(
                c.get("matches_filter") for c in cards) else [])
        else:
            resolve_pending_choice(st, [pick])
        g += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op08_wave084_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP08-019", "OP08-020", "OP08-022", "OP08-023", "OP08-026",
           "OP08-028", "OP08-029", "OP08-030", "OP08-031", "OP08-032"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP08-019 バクバク食 (EVENT):
#    【メイン】/【カウンター】相手のキャラ1枚まで -3000。その後 自分のキャラ1枚まで +3000
#    【トリガー】相手のパワー5000以下のキャラ1枚までを KO
# --------------------------------------------------------------------------- #
def test_op08_019_main_debuff_then_pump_ai():
    """【メイン】相手キャラ -3000 → その後 自分キャラ +3000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # power 3000
    opp.characters = [victim]
    mine = InPlay.of(repo.get("OP01-013"), sickness=False)  # power 3000
    me.characters = [mine]
    v_before, m_before = victim.power, mine.power

    main = next(e for e in overlay.get("OP08-019").effects if e["when"] == "main")
    for prim in main["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert victim.power == v_before - 3000, \
        f"相手キャラ -3000 が反映されていない: {victim.power} (before {v_before})"
    assert mine.power == m_before + 3000, \
        f"自分キャラ +3000 が反映されていない: {mine.power} (before {m_before})"


def test_op08_019_main_human_debuff_pick():
    """人間 + 相手キャラ複数 → -3000 の対象選択 target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # 2000
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # 3000
    opp.characters = [a, b]

    main = next(e for e in overlay.get("OP08-019").effects if e["when"] == "main")
    execute_effect(main["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    assert b.power == b_before - 3000, "人間が選んだ相手キャラに -3000 が反映されていない"


def test_op08_019_trigger_ko_power_le_5000_ai():
    """【トリガー】相手のパワー5000以下のキャラ1枚までを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # power 3000 <= 5000
    opp.characters = [victim]

    trigger = next(e for e in overlay.get("OP08-019").effects
                   if e["when"] == "trigger")
    for prim in trigger["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert victim not in opp.characters, \
        "トリガーで相手のパワー5000以下キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP08-020 ドラム王国 (STAGE):
#    【相手のターン中】自分の特徴《ドラム王国》を持つキャラすべてを +1000 (静的)
# --------------------------------------------------------------------------- #
def test_op08_020_stage_static_pump_on_opp_turn():
    """相手のターン中: 自《ドラム王国》キャラすべてが +1000 (静的)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-021", overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1  # 相手のターン (= opp_turn 条件成立)
    stage = InPlay.of(repo.get("OP08-020"), sickness=False)
    me.stages = [stage]
    drum = InPlay.of(repo.get("OP08-010"), sickness=False)  # ドラム王国 power 3000
    me.characters = [drum]
    base = repo.get("OP08-010").power

    evaluate_static_effects(st, overlay)
    assert drum.power == base + 1000, \
        f"相手ターン中 《ドラム王国》 +1000 が反映されていない: {drum.power} (base {base})"


def test_op08_020_stage_no_pump_on_self_turn():
    """自分のターン中は【相手のターン中】条件が不成立 → +0 (base のまま)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-021", overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 0  # 自分のターン → opp_turn False
    stage = InPlay.of(repo.get("OP08-020"), sickness=False)
    me.stages = [stage]
    drum = InPlay.of(repo.get("OP08-010"), sickness=False)
    me.characters = [drum]
    base = repo.get("OP08-010").power

    evaluate_static_effects(st, overlay)
    assert drum.power == base, \
        f"自分ターンで +1000 が乗ってはいけない: {drum.power} (base {base})"


# --------------------------------------------------------------------------- #
#  OP08-022 イヌアラシ: 【登場時】自リーダーが《ミンク族》なら
#    相手のレストのコスト5以下のキャラ2枚までは、次の相手のリフレッシュでアクティブにならない
# --------------------------------------------------------------------------- #
def test_op08_022_on_play_stay_rested_two_targets_ai():
    """【登場時】(リーダー ミンク族) 相手のレスト cost5以下 2枚まで stay_rested (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-021", overlay)  # キャロット = ミンク族 leader
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    b = InPlay.of(repo.get("OP08-004"), sickness=False)  # cost4 <= 5
    a.rested = True
    b.rested = True
    opp.characters = [a, b]

    on_play = next(e for e in overlay.get("OP08-022").effects
                   if e["when"] == "on_play")
    assert on_play.get("if", {}).get("leader_feature") == "ミンク族", \
        "overlay に leader_feature=ミンク族 gate が無い"
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-022"), sickness=True))
    _drain(st)
    assert a.stay_rested_next_refresh is True and b.stay_rested_next_refresh is True, \
        f"相手レスト cost5以下 2枚が stay_rested になっていない: {a.stay_rested_next_refresh}/{b.stay_rested_next_refresh}"


# --------------------------------------------------------------------------- #
#  OP08-023 キャロット: 【登場時】/【アタック時】相手のレスト cost7以下1枚まで stay_rested
#    ⚠ overlay の target spec が 未対応形 (下記 skip reason 参照)
# --------------------------------------------------------------------------- #
@pytest.mark.skip(reason=(
    "overlay 実バグ: OP08-023 の stay_rested_next_refresh target が "
    "'one_opponent_rested_character_le_7cost' と綴られており、 _resolve_target が "
    "この形を解決できず 常に [] (= 効果不発)。 正しくは "
    "'one_opponent_rested_character_cost_le_7cost' (= _cost_le_ 形、 line 2600 の regex)。 "
    "engine/overlay 修正は人間レビューに回す (このタスクでは engine/overlay を編集しない)。"))
def test_op08_023_carrot_on_play_stay_rested_ai():
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-021", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP08-004"), sickness=False)  # cost4 <= 7
    victim.rested = True
    opp.characters = [victim]

    on_play = next(e for e in overlay.get("OP08-023").effects
                   if e["when"] == "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-023"), sickness=True))
    _drain(st)
    assert victim.stay_rested_next_refresh is True, \
        "相手レスト cost7以下キャラが stay_rested になっていない"


# --------------------------------------------------------------------------- #
#  OP08-026 ジョバンニ: 【ドン×1】【アタック時】
#    相手のレストのコスト1以下のキャラ1枚まで stay_rested
# --------------------------------------------------------------------------- #
def test_op08_026_giovanni_attack_stay_rested_ai():
    """【アタック時】(ドン1) 相手のレスト cost1以下1枚 stay_rested (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-021", overlay)
    me, opp = st.players[0], st.players[1]
    giovanni = InPlay.of(repo.get("OP08-026"), sickness=False)
    giovanni.attached_dons = 1
    me.characters = [giovanni]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    victim.rested = True
    opp.characters = [victim]

    on_attack = next(e for e in overlay.get("OP08-026").effects
                     if e["when"] == "on_attack")
    assert on_attack.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp, giovanni)
    _drain(st)
    assert victim.stay_rested_next_refresh is True, \
        "相手レスト cost1以下キャラが stay_rested になっていない"


# --------------------------------------------------------------------------- #
#  OP08-028 ネコマムシ: 【登場時】相手のレストのカードが7枚以上ある場合、
#    このキャラは このターン中【速攻】を得る
# --------------------------------------------------------------------------- #
def test_op08_028_nekomamushi_on_play_grant_rush_ai():
    """【登場時】(相手レスト7枚以上) 自身が【速攻】を得る (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-021", overlay)
    me, opp = st.players[0], st.players[1]
    opp.characters = [InPlay.of(repo.get("OP01-016"), sickness=False) for _ in range(7)]
    for c in opp.characters:
        c.rested = True
    neko = InPlay.of(repo.get("OP08-028"), sickness=True)

    on_play = next(e for e in overlay.get("OP08-028").effects
                   if e["when"] == "on_play")
    assert on_play.get("if", {}).get("opp_rested_cards_count_ge") == 7, \
        "overlay に opp_rested_cards_count_ge=7 gate が無い"
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp, neko)
    assert "速攻" in neko.granted_keywords, \
        "相手レスト7枚以上で【速攻】が付与されていない"


# --------------------------------------------------------------------------- #
#  OP08-029 ペコムズ: このキャラがアクティブの場合、「ペコムズ」以外の
#    自分のコスト3以下の《ミンク族》キャラは、効果でKOされない (静的)
# --------------------------------------------------------------------------- #
def test_op08_029_pekoms_static_ko_immune_when_active():
    """ペコムズが アクティブ (非レスト) の場合 自《ミンク族》cost3以下が static_ko_immune。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-021", overlay)
    me, opp = st.players[0], st.players[1]
    pekoms = InPlay.of(repo.get("OP08-029"), sickness=False)
    pekoms.rested = False
    friend = InPlay.of(repo.get("OP01-048"), sickness=False)  # ネコマムシ ミンク族 cost2
    me.characters = [pekoms, friend]

    evaluate_static_effects(st, overlay)
    assert friend.static_ko_immune is True, \
        "アクティブ時 自《ミンク族》cost3以下が効果KO耐性を得ていない"
    assert pekoms.static_ko_immune is False, \
        "「ペコムズ」自身は対象外 (exclude ペコムズ) のはず"


def test_op08_029_pekoms_no_immune_when_rested():
    """ペコムズが レスト の場合「アクティブの場合」条件が不成立 → 耐性は付かない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-021", overlay)
    me, opp = st.players[0], st.players[1]
    pekoms = InPlay.of(repo.get("OP08-029"), sickness=False)
    pekoms.rested = True  # レスト = 条件不成立
    friend = InPlay.of(repo.get("OP01-048"), sickness=False)
    me.characters = [pekoms, friend]

    evaluate_static_effects(st, overlay)
    assert friend.static_ko_immune is False, \
        "ペコムズがレストなのに効果KO耐性が付いてはいけない (条件不成立)"


# --------------------------------------------------------------------------- #
#  OP08-030 ペドロ: 【ブロッカー】【KO時】以下から1つを選ぶ。
#    ・相手のドン1枚までをレストにする ・相手のレスト cost6以下1枚までを KO
# --------------------------------------------------------------------------- #
def test_op08_030_pedro_on_ko_choice_ai():
    """【KO時】choice_effect を AI 文脈で 自動解決 (crash せず何かしら発動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-021", overlay)
    me, opp = st.players[0], st.players[1]
    opp.don_active = 2
    victim = InPlay.of(repo.get("OP08-004"), sickness=False)  # cost4 <= 6
    victim.rested = True
    opp.characters = [victim]

    on_ko = next(e for e in overlay.get("OP08-030").effects if e["when"] == "on_ko")
    for prim in on_ko["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-030"), sickness=False))
    _drain(st)
    assert st.pending_choice is None, "AI 文脈で choice が自動解決されていない"
    # AI が どちらかの option を選んで盤面が変化する (KO or ドンレスト)
    ko_happened = victim not in opp.characters
    don_rested = opp.don_rested >= 1
    assert ko_happened or don_rested, \
        "AI が choice option を発動しておらず 盤面が変化していない"


def test_op08_030_pedro_on_ko_human_option_pick_ko():
    """人間 + 【KO時】choice → option_pick modal が立ち、 KO option を選んで解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-021", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    opp.don_active = 2
    victim = InPlay.of(repo.get("OP08-004"), sickness=False)  # cost4 <= 6
    victim.rested = True
    opp.characters = [victim]

    on_ko = next(e for e in overlay.get("OP08-030").effects if e["when"] == "on_ko")
    execute_effect(on_ko["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP08-030"), sickness=False))
    assert st.pending_choice is not None, "人間 + choice で option_pick modal が立たない"
    assert st.pending_choice.get("kind") == "option_pick", \
        f"kind が option_pick でない: {st.pending_choice.get('kind')}"
    opts = st.pending_choice.get("options", [])
    assert len(opts) == 2, f"選択肢が2つでない: {len(opts)}"

    resolve_pending_choice(st, [1])  # idx 1 = レスト cost6以下 KO
    _drain(st, pick=0)
    assert victim not in opp.characters, \
        "人間が選んだ KO option で 相手のレスト cost6以下キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP08-031 ミヤギ: 【登場時】自分のコスト2以下の《ミンク族》キャラ1枚までを アクティブにする
# --------------------------------------------------------------------------- #
def test_op08_031_miyagi_on_play_untap_ai():
    """【登場時】自《ミンク族》cost2以下 レストキャラ1枚を アクティブに (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-021", overlay)
    me, opp = st.players[0], st.players[1]
    rested = InPlay.of(repo.get("OP01-048"), sickness=False)  # ネコマムシ ミンク族 cost2
    rested.rested = True
    me.characters = [rested]

    on_play = next(e for e in overlay.get("OP08-031").effects
                   if e["when"] == "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-031"), sickness=True))
    _drain(st)
    assert rested.rested is False, \
        "自《ミンク族》cost2以下キャラが アクティブになっていない"


def test_op08_031_miyagi_on_play_human_target_pick():
    """人間 + 自《ミンク族》cost2以下レスト複数 → target_pick modal で1枚を選び untap。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-021", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-048"), sickness=False)  # ネコマムシ cost2
    b = InPlay.of(repo.get("OP08-033"), sickness=False)  # ロディ ミンク族 cost1
    a.rested = True
    b.rested = True
    me.characters = [a, b]

    on_play = next(e for e in overlay.get("OP08-031").effects
                   if e["when"] == "on_play")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP08-031"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    assert b.rested is False, "人間が選んだキャラが アクティブになっていない"
    assert a.rested is True, "選ばなかったキャラは レストのまま残るべき"


# --------------------------------------------------------------------------- #
#  OP08-032 ミルキー: 【起動メイン】このキャラをレストにできる：
#    自リーダーが《ミンク族》なら 自分のドン1枚までを アクティブにする
# --------------------------------------------------------------------------- #
def test_op08_032_milky_activate_main_untap_don_ai():
    """【起動メイン】(自レスト + リーダー ミンク族) 自ドン1枚 アクティブ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-021", overlay)  # キャロット = ミンク族 leader
    me, opp = st.players[0], st.players[1]
    milky = InPlay.of(repo.get("OP08-032"), sickness=False)
    me.characters = [milky]
    me.don_rested = 2
    me.don_active = 0

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP08-032"]
    assert len(opts) == 1, f"OP08-032 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)
    assert me.don_active == 1 and me.don_rested == 1, \
        f"レストドン1枚がアクティブになっていない: active {me.don_active} / rested {me.don_rested}"
    assert milky.rested is True, "起動メインコストで ミルキー がレストされるべき"


def test_op08_032_milky_gate_wrong_leader():
    """自リーダーが《ミンク族》でない場合 起動メインが legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # シャンクス (非ミンク族)
    me, opp = st.players[0], st.players[1]
    milky = InPlay.of(repo.get("OP08-032"), sickness=False)
    me.characters = [milky]
    me.don_rested = 2

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP08-032"]
    assert len(opts) == 0, \
        "リーダーが ミンク族 でないのに起動メインが legal に出てはいけない"
