# -*- coding: utf-8 -*-
"""OP02/OP03 弾 (紫ドン戻し / 黒コスト-down / 赤 白ひげ海賊団) 効果 回帰テスト
バックフィル (自動生成 wave 035):
OP02-120 / OP02-121 / OP03-001 / OP03-002 / OP03-003 / OP03-005 /
OP03-008 / OP03-009 / OP03-011 / OP03-012 の 10 枚。

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


def _get_eff(overlay, cid, when, needle=None):
    for e in overlay.get(cid).effects:
        if e["when"] == when and (needle is None or needle in str(e["do"])):
            return e
    raise KeyError(cid, when, needle)


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
def test_all_op0203_wave35_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP02-120", "OP02-121", "OP03-001", "OP03-002", "OP03-003",
           "OP03-005", "OP03-008", "OP03-009", "OP03-011", "OP03-012"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP02-120 ウタ: 【登場時】ドン!!-2：自リーダーとキャラすべてを、次の自分の
#                 ターン開始時まで、パワー+1000。
# --------------------------------------------------------------------------- #
def test_op02_120_uta_on_play_team_pump_ai():
    """【登場時】自リーダーとキャラ全員に +1000 (次の自分のターン開始時まで)。
    do (= power_pump all_self_team) を直接発火し team 全員に反映されるか。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # 赤リーダー power5000
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ power3000
    me.characters = [friend]

    leader_before = me.leader.power
    friend_before = friend.power
    on_play = _get_eff(overlay, "OP02-120", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-120"), sickness=True))

    assert me.leader.power == leader_before + 1000, \
        f"自リーダーに +1000 が反映されていない: {me.leader.power}"
    assert friend.power == friend_before + 1000, \
        f"自キャラに +1000 が反映されていない: {friend.power}"


# --------------------------------------------------------------------------- #
#  OP02-121 クザン: 【自分のターン中】相手キャラ全コスト-5 (static) /
#                   【登場時】相手のコスト0のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op02_121_kuzan_static_opp_cost_down():
    """静的効果 (自分のターン中): 相手キャラ全員 コスト-5 (0 未満は 0 clamp)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # 自ターン
    me, opp = st.players[0], st.players[1]
    kuzan = InPlay.of(repo.get("OP02-121"), sickness=False)
    me.characters = [kuzan]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2
    opp.characters = [victim]

    evaluate_static_effects(st, overlay)
    # cost2 - 5 = -3 → max(0, -3) = 0
    assert victim.base_cost == 0, \
        f"相手キャラの コスト-5 (0 clamp) が反映されていない: {victim.base_cost}"


def test_op02_121_kuzan_static_off_turn_no_cost_down():
    """相手ターン中は【自分のターン中】条件が不成立 → コスト据え置き。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    st.turn_player_idx = 1  # 相手ターン
    me, opp = st.players[0], st.players[1]
    kuzan = InPlay.of(repo.get("OP02-121"), sickness=False)
    me.characters = [kuzan]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    opp.characters = [victim]

    evaluate_static_effects(st, overlay)
    assert victim.base_cost == 2, \
        f"相手ターンで コスト-5 が乗ってはいけない: {victim.base_cost}"


def test_op02_121_kuzan_on_play_ko_cost0_ai():
    """【登場時】相手の 現在コスト0 キャラ1枚を KO (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)
    victim.base_cost_override = 0  # 現在コスト0 (= 対象成立)
    opp.characters = [victim]

    on_play_ko = _get_eff(overlay, "OP02-121", "on_play")
    for prim in on_play_ko["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-121"), sickness=True))
    assert victim not in opp.characters, "現在コスト0の相手キャラが KO されていない"


def test_op02_121_kuzan_on_play_ko_nonzero_not_targeted():
    """現在コスト >0 の相手キャラは 対象外 → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 (override なし)
    opp.characters = [victim]

    on_play_ko = _get_eff(overlay, "OP02-121", "on_play")
    for prim in on_play_ko["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-121"), sickness=True))
    assert victim in opp.characters, "コスト >0 のキャラが KO されてはいけない (対象外)"


