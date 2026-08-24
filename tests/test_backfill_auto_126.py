# -*- coding: utf-8 -*-
"""OP13 (赤 ルフィ・革命軍 系 / 緑 FILM・革命軍・ドン加速 系) 効果 回帰テスト
バックフィル (自動生成 wave 126):
OP13-019 / OP13-020 / OP13-021 / OP13-022 / OP13-023 /
OP13-024 / OP13-025 / OP13-028 / OP13-030 / OP13-032 の 10 枚。

目的 (= test_backfill_auto_001〜125.py と同一方針):
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
    resolve_triggers,
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
    trigger_on_ko,
    trigger_on_play,
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


def _do(overlay, cid, when, must_contain=None):
    """指定 card_id の overlay から when 一致 (+ do[0] に must_contain キー) の効果の do を返す。"""
    for e in overlay.get(cid).effects:
        if e.get("when") != when:
            continue
        if must_contain is not None and must_contain not in e["do"][0]:
            continue
        return e["do"], e
    raise AssertionError(f"{cid} に when={when} (contain={must_contain}) の効果がない")


def _drain(st, guard=14):
    """pending_choice を種別ごとに適切に選び続けて解決しきる。"""
    g = 0
    while st.pending_choice is not None and g < guard:
        kind = st.pending_choice.get("kind", "")
        if kind in ("optional_cost_confirm", "reveal_top_play_confirm",
                    "replace_ko_optional"):
            resolve_pending_choice(st, [1])
        else:
            cands = (st.pending_choice.get("candidates")
                     or st.pending_choice.get("cards")
                     or st.pending_choice.get("options") or [])
            resolve_pending_choice(st, [0] if len(cands) > 0 else [])
        g += 1


# 定番 leader / helper カード
_NEUTRAL = "OP01-001"        # ロロノア・ゾロ (leader、 超新星/麦わらの一味)
_VICTIM = "OP01-016"         # ナミ (麦わらの一味 cost1 pow2000 CHARACTER)
_FILLER = "OP01-013"         # サンジ (麦わらの一味 cost2 pow3000 CHARACTER)
_LUFFY_C = "OP14-013"        # モンキー・Ｄ・ルフィ (CHARACTER 赤 cost1)
_BIG = "OP13-023"            # ウタ (CHARACTER 緑 cost4 pow5000、 特徴 FILM)
_COST10 = "OP13-028"         # シャンクス (CHARACTER 緑 cost10 pow12000)
_FILM_LEADER = "OP06-001"    # ウタ (LEADER、 特徴 FILM)
_NONFILM_LEADER = "EB04-001"  # ジュエリー・ボニー (LEADER、 FILM/打 いずれも無し)


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave126_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP13-019", "OP13-020", "OP13-021", "OP13-022", "OP13-023",
           "OP13-024", "OP13-025", "OP13-028", "OP13-030", "OP13-032"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP13-019 "火炎"が許さねェってよ!! (EVENT 赤 cost1):
#    【メイン】ドン4レスト：相手キャラ1枚を このターン中 -3000。
#      その後、 相手のパワー3000以下のキャラ1枚を KO。
#    【カウンター】自リーダーを このバトル中 +3000。
# --------------------------------------------------------------------------- #
def test_op13_019_main_debuff_then_ko_ai():
    """【メイン】do: 相手キャラ -3000 → その後 パワー3000以下を KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_BIG), sickness=False)  # pow5000 → -3000 で 2000 ≤3000
    opp.characters = [victim]

    do, _ = _do(overlay, "OP13-019", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert victim not in opp.characters, \
        "-3000 でパワー3000以下になった相手キャラが KO されていない"


def test_op13_019_main_debuff_human_pick():
    """人間 + 相手キャラ複数 → -3000 の対象選択 target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_BIG), sickness=False)     # pow5000
    b = InPlay.of(repo.get(_FILLER), sickness=False)  # pow3000
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP13-019", "main")
    execute_effect(do[0], st, me, opp, None)  # 先頭 = power_pump

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    a_before = a.power
    resolve_pending_choice(st, [a_idx])
    assert a.power == a_before - 3000, "人間が選んだ相手キャラに -3000 が反映されていない"


def test_op13_019_counter_pump_leader():
    """【カウンター】 自リーダーを このバトル中 パワー+3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    do, _ = _do(overlay, "OP13-019", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 3000, \
        f"カウンターの +3000 が自リーダーに反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  OP13-020 拳・骨・隕石 (EVENT 赤 cost3):
#    【メイン】相手のキャラ1枚までを、このターン中、パワー-5000。
#    【トリガー】このカードの【メイン】効果を発動する。
# --------------------------------------------------------------------------- #
def test_op13_020_main_debuff_ai():
    """【メイン】 相手キャラ1体を -5000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # pow3000
    opp.characters = [victim]

    power_before = victim.power
    do, _ = _do(overlay, "OP13-020", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert victim.power == power_before - 5000, \
        f"相手キャラ -5000 が反映されていない: {victim.power} (before {power_before})"


def test_op13_020_main_debuff_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal が立ち resolve で 1体に -5000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_VICTIM), sickness=False)
    b = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP13-020", "main")
    execute_effect(do[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    assert b.power == b_before - 5000, "人間が選んだ相手キャラに -5000 が反映されていない"


def test_op13_020_trigger_fires_main():
    """【トリガー】 fire_self_effect で【メイン】(相手キャラ -5000) が再発火する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # pow3000
    opp.characters = [victim]
    # EVENT 自身を self_inplay に渡す (= fire_self_effect の src_cid 解決に必要)
    self_ip = InPlay.of(repo.get("OP13-020"), sickness=True)

    power_before = victim.power
    do, _ = _do(overlay, "OP13-020", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, self_ip)
    _drain(st)

    assert victim.power == power_before - 5000, \
        f"トリガーで【メイン】(-5000) が発火していない: {victim.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  OP13-021 ゴムゴムの銃乱打 (EVENT 赤 cost1):
#    【メイン】自「モンキー・Ｄ・ルフィ」1枚にレストドン1まで付与 → その後 相手キャラ1体 -2000。
#    【トリガー】相手のキャラ1枚までを、このターン中、パワー-2000。
# --------------------------------------------------------------------------- #
def test_op13_021_main_attach_then_debuff_ai():
    """【メイン】 ルフィにレストドン1付与 + 相手キャラ -2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2
    luffy = InPlay.of(repo.get(_LUFFY_C), sickness=False)
    me.characters = [luffy]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # pow3000
    opp.characters = [victim]

    don_before = luffy.attached_dons
    rested_before = me.don_rested
    victim_before = victim.power
    do, _ = _do(overlay, "OP13-021", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert luffy.attached_dons == don_before + 1, \
        f"ルフィにレストドン1が付与されていない: {luffy.attached_dons}"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"
    assert victim.power == victim_before - 2000, \
        f"相手キャラ -2000 が反映されていない: {victim.power} (before {victim_before})"


def test_op13_021_main_debuff_human_pick():
    """人間 + 相手キャラ複数 → -2000 の対象選択 target_pick modal が立つ (do[1] を直接発火)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_VICTIM), sickness=False)
    b = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP13-021", "main")
    execute_effect(do[1], st, me, opp, None)  # do[1] = power_pump 相手 -2000

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    assert b.power == b_before - 2000, "人間が選んだ相手キャラに -2000 が反映されていない"


