# -*- coding: utf-8 -*-
"""ST14 弾 効果 回帰テスト バックフィル (自動生成 wave 178):
ST14-002 / ST14-003 / ST14-004 / ST14-006 / ST14-007 / ST14-008 /
ST14-009 / ST14-011 / ST14-012 / ST14-014 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_001.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択を持つカードは 人間 actor で pending_choice が正しい kind + 候補で立ち、
      resolve_pending_choice で解決できる (= 人間が選べる)
  (3) 同じ効果を AI 文脈 (human_player_idx=None) で回しても crash せず自動解決する
      (= AI が選べる)

ST14 は 黒 麦わらの一味 の 「コスト N 以上のキャラがいる場合」 系 build-around。
高コスト gate 用の 実カード = EB04-003 (cost8 赤/パンクハザード/海軍) /
EB02-052 (cost10 黄/空島)。 いずれも 黒麦わら では無い ので
「黒 麦わらの一味」 filter の 対象にはならず、 gate 判定のみに使える。
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


def _state(repo, leader_id="OP01-001", overlay=None, human_idx=None,
           opp_leader_id="OP01-001"):
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


# 高コスト gate 用の 非-黒麦わら 実カード
_GATE_C8 = "EB04-003"   # cost8 赤/パンクハザード/海軍
_GATE_C10 = "EB02-052"  # cost10 黄/空島


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_st14_wave178_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["ST14-002", "ST14-003", "ST14-004", "ST14-006", "ST14-007",
           "ST14-008", "ST14-009", "ST14-011", "ST14-012", "ST14-014"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  ST14-002 ウソップ: 【ドン!!×1】【アタック時】自コスト8以上キャラがいれば
#                     相手のコスト4以下キャラ1枚までを KO
# --------------------------------------------------------------------------- #
def test_st14_002_usopp_attack_ko_ai():
    """【アタック時】相手のコスト4以下キャラ1枚を KO (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost1 (≤4)
    opp.characters = [victim]

    eff = next(e for e in overlay.get("ST14-002").effects
               if e["when"] == "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST14-002"), sickness=False))

    assert victim not in opp.characters, "相手のコスト4以下キャラが KO されていない"