def test_op02_121_kuzan_on_play_ko_human_pick():
    """人間 + 現在コスト0 の相手キャラ 複数 → target_pick modal が立ち resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)
    b = InPlay.of(repo.get("OP01-016"), sickness=False)
    a.base_cost_override = 0
    b.base_cost_override = 0
    opp.characters = [a, b]

    on_play_ko = _get_eff(overlay, "OP02-121", "on_play")
    execute_effect(on_play_ko["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP02-121"), sickness=True))

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
#  OP03-001 ポートガス・D・エース (LEADER): アタック時/被アタック時、手札の
#    イベント/ステージを任意枚数捨て、 捨てた1枚につき このバトル中 +1000。
# --------------------------------------------------------------------------- #
def test_op03_001_ace_attack_discard_buff_ai():
    """【アタック時】手札のイベント/ステージを捨てて 捨てた枚数×1000 リーダーへ battle_buff。
    AI: 手札に 2 枚 (EVENT + STAGE) → +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-001", overlay)  # エース自身がリーダー
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("EB02-007"), repo.get("EB01-011")]  # 赤EVENT / STAGE

    buff_before = me.leader.battle_buff
    on_attack = _get_eff(overlay, "OP03-001", "on_attack")
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp, me.leader)

    assert me.leader.battle_buff == buff_before + 2000, \
        f"イベント/ステージ2枚捨てで +2000 が反映されていない: {me.leader.battle_buff}"
    assert len(me.hand) == 0, "捨てたイベント/ステージが手札から除かれていない"


def test_op03_001_ace_attack_discard_buff_human_pick():
    """人間 acting + 手札にイベント/ステージ → optional_discard_buff_pick modal が立ち、
    選んだ枚数分だけ +1000/枚。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    ev = repo.get("EB02-007")  # 赤EVENT
    stage = repo.get("EB01-011")  # STAGE
    me.hand = [ev, stage]

    on_attack = _get_eff(overlay, "OP03-001", "on_attack")
    execute_effect(on_attack["do"][0], st, me, opp, me.leader)

    assert st.pending_choice is not None, "人間 + 候補で discard modal が立たない"
    assert st.pending_choice.get("kind") == "optional_discard_buff_pick", \
        f"kind が optional_discard_buff_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"捨て候補が2枚でない: {len(cands)}"

    buff_before = me.leader.battle_buff
    resolve_pending_choice(st, [0])  # 1 枚だけ捨てる
    _drain(st)
    assert me.leader.battle_buff == buff_before + 1000, \
        f"1 枚捨てで +1000 が反映されていない: {me.leader.battle_buff}"
    assert len(me.hand) == 1, "1 枚捨てたので手札は1枚残るべき"


def test_op03_001_ace_opp_attack_discard_buff_ai():
    """【アタックされた時】も同じく手札イベント/ステージ捨てで リーダー +1000/枚 (防御)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("EB02-007")]  # 1 枚

    buff_before = me.leader.battle_buff
    opp_attack = _get_eff(overlay, "OP03-001", "opp_attack_on_leader")
    for prim in opp_attack["do"]:
        execute_effect(prim, st, me, opp, me.leader)

    assert me.leader.battle_buff == buff_before + 1000, \
        f"被アタック時 1 枚捨てで +1000 が反映されていない: {me.leader.battle_buff}"


