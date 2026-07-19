# -*- coding: utf-8 -*-
"""EB03 弾 効果 回帰テスト バックフィル (自動生成 wave 010):
EB03-004 / EB03-006 / EB03-008 / EB03-009 / EB03-010 / EB03-011 /
EB03-012 / EB03-013 / EB03-014 / EB03-015 の 10 枚。

目的 (= test_backfill_auto_001〜009.py と同一方針):
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
    eval_condition,
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
    デッキは効果の薄いバニラ気味カード (ST01-004) で埋める。"""
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
    """指定 card_id の overlay から when 一致の効果の (do, effect) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e["do"], e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]["do"], matches[0]


def _am(st, me, overlay, cid):
    """指定 card_id の legal な起動メイン (src, eff) を返す (無ければ空 list)。"""
    return [(src, eff) for (src, eff) in list_activate_main_effects(st, me, overlay)
            if src.card.card_id == cid]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_eb03_wave10_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["EB03-004", "EB03-006", "EB03-008", "EB03-009", "EB03-010",
           "EB03-011", "EB03-012", "EB03-013", "EB03-014", "EB03-015"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  EB03-004 カリーナ: 【ブロッカー】【相手のターン中】自リーダー多色 &
#    元々パワー6000以上の自キャラがいない → このキャラ +4000 (静的)
# --------------------------------------------------------------------------- #
def test_eb03_004_karina_static_pump_opp_turn():
    """相手ターン中 + 多色リーダー + 6000以上キャラ不在 → +4000 (2000 -> 6000)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB03-001", overlay)  # ネフェルタリ・ビビ (赤/青 = 多色)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1  # 相手ターン (= opp_turn 条件成立)
    karina = InPlay.of(repo.get("EB03-004"), sickness=False)  # power 2000
    me.characters = [karina]

    assert eval_condition({"leader_multicolor": True}, st, me) is True, \
        "多色リーダーで leader_multicolor が成立していない"
    evaluate_static_effects(st, overlay)
    assert karina.power == karina.card.power + 4000, \
        f"相手ターンの静的 +4000 が反映されていない: {karina.power} (base {karina.card.power})"


def test_eb03_004_karina_static_no_pump_with_big_chara():
    """元々パワー6000以上の自キャラがいる場合は条件不成立 → +4000 は乗らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB03-001", overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1
    karina = InPlay.of(repo.get("EB03-004"), sickness=False)
    big = InPlay.of(repo.get("EB03-002"), sickness=False)  # 元々パワー 6000
    me.characters = [karina, big]

    evaluate_static_effects(st, overlay)
    assert karina.power == karina.card.power, \
        f"6000以上キャラ在で +4000 が乗ってはいけない: {karina.power}"


def test_eb03_004_karina_static_no_pump_own_turn():
    """自分のターン中は【相手のターン中】条件が不成立 → +4000 は乗らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB03-001", overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 0  # 自分のターン
    karina = InPlay.of(repo.get("EB03-004"), sickness=False)
    me.characters = [karina]

    evaluate_static_effects(st, overlay)
    assert karina.power == karina.card.power, \
        f"自分ターンで +4000 が乗ってはいけない: {karina.power}"


# --------------------------------------------------------------------------- #
#  EB03-006 ナミ: 【登場時】自アクティブリーダー -5000 する:1ドロー (任意コスト) /
#    【起動メイン】【ターン1回】アラバスタ王国リーダーで 相手キャラ1枚 -1000
# --------------------------------------------------------------------------- #
def test_eb03_006_nami_on_play_optional_draw_ai():
    """登場時 (任意): 自リーダー このターン -5000 → 1ドロー。 AI は払って引く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("ST01-004")] * 5

    leader_before = me.leader.power
    deck_before = len(me.deck)
    do, _ = _do(overlay, "EB03-006", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-006"), sickness=False))
    assert len(me.hand) == 1, "登場時の任意ドローが起きていない"
    assert len(me.deck) == deck_before - 1, "ドローでデッキが1枚減っていない"
    assert me.leader.power == leader_before - 5000, \
        f"コストで自リーダーが -5000 されていない: {me.leader.power} (before {leader_before})"


def test_eb03_006_nami_activate_main_debuff_ai():
    """起動メイン (アラバスタ王国リーダー): 相手キャラ1枚を このターン中 -1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB03-001", overlay)  # ネフェルタリ・ビビ (アラバスタ王国)
    me, opp = st.players[0], st.players[1]
    nami = InPlay.of(repo.get("EB03-006"), sickness=False)
    me.characters = [nami]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # 2000
    opp.characters = [victim]

    assert eval_condition({"leader_feature": "アラバスタ王国"}, st, me) is True, \
        "アラバスタ王国リーダーで leader_feature が成立していない"
    opts = _am(st, me, overlay, "EB03-006")
    assert len(opts) == 1, f"EB03-006 の起動メインが legal に出ない: {len(opts)}"
    power_before = victim.power
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, pick=[0])
    assert victim.power == power_before - 1000, \
        f"起動メインの相手 -1000 が反映されていない: {victim.power} (before {power_before})"