def test_op13_021_trigger_debuff_ai():
    """【トリガー】 相手キャラ1体を -2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]

    power_before = victim.power
    do, _ = _do(overlay, "OP13-021", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert victim.power == power_before - 2000, \
        f"トリガーの -2000 が反映されていない: {victim.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  OP13-022 フーシャ村 (STAGE 赤 cost1):
#    【起動メイン】このステージをレストにできる：自分の元々のパワー2000以下のキャラ1枚を
#      このターン中、パワー+1000。
# --------------------------------------------------------------------------- #
def test_op13_022_activate_main_pump_ai():
    """起動メイン: ステージをレスト (コスト) → 元々P2000以下キャラ +1000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("OP13-022"), sickness=False)
    me.stages = [stage]
    target = InPlay.of(repo.get(_VICTIM), sickness=False)  # pow2000 (≤2000)
    me.characters = [target]

    power_before = target.power
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP13-022"]
    assert len(opts) == 1, \
        f"OP13-022 (ステージ) の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    assert target.power == power_before + 1000, \
        f"元々P2000以下キャラへの +1000 が反映されていない: {target.power} (before {power_before})"
    assert stage.rested is True, "起動メインコストでステージがレストされるべき"


def test_op13_022_pump_human_pick():
    """人間 + 元々P2000以下キャラ複数 → 内側 power_pump を直接発火で target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_VICTIM), sickness=False)  # pow2000
    b = InPlay.of(repo.get(_VICTIM), sickness=False)  # pow2000
    me.characters = [a, b]

    do, entry = _do(overlay, "OP13-022", "activate_main")
    inner_pump = do[0]["optional_cost_then"]["effect"][0]  # power_pump one_self_chara_filtered
    execute_effect(inner_pump, st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    assert b.power == b_before + 1000, "人間が選んだキャラに +1000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP13-023 ウタ (CHARACTER 緑 cost4 pow5000):
#    【登場時】自ドン2までアクティブ → その後 このターン中 元々コスト5以上のキャラを登場不可。
#    【KO時】自分の手札からコスト5以下のキャラ1枚までを、レストで登場。
# --------------------------------------------------------------------------- #
def test_op13_023_on_play_untap_and_block_ai():
    """【登場時】 レストドン2アクティブ + 元々コスト5+ 登場禁止フラグ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 3
    me.don_active = 0
    uta = InPlay.of(repo.get("OP13-023"), sickness=True)
    me.characters = [uta]

    trigger_on_play(st, me, opp, uta, overlay)
    _drain(st)

    assert me.don_active == 2, f"ドン2枚がアクティブになっていない: {me.don_active}"
    assert me.don_rested == 1, f"アクティブ化でレストドンが2枚減るべき: {me.don_rested}"
    assert me.block_chara_play_cost_ge_threshold == 5, \
        f"元々コスト5+ 登場禁止フラグが立っていない: {me.block_chara_play_cost_ge_threshold}"


