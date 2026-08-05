# -*- coding: utf-8 -*-
"""OP04 (緑 ドンキホーテ海賊団) 効果 回帰テスト バックフィル (自動生成 wave 046):
OP04-022 / OP04-024 / OP04-025 / OP04-026 / OP04-027 / OP04-028 /
OP04-029 / OP04-030 / OP04-032 / OP04-033 の 10 枚。

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
    eval_condition,
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

# ドンキホーテ海賊団 特徴を持つ LEADER (= 緑/紫 ドフラミンゴ OP04-019)。
DOFLA_LEADER = "OP04-019"


def _cond_of(eff: dict) -> dict:
    """効果の発動条件を取り出す (top-level `if` / `conditional` / optional_cost_then 内 の三形対応)。

    ⚠ 2026-08-05: 公式は 「「：」以前が発動コスト」 (cardqa_st_06)。 コロン後の条件は **効果のみ**
    を gate するので、 overlay ではその条件を `conditional` の中へ移した。
    `optional_cost_then` を持つ効果では **cost を条件の外に出す** 必要があるため、
    conditional は `effect` 配列の中に入る。 条件自体は変わっていないので、
    テストはどの位置でも読めればよい。
    """
    if isinstance(eff.get("if"), dict):
        return eff["if"]
    def _dig(arr):
        for _p in arr or []:
            if not isinstance(_p, dict):
                continue
            if "conditional" in _p:
                return (_p.get("conditional") or {}).get("if") or {}
            if "optional_cost_then" in _p:
                got = _dig((_p["optional_cost_then"] or {}).get("effect") or [])
                if got:
                    return got
        return {}
    return _dig(eff.get("do") or [])


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


def _all_eff(overlay, cid, when):
    return [e for e in overlay.get(cid).effects if e["when"] == when]


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
def test_all_wave46_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP04-022", "OP04-024", "OP04-025", "OP04-026", "OP04-027",
           "OP04-028", "OP04-029", "OP04-030", "OP04-032", "OP04-033"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP04-022 エリック (CHARACTER 緑 cost1):
#    【起動メイン】このキャラをレストにできる：相手のコスト1以下のキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_op04_022_activate_main_rest_opp_cost_le_1_ai():
    """【起動メイン】相手のコスト1以下キャラ1枚をレスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [victim]
    assert victim.rested is False

    eff = _get_eff(overlay, "OP04-022", "activate_main")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-022"), sickness=False))
        _drain(st, [0])

    assert victim.rested is True, "相手のコスト1以下キャラがレストにされていない"


def test_op04_022_activate_main_no_target_cost_gt_1():
    """相手キャラがコスト2以上なら対象外 → レストされない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 (対象外)
    opp.characters = [victim]

    eff = _get_eff(overlay, "OP04-022", "activate_main")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-022"), sickness=False))
        _drain(st, [0])

    assert victim.rested is False, \
        "コスト2のキャラがレストされている (コスト1以下制約が効いていない)"


def test_op04_022_activate_main_human_target_pick():
    """人間 actor: レスト対象の target_pick modal が立ち、 解決でレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    v1 = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    v2 = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 (複数候補で modal)
    opp.characters = [v1, v2]

    eff = _get_eff(overlay, "OP04-022", "activate_main")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP04-022"), sickness=False))

    assert st.pending_choice is not None, "人間 + 対象選択で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    assert (v1.rested or v2.rested), "人間選択後 相手キャラがレストにされていない"