def test_eb03_006_nami_activate_main_human_pick():
    """人間 + 相手キャラ 複数 → 相手 -1000 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB03-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    nami = InPlay.of(repo.get("EB03-006"), sickness=False)
    me.characters = [nami]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)
    b = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [a, b]

    opts = _am(st, me, overlay, "EB03-006")
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が 2 体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b.power == b_before - 1000, "人間が選んだ相手キャラに -1000 が反映されていない"


# --------------------------------------------------------------------------- #
#  EB03-008 ひばり: 【登場時】/【アタック時】自《SWORD》リーダーかキャラ1枚に
#    アクティブキャラへのアタック権を付与 / 【起動メイン】【ターン1回】相手キャラ1枚 -1000
# --------------------------------------------------------------------------- #
def test_eb03_008_hibari_on_play_give_attack_active_ai():
    """登場時: 自《SWORD》キャラ (ひばり自身) にアクティブキャラアタック権を付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    hibari = InPlay.of(repo.get("EB03-008"), sickness=False)  # 特徴 SWORD
    me.characters = [hibari]

    do, _ = _do(overlay, "EB03-008", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp, hibari)
    assert "アクティブアタック可" in hibari.granted_keywords, \
        "登場時のアクティブキャラアタック権付与が反映されていない"


def test_eb03_008_hibari_activate_main_debuff_ai():
    """起動メイン: 相手キャラ1枚を このターン中 -1000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    hibari = InPlay.of(repo.get("EB03-008"), sickness=False)
    me.characters = [hibari]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # 2000
    opp.characters = [victim]

    opts = _am(st, me, overlay, "EB03-008")
    assert len(opts) == 1, f"EB03-008 の起動メインが legal に出ない: {len(opts)}"
    power_before = victim.power
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, pick=[0])
    assert victim.power == power_before - 1000, \
        f"起動メインの相手 -1000 が反映されていない: {victim.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  EB03-009 マキノ: 【起動メイン】このキャラをレスト:
#    自分の元々の効果のないキャラ1枚を このターン中 +2000
# --------------------------------------------------------------------------- #
def test_eb03_009_makino_activate_main_pump_no_effect_ai():
    """起動メイン (自レストコスト): 効果のない自キャラ1枚を +2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    makino = InPlay.of(repo.get("EB03-009"), sickness=False)
    vanilla = InPlay.of(repo.get("EB03-002"), sickness=False)  # 元々効果なし
    me.characters = [makino, vanilla]

    opts = _am(st, me, overlay, "EB03-009")
    assert len(opts) == 1, f"EB03-009 の起動メインが legal に出ない: {len(opts)}"
    power_before = vanilla.power
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, pick=[0])
    assert vanilla.power == power_before + 2000, \
        f"効果なしキャラへの +2000 が反映されていない: {vanilla.power} (before {power_before})"
    assert makino.rested is True, "起動メインコストで マキノ がレストされるべき"


