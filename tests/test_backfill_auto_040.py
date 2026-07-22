# -*- coding: utf-8 -*-
"""OP03 弾 (紫 W7・GC・インペルダウン ドン操作 / 黒 CP9・海軍) 効果 回帰テスト
バックフィル (自動生成 wave 040):
OP03-067 / OP03-068 / OP03-069 / OP03-070 / OP03-071 / OP03-072 /
OP03-073 / OP03-074 / OP03-076 / OP03-078 の 10 枚。

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
def test_all_op03_wave40_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP03-067", "OP03-068", "OP03-069", "OP03-070", "OP03-071",
           "OP03-072", "OP03-073", "OP03-074", "OP03-076", "OP03-078"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP03-067 ピープリー・ルル (CHARACTER 紫 cost5):
#    【ドン!!×1】【アタック時】自リーダーが特徴《GC》を持つ場合、
#              ドン!!デッキからドン!!1枚までを、レストで追加する。
# --------------------------------------------------------------------------- #
def test_op03_067_lulu_attack_add_rested_don_when_gc_ai():
    """【アタック時】(リーダー GC + ドン!!×1) レストドン1枚を追加 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-058", overlay)  # アイスバーグ W7/GC リーダー
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP03-067"), sickness=False)
    src.attached_dons = 1  # ドン!!×1 ゲート成立
    me.characters = [src]
    rested_before = me.don_rested
    deck_don_before = me.don_remaining_in_deck

    eff = _get_eff(overlay, "OP03-067", "on_attack")
    assert eff.get("if", {}).get("leader_feature") == "GC", \
        "overlay の リーダー特徴 GC 条件が無い"
    assert eval_condition(eff["if"], st, me, src) is True, \
        "テスト前提: リーダー GC + ドン1 で条件成立していない"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, src)

    assert me.don_rested == rested_before + 1, \
        f"アタック時に レストドンが1枚追加されていない: {me.don_rested} (before {rested_before})"
    assert me.don_remaining_in_deck == deck_don_before - 1, \
        "ドンデッキから1枚が引かれていない"


def test_op03_067_lulu_condition_false_when_not_gc():
    """リーダーが GC を持たない場合、【アタック時】条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ (GCでない)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP03-067"), sickness=False)
    src.attached_dons = 1
    me.characters = [src]
    eff = _get_eff(overlay, "OP03-067", "on_attack")
    assert eval_condition(eff["if"], st, me, src) is False, \
        "リーダーが GC でないのに条件が成立している"


# --------------------------------------------------------------------------- #
#  OP03-068 ミノゼブラ (CHARACTER 紫 cost4):
#    【バニッシュ】【KO時】自リーダーが特徴《インペルダウン》を持つ場合、
#              ドン!!デッキからドン!!1枚までを、レストで追加する。
# --------------------------------------------------------------------------- #
def test_op03_068_minozebra_on_ko_add_rested_don_when_impel_ai():
    """【KO時】(リーダー インペルダウン) レストドン1枚を追加 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB01-021", overlay)  # ハンニャバル インペルダウン リーダー
    me, opp = st.players[0], st.players[1]
    rested_before = me.don_rested
    deck_don_before = me.don_remaining_in_deck

    eff = _get_eff(overlay, "OP03-068", "on_ko")
    assert eff.get("if", {}).get("leader_feature") == "インペルダウン", \
        "overlay の リーダー特徴 インペルダウン 条件が無い"
    assert eval_condition(eff["if"], st, me) is True, \
        "テスト前提: リーダーが インペルダウン で条件成立していない"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-068"), sickness=False))

    assert me.don_rested == rested_before + 1, \
        f"KO時に レストドンが1枚追加されていない: {me.don_rested} (before {rested_before})"
    assert me.don_remaining_in_deck == deck_don_before - 1, \
        "ドンデッキから1枚が引かれていない"