# --------------------------------------------------------------------------- #
#  OP04-024 シュガー (CHARACTER 緑 cost2):
#    【相手のターン中】【ターン1回】相手がキャラを登場させた時、自分のリーダーが特徴
#      《ドンキホーテ海賊団》を持つ場合、相手のキャラ1枚までを、レストにする。
#      その後、このキャラをレストにする。
#    【登場時】相手のコスト4以下のキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_op04_024_on_play_rest_opp_cost_le_4_ai():
    """【登場時】相手のコスト4以下キャラ1枚をレスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 (<=4)
    opp.characters = [victim]

    on_play = _get_eff(overlay, "OP04-024", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-024"), sickness=False))
        _drain(st, [0])

    assert victim.rested is True, "【登場時】相手コスト4以下キャラがレストにされていない"


def test_op04_024_opp_turn_trigger_condition_requires_dofla_leader():
    """【相手のターン中】trigger 条件 = opp_turn + ドンキホーテ海賊団 リーダー。"""
    repo = _repo()
    overlay = _overlay()
    eff = _get_eff(overlay, "OP04-024", "on_opp_chara_played")

    # ドフラ系リーダー + 相手ターン → 条件成立
    st = _state(repo, DOFLA_LEADER, overlay)
    st.turn_player_idx = 1  # 相手ターン
    me = st.players[0]
    for c in eff.get("conditions", []):
        assert eval_condition(c, st, me) is True, \
            f"ドフラリーダー + 相手ターンで条件不成立: {c}"

    # 非ドフラリーダー → leader_feature 条件が不成立
    st2 = _state(repo, "OP01-001", overlay)
    st2.turn_player_idx = 1
    me2 = st2.players[0]
    results = [eval_condition(c, st2, me2) for c in eff.get("conditions", [])]
    assert not all(results), \
        "非ドフラリーダーでも全条件成立している (leader_feature gate が効いていない)"


def test_op04_024_opp_turn_trigger_rest_opp_then_self_ai():
    """【相手のターン中】相手キャラ1枚レスト + 自身レスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, DOFLA_LEADER, overlay)
    st.turn_player_idx = 1  # 相手ターン
    me, opp = st.players[0], st.players[1]
    sugar = InPlay.of(repo.get("OP04-024"), sickness=False)
    me.characters = [sugar]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [victim]

    eff = _get_eff(overlay, "OP04-024", "on_opp_chara_played")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, sugar)
        _drain(st, [0])

    assert victim.rested is True, "相手キャラがレストにされていない"
    assert sugar.rested is True, "その後 自身(シュガー)がレストになっていない"


# --------------------------------------------------------------------------- #
#  OP04-025 ジョーラ (CHARACTER 緑 cost4):
#    【相手のアタック時】➁(コストエリアのドン!!を指定の数レストにできる)：
#      相手のコスト4以下のキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_op04_025_opp_attack_optcost_rest_ai():
    """【相手のアタック時】任意コスト(自ドン2レスト) → 相手コスト4以下1枚レスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    joora = InPlay.of(repo.get("OP04-025"), sickness=False)
    me.characters = [joora]
    me.don_active = 3
    me.don_rested = 0
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 (<=4)
    opp.characters = [victim]

    on_oa = _get_eff(overlay, "OP04-025", "opp_attack")
    for prim in on_oa["do"]:
        execute_effect(prim, st, me, opp, joora)
        _drain(st, [1])  # 任意コストは AI が承諾

    assert me.don_rested == 2, \
        f"コストで自ドン!!2枚がレストになっていない: {me.don_rested}"
    assert victim.rested is True, "相手のコスト4以下キャラがレストにされていない"


def test_op04_025_opp_attack_no_effect_when_insufficient_don():
    """自ドン!!が2枚未満なら 任意コスト不能 → 相手キャラレストは起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    joora = InPlay.of(repo.get("OP04-025"), sickness=False)
    me.characters = [joora]
    me.don_active = 1  # 2枚未満
    me.don_rested = 0
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [victim]

    on_oa = _get_eff(overlay, "OP04-025", "opp_attack")
    for prim in on_oa["do"]:
        execute_effect(prim, st, me, opp, joora)
        _drain(st, [1])

    assert victim.rested is False, \
        "自ドン!!不足なのに 相手キャラがレストにされている (コスト未払いで発火してはならない)"