def test_st14_002_usopp_attack_ko_human_pick():
    """人間 + 相手のコスト4以下キャラ 複数 → target_pick modal が立ち resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    opp.characters = [a, b]

    eff = next(e for e in overlay.get("ST14-002").effects
               if e["when"] == "on_attack")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST14-002"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [b_idx])
        guard += 1
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  ST14-003 サンジ: 【登場時】自コスト6以上キャラがいれば 相手のコスト5以下キャラ1枚 KO
# --------------------------------------------------------------------------- #
def test_st14_003_sanji_on_play_ko_ai():
    """【登場時】相手のコスト5以下キャラ1枚を KO (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    gate = InPlay.of(repo.get(_GATE_C8), sickness=False)  # cost8 (≥6) gate
    me.characters = [gate]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 (≤5)
    opp.characters = [victim]

    eff = next(e for e in overlay.get("ST14-003").effects
               if e["when"] == "on_play")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST14-003"), sickness=False))

    assert victim not in opp.characters, "相手のコスト5以下キャラが KO されていない"


def test_st14_003_sanji_on_play_ko_human_pick():
    """人間 + 相手のコスト5以下キャラ 複数 → target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(_GATE_C8), sickness=False)]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)
    b = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [a, b]

    eff = next(e for e in overlay.get("ST14-003").effects
               if e["when"] == "on_play")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST14-003"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    assert len(st.pending_choice.get("candidates", [])) == 2


# --------------------------------------------------------------------------- #
#  ST14-004 ジンベエ: 【起動メイン】【ターン1回】自黒麦わらキャラ1枚までを
#                     次の相手ターン終了時まで コスト+2
# --------------------------------------------------------------------------- #
def test_st14_004_jinbe_activate_main_cost_plus_ai():
    """起動メイン: 自黒麦わらキャラ1枚のコストを +2 (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    jinbe = InPlay.of(repo.get("ST14-004"), sickness=False)
    target = InPlay.of(repo.get("ST14-003"), sickness=False)  # 黒 麦わらの一味 cost5
    me.characters = [jinbe, target]

    cost_before = target.base_cost
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST14-004"]
    assert len(opts) == 1, \
        f"ST14-004 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert target.base_cost == cost_before + 2, \
        f"黒麦わらキャラの コスト +2 が反映されていない: {target.base_cost} (before {cost_before})"


def test_st14_004_jinbe_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    jinbe = InPlay.of(repo.get("ST14-004"), sickness=False)
    me.characters = [jinbe, InPlay.of(repo.get("ST14-003"), sickness=False)]

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST14-004"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST14-004"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


def test_st14_004_jinbe_activate_main_human_pick():
    """人間 + 自黒麦わらキャラ 複数 → target_pick modal が立ち resolve で +2。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    jinbe = InPlay.of(repo.get("ST14-004"), sickness=False)
    t1 = InPlay.of(repo.get("ST14-003"), sickness=False)  # 黒 麦わら
    t2 = InPlay.of(repo.get("ST14-002"), sickness=False)  # 黒 麦わら
    me.characters = [jinbe, t1, t2]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST14-004"]
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (黒麦わら2体) が 2 件でない: {len(cands)}"

    t2_idx = next(i for i, c in enumerate(cands) if c["iid"] == t2.instance_id)
    t2_before = t2.base_cost
    resolve_pending_choice(st, [t2_idx])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [t2_idx])
        guard += 1
    assert t2.base_cost == t2_before + 2, "人間が選んだキャラの コスト +2 が反映されていない"


# --------------------------------------------------------------------------- #
#  ST14-006 ナミ: 【ブロッカー】【登場時】自コスト8以上キャラがいて 手札6枚以下なら 1ドロー
# --------------------------------------------------------------------------- #
def test_st14_006_nami_on_play_draw():
    """【登場時】(自cost8以上 + 手札6以下 gate) カード1枚を引く。 対象選択なし。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("OP01-013")] * 5

    eff = next(e for e in overlay.get("ST14-006").effects
               if e["when"] == "on_play")
    ifc = eff.get("if", {})
    assert ifc.get("self_hand_count_le") == 6, "overlay の 手札6以下 gate が無い"
    assert "self_chara_filtered_count_ge" in ifc, "overlay の コスト8以上 gate が無い"

    hand_before = len(me.hand)
    deck_before = len(me.deck)
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST14-006"), sickness=False))
    assert len(me.hand) == hand_before + 1, "登場時の 1ドローが起きていない"
    assert len(me.deck) == deck_before - 1, "ドロー分デッキが1枚減るべき"


# --------------------------------------------------------------------------- #
#  ST14-007 ニコ・ロビン: 【登場時】/【アタック時】自コスト8以上キャラがいれば
#                        相手キャラ1枚までを このターン中 コスト-5
# --------------------------------------------------------------------------- #
def test_st14_007_robin_cost_minus_ai():
    """【アタック時】相手キャラ1枚を コスト-5 (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(_GATE_C10), sickness=False)]  # cost10 gate
    victim = InPlay.of(repo.get(_GATE_C8), sickness=False)  # cost8 victim
    opp.characters = [victim]

    cost_before = victim.base_cost
    eff = next(e for e in overlay.get("ST14-007").effects
               if e["when"] == "on_attack")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST14-007"), sickness=False))
    assert victim.base_cost == cost_before - 5, \
        f"相手キャラの コスト-5 が反映されていない: {victim.base_cost} (before {cost_before})"


def test_st14_007_robin_cost_minus_human_pick():
    """人間 + 相手キャラ 複数 → target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(_GATE_C10), sickness=False)]
    x = InPlay.of(repo.get("OP01-016"), sickness=False)
    y = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [x, y]

    eff = next(e for e in overlay.get("ST14-007").effects
               if e["when"] == "on_attack")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST14-007"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    assert len(st.pending_choice.get("candidates", [])) == 2


