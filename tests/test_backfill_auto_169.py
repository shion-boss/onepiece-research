# -*- coding: utf-8 -*-
"""ST05 / ST06 弾 効果 回帰テスト バックフィル (自動生成 wave 169):
ST05-017 / ST06-002 / ST06-004 / ST06-005 / ST06-006 / ST06-010 /
ST06-012 / ST06-014 / ST06-015 / ST06-016 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_001.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 任意コスト を 持つカードは 人間 actor で pending_choice が
      正しい kind + 候補で立ち、 resolve_pending_choice で解決できる (= 人間が選べる)
  (3) 同じ効果を AI 文脈 (human_player_idx=None) で回しても crash せず自動解決する
      (= AI が選べる)

補足 (このwaveのカードが要求するゲーム状態):
  - OPTCG のカード DB に「印刷コスト 0」のキャラは存在しないため、 コスト0 判定
    (ST06-002 の KO / ST06-004 の条件) は cost_minus_until_turn_end で実効コストを 0 に
    落として再現する (= 実戦の黒コントロールの動き)。
  - ST05-017 の《FILM》対象は、 テスト用リーダー ST05-001 シャンクス自身が特徴《FILM》を
    持つため、 追加のキャラを置かなくても対象が成立する。
"""

from __future__ import annotations

import dataclasses
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


