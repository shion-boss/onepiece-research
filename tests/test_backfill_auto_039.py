# -*- coding: utf-8 -*-
"""OP03 弾 (青 東の海 ミル/バウンス / 紫 W7・GC ドン操作) 効果 回帰テスト
バックフィル (自動生成 wave 039):
OP03-051 / OP03-053 / OP03-054 / OP03-055 / OP03-057 / OP03-060 /
OP03-062 / OP03-063 / OP03-064 / OP03-066 の 10 枚。

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
    eval_condition,
    evaluate_static_effects,
    execute_effect,
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
def test_all_op03_wave39_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP03-051", "OP03-053", "OP03-054", "OP03-055", "OP03-057",
           "OP03-060", "OP03-062", "OP03-063", "OP03-064", "OP03-066"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP03-051 ベルメール (CHARACTER 青 cost4):
#    【ドン!!×1】アタックで相手ライフにダメージ時、自デッキ上7枚をトラッシュ (任意)。
#    【KO時】自デッキ上3枚をトラッシュ (任意)。
# --------------------------------------------------------------------------- #
def test_op03_051_bellemere_life_taken_mill7_ai():
    """【ドン!!×1】相手ライフダメージ時、自デッキ上7枚をトラッシュ (AI、 ドン1ゲート)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP03-051"), sickness=False)
    src.attached_dons = 1  # ドン!!×1 ゲート成立
    me.characters = [src]
    deck_before = len(me.deck)
    trash_before = len(me.trash)

    eff = _get_eff(overlay, "OP03-051", "on_opp_life_taken")
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドン!!×1 ゲート self_attached_don_ge=1 が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, src)

    assert len(me.deck) == deck_before - 7, \
        f"デッキ上7枚がトラッシュされていない: {len(me.deck)} (before {deck_before})"
    assert len(me.trash) == trash_before + 7, "トラッシュが7枚増えていない"


def test_op03_051_bellemere_on_ko_mill3_ai():
    """【KO時】自デッキ上3枚をトラッシュ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP03-051"), sickness=False)
    deck_before = len(me.deck)
    trash_before = len(me.trash)

    eff = _get_eff(overlay, "OP03-051", "on_ko")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, src)

    assert len(me.deck) == deck_before - 3, \
        f"KO時に自デッキ上3枚がトラッシュされていない: {len(me.deck)} (before {deck_before})"
    assert len(me.trash) == trash_before + 3, "トラッシュが3枚増えていない"


# --------------------------------------------------------------------------- #
#  OP03-053 ヨサク&ジョニー (CHARACTER 青 cost1 power3000):
#    【ドン!!×1】自分のデッキが20枚以下の場合、このキャラはパワー+2000。
# --------------------------------------------------------------------------- #
def test_op03_053_yosaku_johnny_static_pump_deck_le20():
    """静的 (ドン!!×1 + 自デッキ20枚以下): 自身 static_buff +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP01-013")] * 20  # デッキ 20 枚 (<=20)
    yj = InPlay.of(repo.get("OP03-053"), sickness=False)
    yj.attached_dons = 1  # ドン!!×1 ゲート成立
    me.characters = [yj]

    evaluate_static_effects(st, overlay)
    assert yj.static_buff == 2000, \
        f"条件成立時 static_buff +2000 が乗っていない: {yj.static_buff}"


def test_op03_053_yosaku_johnny_no_pump_deck_over20():
    """自デッキが21枚以上 (=20枚超) では条件不成立 → static_buff +0。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP01-013")] * 30  # 30 枚 (>20)
    yj = InPlay.of(repo.get("OP03-053"), sickness=False)
    yj.attached_dons = 1
    me.characters = [yj]

    evaluate_static_effects(st, overlay)
    assert yj.static_buff == 0, \
        f"デッキ20枚超では +2000 が乗ってはいけない: {yj.static_buff}"


def test_op03_053_yosaku_johnny_no_pump_without_don():
    """ドン!!×1 が付与されていなければ条件不成立 → static_buff +0。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP01-013")] * 20
    yj = InPlay.of(repo.get("OP03-053"), sickness=False)
    yj.attached_dons = 0  # ドン未付与 → n=1 ゲート不成立
    me.characters = [yj]

    evaluate_static_effects(st, overlay)
    assert yj.static_buff == 0, \
        f"ドン未付与では +2000 が乗ってはいけない: {yj.static_buff}"