def test_eb03_009_makino_activate_main_human_pick():
    """人間 + 効果なしキャラ 複数 → +2000 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    makino = InPlay.of(repo.get("EB03-009"), sickness=False)
    v1 = InPlay.of(repo.get("EB03-002"), sickness=False)  # 効果なし
    v2 = InPlay.of(repo.get("EB03-019"), sickness=False)  # 効果なし
    me.characters = [makino, v1, v2]

    opts = _am(st, me, overlay, "EB03-009")
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (効果なしキャラ 2 体) が 2 件でない: {len(cands)}"
    v2_idx = next(i for i, c in enumerate(cands) if c["iid"] == v2.instance_id)
    v2_before = v2.power
    resolve_pending_choice(st, [v2_idx])
    _drain(st)
    assert v2.power == v2_before + 2000, "人間が選んだキャラに +2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  EB03-010 モネ: 【ブロッカー】【登場時】上5枚を見て パワー1000以下キャラ or
#    イベント1枚を公開手札、 残りをデッキ下
# --------------------------------------------------------------------------- #
def test_eb03_010_monet_on_play_search_ai():
    """登場時: 上5枚から パワー1000以下キャラを手札へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    small = repo.get("PRB02-009")  # CHARACTER power 1000 (<=1000)
    me.deck = [small] + [repo.get("ST01-004")] * 10
    me.hand = []

    do, _ = _do(overlay, "EB03-010", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-010"), sickness=False))
    assert any(c.card_id == "PRB02-009" for c in me.hand), \
        "上5枚から パワー1000以下キャラが手札に加わっていない"


def test_eb03_010_monet_on_play_human_search_modal():
    """人間: 上5枚公開の search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    small = repo.get("PRB02-009")
    me.deck = [small] + [repo.get("ST01-004")] * 10
    me.hand = []

    do, _ = _do(overlay, "EB03-010", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB03-010"), sickness=False))
    assert st.pending_choice is not None, "人間で search modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st)
    assert any(c.card_id == "PRB02-009" for c in me.hand), \
        "人間が選んだ パワー1000以下キャラが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  EB03-011 いつかまた〜 (EVENT): 【カウンター】ビビリーダーで 自リーダー/キャラ1枚 +4000 /
#    【トリガー】相手キャラ1枚 このターン中 -2000
# --------------------------------------------------------------------------- #
def test_eb03_011_counter_pump_ai():
    """カウンター (ビビリーダー): 自リーダーかキャラ1枚 このバトル +4000 (AI 既定=リーダー)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB03-001", overlay)  # ネフェルタリ・ビビ
    me, opp = st.players[0], st.players[1]

    do, e = _do(overlay, "EB03-011", "counter", needle="power_pump")
    assert eval_condition({"leader_name": "ネフェルタリ・ビビ"}, st, me) is True, \
        "ビビリーダーで leader_name 条件が成立していない"
    power_before = me.leader.power
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert me.leader.power == power_before + 4000, \
        f"カウンターの +4000 が自リーダーに反映されていない: {me.leader.power}"


def test_eb03_011_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +4000 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB03-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [friend]

    do, _ = _do(overlay, "EB03-011", "counter", needle="power_pump")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert friend.power == friend_before + 4000, \
        "人間が選んだキャラに +4000 が反映されていない"


def test_eb03_011_trigger_debuff_ai():
    """トリガー: 相手キャラ1枚を このターン中 -2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # 2000
    opp.characters = [victim]

    do, _ = _do(overlay, "EB03-011", "trigger")
    power_before = victim.power
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert victim.power == power_before - 2000, \
        f"トリガーの相手 -2000 が反映されていない: {victim.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  EB03-012 お玉: 【起動メイン】このキャラをレスト:以下から1つ
#    ・相手のコスト3以下《動物/SMILE》キャラ1枚をレスト
#    ・相手のドン1枚をレスト
# --------------------------------------------------------------------------- #
def test_eb03_012_otama_activate_main_rest_chara_ai():
    """起動メイン (自レストコスト): choice で 相手《動物/SMILE》cost3以下キャラをレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    otama = InPlay.of(repo.get("EB03-012"), sickness=False)
    me.characters = [otama]
    victim = InPlay.of(repo.get("EB04-035"), sickness=False)  # SMILE cost3
    opp.characters = [victim]

    opts = _am(st, me, overlay, "EB03-012")
    assert len(opts) == 1, f"EB03-012 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, pick=[0])
    assert otama.rested is True, "起動メインコストで お玉 がレストされるべき"
    assert victim.rested is True, "choice で相手《動物/SMILE》キャラがレストされていない"


def test_eb03_012_otama_activate_main_human_option_modal():
    """人間: choice_effect の option_pick modal が 2 択で立ち、 キャラレストを選べる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    otama = InPlay.of(repo.get("EB03-012"), sickness=False)
    me.characters = [otama]
    victim = InPlay.of(repo.get("EB04-035"), sickness=False)  # SMILE cost3
    opp.characters = [victim]
    opp.don_active = 3  # ドンレスト option も valid にする

    opts = _am(st, me, overlay, "EB03-012")
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])
    assert st.pending_choice is not None, "人間で option_pick modal が立たない"
    assert st.pending_choice.get("kind") == "option_pick", \
        f"kind が option_pick でない: {st.pending_choice.get('kind')}"
    options = st.pending_choice.get("options", [])
    assert len(options) == 2, f"valid option が 2 件でない: {len(options)}"
    resolve_pending_choice(st, [0])  # キャラをレスト option
    _drain(st, pick=[0])
    assert victim.rested is True, "人間が選んだ キャラレストが反映されていない"


# --------------------------------------------------------------------------- #
#  EB03-013 キャロット: 【起動メイン】【ターン1回】登場ターンなら
#    相手のレストcost5以下キャラ1枚KO → その後 手札から「ゾウ」1枚を登場
# --------------------------------------------------------------------------- #
def test_eb03_013_carrot_activate_main_ko_and_play_zou_ai():
    """起動メイン (登場ターン): 相手レストcost5以下を KO → 手札の「ゾウ」を登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    carrot = InPlay.of(repo.get("EB03-013"), sickness=True)  # このターン登場
    me.characters = [carrot]
    victim = InPlay.of(repo.get("EB03-002"), sickness=False)  # cost5
    victim.rested = True
    opp.characters = [victim]
    me.hand = [repo.get("OP08-039")]  # ゾウ (STAGE)

    opts = _am(st, me, overlay, "EB03-013")
    assert len(opts) == 1, f"EB03-013 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, pick=[0])
    assert victim not in opp.characters, "相手のレストcost5以下キャラが KO されていない"
    assert any(s.card.card_id == "OP08-039" for s in me.stages), \
        "手札の「ゾウ」が登場していない"


def test_eb03_013_carrot_activate_main_not_summoning_turn():
    """登場ターンでない (sickness=False) 場合は起動メインが legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    carrot = InPlay.of(repo.get("EB03-013"), sickness=False)  # 登場ターンでない
    me.characters = [carrot]
    victim = InPlay.of(repo.get("EB03-002"), sickness=False)
    victim.rested = True
    opp.characters = [victim]

    opts = _am(st, me, overlay, "EB03-013")
    assert len(opts) == 0, "登場ターンでないのに起動メインが legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  EB03-014 くいな: 【起動メイン】【ターン1回】このキャラをレスト:
#    属性《斬》リーダーに レストドン2枚までを付与
# --------------------------------------------------------------------------- #
def test_eb03_014_kuina_activate_main_attach_rested_don_ai():
    """起動メイン (自レスト + 斬リーダー): 自リーダーにレストドン2枚を付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB03-001", overlay)  # ネフェルタリ・ビビ 属性《斬》
    me, opp = st.players[0], st.players[1]
    kuina = InPlay.of(repo.get("EB03-014"), sickness=False)
    me.characters = [kuina]
    me.don_rested = 3

    assert eval_condition({"leader_attribute": "斬"}, st, me) is True, \
        "斬リーダーで leader_attribute 条件が成立していない"
    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    opts = _am(st, me, overlay, "EB03-014")
    assert len(opts) == 1, f"EB03-014 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    assert me.leader.attached_dons == don_before + 2, \
        f"自リーダーへレストドン2枚が付与されていない: {me.leader.attached_dons}"
    assert me.don_rested == rested_before - 2, "レストドンが2枚消費されるべき"
    assert kuina.rested is True, "起動メインコストで くいな がレストされるべき"


def test_eb03_014_kuina_activate_main_once_per_turn():
    """【ターン1回】: 一度発動したら再び legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB03-001", overlay)
    me, opp = st.players[0], st.players[1]
    kuina = InPlay.of(repo.get("EB03-014"), sickness=False)
    me.characters = [kuina]
    me.don_rested = 5

    opts1 = _am(st, me, overlay, "EB03-014")
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    opts2 = _am(st, me, overlay, "EB03-014")
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  EB03-015 ケイミー: 【起動メイン】このキャラをレスト:
#    自《魚人族/人魚族》リーダーかキャラ1枚に レストドン1枚を付与 →
#    その後 相手のコスト2以下キャラ1枚をレスト
# --------------------------------------------------------------------------- #
def test_eb03_015_camie_activate_main_attach_and_rest_ai():
    """起動メイン (自レスト): 自《魚人族/人魚族》に レストドン1付与 → 相手cost2以下をレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP14-040", overlay)  # 魚人族/人魚族 リーダー
    me, opp = st.players[0], st.players[1]
    camie = InPlay.of(repo.get("EB03-015"), sickness=False)
    me.characters = [camie]
    me.don_rested = 2
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 (<=2)
    opp.characters = [victim]

    don_before = me.leader.attached_dons
    opts = _am(st, me, overlay, "EB03-015")
    assert len(opts) == 1, f"EB03-015 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, pick=[0])
    assert me.leader.attached_dons == don_before + 1, \
        f"自リーダーへレストドン1枚が付与されていない: {me.leader.attached_dons}"
    assert victim.rested is True, "その後の 相手cost2以下キャラのレストが反映されていない"
    assert camie.rested is True, "起動メインコストで ケイミー がレストされるべき"


def test_eb03_015_camie_activate_main_human_attach_pick():
    """人間 + 自《魚人族/人魚族》リーダー+キャラ 複数 → レストドン付与先の target_pick が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP14-040", overlay, human_idx=0)  # 魚人族/人魚族 リーダー
    me, opp = st.players[0], st.players[1]
    camie = InPlay.of(repo.get("EB03-015"), sickness=False)  # 特徴 人魚族/魚人島
    me.characters = [camie]
    me.don_rested = 2

    opts = _am(st, me, overlay, "EB03-015")
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])
    assert st.pending_choice is not None, "人間 + 複数候補で付与先 modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) >= 2, f"付与先候補 (リーダー + 自身) が 2 件以上でない: {len(cands)}"
    resolve_pending_choice(st, [0])
    _drain(st, pick=[0])
    assert me.leader.attached_dons + camie.attached_dons >= 1, \
        "人間が選んだ対象にレストドンが付与されていない"