def _eff(overlay, cid, when):
    return next(e for e in overlay.get(cid).effects if e["when"] == when)


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave169_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["ST05-017", "ST06-002", "ST06-004", "ST06-005", "ST06-006",
           "ST06-010", "ST06-012", "ST06-014", "ST06-015", "ST06-016"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  ST05-017 鎧合体 (EVENT 紫 cost2):
#    【カウンター】自分の特徴《FILM》を持つ、リーダーかキャラ1枚までを、このバトル中、
#                 パワー+4000。そのカードがキャラの場合、そのキャラは、このターン中、KOされない。
#    【トリガー】ドン‼デッキからドン‼1枚までをアクティブで追加する。
# --------------------------------------------------------------------------- #
def test_st05_017_counter_pump_and_ko_immune_ai():
    """【カウンター】AI: 唯一の《FILM》対象 = 自リーダー(シャンクス)へ +4000 + KO耐性。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST05-001", overlay)  # シャンクス (FILM/四皇/赤髪海賊団)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    for prim in _eff(overlay, "ST05-017", "counter")["do"]:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 4000, \
        f"カウンターの +4000 が FILM リーダーに反映されていない: {me.leader.power}"
    assert me.leader.ko_immune_until_turn_end is True, \
        "FILM 対象に KO 耐性が付与されていない"


def test_st05_017_counter_pump_human_pick():
    """人間 + FILM リーダー + FILM キャラ の 2 候補 → target_pick modal → resolve で
    選んだキャラに +4000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST05-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    # 合成 FILM キャラ (DB に FILM キャラが無いため CardDef を replace で生成)
    film_def = dataclasses.replace(
        repo.get("OP01-016"), card_id="FILM-TEST", name="FILMテスト",
        features=("FILM",),
    )
    film = InPlay.of(film_def, sickness=False)
    me.characters = [film]

    execute_effect(_eff(overlay, "ST05-017", "counter")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+FILMキャラ) が 2 件でない: {len(cands)}"

    film_idx = next(i for i, c in enumerate(cands) if c["iid"] == film.instance_id)
    film_before = film.power
    resolve_pending_choice(st, [film_idx])
    assert film.power == film_before + 4000, \
        "人間が選んだ FILM キャラに +4000 が反映されていない"


def test_st05_017_trigger_add_don_ai():
    """【トリガー】デッキから ドン!! 1 枚を アクティブで追加する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST05-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 0
    me.don_rested = 0

    for prim in _eff(overlay, "ST05-017", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)

    assert me.don_active == 1, \
        f"トリガーで アクティブドンが1枚追加されていない: {me.don_active}"


# --------------------------------------------------------------------------- #
#  ST06-002 コビー (CHARACTER 黒 cost1 power2000):
#    【登場時】自分の手札1枚を捨てることができる：相手のコスト0のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def _cost0_opp_victim(repo):
    """実効コスト 0 の相手キャラ (印刷 cost1 の ナミ を -1)。"""
    v = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    v.cost_minus_until_turn_end = 1  # base_cost -> 0
    return v


def test_st06_002_on_play_optional_ko_cost0_ai():
    """【登場時】AI: 手札1枚を捨て、 相手の実効コスト0キャラを KO する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]  # 捨てるコスト用
    victim = _cost0_opp_victim(repo)
    opp.characters = [victim]
    assert victim.base_cost == 0, "テスト前提: victim の実効コストが0でない"

    execute_effect(_eff(overlay, "ST06-002", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST06-002"), sickness=True))

    assert victim not in opp.characters, "相手の実効コスト0キャラが KO されていない"
    assert len(me.hand) == 0, "任意コストで手札1枚が捨てられるべき"


def test_st06_002_on_play_ko_excludes_nonzero_cost():
    """実効コストが 0 でない (= コスト1) キャラは対象外 → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 (減算なし)
    opp.characters = [victim]

    execute_effect(_eff(overlay, "ST06-002", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST06-002"), sickness=True))

    assert victim in opp.characters, "コスト0でないキャラが KO されてはいけない (対象外)"


def test_st06_002_on_play_human_optional_cost_then_ko():
    """人間: 任意コスト (= 「捨てることができる」) の optional_cost_confirm modal が立ち、
    承諾 → KO 対象の target_pick を解決すると相手コスト0キャラが KO される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]
    victim = _cost0_opp_victim(repo)
    opp.characters = [victim]

    execute_effect(_eff(overlay, "ST06-002", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST06-002"), sickness=True))
    assert st.pending_choice is not None, "人間 任意コストの確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾 (= 手札を捨てて発動)
    # 続く KO 対象選択 (単一候補) を解決
    guard = 0
    while st.pending_choice is not None and guard < 6:
        resolve_pending_choice(st, [0])
        guard += 1

    assert victim not in opp.characters, "人間承諾後 相手コスト0キャラが KO されていない"
    assert len(me.hand) == 0, "承諾後 手札1枚が捨てられるべき"


# --------------------------------------------------------------------------- #
#  ST06-004 スモーカー (CHARACTER 黒 cost5 power7000):
#    このキャラは効果でKOされない。
#    【ドン!!×1】コスト0のキャラがいる場合、このキャラは【ダブルアタック】を得る。
# --------------------------------------------------------------------------- #
def test_st06_004_double_attack_with_don_and_cost0():
    """ドン1付与 + 場に実効コスト0キャラ → static_granted_keywords に ダブルアタック。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    smoker = InPlay.of(repo.get("ST06-004"), sickness=False)
    smoker.attached_dons = 1
    zero = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    zero.cost_minus_until_turn_end = 1  # base_cost -> 0
    me.characters = [smoker, zero]

    evaluate_static_effects(st, overlay)
    assert "ダブルアタック" in smoker.static_granted_keywords, \
        f"ドン1 + コスト0キャラで ダブルアタック が付与されていない: {smoker.static_granted_keywords}"


def test_st06_004_no_double_attack_without_cost0():
    """コスト0のキャラがいなければ (条件不成立) → ダブルアタックを得ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    smoker = InPlay.of(repo.get("ST06-004"), sickness=False)
    smoker.attached_dons = 1
    me.characters = [smoker]  # 自身 cost5 のみ = コスト0キャラ不在

    evaluate_static_effects(st, overlay)
    assert "ダブルアタック" not in smoker.static_granted_keywords, \
        "コスト0キャラ不在で ダブルアタック が付与されてはいけない"


def test_st06_004_no_double_attack_without_don():
    """ドン!!×1 が付いていなければ → ダブルアタックを得ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    smoker = InPlay.of(repo.get("ST06-004"), sickness=False)
    smoker.attached_dons = 0  # ドン未付与
    zero = InPlay.of(repo.get("OP01-016"), sickness=False)
    zero.cost_minus_until_turn_end = 1
    me.characters = [smoker, zero]

    evaluate_static_effects(st, overlay)
    assert "ダブルアタック" not in smoker.static_granted_keywords, \
        "ドン未付与で ダブルアタック が付与されてはいけない"


# --------------------------------------------------------------------------- #
#  ST06-005 センゴク (CHARACTER 黒 cost5 power6000):
#    【アタック時】相手のキャラ1枚までを、このターン中、コスト-4。
# --------------------------------------------------------------------------- #
def test_st06_005_on_attack_cost_minus_ai():
    """【アタック時】AI: 相手キャラ1枚を このターン中 コスト-4 (cost6 → 2)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-040"), sickness=False)  # cost6
    opp.characters = [victim]

    cost_before = victim.base_cost
    execute_effect(_eff(overlay, "ST06-005", "on_attack")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST06-005"), sickness=False))

    assert victim.base_cost == cost_before - 4, \
        f"アタック時 コスト-4 が反映されていない: {victim.base_cost} (before {cost_before})"


def test_st06_005_on_attack_cost_minus_human_pick():
    """人間 + 相手キャラ複数 → cost_minus target_pick modal → resolve で選んだ1体に -4。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-040"), sickness=False)   # cost6
    b = InPlay.of(repo.get("OP01-110"), sickness=False)   # cost6
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "ST06-005", "on_attack")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST06-005"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で cost_minus modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    assert st.pending_choice.get("primitive_kind") == "cost_minus", \
        "primitive_kind が cost_minus でない"

    b_idx = next(i for i, c in enumerate(st.pending_choice["candidates"])
                 if c["iid"] == b.instance_id)
    b_before = b.base_cost
    resolve_pending_choice(st, [b_idx])
    assert b.base_cost == b_before - 4, "人間が選んだ相手キャラに -4 が反映されていない"
    assert a.base_cost == repo.get("OP01-040").cost, "選ばなかったキャラのコストは不変であるべき"


# --------------------------------------------------------------------------- #
#  ST06-006 たしぎ (CHARACTER 黒 cost3 power4000):
#    【起動メイン】このキャラをレストにできる：相手のキャラ1枚までを、このターン中、コスト-2。
# --------------------------------------------------------------------------- #
def test_st06_006_activate_main_cost_minus_ai():
    """起動メイン: 自身をレスト (コスト) → 相手キャラ1枚を コスト-2 (cost6 → 4)。 AI 自動。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    tashigi = InPlay.of(repo.get("ST06-006"), sickness=False)
    me.characters = [tashigi]
    victim = InPlay.of(repo.get("OP01-040"), sickness=False)  # cost6
    opp.characters = [victim]

    cost_before = victim.base_cost
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST06-006"]
    assert len(opts) == 1, f"ST06-006 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert victim.base_cost == cost_before - 2, \
        f"起動メイン コスト-2 が反映されていない: {victim.base_cost} (before {cost_before})"
    assert tashigi.rested is True, "起動メインコストで たしぎ がレストされるべき"


def test_st06_006_activate_main_cost_minus_human_pick():
    """人間 + 相手キャラ複数 → cost_minus target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    tashigi = InPlay.of(repo.get("ST06-006"), sickness=False)
    me.characters = [tashigi]
    a = InPlay.of(repo.get("OP01-040"), sickness=False)  # cost6
    b = InPlay.of(repo.get("OP01-110"), sickness=False)  # cost6
    opp.characters = [a, b]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST06-006"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間 + 複数候補で cost_minus modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"

    b_idx = next(i for i, c in enumerate(st.pending_choice["candidates"])
                 if c["iid"] == b.instance_id)
    b_before = b.base_cost
    resolve_pending_choice(st, [b_idx])
    assert b.base_cost == b_before - 2, "人間が選んだ相手キャラに -2 が反映されていない"


# --------------------------------------------------------------------------- #
#  ST06-010 ヘルメッポ (CHARACTER 黒 cost2 power3000):
#    【登場時】相手のキャラ1枚までを、このターン中、コスト-3。
# --------------------------------------------------------------------------- #
def test_st06_010_on_play_cost_minus_ai():
    """【登場時】AI: 相手キャラ1枚を コスト-3 (cost6 → 3)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-040"), sickness=False)  # cost6
    opp.characters = [victim]

    cost_before = victim.base_cost
    execute_effect(_eff(overlay, "ST06-010", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST06-010"), sickness=True))

    assert victim.base_cost == cost_before - 3, \
        f"登場時 コスト-3 が反映されていない: {victim.base_cost} (before {cost_before})"


def test_st06_010_on_play_cost_minus_human_pick():
    """人間 + 相手キャラ複数 → cost_minus target_pick modal → resolve で選んだ1体に -3。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-040"), sickness=False)  # cost6
    b = InPlay.of(repo.get("OP01-110"), sickness=False)  # cost6
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "ST06-010", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST06-010"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で cost_minus modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"

    b_idx = next(i for i, c in enumerate(st.pending_choice["candidates"])
                 if c["iid"] == b.instance_id)
    b_before = b.base_cost
    resolve_pending_choice(st, [b_idx])
    assert b.base_cost == b_before - 3, "人間が選んだ相手キャラに -3 が反映されていない"


# --------------------------------------------------------------------------- #
#  ST06-012 モンキー・D・ガープ (CHARACTER 黒 cost5 power6000):
#    【起動メイン】自分の手札1枚を捨て、このキャラをレストにできる：
#                 相手のコスト4以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_st06_012_activate_main_ko_cost4_ai():
    """起動メイン: 手札1捨て + 自レスト (コスト) → 相手コスト4以下キャラを KO。 AI 自動。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    garp = InPlay.of(repo.get("ST06-012"), sickness=False)
    me.characters = [garp]
    me.hand = [repo.get("OP01-013")]  # 捨てるコスト用
    victim = InPlay.of(repo.get("OP01-020"), sickness=False)  # cost2 (対象)
    opp.characters = [victim]

    hand_before = len(me.hand)
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST06-012"]
    assert len(opts) == 1, f"ST06-012 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert victim not in opp.characters, "相手のコスト4以下キャラが KO されていない"
    assert garp.rested is True, "起動メインコストで ガープ がレストされるべき"
    assert len(me.hand) == hand_before - 1, "起動メインコストで手札1枚が捨てられるべき"


def test_st06_012_activate_main_ko_high_cost_immune():
    """相手のコスト5以上キャラは KO 対象外 → KO されない (コスト4以下のみ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    garp = InPlay.of(repo.get("ST06-012"), sickness=False)
    me.characters = [garp]
    me.hand = [repo.get("OP01-013")]
    victim = InPlay.of(repo.get("OP01-040"), sickness=False)  # cost6 (対象外)
    opp.characters = [victim]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST06-012"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    assert victim in opp.characters, "コスト5以上キャラが KO されてはいけない (対象外)"


def test_st06_012_activate_main_ko_human_pick():
    """人間: 捨てるカード (activate_main_discard_pick) → KO 対象 (target_pick) の 2 段解決で
    選んだ相手コスト4以下キャラが KO される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    garp = InPlay.of(repo.get("ST06-012"), sickness=False)
    me.characters = [garp]
    me.hand = [repo.get("OP01-013"), repo.get("OP01-016")]
    a = InPlay.of(repo.get("OP01-020"), sickness=False)  # cost2 (対象)
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 (対象)
    opp.characters = [a, b]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST06-012"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    target_pick_seen = False
    guard = 0
    while st.pending_choice is not None and guard < 8:
        pc = st.pending_choice
        if pc.get("kind") == "target_pick":
            target_pick_seen = True
            b_idx = next(i for i, c in enumerate(pc["candidates"])
                         if c["iid"] == b.instance_id)
            resolve_pending_choice(st, [b_idx])
        else:
            resolve_pending_choice(st, [0])
        guard += 1

    assert target_pick_seen, "人間の KO 対象 target_pick modal が立たない"
    assert b not in opp.characters, "人間が選んだ相手キャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"
    assert garp.rested is True, "起動メインコストで ガープ がレストされるべき"


# --------------------------------------------------------------------------- #
#  ST06-014 衝撃波 (EVENT 黒 cost2):
#    【カウンター】自分のリーダーかキャラ1枚までを、このバトル中、パワー+4000。
#    【トリガー】相手のコスト4以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_st06_014_counter_pump_ai():
    """【カウンター】AI: 自リーダーを このバトル中 パワー+4000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    for prim in _eff(overlay, "ST06-014", "counter")["do"]:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 4000, \
        f"カウンターの +4000 が自リーダーに反映されていない: {me.leader.power}"


def test_st06_014_trigger_ko_cost4_ai():
    """【トリガー】AI: 相手のコスト4以下キャラを KO。 コスト5以上は残る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    low = InPlay.of(repo.get("OP01-020"), sickness=False)   # cost2 (対象)
    high = InPlay.of(repo.get("OP01-040"), sickness=False)  # cost6 (対象外)
    opp.characters = [high, low]

    for prim in _eff(overlay, "ST06-014", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)

    assert low not in opp.characters, "トリガーで相手コスト4以下キャラが KO されていない"
    assert high in opp.characters, "コスト5以上キャラは KO 対象外で残るべき"


# --------------------------------------------------------------------------- #
#  ST06-015 大噴火 (EVENT 黒 cost1):
#    【メイン】カード1枚を引く。その後、相手のキャラ1枚までを、このターン中、コスト-2。
#    【トリガー】相手は自身の手札1枚を選び、捨てる。
# --------------------------------------------------------------------------- #
def test_st06_015_main_draw_and_cost_minus_ai():
    """【メイン】AI: 1 ドロー → 相手キャラ1枚を コスト-2 (cost6 → 4)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("OP01-013")] * 10
    victim = InPlay.of(repo.get("OP01-040"), sickness=False)  # cost6
    opp.characters = [victim]

    cost_before = victim.base_cost
    for prim in _eff(overlay, "ST06-015", "main")["do"]:
        execute_effect(prim, st, me, opp, None)

    assert len(me.hand) == 1, "メインの draw が起きていない"
    assert victim.base_cost == cost_before - 2, \
        f"メインの コスト-2 が反映されていない: {victim.base_cost} (before {cost_before})"


def test_st06_015_main_cost_minus_human_pick():
    """人間 + 相手キャラ複数 → draw 後の cost_minus で target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("OP01-013")] * 10
    a = InPlay.of(repo.get("OP01-040"), sickness=False)  # cost6
    b = InPlay.of(repo.get("OP01-110"), sickness=False)  # cost6
    opp.characters = [a, b]

    for prim in _eff(overlay, "ST06-015", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
        if st.pending_choice is not None:
            break

    assert st.pending_choice is not None, "人間 + 複数候補で cost_minus modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"

    b_idx = next(i for i, c in enumerate(st.pending_choice["candidates"])
                 if c["iid"] == b.instance_id)
    b_before = b.base_cost
    resolve_pending_choice(st, [b_idx])
    assert b.base_cost == b_before - 2, "人間が選んだ相手キャラに -2 が反映されていない"


def test_st06_015_trigger_force_opp_discard_ai():
    """【トリガー】相手は自身の手札1枚を捨てる → 相手手札が1枚減る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.hand = [repo.get("OP01-013"), repo.get("OP01-016")]

    hand_before = len(opp.hand)
    for prim in _eff(overlay, "ST06-015", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)

    assert len(opp.hand) == hand_before - 1, \
        f"トリガーで相手手札が1枚捨てられていない: {len(opp.hand)} (before {hand_before})"


# --------------------------------------------------------------------------- #
#  ST06-016 ホワイト・アウト (EVENT 黒 cost1):
#    【カウンター】自分のリーダーかキャラ1枚までを、このバトル中、パワー+2000。
#    【トリガー】カード1枚を引き、自分のキャラは、このターン中、KOされない。
# --------------------------------------------------------------------------- #
def test_st06_016_counter_pump_ai():
    """【カウンター】AI: 自リーダーを このバトル中 パワー+2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    for prim in _eff(overlay, "ST06-016", "counter")["do"]:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 2000, \
        f"カウンターの +2000 が自リーダーに反映されていない: {me.leader.power}"


def test_st06_016_trigger_draw_and_ko_immune_ai():
    """【トリガー】1 ドロー + 自分のキャラ全てに このターン中 KO 耐性。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("OP01-013")] * 10
    c1 = InPlay.of(repo.get("OP01-020"), sickness=False)
    c2 = InPlay.of(repo.get("OP01-016"), sickness=False)
    me.characters = [c1, c2]

    for prim in _eff(overlay, "ST06-016", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)

    assert len(me.hand) == 1, "トリガーの draw が起きていない"
    assert c1.ko_immune_until_turn_end is True, "自キャラ c1 に KO 耐性が付与されていない"
    assert c2.ko_immune_until_turn_end is True, "自キャラ c2 に KO 耐性が付与されていない"