def test_op03_068_minozebra_condition_false_when_not_impel():
    """リーダーが インペルダウン を持たない場合、【KO時】条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ (インペルダウンでない)
    me, opp = st.players[0], st.players[1]
    eff = _get_eff(overlay, "OP03-068", "on_ko")
    assert eval_condition(eff["if"], st, me) is False, \
        "リーダーが インペルダウン でないのに条件が成立している"


# --------------------------------------------------------------------------- #
#  OP03-069 ミノリノケロス (CHARACTER 紫 cost3):
#    【KO時】自リーダーが特徴《インペルダウン》を持つ場合、カード2枚を引き、手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op03_069_minorinokerosu_on_ko_draw2_discard1_ai():
    """【KO時】(リーダー インペルダウン) カード2枚引き + 手札1枚捨て (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB01-021", overlay)  # ハンニャバル インペルダウン リーダー
    me, opp = st.players[0], st.players[1]
    me.hand = []
    deck_before = len(me.deck)

    eff = _get_eff(overlay, "OP03-069", "on_ko")
    assert eff.get("if", {}).get("leader_feature") == "インペルダウン", \
        "overlay の リーダー特徴 インペルダウン 条件が無い"
    assert eval_condition(eff["if"], st, me) is True, \
        "テスト前提: リーダーが インペルダウン で条件成立していない"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-069"), sickness=False))

    # draw2 (hand+2, deck-2) → discard1 (hand-1) = hand 1 / deck-2
    assert len(me.hand) == 1, f"draw2 + discard1 後の手札が1枚でない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 2, \
        f"2枚ドローでデッキが2枚減っていない: {len(me.deck)} (before {deck_before})"


def test_op03_069_minorinokerosu_condition_false_when_not_impel():
    """リーダーが インペルダウン を持たない場合、【KO時】条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    eff = _get_eff(overlay, "OP03-069", "on_ko")
    assert eval_condition(eff["if"], st, me) is False, \
        "リーダーが インペルダウン でないのに条件が成立している"


# --------------------------------------------------------------------------- #
#  OP03-070 モンキー・D・ルフィ (CHARACTER 紫 cost6):
#    【登場時】ドン!!-1，自分の手札からコスト5のキャラカード1枚を捨てることができる：
#             このキャラは、このターン中、【速攻】を得る。
# --------------------------------------------------------------------------- #
def test_op03_070_luffy_on_play_optional_cost_give_rush_ai():
    """【登場時】ドン返却 + コスト5キャラ1枚捨て → 自身に【速攻】付与 (AI: cost 払える為 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 2  # ドン!!-1 用
    me.hand = [repo.get("EB04-016")]  # トリ (コスト5 CHARACTER) = 捨てるコスト
    luffy = InPlay.of(repo.get("OP03-070"), sickness=True)
    me.characters = [luffy]
    hand_before = len(me.hand)

    on_play = _get_eff(overlay, "OP03-070", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp, luffy)

    assert "速攻" in luffy.granted_keywords, \
        f"任意コスト後に【速攻】が付与されていない: {luffy.granted_keywords}"
    assert len(me.hand) == hand_before - 1, "コストでコスト5キャラが1枚捨てられていない"


def test_op03_070_luffy_no_rush_when_no_cost5_char():
    """手札にコスト5キャラが無ければ cost 不能 → 【速攻】は付与されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 2
    me.hand = [repo.get("OP01-013")]  # サンジ cost2 = コスト5でない
    luffy = InPlay.of(repo.get("OP03-070"), sickness=True)
    me.characters = [luffy]

    on_play = _get_eff(overlay, "OP03-070", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp, luffy)

    assert "速攻" not in luffy.granted_keywords, \
        "コスト5キャラが無いのに【速攻】が付与されている"


def test_op03_070_luffy_on_play_human_optional_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、承諾で【速攻】付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_active = 2
    me.hand = [repo.get("EB04-016")]  # コスト5 キャラ
    luffy = InPlay.of(repo.get("OP03-070"), sickness=True)
    me.characters = [luffy]

    on_play = _get_eff(overlay, "OP03-070", "on_play")
    execute_effect(on_play["do"][0], st, me, opp, luffy)

    assert st.pending_choice is not None, "人間 + 任意コストで確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾 (= 払って発動)
    _drain(st, [0])
    assert "速攻" in luffy.granted_keywords, \
        "人間承諾後に【速攻】が付与されていない"


# --------------------------------------------------------------------------- #
#  OP03-071 ロブ・ルッチ (CHARACTER 紫 cost5):
#    【アタック時】ドン!!-1：相手のコスト5以下のキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_op03_071_rob_lucci_attack_rest_cost_le5_ai():
    """【アタック時】相手コスト5以下キャラ1枚をレスト (AI 自動、 ドン返却コストは別ゲート)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP03-071"), sickness=False)
    me.characters = [src]
    victim = InPlay.of(repo.get("OP01-005"), sickness=False)  # ウタ cost4 (<=5)
    victim.rested = False
    opp.characters = [victim]

    eff = _get_eff(overlay, "OP03-071", "on_attack")
    assert eff.get("cost", {}).get("pay_don") == 1, \
        "overlay の ドン!!-1 コスト pay_don=1 が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, src)

    assert victim.rested is True, "相手コスト5以下キャラがレストされていない"


def test_op03_071_rob_lucci_attack_rest_human_pick():
    """人間 + 相手コスト5以下キャラ 複数 → target_pick modal が立ち resolve で 1 体レスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP03-071"), sickness=False)
    me.characters = [src]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2
    b = InPlay.of(repo.get("OP01-005"), sickness=False)   # ウタ cost4
    a.rested = False
    b.rested = False
    opp.characters = [a, b]

    eff = _get_eff(overlay, "OP03-071", "on_attack")
    execute_effect(eff["do"][0], st, me, opp, src)

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b.rested is True, "人間が選んだ相手キャラがレストされていない"
    assert a.rested is False, "選ばなかった相手キャラはアクティブのまま"


# --------------------------------------------------------------------------- #
#  OP03-072 ゴムゴムのJET銃乱打 (EVENT 紫):
#    【カウンター】自分の手札1枚を捨てることができる：自分のリーダーかキャラ1枚まで、+3000。
#    【トリガー】ドン!!デッキからドン!!1枚までを、アクティブで追加する。
# --------------------------------------------------------------------------- #
def test_op03_072_counter_optional_cost_pump_ai():
    """【カウンター】手札1捨て → 自リーダー +3000 (AI: cost 払える為 自動発動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]  # 捨てるコスト用
    power_before = me.leader.power
    hand_before = len(me.hand)

    eff = _get_eff(overlay, "OP03-072", "counter")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 3000, \
        f"任意コスト後の +3000 が自リーダーに反映されていない: {me.leader.power}"
    assert len(me.hand) == hand_before - 1, "任意コストで手札1枚が捨てられていない"


def test_op03_072_counter_optional_cost_human_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]

    eff = _get_eff(overlay, "OP03-072", "counter")
    execute_effect(eff["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 任意コストで確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    power_before = me.leader.power
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert me.leader.power == power_before + 3000, \
        "人間承諾後 自リーダーに +3000 が反映されていない"


def test_op03_072_trigger_add_active_don_ai():
    """【トリガー】ドンデッキからアクティブドン1枚を追加 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    active_before = me.don_active
    deck_don_before = me.don_remaining_in_deck

    eff = _get_eff(overlay, "OP03-072", "trigger")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)

    assert me.don_active == active_before + 1, \
        f"トリガーでアクティブドンが1枚追加されていない: {me.don_active}"
    assert me.don_remaining_in_deck == deck_don_before - 1, \
        "ドンデッキから1枚が引かれていない"


# --------------------------------------------------------------------------- #
#  OP03-073 船底解体斬り (EVENT 紫 cost1):
#    【メイン】ドン!!-1：自リーダーが特徴《W7》を持つ場合、相手のコスト2以下のキャラ1枚までを、KOする。
#    【トリガー】このカードの【メイン】効果を発動する。
# --------------------------------------------------------------------------- #
def test_op03_073_main_ko_cost_le2_when_w7_ai():
    """【メイン】(リーダー W7) 相手コスト2以下キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-058", overlay)  # アイスバーグ W7/GC リーダー
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2 (<=2)
    opp.characters = [victim]

    eff = _get_eff(overlay, "OP03-073", "main")
    assert eff.get("if", {}).get("leader_feature") == "W7", \
        "overlay の リーダー特徴 W7 条件が無い"
    assert eval_condition(eff["if"], st, me) is True, \
        "テスト前提: リーダーが W7 で条件成立していない"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)

    assert victim not in opp.characters, "相手コスト2以下キャラが KO されていない"


def test_op03_073_condition_false_when_not_w7():
    """リーダーが W7 を持たない場合、【メイン】条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    eff = _get_eff(overlay, "OP03-073", "main")
    assert eval_condition(eff["if"], st, me) is False, \
        "リーダーが W7 でないのに条件が成立している"


def test_op03_073_main_ko_human_pick():
    """人間 + 相手コスト2以下キャラ 複数 → KO の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-058", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost1
    opp.characters = [a, b]

    eff = _get_eff(overlay, "OP03-073", "main")
    execute_effect(eff["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残る"


# --------------------------------------------------------------------------- #
#  OP03-074 独楽結び (EVENT 紫 cost2):
#    【メイン】ドン!!-2：相手のコスト4以下のキャラ1枚までを、持ち主のデッキの下に置く。
#    【トリガー】このカードの【メイン】効果を発動する。
# --------------------------------------------------------------------------- #
def test_op03_074_main_return_deck_bottom_cost_le4_ai():
    """【メイン】相手コスト4以下キャラを持ち主デッキ底へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-005"), sickness=False)  # ウタ cost4 (<=4)
    opp.characters = [victim]
    opp_deck_before = len(opp.deck)

    eff = _get_eff(overlay, "OP03-074", "main")
    assert eff.get("cost", {}).get("pay_don") == 2, \
        "overlay の ドン!!-2 コスト pay_don=2 が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)

    assert victim not in opp.characters, "相手コスト4以下キャラがデッキ底に送られていない"
    assert len(opp.deck) == opp_deck_before + 1, "戻したキャラが持ち主デッキに加わっていない"


def test_op03_074_main_return_human_pick():
    """人間 + 相手コスト4以下キャラ 複数 → return_to_deck_bottom の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2
    b = InPlay.of(repo.get("OP01-005"), sickness=False)   # ウタ cost4
    opp.characters = [a, b]

    eff = _get_eff(overlay, "OP03-074", "main")
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
#  OP03-076 ロブ・ルッチ (LEADER 黒 CP9):
#    【自分のターン中】【ターン1回】自分の手札2枚を捨てることができる：
#              相手のキャラがKOされた時、このリーダーをアクティブにする。
# --------------------------------------------------------------------------- #
def test_op03_076_rob_lucci_leader_untap_on_opp_ko_ai():
    """【相手キャラKO時】手札2枚捨て → 自リーダーをアクティブに (AI: cost 払える為 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-076", overlay)  # ロブ・ルッチ (CP9) リーダー自身
    me, opp = st.players[0], st.players[1]
    me.leader.rested = True  # レスト状態 → アクティブ化を検証
    me.hand = [repo.get("OP01-013"), repo.get("OP01-016")]  # 捨てるコスト用 2 枚
    hand_before = len(me.hand)

    eff = _get_eff(overlay, "OP03-076", "on_opp_chara_ko")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, me.leader)

    assert me.leader.rested is False, "手札2枚捨てで自リーダーがアクティブになっていない"
    assert len(me.hand) == hand_before - 2, "任意コストで手札2枚が捨てられていない"


def test_op03_076_rob_lucci_leader_untap_human_confirm():
    """人間 actor: 任意コスト (手札2捨て) → optional_cost_confirm modal が立ち、承諾でアクティブ化。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-076", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.leader.rested = True
    me.hand = [repo.get("OP01-013"), repo.get("OP01-016")]

    eff = _get_eff(overlay, "OP03-076", "on_opp_chara_ko")
    execute_effect(eff["do"][0], st, me, opp, me.leader)

    assert st.pending_choice is not None, "人間 + 任意コストで確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert me.leader.rested is False, "人間承諾後 自リーダーがアクティブになっていない"


# --------------------------------------------------------------------------- #
#  OP03-078 イッショウ (CHARACTER 黒 cost8):
#    【ドン!!×1】【自分のターン中】相手のキャラすべてをコスト-3。
#    【登場時】相手の手札が6枚以上ある場合、相手の手札2枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op03_078_issho_on_play_discard_opp_hand_when_ge6_ai():
    """【登場時】相手の手札6枚以上 → 相手の手札2枚を捨てる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.hand = [repo.get("OP01-013")] * 6  # 6 枚 (>=6 条件成立)
    hand_before = len(opp.hand)

    on_play = _get_eff(overlay, "OP03-078", "on_play")
    assert on_play.get("conditions", [{}])[0].get("opp_hand_count_ge") == 6, \
        "overlay の 相手手札6枚以上条件が無い"
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-078"), sickness=True))

    assert len(opp.hand) == hand_before - 2, \
        f"相手の手札が2枚捨てられていない: {len(opp.hand)} (before {hand_before})"


def test_op03_078_issho_static_opp_cost_minus3():
    """静的効果 (ドン!!×1 + 自ターン中): 相手キャラすべてを コスト-3。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    issho = InPlay.of(repo.get("OP03-078"), sickness=False)
    issho.attached_dons = 1  # ドン!!×1 ゲート成立
    me.characters = [issho]
    victim = InPlay.of(repo.get("OP01-005"), sickness=False)  # ウタ cost4
    opp.characters = [victim]
    cost_before = victim.card.cost  # 元コスト 4

    evaluate_static_effects(st, overlay)

    assert victim.base_cost == max(0, cost_before - 3), \
        f"相手キャラの現在コストが -3 されていない: {victim.base_cost} (元 {cost_before})"


def test_op03_078_issho_no_static_off_turn():
    """相手ターン中は【自分のターン中】条件が不成立 → コスト-3 は乗らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    st.turn_player_idx = 1  # 相手ターン → self_turn False
    me, opp = st.players[0], st.players[1]
    issho = InPlay.of(repo.get("OP03-078"), sickness=False)
    issho.attached_dons = 1
    me.characters = [issho]
    victim = InPlay.of(repo.get("OP01-005"), sickness=False)  # ウタ cost4
    opp.characters = [victim]

    evaluate_static_effects(st, overlay)

    assert victim.base_cost == victim.card.cost, \
        f"相手ターン中に コスト-3 が乗ってはいけない: {victim.base_cost}"
