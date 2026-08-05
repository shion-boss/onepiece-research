# -*- coding: utf-8 -*-
"""EB04 弾 効果 回帰テスト バックフィル (自動生成 wave 015):
EB04-005 / EB04-006 / EB04-008 / EB04-009 / EB04-010 / EB04-011 /
EB04-012 / EB04-013 / EB04-014 / EB04-015 の 10 枚。

目的 (= test_backfill_auto_001〜014.py と同一方針):
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
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
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
def test_all_wave15_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["EB04-005", "EB04-006", "EB04-008", "EB04-009", "EB04-010",
           "EB04-011", "EB04-012", "EB04-013", "EB04-014", "EB04-015"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  EB04-005 トラファルガー・ロー (CHARACTER 赤 cost3 power5000):
#    相手の元々のパワー5000以上のキャラが2枚以上いない場合、このキャラはアタックできない (常在)
# --------------------------------------------------------------------------- #
def test_eb04_005_law_static_cannot_attack_when_few_strong_opp():
    """相手の元々P5000+ キャラが 1 枚 (= 2 未満) → このキャラはアタック不可 (常在)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    law = InPlay.of(repo.get("EB04-005"), sickness=False)
    me.characters = [law]
    opp.characters = [InPlay.of(repo.get("ST01-013"), sickness=False)]  # ゾロ power5000 (1 枚)

    evaluate_static_effects(st, overlay)
    assert law.cannot_attack_static is True, \
        "相手の元々P5000+ キャラが 2 未満なのに アタック不可 が立っていない"