def test_op13_023_on_ko_play_from_hand_rested_ai():
    """【KO時】 手札からコスト5以下キャラをレストで登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]  # サンジ cost2 (≤5)
    me.characters = []

    chars_before = len(me.characters)
    trigger_on_ko(st, me, opp, repo.get("OP13-023"), overlay)
    resolve_triggers(st)  # KO グループは enqueue のみ = 実経路と同じくここでドレイン
    _drain(st)

    assert len(me.characters) == chars_before + 1, \
        "手札からコスト5以下キャラが登場していない"
    played = me.characters[-1]
    assert played.card.card_id == _FILLER, "登場したキャラが手札のカードでない"
    assert played.rested is True, "【KO時】の登場は レスト状態であるべき"


# --------------------------------------------------------------------------- #
#  OP13-024 ゴードン (CHARACTER 緑 cost1):
#    【登場時】手札から特徴《音楽》か《FILM》を1枚公開できる：
#      このターン終了時、 自ドン2までアクティブ。
# --------------------------------------------------------------------------- #
def test_op13_024_on_play_reveal_schedules_untap_ai():
    """【登場時】 FILM カード公開 (任意コスト) → ターン終了時ドン2アクティブ を予約 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_BIG)]  # ウタ = 特徴 FILM (公開コスト用)
    me.don_rested = 3
    gordon = InPlay.of(repo.get("OP13-024"), sickness=True)
    me.characters = [gordon]

    trigger_on_play(st, me, opp, gordon, overlay)
    _drain(st)

    sched = list(getattr(me, "scheduled_at_self_turn_end", []) or [])
    assert len(sched) >= 1, "ターン終了時発動 (ドンアクティブ) が予約されていない"
    # 予約内容に untap_don が含まれる
    assert any("untap_don" in prim
               for entry in sched
               for prim in entry.get("do", [])), \
        "予約された効果に untap_don が含まれていない"


def test_op13_024_on_play_no_reveal_no_schedule():
    """負例: 手札に《音楽》《FILM》が無ければ 公開コスト不能 → 予約されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_VICTIM)]  # ナミ = 麦わらの一味 のみ (音楽/FILM 無し)
    me.don_rested = 3
    gordon = InPlay.of(repo.get("OP13-024"), sickness=True)
    me.characters = [gordon]

    trigger_on_play(st, me, opp, gordon, overlay)
    _drain(st)

    sched = list(getattr(me, "scheduled_at_self_turn_end", []) or [])
    assert not any("untap_don" in prim
                   for entry in sched
                   for prim in entry.get("do", [])), \
        "公開コストを払えないのにドンアクティブが予約されてはいけない"


# --------------------------------------------------------------------------- #
#  OP13-025 コビー (CHARACTER 緑 cost5 pow6000):
#    【ブロッカー】【登場時】自リーダーが特徴《FILM》か属性(打)を持つ場合、
#      自分のドン‼1枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_op13_025_on_play_untap_when_film_leader_ai():
    """【登場時】 自リーダーが FILM → ドン1アクティブ (条件成立、 AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _FILM_LEADER, overlay)  # ウタ (FILM) leader
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2
    me.don_active = 0
    coby = InPlay.of(repo.get("OP13-025"), sickness=True)
    me.characters = [coby]

    trigger_on_play(st, me, opp, coby, overlay)
    _drain(st)

    assert me.don_active == 1, f"FILM リーダーで ドン1アクティブが起きていない: {me.don_active}"
    assert me.don_rested == 1, "アクティブ化でレストドンが1枚減るべき"