# --------------------------------------------------------------------------- #
#  ST14-008 ハレダス: 【起動メイン】このキャラをレスト → 自黒麦わらキャラ1枚 コスト+2、
#                     その後 自コスト8以上キャラがいれば 1ドロー + 手札1捨て
# --------------------------------------------------------------------------- #
def test_st14_008_haredas_activate_main_ai():
    """起動メイン: 自レスト → 黒麦わらキャラ コスト+2 → cost8以上gateで 1ドロー+1捨て。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    haredas = InPlay.of(repo.get("ST14-008"), sickness=False)
    target = InPlay.of(repo.get("ST14-003"), sickness=False)   # 黒 麦わら cost5
    gate = InPlay.of(repo.get(_GATE_C8), sickness=False)       # cost8 gate (非-黒麦わら)
    me.characters = [haredas, target, gate]
    me.hand = [repo.get("OP01-013")]
    me.deck = [repo.get("OP01-016")] * 5

    cost_before = target.base_cost
    hand_before = len(me.hand)
    deck_before = len(me.deck)
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST14-008"]
    assert len(opts) == 1, \
        f"ST14-008 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert haredas.rested is True, "起動メインコストで ハレダス がレストされるべき"
    assert target.base_cost == cost_before + 2, \
        f"黒麦わらキャラの コスト+2 が反映されていない: {target.base_cost}"
    # 1 ドロー + 1 捨て = 手札 net ±0、 デッキ -1
    assert len(me.hand) == hand_before, \
        f"1ドロー+1捨てで 手札 net ±0 のはず: {len(me.hand)} (before {hand_before})"
    assert len(me.deck) == deck_before - 1, "1ドローで デッキが1枚減るべき"


# --------------------------------------------------------------------------- #
#  ST14-009 フランキー: 【ドン!!×1】【相手のターン中】自コスト6以上キャラがいれば
#                       このキャラは相手効果で KO されず パワー+2000
# --------------------------------------------------------------------------- #
def test_st14_009_franky_static_immune_and_pump_opp_turn():
    """静的効果 (on_attached_don n=1、 相手ターン + 自cost6以上gate):
    KO 耐性 + パワー+2000。 evaluate_static_effects で検証。
    効果 +2000 は 「gate 成立時 vs gate 不成立時」 の power 差分で isolate する
    (= DON+1000 は両状態で同じなので相殺され、 純粋な効果分だけ残る)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    franky_def = repo.get("ST14-009")  # power 6000
    franky = InPlay.of(franky_def, sickness=False)
    gate = InPlay.of(repo.get(_GATE_C8), sickness=False)  # cost8 (≥6) → gate 成立
    me.characters = [franky, gate]
    st.turn_player_idx = 1  # 相手ターン (= opp_turn 条件成立)
    franky.attached_dons = 1  # n=1 ゲート成立
    evaluate_static_effects(st, overlay)
    power_with_gate = franky.power
    immune = franky.ko_immune_until_turn_end

    # gate 不成立 (自cost6以上キャラ無し) の同条件を別 state で作る
    st2 = _state(repo, overlay=overlay)
    me2 = st2.players[0]
    franky2 = InPlay.of(franky_def, sickness=False)
    me2.characters = [franky2]  # gate 無し
    st2.turn_player_idx = 1
    franky2.attached_dons = 1
    evaluate_static_effects(st2, overlay)
    power_without_gate = franky2.power

    assert power_with_gate - power_without_gate == 2000, \
        f"相手ターンの効果 +2000 が反映されていない: " \
        f"with={power_with_gate} without={power_without_gate}"
    assert immune is True, "相手効果 KO 耐性が立っていない"