# --------------------------------------------------------------------------- #
#  OP03-054 ウソーーップ輪ごーむっ!!! (EVENT 青 cost1):
#    【カウンター】自リーダーかキャラ1枚まで +2000。その後、自デッキ上1枚をトラッシュ (任意)。
#    【トリガー】カード1枚を引き、自デッキ上1枚をトラッシュ (任意)。
# --------------------------------------------------------------------------- #
def test_op03_054_counter_pump_and_mill_ai():
    """【カウンター】自リーダー +2000 + 自デッキ上1枚トラッシュ (AI 自動、 リーダー既定)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    power_before = me.leader.power
    deck_before = len(me.deck)

    eff = _get_eff(overlay, "OP03-054", "counter")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 2000, \
        f"カウンターの +2000 が自リーダーに反映されていない: {me.leader.power}"
    assert len(me.deck) == deck_before - 1, \
        f"自デッキ上1枚がトラッシュされていない: {len(me.deck)} (before {deck_before})"


def test_op03_054_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +2000 の対象選択 target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [friend]

    eff = _get_eff(overlay, "OP03-054", "counter")
    execute_effect(eff["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert friend.power == friend_before + 2000, \
        "人間が選んだキャラに +2000 が反映されていない"


def test_op03_054_trigger_draw_and_mill_ai():
    """【トリガー】カード1枚引き + 自デッキ上1枚トラッシュ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    hand_before = len(me.hand)
    deck_before = len(me.deck)

    eff = _get_eff(overlay, "OP03-054", "trigger")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)

    assert len(me.hand) == hand_before + 1, "トリガーで1枚引けていない"
    # draw 1 (deck-1) + mill 1 (deck-1) = deck-2
    assert len(me.deck) == deck_before - 2, \
        f"draw+mill でデッキが2枚減っていない: {len(me.deck)} (before {deck_before})"


# --------------------------------------------------------------------------- #
#  OP03-055 ゴムゴムの大槌 (EVENT 青 cost1):
#    【カウンター】手札1枚を捨てることができる：自リーダー1枚まで +4000。
#                 その後、自デッキ上2枚をトラッシュ (任意)。
#    【トリガー】相手のコスト4以下のキャラ1枚までを、持ち主の手札に戻す。
# --------------------------------------------------------------------------- #
def test_op03_055_counter_optional_cost_pump_ai():
    """【カウンター】手札1捨て → 自リーダー +4000 (AI: cost 払える為 自動発動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]  # 捨てるコスト用
    power_before = me.leader.power
    hand_before = len(me.hand)

    eff = _get_eff(overlay, "OP03-055", "counter")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 4000, \
        f"任意コスト後の +4000 が自リーダーに反映されていない: {me.leader.power}"
    assert len(me.hand) == hand_before - 1, "任意コストで手札1枚が捨てられていない"


def test_op03_055_counter_optional_cost_human_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]

    eff = _get_eff(overlay, "OP03-055", "counter")
    execute_effect(eff["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 任意コストで確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    # 承諾 (= 払って発動) して解決
    power_before = me.leader.power
    resolve_pending_choice(st, [1])
    _drain(st, [0])
    assert me.leader.power == power_before + 4000, \
        "人間承諾後 自リーダーに +4000 が反映されていない"


def test_op03_055_trigger_bounce_cost_le4_ai():
    """【トリガー】相手コスト4以下キャラ 1 枚を手札に戻す (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-005"), sickness=False)  # ウタ cost4 (<=4)
    opp.characters = [victim]
    opp_hand_before = len(opp.hand)

    eff = _get_eff(overlay, "OP03-055", "trigger")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)

    assert victim not in opp.characters, "相手コスト4以下キャラが手札に戻っていない"
    assert len(opp.hand) == opp_hand_before + 1, "戻したキャラが持ち主の手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP03-057 三・千・世・界 (EVENT 青 cost4):