def test_op13_025_on_play_no_untap_when_condition_fails():
    """負例: 自リーダーが FILM でも 属性(打) でもない → ドンアクティブは起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NONFILM_LEADER, overlay)  # ボニー (FILM/打 無し)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2
    me.don_active = 0
    coby = InPlay.of(repo.get("OP13-025"), sickness=True)
    me.characters = [coby]

    trigger_on_play(st, me, opp, coby, overlay)
    _drain(st)

    assert me.don_active == 0, "条件不成立でドンがアクティブになってはいけない"
    assert me.don_rested == 2, "条件不成立でレストドンは減ってはいけない"


# --------------------------------------------------------------------------- #
#  OP13-028 シャンクス (CHARACTER 緑 cost10 pow12000):
#    【登場時】自分のドン‼すべてをアクティブにする → その後 このターン中 手札からプレイ不可。
# --------------------------------------------------------------------------- #
def test_op13_028_on_play_untap_all_and_block_play_ai():
    """【登場時】 全ドンアクティブ + このターン中 手札プレイ禁止フラグ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 5
    me.don_active = 0
    shanks = InPlay.of(repo.get("OP13-028"), sickness=True)
    me.characters = [shanks]

    trigger_on_play(st, me, opp, shanks, overlay)
    _drain(st)

    assert me.don_active == 5, f"全レストドンがアクティブになっていない: {me.don_active}"
    assert me.don_rested == 0, f"レストドンが0にならない: {me.don_rested}"
    # OP13-028「手札からカードをプレイできない」= 通常プレイのみ禁止 (block_hand_play_turn)。
    # 効果登場は禁止しない (cardqa_op_13, db0c0c0d2ab9) ので block_chara_play_until_turn_end とは別フラグ。
    assert me.block_hand_play_until_turn_end is True, \
        "このターン中 手札プレイ禁止フラグが立っていない"
    assert me.block_chara_play_until_turn_end is False, \
        "手札プレイ禁止は登場禁止 (block_chara_play) とは別フラグでなければならない"


# --------------------------------------------------------------------------- #
#  OP13-030 トニートニー・チョッパー (CHARACTER 緑 cost5 pow6000):
#    【登場時】自分のドン‼2枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_op13_030_on_play_untap_two_ai():
    """【登場時】 レストドン2をアクティブ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 3
    me.don_active = 0
    chopper = InPlay.of(repo.get("OP13-030"), sickness=True)
    me.characters = [chopper]

    trigger_on_play(st, me, opp, chopper, overlay)
    _drain(st)

    assert me.don_active == 2, f"ドン2枚がアクティブになっていない: {me.don_active}"
    assert me.don_rested == 1, f"アクティブ化でレストドンが2枚減るべき: {me.don_rested}"


# --------------------------------------------------------------------------- #
#  OP13-032 ニコ・ロビン (CHARACTER 緑 cost7 pow7000):
#    【登場時】相手のコスト8以下のキャラ1枚までは、次の相手のエンドフェイズ終了時まで、
#      レストにできない。
# --------------------------------------------------------------------------- #
def test_op13_032_on_play_set_cannot_rest_ai():
    """【登場時】 相手のコスト8以下キャラ1体に「レスト不能」を付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    target = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (≤8)
    opp.characters = [target]
    robin = InPlay.of(repo.get("OP13-032"), sickness=True)
    me.characters = [robin]

    trigger_on_play(st, me, opp, robin, overlay)
    _drain(st)

    assert target.cannot_be_rested_buff is True, \
        "相手のコスト8以下キャラに レスト不能 buff が付与されていない"


def test_op13_032_on_play_no_target_when_cost_over_8():
    """負例: 相手キャラが コスト8超 なら 対象外 → レスト不能 buff は付かない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    big = InPlay.of(repo.get(_COST10), sickness=False)  # cost10 (>8)
    opp.characters = [big]
    robin = InPlay.of(repo.get("OP13-032"), sickness=True)
    me.characters = [robin]

    trigger_on_play(st, me, opp, robin, overlay)
    _drain(st)

    assert big.cannot_be_rested_buff is False, \
        "コスト8超のキャラに レスト不能 buff が付いてはいけない (対象外)"


def test_op13_032_on_play_set_cannot_rest_human_pick():
    """人間 + 相手のコスト8以下キャラ複数 → target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_VICTIM), sickness=False)   # cost1
    b = InPlay.of(repo.get(_FILLER), sickness=False)   # cost2
    opp.characters = [a, b]
    robin = InPlay.of(repo.get("OP13-032"), sickness=True)
    me.characters = [robin]

    trigger_on_play(st, me, opp, robin, overlay)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b.cannot_be_rested_buff is True, \
        "人間が選んだ相手キャラに レスト不能 buff が付与されていない"
    assert a.cannot_be_rested_buff is False, "選ばなかったキャラには buff が付いてはいけない"