# --------------------------------------------------------------------------- #
#  OP03-002 アディオ: 【ドン!!×1】【アタック時】相手は このバトル中、
#    パワー2000以下のキャラの【ブロッカー】を発動できない。
# --------------------------------------------------------------------------- #
def test_op03_002_adio_on_attack_prevent_blocker_ai():
    """【アタック時】(ドン×1 ゲート) アタッカーに 「P2000以下ブロッカー禁止」 フラグが立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("OP03-002"), sickness=False)
    me.characters = [attacker]

    on_attack = _get_eff(overlay, "OP03-002", "on_attack")
    assert on_attack.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp, attacker)

    assert attacker.attacker_prevents_blocker_power_le == 2000, \
        f"P2000以下ブロッカー禁止フラグが立っていない: " \
        f"{attacker.attacker_prevents_blocker_power_le}"


# --------------------------------------------------------------------------- #
#  OP03-003 イゾウ: 【登場時】デッキ上5枚を見て「イゾウ」以外の 白ひげ海賊団特徴 を
#    含むカード1枚までを手札へ、 残りをデッキ下。
# --------------------------------------------------------------------------- #
def test_op03_003_izou_on_play_search_ai():
    """【登場時】上5枚から 白ひげ海賊団 (イゾウ以外) を手札へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    satch = repo.get("OP03-005")  # サッチ 白ひげ海賊団 (イゾウ以外)
    me.deck = [satch] + [repo.get("OP01-013")] * 20
    me.hand = []

    on_play = _get_eff(overlay, "OP03-003", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-003"), sickness=True))
    assert any(c.card_id == "OP03-005" for c in me.hand), \
        "上5枚から 白ひげ海賊団 キャラが手札に加わっていない"


def test_op03_003_izou_on_play_search_human_pick():
    """人間 + 上5枚に 白ひげ海賊団 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    satch = repo.get("OP03-005")
    me.deck = [satch, repo.get("OP01-013"), repo.get("OP03-009")] + \
        [repo.get("OP01-013")] * 15  # サッチ / ハルタ (両方 白ひげ海賊団)
    me.hand = []

    on_play = _get_eff(overlay, "OP03-003", "on_play")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP03-003"), sickness=True))

    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [])
    assert any(c.card_id in ("OP03-005", "OP03-009") for c in me.hand), \
        "人間が選んだ 白ひげ海賊団 キャラが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP03-005 サッチ: 【起動メイン】【ターン1回】このキャラ +2000 (このターン中)。
#    その後、 このターン終了時、 このキャラをトラッシュに置く。
# --------------------------------------------------------------------------- #
def test_op03_005_satch_activate_main_pump_and_schedule_trash():
    """起動メイン: 自身 +2000 + ターン終了時トラッシュ予約 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    satch = InPlay.of(repo.get("OP03-005"), sickness=False)  # power2000
    me.characters = [satch]

    power_before = satch.power
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP03-005"]
    assert len(opts) == 1, f"OP03-005 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert satch.power == power_before + 2000, \
        f"起動メインの 自己 +2000 が反映されていない: {satch.power}"
    assert satch.trash_at_self_turn_end is True, \
        "ターン終了時トラッシュ予約フラグが立っていない"


def test_op03_005_satch_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    satch = InPlay.of(repo.get("OP03-005"), sickness=False)
    me.characters = [satch]

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP03-005"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP03-005"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP03-008 バギー: 属性(斬)とのバトルでKOされない (static) /
#    【登場時】デッキ上5枚から 赤のイベント1枚を手札へ、 残りデッキ下。
# --------------------------------------------------------------------------- #
def test_op03_008_buggy_static_immune_slash():
    """静的効果: このキャラは 属性(斬) とのバトルで KO されない (immune 属性に 斬 登録)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    buggy = InPlay.of(repo.get("OP03-008"), sickness=False)
    me.characters = [buggy]

    evaluate_static_effects(st, overlay)
    assert "斬" in buggy.ko_immune_battle_attributes_in, \
        f"斬 に対する battle KO 耐性が付与されていない: " \
        f"{buggy.ko_immune_battle_attributes_in}"


def test_op03_008_buggy_on_play_search_red_event_ai():
    """【登場時】上5枚から 赤のイベント1枚を手札へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    red_event = repo.get("EB02-007")  # 赤 EVENT
    me.deck = [red_event] + [repo.get("OP01-013")] * 20
    me.hand = []

    on_play = _get_eff(overlay, "OP03-008", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-008"), sickness=True))
    assert any(c.card_id == "EB02-007" for c in me.hand), \
        "上5枚から 赤のイベントが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP03-009 ハルタ: 【起動メイン】【ターン1回】自リーダーかキャラ1枚に
#    レストのドン!!1枚までを、 付与する。
# --------------------------------------------------------------------------- #
def test_op03_009_haruta_activate_main_attach_rested_don_ai():
    """起動メイン: 自リーダー (AI 既定) にレストドン1枚を付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    haruta = InPlay.of(repo.get("OP03-009"), sickness=False)
    me.characters = [haruta]
    me.don_rested = 2

    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP03-009"]
    assert len(opts) == 1, f"OP03-009 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert me.leader.attached_dons == don_before + 1, \
        "起動メインで自リーダーにレストドンが付与されていない"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"


def test_op03_009_haruta_activate_main_human_target_pick():
    """人間 + 自リーダー/キャラ 複数候補 → target_pick modal が立ち resolve で付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    haruta = InPlay.of(repo.get("OP03-009"), sickness=False)
    me.characters = [haruta]  # 候補 = リーダー + ハルタ の 2 件
    me.don_rested = 2

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP03-009"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+ハルタ) が 2 件でない: {len(cands)}"

    haruta_idx = next(i for i, c in enumerate(cands)
                      if c["iid"] == haruta.instance_id)
    don_before = haruta.attached_dons
    resolve_pending_choice(st, [haruta_idx])
    _drain(st, [haruta_idx])
    assert haruta.attached_dons == don_before + 1, \
        "人間が選んだキャラにレストドンが付与されていない"


# --------------------------------------------------------------------------- #
#  OP03-011 ブラメンコ: 【ドン!!×1】【アタック時】相手のキャラ1枚までを
#    このターン中、 パワー-2000。
# --------------------------------------------------------------------------- #
def test_op03_011_bramenko_on_attack_debuff_ai():
    """【アタック時】(ドン×1 ゲート) 相手キャラ1枚を このターン中 -2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # power3000
    opp.characters = [victim]

    power_before = victim.power
    on_attack = _get_eff(overlay, "OP03-011", "on_attack")
    assert on_attack.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-011"), sickness=False))
    assert victim.power == power_before - 2000, \
        f"相手キャラ -2000 が反映されていない: {victim.power} (before {power_before})"


def test_op03_011_bramenko_on_attack_debuff_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal が立ち resolve で選んだ1体に -2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # power2000
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # power3000
    opp.characters = [a, b]

    on_attack = _get_eff(overlay, "OP03-011", "on_attack")
    execute_effect(on_attack["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP03-011"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b.power == b_before - 2000, "人間が選んだ相手キャラに -2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP03-012 マーシャル・D・ティーチ: 【アタック時】自分のパワー4000以上の赤の
#    キャラ1枚をトラッシュに置くことができる：カード1枚を引く。
#    (overlay は optional_cost_then で ko(cost) → draw → 自身 +1000(このバトル中) を実装。)
# --------------------------------------------------------------------------- #
def test_op03_012_teach_on_attack_optional_ko_then_draw_ai():
    """【アタック時】赤 P4000以上キャラを犠牲 (コスト) → 1 ドロー (AI 自動発動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    teach = InPlay.of(repo.get("OP03-012"), sickness=False)
    fodder = InPlay.of(repo.get("OP01-005"), sickness=False)  # ウタ 赤 power4000
    me.characters = [teach, fodder]
    me.deck = [repo.get("OP01-013")] * 10
    me.hand = []

    hand_before = len(me.hand)
    on_attack = _get_eff(overlay, "OP03-012", "on_attack")
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp, teach)

    assert fodder not in me.characters, \
        "コストで 赤 P4000以上キャラ (ウタ) がトラッシュに置かれるべき"
    assert teach in me.characters, \
        "AI は power 低い方 (ウタ) を犠牲にし ティーチ (6000) は残すべき"
    assert repo.get("OP01-005") in me.trash, "犠牲キャラがトラッシュに無い"
    assert len(me.hand) == hand_before + 1, "1 ドローが発生していない"
    assert teach.power == teach.card.power + 1000, \
        f"その後 このバトル中 +1000 が効いていない: {teach.power} (base {teach.card.power})"


def test_op03_012_teach_on_attack_no_valid_red_body_no_draw():
    """場に 赤 P4000以上の (犠牲にできる) キャラが1体も無ければ cost 不能 → ドローなし。
    (= optional_cost_then の payability gate を検証。 filter=赤&P4000以上 に一致する
     キャラが me.characters に無い状況を作る。)"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    teach = InPlay.of(repo.get("OP03-012"), sickness=False)
    # 場のキャラは 赤 power3000 (=4000 未満) のサンジのみ。 ティーチ本体は場に置かず
    # (= 犠牲候補は me.characters を走査するため 一致 0)。
    weak = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [weak]
    me.deck = [repo.get("OP01-013")] * 10
    me.hand = []

    on_attack = _get_eff(overlay, "OP03-012", "on_attack")
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp, teach)

    assert weak in me.characters, "P4000未満のキャラを犠牲にしてはいけない"
    assert len(me.hand) == 0, "cost 不能なのにドローが起きてはいけない"