def test_st14_009_franky_static_off_self_turn():
    """【相手のターン中】条件 → 自ターン中は 不成立。 効果 pump/immune ともに乗らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    franky_def = repo.get("ST14-009")
    franky = InPlay.of(franky_def, sickness=False)
    me.characters = [franky, InPlay.of(repo.get(_GATE_C8), sickness=False)]
    st.turn_player_idx = 0  # 自ターン → opp_turn False
    franky.attached_dons = 1

    evaluate_static_effects(st, overlay)
    # 自ターン中は DON+1000 が乗る (owner turn) が、 効果 +2000 は乗らない
    assert franky.power == franky_def.power + 1000, \
        f"自ターンで効果 pump が乗ってはいけない: {franky.power} (base {franky_def.power})"
    assert franky.ko_immune_until_turn_end is False, \
        "自ターン中は KO 耐性が立ってはいけない"


# --------------------------------------------------------------------------- #
#  ST14-011 ヘラクレス: 【起動メイン】このキャラをレスト → 自黒麦わらキャラ1枚 コスト+2
# --------------------------------------------------------------------------- #
def test_st14_011_heracles_activate_main_cost_plus_ai():
    """起動メイン: 自レスト → 黒麦わらキャラ1枚 コスト+2 (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    heracles = InPlay.of(repo.get("ST14-011"), sickness=False)
    target = InPlay.of(repo.get("ST14-003"), sickness=False)  # 黒 麦わら cost5
    me.characters = [heracles, target]

    cost_before = target.base_cost
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST14-011"]
    assert len(opts) == 1, \
        f"ST14-011 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert heracles.rested is True, "起動メインコストで ヘラクレス がレストされるべき"
    assert target.base_cost == cost_before + 2, \
        f"黒麦わらキャラの コスト+2 が反映されていない: {target.base_cost}"


def test_st14_011_heracles_activate_main_human_pick():
    """人間 + 自黒麦わらキャラ 複数 → target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    heracles = InPlay.of(repo.get("ST14-011"), sickness=False)
    t1 = InPlay.of(repo.get("ST14-003"), sickness=False)
    t2 = InPlay.of(repo.get("ST14-002"), sickness=False)
    me.characters = [heracles, t1, t2]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST14-011"]
    fire_activate_main(st, me, opp, *opts[0])
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    assert len(st.pending_choice.get("candidates", [])) == 2


# --------------------------------------------------------------------------- #
#  ST14-012 モンキー・D・ルフィ: 自コスト10以上キャラがいれば このキャラは【速攻】を得る
# --------------------------------------------------------------------------- #
def test_st14_012_luffy_static_rush_with_cost10():
    """静的効果 (on_attached_don n=0、 自cost10以上gate): このキャラ(自身)が【速攻】を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("ST14-012"), sickness=False)
    gate = InPlay.of(repo.get(_GATE_C10), sickness=False)  # cost10 (≥10)
    me.characters = [luffy, gate]

    evaluate_static_effects(st, overlay)
    assert luffy.is_rush_now is True, "自cost10以上キャラがいるのに【速攻】を得ていない"


def test_st14_012_luffy_static_no_rush_without_cost10():
    """自cost10以上キャラがいなければ【速攻】は付かない (gate 不成立)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("ST14-012"), sickness=False)
    me.characters = [luffy]  # 他にキャラ無し

    evaluate_static_effects(st, overlay)
    assert luffy.is_rush_now is False, \
        "cost10以上キャラがいないのに【速攻】が付いてはいけない"


# --------------------------------------------------------------------------- #
#  ST14-014 ゴムゴムの巨人の回転弾 (EVENT):
#    【カウンター】コスト8以上キャラがいれば 自リーダーかキャラ1枚 +3000
#    【トリガー】自トラッシュから コスト2以下キャラ1枚までを 手札に加える
# --------------------------------------------------------------------------- #
def test_st14_014_counter_pump_ai():
    """【カウンター】自リーダーか キャラ1枚を +3000 (AI 自動 = リーダー既定)。
    候補を リーダー のみ にして 対象を一意化 (do 直接発火なので cost8 gate は不要)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    eff = next(e for e in overlay.get("ST14-014").effects
               if e["when"] == "counter")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    assert me.leader.power == power_before + 3000, \
        f"カウンターの +3000 が自リーダーに反映されていない: {me.leader.power}"


def test_st14_014_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +3000 の対象選択 target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [friend]

    eff = next(e for e in overlay.get("ST14-014").effects
               if e["when"] == "counter")
    execute_effect(eff["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands)
                      if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert friend.power == friend_before + 3000, \
        "人間が選んだキャラに +3000 が反映されていない"


def test_st14_014_trigger_trash_to_hand_ai():
    """【トリガー】自トラッシュから コスト2以下キャラ1枚までを 手札に加える (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    target = repo.get("OP01-016")  # ナミ cost1 (≤2)
    me.trash = [target]
    me.hand = []

    eff = next(e for e in overlay.get("ST14-014").effects
               if e["when"] == "trigger")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    assert any(c.card_id == "OP01-016" for c in me.hand), \
        "トラッシュから コスト2以下キャラが手札に加わっていない"
    assert not any(c.card_id == "OP01-016" for c in me.trash), \
        "手札に加えたカードがトラッシュに残っている"