def test_eb04_005_law_static_can_attack_when_two_strong_opp():
    """相手の元々P5000+ キャラが 2 枚 → 条件不成立 → アタック不可は立たない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    law = InPlay.of(repo.get("EB04-005"), sickness=False)
    me.characters = [law]
    opp.characters = [InPlay.of(repo.get("ST01-013"), sickness=False),
                      InPlay.of(repo.get("ST01-012"), sickness=False)]  # power5000/6000 (2 枚)

    evaluate_static_effects(st, overlay)
    assert law.cannot_attack_static is False, \
        "相手の元々P5000+ キャラが 2 枚あるのに アタック不可 が立っている"


# --------------------------------------------------------------------------- #
#  EB04-006 モーダ (CHARACTER 赤 cost1):
#    【登場時】自分のデッキの上から7枚を見て、「ルルシア王国」1枚までを公開し手札へ、
#    残りを好きな順番でデッキの下に置く
# --------------------------------------------------------------------------- #
def test_eb04_006_moda_on_play_search_rurushia_ai():
    """登場時: デッキ上7枚から「ルルシア王国」1枚を手札へ (AI 自動)。 手札 +1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    rurushia = repo.get("EB04-010")  # ルルシア王国 (STAGE)
    me.deck = [rurushia] + [repo.get("ST01-004")] * 15
    me.hand = []

    hand_before = len(me.hand)
    do, _ = _do(overlay, "EB04-006", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB04-006"), sickness=True))

    assert len(me.hand) == hand_before + 1, "デッキ上7枚から「ルルシア王国」が手札に加わっていない"
    assert any(c.card_id == "EB04-010" for c in me.hand), "手札に加わったのが「ルルシア王国」でない"


def test_eb04_006_moda_on_play_human_search_modal():
    """人間: デッキ上7枚に「ルルシア王国」あり → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("EB04-010")] + [repo.get("ST01-004")] * 15
    me.hand = []

    do, _ = _do(overlay, "EB04-006", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB04-006"), sickness=True))
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (ルルシア王国) を選択
    _drain(st)
    assert any(c.card_id == "EB04-010" for c in me.hand), \
        "人間が選んだ「ルルシア王国」が手札に加わっていない"


# --------------------------------------------------------------------------- #
#  EB04-008 歪んだ未来 (EVENT 赤 cost1):
#    【メイン】自ライフ2枚以下なら 相手キャラ1枚まで このターン中 パワー-3000 /
#    【カウンター】自リーダーを このバトル中 パワー+3000
# --------------------------------------------------------------------------- #
def test_eb04_008_main_debuff_when_life_le2_ai():
    """メイン: 自ライフ2枚以下 → 相手キャラ1枚 -3000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 2  # ライフ 2 (= 条件成立)
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ power 2000
    opp.characters = [victim]

    assert eval_condition({"self_life_le": 2}, st, me) is True, \
        "ライフ2枚で self_life_le=2 が成立していない"
    power_before = victim.power
    do, _ = _do(overlay, "EB04-008", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert victim.power == power_before - 3000, \
        f"相手キャラ -3000 が反映されていない: {victim.power} (before {power_before})"


def test_eb04_008_counter_self_leader_pump_ai():
    """カウンター: 自リーダーを このバトル中 +3000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    do, _ = _do(overlay, "EB04-008", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 3000, \
        f"カウンターの +3000 が自リーダーに反映されていない: {me.leader.power}"


def test_eb04_008_main_debuff_human_pick():
    """人間 + 相手キャラ 複数 → -3000 の対象選択 target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 2
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # power 2000
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # power 3000
    opp.characters = [a, b]

    do, _ = _do(overlay, "EB04-008", "main")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    assert b.power == b_before - 3000, "人間が選んだ相手キャラに -3000 が反映されていない"


# --------------------------------------------------------------------------- #
#  EB04-009 弟子の船出だ よしなに頼むよ… (EVENT 赤):
#    【メイン】自「シルバーズ・レイリー」1枚にアクティブのドン1枚を付与できる：
#             相手のキャラ1枚まで このターン中 パワー-2000 /
#    【カウンター】自分のキャラか「シルバーズ・レイリー」1枚まで このバトル中 パワー+2000
# --------------------------------------------------------------------------- #
def test_eb04_009_main_attach_don_and_debuff_ai():
    """メイン: レイリーにアクティブドン1付与 (コスト) → 相手キャラ1枚 -2000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    rayleigh = InPlay.of(repo.get("OP09-005"), sickness=False)  # シルバーズ・レイリー
    me.characters = [rayleigh]
    me.don_active = 1
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # power 2000
    opp.characters = [victim]

    don_before = rayleigh.attached_dons
    active_before = me.don_active
    power_before = victim.power
    do, _ = _do(overlay, "EB04-009", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert rayleigh.attached_dons == don_before + 1, \
        "コストでレイリーにアクティブドン1枚が付与されていない"
    assert me.don_active == active_before - 1, "アクティブドンが1枚消費されるべき"
    assert victim.power == power_before - 2000, \
        f"相手キャラ -2000 が反映されていない: {victim.power} (before {power_before})"


def test_eb04_009_main_human_optional_confirm():
    """人間: 任意コスト → optional_cost_confirm modal が立ち、 承諾で -2000 まで解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    rayleigh = InPlay.of(repo.get("OP09-005"), sickness=False)
    me.characters = [rayleigh]
    me.don_active = 1
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)
    opp.characters = [victim]

    power_before = victim.power
    do, _ = _do(overlay, "EB04-009", "main")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾 (= コストを払う)
    _drain(st, pick=[0])
    assert victim.power == power_before - 2000, \
        "人間承諾後 相手キャラに -2000 が反映されていない"


def test_eb04_009_counter_self_pump_ai():
    """カウンター: 自分のキャラ1枚まで +2000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP01-016"), sickness=False)  # power 2000
    me.characters = [friend]

    power_before = friend.power
    do, _ = _do(overlay, "EB04-009", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert friend.power == power_before + 2000, \
        f"カウンターの +2000 が自キャラに反映されていない: {friend.power}"


# --------------------------------------------------------------------------- #
#  EB04-010 ルルシア王国 (STAGE 赤 cost7):
#    【相手のターン中】自分の元々コスト1のキャラすべて パワー+5000 (常在) /
#    【登場時】相手のキャラ1枚まで このターン中 パワー0
# --------------------------------------------------------------------------- #
def test_eb04_010_on_play_set_opp_power_zero_ai():
    """登場時: 相手キャラ1枚を このターン中 パワー0 (AI)。
    (overlay は「パワー0」を -99999 の turn debuff でモデル化 → 実効パワー <= 0。)"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("ST01-013"), sickness=False)  # ゾロ power5000
    opp.characters = [victim]

    assert victim.power > 0, "テスト前提: 対象の初期パワーは正"
    do, _ = _do(overlay, "EB04-010", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB04-010"), sickness=False))

    assert victim.power <= 0, \
        f"登場時に相手キャラのパワーが 0 (以下) になっていない: {victim.power}"


def test_eb04_010_static_pump_cost1_chara_opp_turn():
    """相手ターン中: 自分の元々コスト1キャラすべて +5000 (常在)。"""
    repo = _repo()
    overlay = _overlay()
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    stage = InPlay.of(repo.get("EB04-010"), sickness=False)
    nami = InPlay.of(repo.get("ST01-007"), sickness=False)  # ナミ 元々コスト1 power1000
    p0.stages = [stage]
    p0.characters = [nami]
    st = GameState(players=[p0, p1], phase=Phase.MAIN, effects_overlay=overlay)
    st.turn_player_idx = 1  # 相手ターン (= opp_turn 成立)
    st.human_player_idx = None

    base = nami.card.power
    evaluate_static_effects(st, overlay)
    assert nami.power == base + 5000, \
        f"相手ターン中に元々コスト1キャラ +5000 が乗っていない: {nami.power} (base {base})"


def test_eb04_010_static_no_pump_own_turn():
    """自分のターン中は【相手のターン中】条件が不成立 → +5000 は乗らない。"""
    repo = _repo()
    overlay = _overlay()
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p0.stages = [InPlay.of(repo.get("EB04-010"), sickness=False)]
    nami = InPlay.of(repo.get("ST01-007"), sickness=False)
    p0.characters = [nami]
    st = GameState(players=[p0, p1], phase=Phase.MAIN, effects_overlay=overlay)
    st.turn_player_idx = 0  # 自分のターン → opp_turn False
    st.human_player_idx = None

    base = nami.card.power
    evaluate_static_effects(st, overlay)
    assert nami.power == base, \
        f"自ターン中に +5000 が乗ってはいけない: {nami.power} (base {base})"


# --------------------------------------------------------------------------- #
#  EB04-011 ウロコ (CHARACTER 緑 cost7 power8000):
#    【速攻：キャラ】【登場時】自分の特徴《海王類》を持つキャラ1枚につき1ドロー、
#    その後 引いた枚数分 自分の手札を捨てる
# --------------------------------------------------------------------------- #
def test_eb04_011_uroko_on_play_draw_per_kaiourui_then_discard_ai():
    """登場時: 海王類キャラ2枚 → 2ドロー → 2捨て (AI)。 デッキ -2 / トラッシュ +2 / 手札 ±0。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    # 盤面に 海王類 キャラ 2 枚
    me.characters = [InPlay.of(repo.get("OP11-027"), sickness=False),  # ギョロ目 海王類
                     InPlay.of(repo.get("OP11-036"), sickness=False)]  # マダラ 海王類
    me.deck = [repo.get("ST01-004")] * 10
    me.hand = [repo.get("OP01-013")] * 3

    hand_before = len(me.hand)
    deck_before = len(me.deck)
    trash_before = len(me.trash)
    do, _ = _do(overlay, "EB04-011", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB04-011"), sickness=True))

    assert len(me.deck) == deck_before - 2, "海王類2枚分の2ドローが起きていない (デッキ -2)"
    assert len(me.trash) == trash_before + 2, "引いた枚数分 (2枚) が捨てられていない (トラッシュ +2)"
    assert len(me.hand) == hand_before, \
        f"手札 net (2ドロー -2捨て = ±0) が合わない: {len(me.hand)} (before {hand_before})"


def test_eb04_011_uroko_on_play_human_discard_modal():
    """人間: 引いた後 どの手札を捨てるか選ぶ self_hand_discard_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP11-027"), sickness=False),
                     InPlay.of(repo.get("OP11-036"), sickness=False)]
    me.deck = [repo.get("ST01-004")] * 10
    me.hand = [repo.get("OP01-013")] * 3  # 引いた後 5 枚 > 捨て2

    do, _ = _do(overlay, "EB04-011", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB04-011"), sickness=True))

    assert st.pending_choice is not None, "人間 + 手札超過で discard modal が立たない"
    assert st.pending_choice.get("kind") == "self_hand_discard_pick", \
        f"kind が self_hand_discard_pick でない: {st.pending_choice.get('kind')}"
    assert st.pending_choice.get("limit") == 2, \
        f"捨て枚数 limit が 2 でない: {st.pending_choice.get('limit')}"
    trash_before = len(me.trash)
    resolve_pending_choice(st, [0, 1])  # 先頭2枚を捨てる
    _drain(st)
    assert len(me.trash) == trash_before + 2, "人間選択後 手札2枚が捨てられていない"


# --------------------------------------------------------------------------- #
#  EB04-012 菊之丞 (CHARACTER 緑 cost7):
#    【起動メイン】【ターン1回】このキャラが登場したターンの場合、
#    自分の特徴《ワノ国》を持つリーダーをアクティブにする
# --------------------------------------------------------------------------- #
def test_eb04_012_kikunojo_activate_main_untap_leader_ai():
    """起動メイン: 登場ターン中 + ワノ国リーダー → 自リーダーをアクティブに (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB01-001", overlay)  # 光月おでん (ワノ国 leader)
    me, opp = st.players[0], st.players[1]
    kiku = InPlay.of(repo.get("EB04-012"), sickness=True)  # 登場ターン中
    me.characters = [kiku]
    me.leader.rested = True  # レストのリーダーをアクティブにする対象

    opts = _am(st, me, overlay, "EB04-012")
    assert len(opts) == 1, f"EB04-012 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert me.leader.rested is False, "起動メインで自リーダーがアクティブになっていない"


def test_eb04_012_kikunojo_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB01-001", overlay)
    me, opp = st.players[0], st.players[1]
    kiku = InPlay.of(repo.get("EB04-012"), sickness=True)
    me.characters = [kiku]
    me.leader.rested = True

    opts1 = _am(st, me, overlay, "EB04-012")
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])

    opts2 = _am(st, me, overlay, "EB04-012")
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


def test_eb04_012_kikunojo_activate_main_not_legal_after_summon_turn():
    """登場したターンでない (= 召喚酔いなし) 場合、 条件不成立で起動メインは legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB01-001", overlay)
    me, opp = st.players[0], st.players[1]
    kiku = InPlay.of(repo.get("EB04-012"), sickness=False)  # 登場ターンでない
    me.characters = [kiku]
    me.leader.rested = True

    opts = _am(st, me, overlay, "EB04-012")
    assert len(opts) == 0, "登場ターンでないのに起動メインが legal に出ている"


# --------------------------------------------------------------------------- #
#  EB04-013 キャロット (CHARACTER 緑 cost8):
#    【登場時】自リーダーが特徴《ミンク族》を持つ場合、自分の特徴《ミンク族》を持つキャラ
#    2枚までとリーダーをアクティブにする
# --------------------------------------------------------------------------- #
def test_eb04_013_carrot_on_play_untap_mink_and_leader_ai():
    """登場時 (ミンク族リーダー): 自リーダー + ミンク族キャラ2枚をアクティブに (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-021", overlay)  # キャロット (ミンク族 leader)
    me, opp = st.players[0], st.players[1]
    me.leader.rested = True
    m1 = InPlay.of(repo.get("OP08-024"), sickness=False)  # コンスロット ミンク族
    m2 = InPlay.of(repo.get("OP08-025"), sickness=False)  # シシリアン ミンク族
    m1.rested = True
    m2.rested = True
    me.characters = [m1, m2]

    assert eval_condition({"leader_feature": "ミンク族"}, st, me) is True, \
        "テスト前提: リーダーが ミンク族 でない"
    do, _ = _do(overlay, "EB04-013", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB04-013"), sickness=True))

    assert me.leader.rested is False, "登場時に自リーダーがアクティブになっていない"
    assert m1.rested is False and m2.rested is False, \
        "ミンク族キャラ2枚がアクティブになっていない"


# --------------------------------------------------------------------------- #
#  EB04-014 光月スキヤキ (CHARACTER 緑 cost3):
#    【ブロッカー】【起動メイン】【ターン1回】自分の特徴《ワノ国》を持つリーダーに
#    レストのドン1枚までを付与する
# --------------------------------------------------------------------------- #
def test_eb04_014_sukiyaki_activate_main_attach_rested_don_ai():
    """起動メイン: ワノ国リーダーにレストのドン1枚を付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB01-001", overlay)  # 光月おでん (ワノ国 leader)
    me, opp = st.players[0], st.players[1]
    sukiyaki = InPlay.of(repo.get("EB04-014"), sickness=False)
    me.characters = [sukiyaki]
    me.don_rested = 2  # レストドン供給源

    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    opts = _am(st, me, overlay, "EB04-014")
    assert len(opts) == 1, f"EB04-014 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert me.leader.attached_dons == don_before + 1, \
        "起動メインで自リーダーにレストのドンが付与されていない"
    assert me.don_rested == rested_before - 1, "レストのドンが1枚消費されるべき"


def test_eb04_014_sukiyaki_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB01-001", overlay)
    me, opp = st.players[0], st.players[1]
    sukiyaki = InPlay.of(repo.get("EB04-014"), sickness=False)
    me.characters = [sukiyaki]
    me.don_rested = 3

    opts1 = _am(st, me, overlay, "EB04-014")
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])

    opts2 = _am(st, me, overlay, "EB04-014")
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  EB04-015 ジンベエ (CHARACTER 緑 cost7):
#    【ブロッカー】【KO時】自分のカード1枚をレストにできる：自リーダーが特徴《魚人族》か
#    《人魚族》を持つ場合、自分の手札からコスト6以下の緑のキャラカード1枚までを登場させる
# --------------------------------------------------------------------------- #
def test_eb04_015_jinbe_on_ko_play_green_chara_ai():
    """KO時: 自カード1枚レスト (コスト) → 手札の緑コスト6以下キャラ1枚を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP11-021", overlay)  # ジンベエ (魚人族 leader)
    me, opp = st.players[0], st.players[1]
    # レストコスト用の別キャラ + 登場させる手札キャラ (緑 cost1 vanilla)
    cost_chara = InPlay.of(repo.get("OP08-024"), sickness=False)  # コンスロット 緑 (active)
    me.characters = [cost_chara]
    green_hand = repo.get("OP01-036")  # お鶴 緑 cost1
    assert "緑" in green_hand.color and green_hand.cost <= 6, \
        "テスト前提: 手札キャラが 緑 cost6以下 でない"
    me.hand = [green_hand]

    assert eval_condition({"leader_features_any": ["魚人族", "人魚族"]}, st, me) is True, \
        "テスト前提: リーダーが 魚人族/人魚族 でない"
    hand_before = len(me.hand)
    chars_before = len(me.characters)
    do, _ = _do(overlay, "EB04-015", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB04-015"), sickness=False))

    assert any(c.card.card_id == "OP01-036" for c in me.characters), \
        "手札の緑コスト6以下キャラが登場していない"
    assert len(me.hand) == hand_before - 1, "登場で手札が1枚減っていない"
    assert len(me.characters) == chars_before + 1, "キャラが1体増えていない"


def test_eb04_015_jinbe_on_ko_human_optional_confirm():
    """人間: 任意コスト → optional_cost_confirm modal が立ち、 承諾で登場まで解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP11-021", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    cost_chara = InPlay.of(repo.get("OP08-024"), sickness=False)
    me.characters = [cost_chara]
    me.hand = [repo.get("OP01-036")]  # お鶴 緑 cost1

    do, _ = _do(overlay, "EB04-015", "on_ko")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB04-015"), sickness=False))
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾 (= コストを払う)
    _drain(st, pick=[0])
    assert any(c.card.card_id == "OP01-036" for c in me.characters), \
        "人間承諾後 手札の緑キャラが登場していない"