#    【メイン】コスト5以下のキャラ1枚までを、持ち主のデッキの下に置く。
#    【トリガー】コスト3以下のキャラ1枚までを、持ち主のデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op03_057_main_return_deck_bottom_cost_le5_ai():
    """【メイン】相手コスト5以下キャラを持ち主デッキ底へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-005"), sickness=False)  # ウタ cost4 (<=5)
    opp.characters = [victim]
    opp_deck_before = len(opp.deck)

    eff = _get_eff(overlay, "OP03-057", "main")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)

    assert victim not in opp.characters, "相手コスト5以下キャラがデッキ底に送られていない"
    assert len(opp.deck) == opp_deck_before + 1, "戻したキャラが持ち主デッキに加わっていない"


def test_op03_057_trigger_return_deck_bottom_ai():
    """【トリガー】相手キャラを持ち主デッキ底へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2
    opp.characters = [victim]
    opp_deck_before = len(opp.deck)

    eff = _get_eff(overlay, "OP03-057", "trigger")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)

    assert victim not in opp.characters, "トリガーで相手キャラがデッキ底に送られていない"
    assert len(opp.deck) == opp_deck_before + 1, "戻したキャラが持ち主デッキに加わっていない"


def test_op03_057_main_return_human_pick():
    """人間 + 相手キャラ複数 → return_to_deck_bottom の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2
    b = InPlay.of(repo.get("OP01-005"), sickness=False)   # ウタ cost4
    opp.characters = [a, b]

    eff = _get_eff(overlay, "OP03-057", "main")
    execute_effect(eff["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b not in opp.characters, "人間が選んだ相手キャラがデッキ底に送られていない"
    assert a in opp.characters, "選ばなかった相手キャラは場に残る"


# --------------------------------------------------------------------------- #
#  OP03-060 カリファ (CHARACTER 紫 cost4):
#    【アタック時】ドン!!-1：カード2枚を引き、自分の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op03_060_kalifa_attack_draw2_discard1_ai():
    """【アタック時】カード2枚引き + 手札1枚捨て (AI 自動、 ドン返却コストは別ゲート)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP03-060"), sickness=False)
    me.characters = [src]
    me.hand = []
    deck_before = len(me.deck)

    eff = _get_eff(overlay, "OP03-060", "on_attack")
    assert eff.get("cost", {}).get("pay_don") == 1, \
        "overlay の ドン!!-1 コスト pay_don=1 が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, src)

    # draw2 (hand+2, deck-2) → discard1 (hand-1) = hand 1 / deck-2
    assert len(me.hand) == 1, f"draw2 + discard1 後の手札が1枚でない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 2, \
        f"2枚ドローでデッキが2枚減っていない: {len(me.deck)} (before {deck_before})"


# --------------------------------------------------------------------------- #
#  OP03-062 ココロ (CHARACTER 紫 cost1):
#    【登場時】自デッキ上5枚を見て「ココロ」以外の特徴《W7》1枚までを公開し手札に加える。
#              その後、残りを好きな順番でデッキ下に置く。
# --------------------------------------------------------------------------- #
def test_op03_062_kokoro_on_play_search_w7_ai():
    """【登場時】デッキ上5枚から W7 キャラ (トム) を手札に加える (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    tom = repo.get("OP13-069")  # トム 魚人族/W7
    assert "W7" in (tom.features or ""), "テスト前提: OP13-069 は W7"
    me.deck = [tom] + [repo.get("OP01-013")] * 20
    me.hand = []

    on_play = _get_eff(overlay, "OP03-062", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-062"), sickness=True))

    assert any(c.card_id == "OP13-069" for c in me.hand), \
        "デッキ上5枚から W7 キャラが手札に加わっていない"


def test_op03_062_kokoro_on_play_search_human_pick():
    """人間 + デッキ上5枚に W7 複数 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    tom = repo.get("OP13-069")
    me.deck = [tom, repo.get("OP01-013"), tom] + [repo.get("OP01-013")] * 15
    me.hand = []

    on_play = _get_eff(overlay, "OP03-062", "on_play")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP03-062"), sickness=True))

    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (トム) を選択
    _drain(st, [])
    assert any(c.card_id == "OP13-069" for c in me.hand), \
        "人間が選んだ W7 キャラが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP03-063 ザンバイ (CHARACTER 紫 cost3):
