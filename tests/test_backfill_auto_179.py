# -*- coding: utf-8 -*-
"""ST14 / ST15 / ST16 弾 効果 回帰テスト バックフィル (自動生成 wave 179):
ST14-015 / ST14-016 / ST14-017 / ST15-001 / ST15-002 / ST15-003 /
ST15-005 / ST16-001 / ST16-002 / ST16-003 の 10 枚。

目的 (= test_backfill_auto_001〜178.py と同一方針):
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
from engine.effects import (
    eval_condition,
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
    try_replace_ko,
)
from engine.deck import CardRepository

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001",
           turn_player=0):
    """P0 = テスト対象デッキ、 P1 = ダミー。 MAIN / turn_number=3。
    デッキは効果の薄いカード (OP01-016 ナミ) で埋める。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("OP01-016")] * 30
    p1.deck = [repo.get("OP01-016")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn_player
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果の (do 配列, eff) を返す。"""
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


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave179_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["ST14-015", "ST14-016", "ST14-017", "ST15-001", "ST15-002",
           "ST15-003", "ST15-005", "ST16-001", "ST16-002", "ST16-003"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  ST14-015 ゴムゴムの…攻城砲 (EVENT 黒 cost2):
#    【メイン】自リーダーかキャラ1枚 +3000。 その後、 自コスト8以上キャラがいれば
#             相手のコスト2以下のキャラ1枚を KO。
# --------------------------------------------------------------------------- #
def test_st14_015_main_pump_ai():
    """【メイン】(1) 自リーダーに +3000 (AI 自動、 リーダーのみ = 候補1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST14-001", overlay)  # 黒 麦わら リーダー
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    do, _ = _do(overlay, "ST14-015", "main")
    # pump 部分 (do[0]) のみ発火 (conditional は 別テスト)
    execute_effect(do[0], st, me, opp, None)
    _drain(st, [0])
    assert me.leader.power == power_before + 3000, \
        f"メインの +3000 が自リーダーに反映されていない: {me.leader.power}"


def test_st14_015_main_conditional_ko_ai():
    """【メイン】(2) 自コスト8以上キャラがいれば 相手コスト2以下キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST14-001", overlay)
    me, opp = st.players[0], st.players[1]
    big = InPlay.of(repo.get("EB04-013"), sickness=False)  # cost8 キャラ
    me.characters = [big]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost1 ≤ 2
    opp.characters = [victim]

    do, _ = _do(overlay, "ST14-015", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim not in opp.characters, \
        "自コスト8以上キャラ存在時に 相手コスト2以下キャラが KO されていない"


def test_st14_015_main_conditional_no_big_survives():
    """自コスト8以上キャラがいなければ 相手キャラは KO されない (条件不成立)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST14-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [victim]  # 自分側に cost8 以上キャラなし

    do, _ = _do(overlay, "ST14-015", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim in opp.characters, \
        "自コスト8以上キャラ不在なのに 相手キャラが KO されている"


def test_st14_015_main_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +3000 の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST14-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP15-081"), sickness=False)  # 黒麦わら サンジ
    me.characters = [friend]

    do, _ = _do(overlay, "ST14-015", "main")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands)
                      if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert friend.power == friend_before + 3000, \
        "人間が選んだキャラに +3000 が反映されていない"


# --------------------------------------------------------------------------- #
#  ST14-016 仲間がいる゛よ!!!! (EVENT 黒 cost1):
#    【メイン】カード1枚を引く。 その後 自キャラ1枚を 次の相手ターン終了時まで コスト+3。
# --------------------------------------------------------------------------- #
def test_st14_016_main_draw_and_cost_up_ai():
    """【メイン】1 ドロー + 自キャラを コスト+3 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST14-001", overlay)
    me, opp = st.players[0], st.players[1]
    target = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2
    me.characters = [target]
    me.hand = []
    me.deck = [repo.get("OP01-016")] * 10

    deck_before = len(me.deck)
    base_before = target.base_cost
    do, _ = _do(overlay, "ST14-016", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert len(me.hand) == 1, "メインの 1 ドローが起きていない"
    assert len(me.deck) == deck_before - 1, "1 ドローでデッキが1枚減っていない"
    assert target.base_cost == base_before + 3, \
        f"自キャラの コスト+3 が反映されていない: {target.base_cost} (before {base_before})"


def test_st14_016_main_cost_up_human_pick():
    """人間 + 自キャラ 複数 → コスト+3 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST14-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    me.characters = [a, b]
    me.deck = [repo.get("OP01-016")] * 10

    do, _ = _do(overlay, "ST14-016", "main")
    # draw (do[0]) を消化 → cost_minus (do[1]) で modal
    for prim in do:
        execute_effect(prim, st, me, opp, None)
        if st.pending_choice is not None:
            break
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.base_cost
    resolve_pending_choice(st, [b_idx])
    assert b.base_cost == b_before + 3, \
        "人間が選んだキャラに コスト+3 が反映されていない"


def test_st14_016_trigger_ko_cost_le_3_ai():
    """【トリガー】相手のコスト3以下キャラ1枚を KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST14-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 ≤ 3
    opp.characters = [victim]

    do, _ = _do(overlay, "ST14-016", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim not in opp.characters, \
        "トリガーで 相手コスト3以下キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  ST14-017 サウザンド・サニー号 (STAGE 黒 cost1):
#    自黒《麦わらの一味》キャラ全て コスト+1 (静的)。
#    【登場時】自リーダーが《麦わらの一味》なら 1 ドロー。
# --------------------------------------------------------------------------- #
def test_st14_017_static_cost_up_ai():
    """静的: 自黒《麦わらの一味》キャラ全て コスト+1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST14-001", overlay)
    me = st.players[0]
    sanji = InPlay.of(repo.get("OP15-081"), sickness=False)  # 黒麦わら サンジ cost1
    stage = InPlay.of(repo.get("ST14-017"), sickness=False)
    me.characters = [sanji]
    me.stages = [stage]

    base_cost = repo.get("OP15-081").cost
    evaluate_static_effects(st, overlay)
    assert sanji.base_cost == base_cost + 1, \
        f"自黒麦わらキャラの コスト+1 が反映されていない: {sanji.base_cost} (印刷 {base_cost})"


def test_st14_017_on_play_draw_ai():
    """【登場時】自リーダーが《麦わらの一味》なら 1 ドロー (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST14-001", overlay)  # 黒麦わら リーダー
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("OP01-016")] * 10

    do, eff = _do(overlay, "ST14-017", "on_play")
    assert eval_condition(eff.get("if", {}), st, me) is True, \
        "麦わらリーダーで登場時条件が成立していない"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST14-017"), sickness=True))
    _drain(st, [0])
    assert len(me.hand) == 1, "登場時の 1 ドローが起きていない"


def test_st14_017_on_play_condition_false_non_mugiwara():
    """自リーダーが《麦わらの一味》でなければ 登場時条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-001", overlay)  # エドワード (四皇/白ひげ、 非麦わら)
    me = st.players[0]
    _, eff = _do(overlay, "ST14-017", "on_play")
    assert eval_condition(eff.get("if", {}), st, me) is False, \
        "非麦わらリーダーで登場時条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  ST15-001 アトモス (CHARACTER 赤 cost4 power5000):
#    【アタック時】自リーダーが「エドワード・ニューゲート」なら、 このターン中
#                 自効果でライフを手札に加えられない。
# --------------------------------------------------------------------------- #
def test_st15_001_on_attack_prevent_life_to_hand_ai():
    """【アタック時】エドワード・ニューゲート リーダーで 自効果ライフ→手札 を禁止。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-001", overlay)  # エドワード・ニューゲート
    me, opp = st.players[0], st.players[1]
    atomos = InPlay.of(repo.get("ST15-001"), sickness=False)
    me.characters = [atomos]

    assert me.prevent_self_life_to_hand_until_turn_end is False
    do, eff = _do(overlay, "ST15-001", "on_attack")
    assert eff.get("if", {}).get("leader_name") == "エドワード・ニューゲート", \
        "overlay の leader_name ゲートが無い"
    for prim in do:
        execute_effect(prim, st, me, opp, atomos)
    assert me.prevent_self_life_to_hand_until_turn_end is True, \
        "アタック時に 自効果ライフ→手札 禁止フラグが立っていない"


def test_st15_001_condition_false_non_newgate():
    """リーダーが エドワード・ニューゲート でなければ 条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ (≠ エドワード)
    me = st.players[0]
    _, eff = _do(overlay, "ST15-001", "on_attack")
    assert eval_condition(eff.get("if", {}), st, me) is False, \
        "非エドワードリーダーで条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  ST15-002 エドワード・ニューゲート (CHARACTER 赤 cost7 power8000):
#    【登場時】自リーダーかキャラ1枚に レストのドン1枚を付与。
#    【起動メイン】このキャラをレスト：相手のパワー5000以下キャラ1枚を KO。
# --------------------------------------------------------------------------- #
def test_st15_002_on_play_attach_rested_don_ai():
    """【登場時】自リーダーに レストドン1枚を付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2

    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    do, _ = _do(overlay, "ST15-002", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST15-002"), sickness=True))
    _drain(st, [0])
    assert me.leader.attached_dons == don_before + 1, \
        "登場時に 自リーダーへ レストドンが付与されていない"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"


def test_st15_002_activate_main_ko_le_5000_ai():
    """【起動メイン】自身をレスト → 相手パワー5000以下キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-001", overlay)
    me, opp = st.players[0], st.players[1]
    whitebeard = InPlay.of(repo.get("ST15-002"), sickness=False)
    me.characters = [whitebeard]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ power2000 ≤ 5000
    opp.characters = [victim]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST15-002"]
    assert len(opts) == 1, f"ST15-002 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert victim not in opp.characters, "相手パワー5000以下キャラが KO されていない"
    assert whitebeard.rested is True, "起動メインコストで自身がレストされるべき"


def test_st15_002_activate_main_human_ko_pick():
    """人間 + 相手パワー5000以下キャラ 複数 → KO の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    whitebeard = InPlay.of(repo.get("ST15-002"), sickness=False)
    me.characters = [whitebeard]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # power2000
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # power3000
    opp.characters = [a, b]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST15-002"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])
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
#  ST15-003 キングデュー (CHARACTER 赤 cost3 power4000):
#    【ブロッカー】【相手のターン中】このキャラが効果で KO された時、
#                 自リーダー1枚を このターン中 パワー+2000。
# --------------------------------------------------------------------------- #
def test_st15_003_on_ko_leader_pump_ai():
    """【相手ターン中】効果 KO 時 → 自リーダー +2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-001", overlay, turn_player=1)  # 相手ターン
    me, opp = st.players[0], st.players[1]

    do, eff = _do(overlay, "ST15-003", "on_ko")
    assert eff.get("if", {}).get("opp_turn") is True, \
        "overlay の【相手のターン中】(opp_turn) ゲートが無い"
    assert eff.get("if", {}).get("by_opp_effect") is True, \
        "overlay の【効果でKO】(by_opp_effect) ゲートが無い"
    power_before = me.leader.power
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST15-003"), sickness=False))
    _drain(st, [0])
    assert me.leader.power == power_before + 2000, \
        f"KO時 自リーダー +2000 が反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  ST15-005 ポートガス・D・エース (CHARACTER 赤 cost5 power6000):
#    自リーダーが《白ひげ海賊団》を含む特徴なら【速攻】(静的)。
#    【ターン1回】相手効果で場を離れる場合、 代わりに このターン中 パワー-2000できる。
# --------------------------------------------------------------------------- #
def test_st15_005_static_rush_when_whitebeard_leader():
    """静的: 白ひげ海賊団 リーダーで 自身に【速攻】が付与される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-001", overlay)  # 四皇/白ひげ海賊団 リーダー
    me = st.players[0]
    ace = InPlay.of(repo.get("ST15-005"), sickness=True)
    me.characters = [ace]

    evaluate_static_effects(st, overlay)
    assert "速攻" in ace.static_granted_keywords, \
        "白ひげ海賊団 リーダー時に【速攻】が静的付与されていない"
    assert ace.is_rush_now is True, "白ひげ海賊団 リーダー時に is_rush_now が True でない"


def test_st15_005_static_no_rush_non_whitebeard():
    """非 白ひげ海賊団 リーダーでは【速攻】は付与されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ (非 白ひげ)
    me = st.players[0]
    ace = InPlay.of(repo.get("ST15-005"), sickness=True)
    me.characters = [ace]

    evaluate_static_effects(st, overlay)
    assert "速攻" not in ace.static_granted_keywords, \
        "非 白ひげ海賊団 リーダーで【速攻】が静的付与されている"


def test_st15_005_replace_leave_self_debuff_ai():
    """【ターン1回】相手効果で離脱 → 代わりに 自身 -2000 で場に残る (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-001", overlay)
    me, opp = st.players[0], st.players[1]
    ace = InPlay.of(repo.get("ST15-005"), sickness=False)
    me.characters = [ace]

    power_before = ace.power
    replaced = try_replace_ko(
        st, me, opp, ace, overlay, by_opp_effect=True, leave_kind="ko",
    )
    _drain(st, [0])
    assert replaced is True, "相手効果離脱が -2000 で置換されていない"
    assert ace in me.characters, "置換成立時 エースは場に残るべき"
    assert ace.power == power_before - 2000, \
        f"置換で 自身 -2000 が反映されていない: {ace.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  ST16-001 ウタ (CHARACTER 緑 cost4 power6000):
#    【ブロッカー】【起動メイン】【ターン1回】手札の《FILM》1枚を捨てる：
#                 自リーダーかキャラ1枚に レストのドン1枚を付与。
# --------------------------------------------------------------------------- #
def test_st16_001_activate_main_discard_film_attach_don_ai():
    """【起動メイン】FILM 1枚捨てて 自リーダーに レストドン1枚を付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST11-001", overlay)  # ウタ (緑 FILM) リーダー
    me, opp = st.players[0], st.players[1]
    uta = InPlay.of(repo.get("ST16-001"), sickness=False)
    me.characters = [uta]
    me.hand = [repo.get("OP13-026")]  # サニーくん FILM = 捨てるコスト
    me.don_rested = 2

    don_before = me.leader.attached_dons
    hand_before = len(me.hand)
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST16-001"]
    assert len(opts) == 1, f"ST16-001 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert me.leader.attached_dons == don_before + 1, \
        "起動メインで 自リーダーへ レストドンが付与されていない"
    assert len(me.hand) == hand_before - 1, "FILM 捨てコストで手札が1枚減るべき"
    assert any(c.card_id == "OP13-026" for c in me.trash), \
        "捨てた FILM カードがトラッシュに置かれていない"


def test_st16_001_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST11-001", overlay)
    me, opp = st.players[0], st.players[1]
    uta = InPlay.of(repo.get("ST16-001"), sickness=False)
    me.characters = [uta]
    me.hand = [repo.get("OP13-026"), repo.get("OP13-026")]  # FILM ×2
    me.don_rested = 3

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST16-001"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST16-001"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  ST16-002 ゴードン (CHARACTER 緑 cost2):
#    【ブロッカー】【相手のアタック時】手札の《音楽》を任意枚数捨ててよい。
#                 捨てた1枚につき 自リーダーかキャラ1枚は このバトル中 パワー+1000。
# --------------------------------------------------------------------------- #
def test_st16_002_opp_attack_discard_buff_ai():
    """【相手のアタック時】《音楽》2枚捨てて 自チーム +2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST11-001", overlay, turn_player=1)  # 相手ターン
    me, opp = st.players[0], st.players[1]
    gordon = InPlay.of(repo.get("ST16-002"), sickness=False)
    me.characters = [gordon]
    me.hand = [repo.get("ST11-004"), repo.get("ST11-004")]  # 新時代 (音楽) ×2

    hand_before = len(me.hand)
    do, _ = _do(overlay, "ST16-002", "opp_attack")
    for prim in do:
        execute_effect(prim, st, me, opp, gordon)
    _drain(st, [0])
    assert len(me.hand) == hand_before - 2, "《音楽》2枚が捨てられていない"
    buffed = [c for c in [me.leader] + me.characters if c.battle_buff >= 2000]
    assert buffed, "捨てた枚数分の battle_buff (+2000) が自チームに乗っていない"


def test_st16_002_opp_attack_human_pick():
    """人間 + 手札の《音楽》 → optional_discard_buff_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST11-001", overlay, human_idx=0, turn_player=1)
    me, opp = st.players[0], st.players[1]
    gordon = InPlay.of(repo.get("ST16-002"), sickness=False)
    me.characters = [gordon]
    me.hand = [repo.get("ST11-004"), repo.get("ST11-004")]

    do, _ = _do(overlay, "ST16-002", "opp_attack")
    execute_effect(do[0], st, me, opp, gordon)
    assert st.pending_choice is not None, "人間 + 候補で discard modal が立たない"
    assert st.pending_choice.get("kind") == "optional_discard_buff_pick", \
        f"kind が optional_discard_buff_pick でない: {st.pending_choice.get('kind')}"
    # 1 枚だけ捨てる選択で解決 → +1000
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    buffed = [c for c in [me.leader] + me.characters if c.battle_buff >= 1000]
    assert buffed, "人間が選んだ捨て枚数分の battle_buff が乗っていない"


# --------------------------------------------------------------------------- #
#  ST16-003 シャーロット・カタクリ (CHARACTER 緑 cost3 power4000):
#    自リーダーが《FILM》を持ち、 自レストカードが6枚以上なら パワー+2000 (静的)。
# --------------------------------------------------------------------------- #
def test_st16_003_static_pump_when_film_and_6_rested():
    """静的: FILM リーダー + 自レスト6枚以上で パワー+2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST11-001", overlay)  # ウタ (緑 FILM)
    me = st.players[0]
    katakuri = InPlay.of(repo.get("ST16-003"), sickness=False)
    me.characters = [katakuri]
    me.don_rested = 6  # レストカード 6 枚 (= 条件成立)

    base = repo.get("ST16-003").power
    evaluate_static_effects(st, overlay)
    assert katakuri.power == base + 2000, \
        f"FILM + レスト6枚で +2000 が反映されていない: {katakuri.power} (印刷 {base})"


def test_st16_003_static_no_pump_few_rested():
    """自レストカードが6枚未満なら +2000 は乗らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST11-001", overlay)
    me = st.players[0]
    katakuri = InPlay.of(repo.get("ST16-003"), sickness=False)
    me.characters = [katakuri]
    me.don_rested = 0  # レストカードなし

    base = repo.get("ST16-003").power
    evaluate_static_effects(st, overlay)
    assert katakuri.power == base, \
        f"レスト6枚未満なのに +2000 が乗っている: {katakuri.power} (印刷 {base})"


def test_st16_003_static_no_pump_non_film_leader():
    """自リーダーが《FILM》でなければ +2000 は乗らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ (非 FILM)
    me = st.players[0]
    katakuri = InPlay.of(repo.get("ST16-003"), sickness=False)
    me.characters = [katakuri]
    me.don_rested = 6

    base = repo.get("ST16-003").power
    evaluate_static_effects(st, overlay)
    assert katakuri.power == base, \
        f"非 FILM リーダーなのに +2000 が乗っている: {katakuri.power} (印刷 {base})"
