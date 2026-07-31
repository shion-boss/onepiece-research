# -*- coding: utf-8 -*-
"""プロモ (P-*) 効果 回帰テスト バックフィル (自動生成 wave 156):
P-017 / P-019 / P-020 / P-024 / P-025 /
P-026 / P-027 / P-030 / P-031 / P-032 の 10 枚。

目的 (= test_backfill_auto_001〜155.py と同一方針):
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
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------- #
#  効果の薄い (= 素材用) カード。
# --------------------------------------------------------------------------- #
NAMI = "OP01-016"           # ナミ (麦わらの一味, cost1 power2000) フィラー / 相手キャラ
COST2 = "OP01-013"          # ウソップ (麦わらの一味, cost2 power3000) フィラー
BIG = "OP02-004"            # エドワード・ニューゲート (cost9 power10000) 高コスト・高パワー
NEUTRAL_LEADER = "OP01-001"  # ロロノア・ゾロ (LEADER)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, turn=0,
           opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 MAIN / turn_number=3。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(COST2)] * 30
    p1.deck = [repo.get(COST2)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _eff(overlay, cid, when):
    """指定 card_id の overlay から when 一致の効果 (先頭) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    assert matches, f"{cid} に when={when} の効果がない"
    return matches[0]


def _drain(st, picks):
    """resolve 後続の連鎖 modal を流す (guard 付き)。"""
    guard = 0
    while st.pending_choice is not None and guard < 6:
        resolve_pending_choice(st, picks)
        guard += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave156_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["P-017", "P-019", "P-020", "P-024", "P-025",
           "P-026", "P-027", "P-030", "P-031", "P-032"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  P-017 トラファルガー・ロー: 【登場時】相手のキャラ1枚までを、このターン中、-2000
# --------------------------------------------------------------------------- #
def test_p017_law_on_play_debuff_ai():
    """【登場時】 AI: 相手キャラ1体を このターン中 パワー-2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(COST2), sickness=False)  # power 3000
    opp.characters = [victim]

    power_before = victim.power
    for prim in _eff(overlay, "P-017", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-017"), sickness=True))

    assert victim.power == power_before - 2000, \
        f"登場時 相手 -2000 が反映されていない: {victim.power} (before {power_before})"


def test_p017_law_on_play_debuff_human_pick():
    """人間 + 相手キャラ 複数 → target_pick modal が立ち resolve で 1 体に -2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(NAMI), sickness=False)   # power 2000
    b = InPlay.of(repo.get(COST2), sickness=False)  # power 3000
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "P-017", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("P-017"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert b.power == b_before - 2000, "人間が選んだ相手キャラに -2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  P-019 ベポ: 【ドン!!×1】【アタック時】相手のパワー3000以下のキャラ1枚までを KO
# --------------------------------------------------------------------------- #
def test_p019_bepo_on_attack_ko_power_le_3000_ai():
    """【アタック時】(ドン1ゲート) 相手のパワー3000以下キャラ1体を KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(COST2), sickness=False)  # power 3000 (= 対象)
    opp.characters = [victim]

    eff = _eff(overlay, "P-019", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-019"), sickness=False))

    assert victim not in opp.characters, "相手のパワー3000以下キャラが KO されていない"


def test_p019_bepo_on_attack_high_power_survives():
    """相手キャラのパワーが 3000 超なら 対象外 → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    tough = InPlay.of(repo.get(BIG), sickness=False)  # power 10000 (対象外)
    opp.characters = [tough]

    for prim in _eff(overlay, "P-019", "on_attack")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-019"), sickness=False))

    assert tough in opp.characters, "パワー3000超のキャラが KO されてはいけない (対象外)"


def test_p019_bepo_on_attack_ko_human_pick():
    """人間 + 相手のパワー3000以下キャラ 複数 → target_pick modal が立ち resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(NAMI), sickness=False)   # power 2000
    b = InPlay.of(repo.get(COST2), sickness=False)  # power 3000
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "P-019", "on_attack")["do"][0], st, me, opp,
                   InPlay.of(repo.get("P-019"), sickness=False))

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
#  P-020 ヘルメッポ: 【登場時】自分のリーダーかキャラ1枚までを、このターン中、+1000
# --------------------------------------------------------------------------- #
def test_p020_helmeppo_on_play_pump_ai():
    """【登場時】 AI: 自リーダー (既定) に このターン中 パワー+1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    for prim in _eff(overlay, "P-020", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-020"), sickness=True))

    assert me.leader.power == power_before + 1000, \
        f"登場時 自リーダー +1000 が反映されていない: {me.leader.power} (before {power_before})"


def test_p020_helmeppo_on_play_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → target_pick modal が立ち resolve で キャラに +1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(COST2), sickness=False)
    me.characters = [friend]

    execute_effect(_eff(overlay, "P-020", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("P-020"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert friend.power == friend_before + 1000, \
        "人間が選んだキャラに +1000 が反映されていない"


# --------------------------------------------------------------------------- #
#  P-024 海賊王に!!!おれはなるっ!!!! (EVENT):
#    【メイン】自分のリーダーは このターン中 自分のキャラ1枚につき +1000
#    【トリガー】自分のリーダーかキャラ1枚までを このターン中 +1000
# --------------------------------------------------------------------------- #
def test_p024_main_leader_pump_per_field_ai():
    """【メイン】自リーダーは 自キャラ数 × +1000。 キャラ3体 → +3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(NAMI), sickness=False) for _ in range(3)]

    power_before = me.leader.power
    for prim in _eff(overlay, "P-024", "main")["do"]:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 3000, \
        f"メイン: 自キャラ3体で +3000 が反映されていない: {me.leader.power} (before {power_before})"


def test_p024_main_leader_pump_zero_field():
    """【メイン】自キャラ 0 体なら +0 (= キャラ数依存の scaling)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = []

    power_before = me.leader.power
    for prim in _eff(overlay, "P-024", "main")["do"]:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before, \
        f"自キャラ0体では +0 のはず: {me.leader.power} (before {power_before})"


def test_p024_trigger_pump_ai_no_crash():
    """【トリガー】 AI: 自リーダー (既定) に +1000。 crash せず反映。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    for prim in _eff(overlay, "P-024", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])

    assert me.leader.power == power_before + 1000, \
        f"トリガー: 自リーダー +1000 が反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  P-025 スモーカー: 【ドン!!×1】属性(特)を持たないキャラとのバトルでKOされない (static)
# --------------------------------------------------------------------------- #
def test_p025_smoker_static_immune_non_toku_with_don():
    """静的 (on_attached_don n=1): ドン1付与で「属性(特)を持たない」バトルKO免疫を得る
    (= ko_immune_battle_attributes_not_in に「特」が入る)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    smoker = InPlay.of(repo.get("P-025"), sickness=False)
    smoker.attached_dons = 1  # ドン!!×1 ゲート成立
    me.characters = [smoker]

    evaluate_static_effects(st, overlay)
    assert "特" in smoker.ko_immune_battle_attributes_not_in, \
        f"属性(特)非保持へのバトルKO免疫が付与されていない: {smoker.ko_immune_battle_attributes_not_in}"


def test_p025_smoker_no_immune_without_don():
    """ドン!!が付いていなければ (n=1 ゲート不成立) 免疫は付かない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    smoker = InPlay.of(repo.get("P-025"), sickness=False)
    smoker.attached_dons = 0  # ゲート不成立
    me.characters = [smoker]

    evaluate_static_effects(st, overlay)
    assert "特" not in smoker.ko_immune_battle_attributes_not_in, \
        "ドン無しでバトルKO免疫が付いてはいけない (ドンゲート)"


# --------------------------------------------------------------------------- #
#  P-026 モーガン: 【アタック時】相手のキャラ1枚までを、このターン中、コスト-3
# --------------------------------------------------------------------------- #
def test_p026_morgan_on_attack_cost_minus_ai():
    """【アタック時】 AI: 相手キャラ1体を このターン中 コスト-3。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(BIG), sickness=False)  # cost 9
    opp.characters = [victim]

    cost_before = victim.base_cost
    for prim in _eff(overlay, "P-026", "on_attack")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-026"), sickness=False))

    assert victim.cost_minus_until_turn_end == 3, \
        f"コスト-3 が反映されていない: cost_minus={victim.cost_minus_until_turn_end}"
    assert victim.base_cost == cost_before - 3, \
        f"base_cost が -3 されていない: {victim.base_cost} (before {cost_before})"


def test_p026_morgan_on_attack_cost_minus_human_pick():
    """人間 + 相手キャラ 複数 → target_pick modal が立ち resolve で 1 体に コスト-3。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(BIG), sickness=False)    # cost 9
    b = InPlay.of(repo.get(COST2), sickness=False)  # cost 2
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "P-026", "on_attack")["do"][0], st, me, opp,
                   InPlay.of(repo.get("P-026"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    a_before = a.base_cost
    resolve_pending_choice(st, [a_idx])
    _drain(st, [a_idx])
    assert a.base_cost == a_before - 3, \
        "人間が選んだ相手キャラに コスト-3 が反映されていない"


# --------------------------------------------------------------------------- #
#  P-027 フランキー将軍:
#    【相手のターン中】自分の元々のパワー3000以下のキャラすべてを、パワー+1000 (static)
# --------------------------------------------------------------------------- #
def test_p027_franky_static_pump_low_power_on_opp_turn():
    """相手ターン中: 自分の元々パワー3000以下キャラすべてが +1000。 高パワーキャラは対象外。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, turn=1)  # 相手ターン (P0 視点で opp_turn)
    me, opp = st.players[0], st.players[1]
    franky = InPlay.of(repo.get("P-027"), sickness=False)  # power 4000 (対象外)
    low = InPlay.of(repo.get(NAMI), sickness=False)        # 元々 power 2000 (対象)
    tough = InPlay.of(repo.get(BIG), sickness=False)       # 元々 power 10000 (対象外)
    me.characters = [franky, low, tough]

    evaluate_static_effects(st, overlay)

    assert low.power == 2000 + 1000, \
        f"相手ターン: 元々P3000以下キャラに +1000 が乗っていない: {low.power}"
    assert tough.power == 10000, \
        f"元々P3000超キャラに pump が乗ってはいけない: {tough.power}"


def test_p027_franky_static_no_pump_on_own_turn():
    """自分のターン中は【相手のターン中】条件が不成立 → pump なし。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, turn=0)  # 自ターン
    me, opp = st.players[0], st.players[1]
    franky = InPlay.of(repo.get("P-027"), sickness=False)
    low = InPlay.of(repo.get(NAMI), sickness=False)  # 元々 power 2000
    me.characters = [franky, low]

    evaluate_static_effects(st, overlay)
    assert low.power == 2000, \
        f"自ターンで pump が乗ってはいけない: {low.power}"


# --------------------------------------------------------------------------- #
#  P-030 ジンベエ: 【KO時】コスト3以下のキャラ1枚までを、持ち主のデッキの下に置く
# --------------------------------------------------------------------------- #
def test_p030_jinbe_on_ko_return_cost_le_3_ai():
    """【KO時】 AI: 相手のコスト3以下キャラ1体を 持ち主のデッキ下へ (= 除去優先)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    jinbe = InPlay.of(repo.get("P-030"), sickness=False)
    me.characters = [jinbe]
    victim = InPlay.of(repo.get(COST2), sickness=False)  # cost 2 (= 対象)
    opp.characters = [victim]
    deck_before = len(opp.deck)

    for prim in _eff(overlay, "P-030", "on_ko")["do"]:
        execute_effect(prim, st, me, opp, jinbe)
    _drain(st, [0])

    assert victim not in opp.characters, "コスト3以下の相手キャラがデッキ下に戻っていない"
    assert len(opp.deck) == deck_before + 1, "戻したキャラが持ち主のデッキに加わっていない"
    assert opp.deck[-1].card_id == COST2, "デッキ「下」(末尾) に置かれていない"


def test_p030_jinbe_on_ko_high_cost_untouched():
    """相手キャラが コスト3超のみなら 対象外 → 戻らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    jinbe = InPlay.of(repo.get("P-030"), sickness=False)
    me.characters = [jinbe]
    tough = InPlay.of(repo.get(BIG), sickness=False)  # cost 9 (= 対象外)
    opp.characters = [tough]

    for prim in _eff(overlay, "P-030", "on_ko")["do"]:
        execute_effect(prim, st, me, opp, jinbe)
    _drain(st, [0])

    assert tough in opp.characters, "コスト3超のキャラが戻ってはいけない (対象外)"


def test_p030_jinbe_on_ko_return_human_pick():
    """人間 + 両陣営コスト3以下キャラ 複数 → target_pick modal が立ち resolve で 1 体を戻す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    jinbe = InPlay.of(repo.get("P-030"), sickness=False)
    my_small = InPlay.of(repo.get(NAMI), sickness=False)  # cost 1 (自)
    me.characters = [jinbe, my_small]
    opp_small = InPlay.of(repo.get(COST2), sickness=False)  # cost 2 (相手)
    opp.characters = [opp_small]

    execute_effect(_eff(overlay, "P-030", "on_ko")["do"][0], st, me, opp, jinbe)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (両陣営) が 2 件でない: {len(cands)}"

    opp_idx = next(i for i, c in enumerate(cands) if c["iid"] == opp_small.instance_id)
    resolve_pending_choice(st, [opp_idx])
    _drain(st, [opp_idx])
    assert opp_small not in opp.characters, "人間が選んだ相手キャラがデッキ下に戻っていない"


# --------------------------------------------------------------------------- #
#  P-031 ウタ: 【登場時】ドン!!デッキからドン!!1枚までを、レストで追加する
# --------------------------------------------------------------------------- #
def test_p031_uta_on_play_add_rested_don_ai():
    """【登場時】 ドンデッキからレストドン1枚をコストエリアに追加 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]

    rested_before = me.don_rested
    remaining_before = me.don_remaining_in_deck
    assert remaining_before >= 1, "テスト前提: ドンデッキに残りがある"
    for prim in _eff(overlay, "P-031", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-031"), sickness=True))

    assert me.don_rested == rested_before + 1, "レストドンが1枚追加されていない"
    assert me.don_remaining_in_deck == remaining_before - 1, "ドンデッキが1枚減っていない"


# --------------------------------------------------------------------------- #
#  P-032 センゴク: 【ドン!!×1】【自分のターン中】相手のキャラすべてを、コスト-2 (static)
# --------------------------------------------------------------------------- #
def test_p032_sengoku_static_opp_cost_minus_on_own_turn():
    """自分のターン中 (ドン1付与): 相手キャラすべてが コスト-2。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, turn=0)  # 自ターン
    me, opp = st.players[0], st.players[1]
    sengoku = InPlay.of(repo.get("P-032"), sickness=False)
    sengoku.attached_dons = 1  # ドン!!×1 ゲート成立
    me.characters = [sengoku]
    a = InPlay.of(repo.get(BIG), sickness=False)    # cost 9 → 7
    b = InPlay.of(repo.get(COST2), sickness=False)  # cost 2 → 0
    opp.characters = [a, b]

    evaluate_static_effects(st, overlay)
    assert a.base_cost == 9 - 2, f"相手キャラ (cost9) が -2 されていない: {a.base_cost}"
    assert b.base_cost == max(0, 2 - 2), f"相手キャラ (cost2) が -2 されていない: {b.base_cost}"


def test_p032_sengoku_static_no_effect_on_opp_turn():
    """相手ターン中は【自分のターン中】条件が不成立 → コスト修正なし。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, turn=1)  # 相手ターン
    me, opp = st.players[0], st.players[1]
    sengoku = InPlay.of(repo.get("P-032"), sickness=False)
    sengoku.attached_dons = 1
    me.characters = [sengoku]
    a = InPlay.of(repo.get(BIG), sickness=False)  # cost 9
    opp.characters = [a]

    evaluate_static_effects(st, overlay)
    assert a.base_cost == 9, f"相手ターンでコスト修正が乗ってはいけない: {a.base_cost}"