def test_op04_025_opp_attack_human_optional_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、 承諾で相手レスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    joora = InPlay.of(repo.get("OP04-025"), sickness=False)
    me.characters = [joora]
    me.don_active = 3
    me.don_rested = 0
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [victim]

    on_oa = _get_eff(overlay, "OP04-025", "opp_attack")
    execute_effect(on_oa["do"][0], st, me, opp, joora)

    assert st.pending_choice is not None, "人間 + 任意コストで確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert victim.rested is True, "人間承諾後 相手キャラがレストにされていない"


# --------------------------------------------------------------------------- #
#  OP04-026 セニョール・ピンク (CHARACTER 緑 cost3):
#    【アタック時】➀：自分のリーダーが特徴《ドンキホーテ海賊団》を持つ場合、
#      相手のコスト4以下のキャラ1枚までを、レストにする。
#      その後、このターン終了時、自分のドン!!1枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_op04_026_on_attack_condition_dofla_leader():
    """【アタック時】効果の if = ドンキホーテ海賊団 リーダー。"""
    repo = _repo()
    overlay = _overlay()
    eff = _get_eff(overlay, "OP04-026", "on_attack")
    st_ok = _state(repo, DOFLA_LEADER, overlay)
    assert eval_condition(_cond_of(eff), st_ok, st_ok.players[0]) is True, \
        "ドフラリーダーで条件成立しない"
    st_ng = _state(repo, "OP01-001", overlay)
    assert eval_condition(_cond_of(eff), st_ng, st_ng.players[0]) is False, \
        "非ドフラリーダーで条件が成立している"


def test_op04_026_on_attack_rest_and_schedule_ai():
    """【アタック時】相手コスト4以下1枚レスト + 自ターン終了時アクティブ予約 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, DOFLA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    pink = InPlay.of(repo.get("OP04-026"), sickness=False)
    me.characters = [pink]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 (<=4)
    opp.characters = [victim]
    sched_before = len(getattr(me, "scheduled_at_self_turn_end", []) or [])

    eff = _get_eff(overlay, "OP04-026", "on_attack")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, pink)
        _drain(st, [0])

    assert victim.rested is True, "相手のコスト4以下キャラがレストにされていない"
    assert len(getattr(me, "scheduled_at_self_turn_end", []) or []) == sched_before + 1, \
        "このターン終了時のドン!!アクティブ化が予約されていない"


# --------------------------------------------------------------------------- #
#  OP04-027 ダディ・マスターソン (CHARACTER 緑 cost4):
#    【ドン!!×1】【自分のターン終了時】このキャラをアクティブにする。
# --------------------------------------------------------------------------- #
def test_op04_027_end_of_turn_untap_self_with_don_gate_ai():
    """【ドン!!×1】【自分のターン終了時】自身をアクティブに (付与ドン1で発火)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    daddy = InPlay.of(repo.get("OP04-027"), sickness=False)
    daddy.rested = True
    daddy.attached_dons = 1  # 【ドン!!×1】ゲート成立
    me.characters = [daddy]

    eff = _get_eff(overlay, "OP04-027", "end_of_turn")
    assert eval_condition(_cond_of(eff), st, me, daddy) is True, \
        "付与ドン1で【ドン!!×1】条件が成立しない"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, daddy)
        _drain(st, [0])

    assert daddy.rested is False, "自身がアクティブにされていない"


def test_op04_027_don_gate_false_without_don():
    """付与ドンが無ければ【ドン!!×1】条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    daddy = InPlay.of(repo.get("OP04-027"), sickness=False)
    daddy.attached_dons = 0
    me.characters = [daddy]

    eff = _get_eff(overlay, "OP04-027", "end_of_turn")
    assert eval_condition(_cond_of(eff), st, me, daddy) is False, \
        "付与ドン0なのに【ドン!!×1】条件が成立している"


# --------------------------------------------------------------------------- #
#  OP04-028 ディアマンテ (CHARACTER 緑 cost5):
#    【ブロッカー】【ドン!!×1】【自分のターン終了時】自分のアクティブのドン!!が2枚以上ある場合、
#      このキャラをアクティブにする。
# --------------------------------------------------------------------------- #
def test_op04_028_end_of_turn_untap_self_when_active_don_ge_2_ai():
    """【自分のターン終了時】アクティブドン2枚以上 + 付与ドン1 → 自身アクティブ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    diamante = InPlay.of(repo.get("OP04-028"), sickness=False)
    diamante.rested = True
    diamante.attached_dons = 1  # 【ドン!!×1】ゲート
    me.characters = [diamante]
    me.don_active = 2  # アクティブドン2枚以上

    eff = _get_eff(overlay, "OP04-028", "end_of_turn")
    assert eval_condition(_cond_of(eff), st, me, diamante) is True, \
        "アクティブドン2 + 付与ドン1 で条件が成立しない"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, diamante)
        _drain(st, [0])

    assert diamante.rested is False, "条件成立時 自身がアクティブにされていない"