#    【ブロッカー】【登場時】ドン!!-1：自リーダーが特徴《W7》を持つ場合、カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op03_063_zambai_on_play_draw_when_w7_leader_ai():
    """【登場時】(リーダー W7) カード1枚引く (AI 自動、 ドン返却コストは別ゲート)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-058", overlay)  # アイスバーグ W7/GC リーダー
    me, opp = st.players[0], st.players[1]
    me.hand = []
    hand_before = len(me.hand)

    on_play = _get_eff(overlay, "OP03-063", "on_play")
    assert on_play.get("if", {}).get("leader_feature") == "W7", \
        "overlay の リーダー特徴 W7 条件が無い"
    assert eval_condition(on_play["if"], st, me) is True, \
        "テスト前提: リーダーが W7 で条件成立していない"
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-063"), sickness=True))

    assert len(me.hand) == hand_before + 1, "W7 リーダー時に1枚引けていない"


def test_op03_063_zambai_condition_false_when_not_w7():
    """リーダーが W7 を持たない場合、【登場時】条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ (W7でない)
    me, opp = st.players[0], st.players[1]
    on_play = _get_eff(overlay, "OP03-063", "on_play")
    assert eval_condition(on_play["if"], st, me) is False, \
        "リーダーが W7 でないのに条件が成立している"


# --------------------------------------------------------------------------- #
#  OP03-064 タイルストン (CHARACTER 紫 cost5):
#    【KO時】自リーダーが特徴《GC》を持つ場合、ドンデッキからドン!!1枚までをレストで追加。
# --------------------------------------------------------------------------- #
def test_op03_064_tilestone_on_ko_add_rested_don_when_gc_ai():
    """【KO時】(リーダー GC) ドンデッキからレストドン1枚を追加 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-058", overlay)  # アイスバーグ W7/GC リーダー
    me, opp = st.players[0], st.players[1]
    rested_before = me.don_rested
    deck_don_before = me.don_remaining_in_deck

    eff = _get_eff(overlay, "OP03-064", "on_ko")
    assert eff.get("if", {}).get("leader_feature") == "GC", \
        "overlay の リーダー特徴 GC 条件が無い"
    assert eval_condition(eff["if"], st, me) is True, \
        "テスト前提: リーダーが GC で条件成立していない"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-064"), sickness=False))

    assert me.don_rested == rested_before + 1, \
        f"KO時に レストドンが1枚追加されていない: {me.don_rested} (before {rested_before})"
    assert me.don_remaining_in_deck == deck_don_before - 1, \
        "ドンデッキから1枚が引かれていない"


def test_op03_064_tilestone_condition_false_when_not_gc():
    """リーダーが GC を持たない場合、【KO時】条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ (GCでない)
    me, opp = st.players[0], st.players[1]
    eff = _get_eff(overlay, "OP03-064", "on_ko")
    assert eval_condition(eff["if"], st, me) is False, \
        "リーダーが GC でないのに条件が成立している"


# --------------------------------------------------------------------------- #
#  OP03-066 パウリー (CHARACTER 紫 cost5):
#    【登場時】②：ドンデッキからドン!!1枚までをアクティブで追加。
#              その後、自分の場にドン!!が8枚以上ある場合、相手のコスト4以下のキャラ1枚をKO。
# --------------------------------------------------------------------------- #
def test_op03_066_pauley_on_play_add_don_and_ko_when_don_ge8_ai():
    """【登場時】ドン1アクティブ追加 → 場ドン8枚以上で相手コスト4以下キャラをKO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 7          # add_don 1 で 8 枚 (= self_don_ge 8 成立)
    me.don_remaining_in_deck = 10
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost1 (<=4)
    opp.characters = [victim]

    on_play = _get_eff(overlay, "OP03-066", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-066"), sickness=True))

    assert me.don_active == 8, f"ドン1アクティブ追加後の場ドンが8でない: {me.don_active}"
    assert victim not in opp.characters, \
        "場ドン8枚以上で相手コスト4以下キャラが KO されていない"


def test_op03_066_pauley_no_ko_when_don_lt8():
    """場ドンが8枚未満なら KO 条件が不成立 → 相手キャラは残る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3          # add_don 1 で 4 枚 (< 8)
    me.don_remaining_in_deck = 10
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost1
    opp.characters = [victim]

    on_play = _get_eff(overlay, "OP03-066", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-066"), sickness=True))

    assert me.don_active == 4, f"ドン1アクティブ追加後の場ドンが4でない: {me.don_active}"
    assert victim in opp.characters, \
        "場ドン8枚未満では相手キャラが KO されてはいけない"