def test_op04_028_condition_false_when_active_don_lt_2():
    """アクティブドンが2枚未満なら条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    diamante = InPlay.of(repo.get("OP04-028"), sickness=False)
    diamante.attached_dons = 1
    me.characters = [diamante]
    me.don_active = 1  # 2枚未満

    eff = _get_eff(overlay, "OP04-028", "end_of_turn")
    assert eval_condition(_cond_of(eff), st, me, diamante) is False, \
        "アクティブドン1枚なのに条件が成立している"


# --------------------------------------------------------------------------- #
#  OP04-029 デリンジャー (CHARACTER 緑 cost3):
#    【自分のターン終了時】自分のドン!!1枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_op04_029_end_of_turn_untap_don_ai():
    """【自分のターン終了時】レストのドン!!1枚をアクティブにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 3
    me.don_active = 0

    eff = _get_eff(overlay, "OP04-029", "end_of_turn")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-029"), sickness=False))
        _drain(st, [0])

    assert me.don_rested == 2, \
        f"レストのドン!!1枚がアクティブにされていない: rested={me.don_rested}"
    assert me.don_active == 1, \
        f"アクティブのドン!!が+1でない: active={me.don_active}"


# --------------------------------------------------------------------------- #
#  OP04-030 トレーボル (CHARACTER 緑 cost6):
#    【登場時】相手のレストのコスト5以下のキャラ1枚までを、KOする。
#    【相手のアタック時】➁：相手のコスト4以下のキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_op04_030_on_play_ko_rested_opp_cost_le_5_ai():
    """【登場時】相手のレストのコスト5以下キャラ1枚をKO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 (<=5)
    victim.rested = True  # レスト状態が KO 対象条件
    opp.characters = [victim]

    on_play = _get_eff(overlay, "OP04-030", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-030"), sickness=False))
        _drain(st, [0])

    assert victim not in opp.characters, "相手のレストキャラがKOされていない"
    assert any(c.card_id == "OP01-013" for c in opp.trash), \
        "KOされたキャラがトラッシュに置かれていない"


def test_op04_030_on_play_no_ko_when_target_active():
    """相手キャラがアクティブなら【登場時】KO 対象外 (レスト条件)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)
    victim.rested = False  # アクティブ = 対象外
    opp.characters = [victim]

    on_play = _get_eff(overlay, "OP04-030", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-030"), sickness=False))
        _drain(st, [0])

    assert victim in opp.characters, \
        "アクティブの相手キャラがKOされている (レスト制約が効いていない)"


def test_op04_030_opp_attack_rest_opp_cost_le_4_ai():
    """【相手のアタック時】相手のコスト4以下キャラ1枚をレスト (AI 自動)。

    注: 任意コスト(➁ 自ドン2レスト)は effect-level `cost` で表現され、 do 配列は
    レスト効果本体のみ。 do を直接実行すると効果本体 (相手レスト) が発火する。
    """
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    trebol = InPlay.of(repo.get("OP04-030"), sickness=False)
    me.characters = [trebol]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 (<=4)
    opp.characters = [victim]

    on_oa = _get_eff(overlay, "OP04-030", "opp_attack")
    # 効果本体は effect-level cost {"rest_self_don": 2} を伴う (= overlay 整合 guard)。
    assert on_oa.get("cost", {}).get("rest_self_don") == 2, \
        "opp_attack の任意コスト ➁(自ドン2レスト) が overlay に無い"
    for prim in on_oa["do"]:
        execute_effect(prim, st, me, opp, trebol)
        _drain(st, [0])

    assert victim.rested is True, "相手のコスト4以下キャラがレストにされていない"


def test_op04_030_on_play_human_ko_target_pick():
    """人間 actor: 【登場時】KO 対象の target_pick modal が立ち、 解決でKO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    v1 = InPlay.of(repo.get("OP01-013"), sickness=False)
    v2 = InPlay.of(repo.get("OP01-013"), sickness=False)
    v1.rested = True
    v2.rested = True  # 複数候補で modal
    opp.characters = [v1, v2]

    on_play = _get_eff(overlay, "OP04-030", "on_play")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP04-030"), sickness=False))

    assert st.pending_choice is not None, "人間 + KO 対象選択で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    assert len(opp.characters) == 1, "人間選択後 相手のレストキャラがKOされていない"


# --------------------------------------------------------------------------- #
#  OP04-032 ベビー5 (CHARACTER 緑 cost1):
#    【自分のターン終了時】このキャラをトラッシュに置くことができる：
#      自分のドン!!2枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_op04_032_end_of_turn_untap_don_2_ai():
    """【自分のターン終了時】レストのドン!!2枚をアクティブにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 5
    me.don_active = 0

    eff = _get_eff(overlay, "OP04-032", "end_of_turn")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-032"), sickness=False))
        _drain(st, [0])

    assert me.don_rested == 3, \
        f"レストのドン!!2枚がアクティブにされていない: rested={me.don_rested}"
    assert me.don_active == 2, \
        f"アクティブのドン!!が+2でない: active={me.don_active}"


# --------------------------------------------------------------------------- #
#  OP04-033 マッハバイス (CHARACTER 緑 cost4):
#    【登場時】自分のリーダーが特徴《ドンキホーテ海賊団》を持つ場合、
#      相手のコスト5以下のキャラ1枚までを、レストにする。
#      その後、このターン終了時、自分のドン!!1枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_op04_033_on_play_condition_dofla_leader():
    """【登場時】効果の if = ドンキホーテ海賊団 リーダー。"""
    repo = _repo()
    overlay = _overlay()
    eff = _get_eff(overlay, "OP04-033", "on_play")
    st_ok = _state(repo, DOFLA_LEADER, overlay)
    assert eval_condition(_cond_of(eff), st_ok, st_ok.players[0]) is True, \
        "ドフラリーダーで条件成立しない"
    st_ng = _state(repo, "OP01-001", overlay)
    assert eval_condition(_cond_of(eff), st_ng, st_ng.players[0]) is False, \
        "非ドフラリーダーで条件が成立している"


def test_op04_033_on_play_rest_and_schedule_ai():
    """【登場時】相手コスト5以下1枚レスト + 自ターン終了時アクティブ予約 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, DOFLA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 (<=5)
    opp.characters = [victim]
    sched_before = len(getattr(me, "scheduled_at_self_turn_end", []) or [])

    on_play = _get_eff(overlay, "OP04-033", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-033"), sickness=False))
        _drain(st, [0])

    assert victim.rested is True, "相手のコスト5以下キャラがレストにされていない"
    assert len(getattr(me, "scheduled_at_self_turn_end", []) or []) == sched_before + 1, \
        "このターン終了時のドン!!アクティブ化が予約されていない"


def test_op04_033_on_play_human_target_pick():
    """人間 actor: レスト対象の target_pick modal が立ち、 解決でレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, DOFLA_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    v1 = InPlay.of(repo.get("OP01-013"), sickness=False)
    v2 = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [v1, v2]

    on_play = _get_eff(overlay, "OP04-033", "on_play")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP04-033"), sickness=False))

    assert st.pending_choice is not None, "人間 + 対象選択で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    assert (v1.rested or v2.rested), "人間選択後 相手キャラがレストにされていない"
