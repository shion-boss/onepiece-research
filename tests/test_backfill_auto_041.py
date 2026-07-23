# -*- coding: utf-8 -*-
"""OP03 弾 (黒 CP9・CP7・海軍) 効果 回帰テスト バックフィル (自動生成 wave 041):
OP03-080 / OP03-081 / OP03-083 / OP03-086 / OP03-088 / OP03-089 /
OP03-090 / OP03-091 / OP03-092 / OP03-093 の 10 枚。

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
def test_all_op03_wave41_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP03-080", "OP03-081", "OP03-083", "OP03-086", "OP03-088",
           "OP03-089", "OP03-090", "OP03-091", "OP03-092", "OP03-093"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP03-080 カク (CHARACTER 黒 cost5):
#    【登場時】自分のトラッシュの『CP』を含む特徴を持つカード2枚を好きな順番で
#      デッキの下に置くことができる：相手のコスト3以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op03_080_kaku_on_play_trash_cost_ko_ai():
    """【登場時】トラッシュCP2枚をデッキ下に戻す任意コスト → 相手コスト3以下キャラをKO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    # トラッシュに CP9 特徴カード 2 枚 (= コスト支払い元)
    me.trash = [repo.get("OP03-088"), repo.get("OP03-088")]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2 (<=3)
    opp.characters = [victim]
    deck_before = len(me.deck)

    on_play = _get_eff(overlay, "OP03-080", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-080"), sickness=True))

    assert victim not in opp.characters, "相手コスト3以下キャラが KO されていない"
    assert len(me.trash) == 0, "コストで CP2枚がトラッシュから抜けていない"
    assert len(me.deck) == deck_before + 2, "戻した CP2枚がデッキ下に加わっていない"


def test_op03_080_kaku_no_fire_without_cp_trash():
    """トラッシュに CP カードが 2 枚無ければ 任意コスト不能 → KO は起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP03-088")]  # CP は 1 枚のみ (limit 2 に足りない)
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [victim]

    on_play = _get_eff(overlay, "OP03-080", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-080"), sickness=True))

    assert victim in opp.characters, "CP2枚が払えないのに KO が起きている"


def test_op03_080_kaku_on_play_human_optional_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、承諾で KO 発動。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP03-088"), repo.get("OP03-088")]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [victim]

    on_play = _get_eff(overlay, "OP03-080", "on_play")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP03-080"), sickness=True))

    assert st.pending_choice is not None, "人間 + 任意コストで確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert victim not in opp.characters, "人間承諾後 相手キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP03-081 カリファ (CHARACTER 黒 cost4):
#    【登場時】カード2枚を引き、自分の手札2枚を捨てる。
#      その後、相手のキャラ1枚までを、このターン中、コスト-2。
# --------------------------------------------------------------------------- #
def test_op03_081_kalifa_on_play_draw_discard_cost_minus_ai():
    """【登場時】2ドロー + 手札2捨て + 相手キャラ1体を コスト-2 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    deck_before = len(me.deck)
    victim = InPlay.of(repo.get("OP01-005"), sickness=False)  # ウタ cost4
    opp.characters = [victim]
    cost_before = victim.base_cost  # 4

    on_play = _get_eff(overlay, "OP03-081", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-081"), sickness=True))

    # draw2 (hand+2 deck-2) → discard2 (hand-2) = hand 0 / deck -2
    assert len(me.hand) == 0, f"2ドロー + 2捨て後の手札が0枚でない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 2, \
        f"2ドローでデッキが2枚減っていない: {len(me.deck)} (before {deck_before})"
    assert victim.base_cost == cost_before - 2, \
        f"相手キャラのコストが -2 されていない: {victim.base_cost} (before {cost_before})"


def test_op03_081_kalifa_cost_minus_human_pick():
    """人間 + 相手キャラ 複数 → コスト-2 の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2
    b = InPlay.of(repo.get("OP01-005"), sickness=False)   # ウタ cost4
    opp.characters = [a, b]

    # cost_minus プリミティブ (do の末尾) を直接発火
    on_play = _get_eff(overlay, "OP03-081", "on_play")
    cost_minus_prim = next(p for p in on_play["do"] if "cost_minus" in p)
    execute_effect(cost_minus_prim, st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.base_cost
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b.base_cost == b_before - 2, "人間が選んだ相手キャラのコストが -2 されていない"
    assert a.base_cost == a.card.cost, "選ばなかった相手キャラのコストは変わらない"


# --------------------------------------------------------------------------- #
#  OP03-083 コーギー (CHARACTER 黒 cost1):
#    【登場時】自分のデッキの上から5枚を見て、カード2枚までを、トラッシュに置く。
#      その後、残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op03_083_corgy_on_play_mill_top5_ai():
    """【登場時】デッキ上5枚から2枚をトラッシュ、 残り3枚をデッキ下 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP01-013")] * 20
    trash_before = len(me.trash)
    deck_before = len(me.deck)

    on_play = _get_eff(overlay, "OP03-083", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-083"), sickness=True))

    assert len(me.trash) == trash_before + 2, \
        f"上5枚から2枚がトラッシュに置かれていない: {len(me.trash)}"
    # 上5枚 除去 → 2枚 trash / 3枚 デッキ下 = net -2
    assert len(me.deck) == deck_before - 2, \
        f"デッキ枚数 net (-2) が合わない: {len(me.deck)} (before {deck_before})"


def test_op03_083_corgy_on_play_human_search_modal():
    """人間 actor: デッキ上5枚を公開して選ばせる search_top_n modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP01-013")] * 20

    on_play = _get_eff(overlay, "OP03-083", "on_play")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP03-083"), sickness=True))

    assert st.pending_choice is not None, "人間 + デッキ有りで search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    _drain(st, [0])  # 解決できること (crash しない)


# --------------------------------------------------------------------------- #
#  OP03-086 スパンダム (CHARACTER 黒 cost1):
#    【登場時】自分のリーダーが『CP』を含む特徴を持つ場合、デッキ上3枚を見て、
#      「スパンダム」以外の『CP』を含む特徴を持つカード1枚までを公開し手札に加える。
#      その後、残りをトラッシュに置く。
# --------------------------------------------------------------------------- #
def test_op03_086_spandam_on_play_search_cp_to_hand_ai():
    """【登場時】(リーダー CP) デッキ上3枚から CP カードを手札へ、 残りをトラッシュ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-076", overlay)  # ロブ・ルッチ (CP9) リーダー
    me, opp = st.players[0], st.players[1]
    cp_card = repo.get("OP03-088")  # フクロウ CP9 (スパンダム以外)
    me.deck = [cp_card] + [repo.get("OP01-013")] * 20
    me.hand = []

    on_play = _get_eff(overlay, "OP03-086", "on_play")
    assert on_play.get("if", {}).get("leader_feature_contains") == "CP", \
        "overlay の リーダー特徴 CP 条件が無い"
    assert eval_condition(on_play["if"], st, me) is True, \
        "テスト前提: リーダーが CP で条件成立していない"
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-086"), sickness=True))

    assert any(c.card_id == "OP03-088" for c in me.hand), \
        "デッキ上3枚から CP カードが手札に加わっていない"


def test_op03_086_spandam_condition_false_when_not_cp_leader():
    """リーダーが『CP』特徴を持たない場合、【登場時】条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ (CPでない)
    me, opp = st.players[0], st.players[1]
    on_play = _get_eff(overlay, "OP03-086", "on_play")
    assert eval_condition(on_play["if"], st, me) is False, \
        "リーダーが CP でないのに条件が成立している"


# --------------------------------------------------------------------------- #
#  OP03-088 フクロウ (CHARACTER 黒 cost3):
#    このキャラは効果でKOされない。【ブロッカー】
# --------------------------------------------------------------------------- #
def test_op03_088_fukurou_static_ko_immune():
    """静的効果: フクロウは効果KO耐性 (static_ko_immune) を常在で得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    fukurou = InPlay.of(repo.get("OP03-088"), sickness=False)
    me.characters = [fukurou]
    assert fukurou.static_ko_immune is False, "評価前は KO 耐性が立っていないはず"

    evaluate_static_effects(st, overlay)

    assert fukurou.static_ko_immune is True, \
        "常在の効果KO耐性 (static_ko_immune) が立っていない"


def test_op03_088_fukurou_intrinsic_blocker():
    """フクロウは【ブロッカー】を印刷で持つ (is_blocker_now)。"""
    repo = _repo()
    fukurou = InPlay.of(_repo().get("OP03-088"), sickness=False)
    assert fukurou.is_blocker_now is True, "印刷ブロッカーが is_blocker_now に反映されていない"


# --------------------------------------------------------------------------- #
#  OP03-089 ブランニュー (CHARACTER 黒 cost2):
#    【登場時】デッキ上3枚を見て、「ブランニュー」以外の特徴《海軍》1枚までを公開し
#      手札に加える。その後、残りをトラッシュに置く。
# --------------------------------------------------------------------------- #
def test_op03_089_brannew_on_play_search_navy_to_hand_ai():
    """【登場時】デッキ上3枚から 海軍キャラ1枚を手札へ、 残りをトラッシュ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    navy = repo.get("OP05-052")  # メイナード 海軍 (ブランニュー以外)
    assert "海軍" in (navy.features or ()), "テスト前提: OP05-052 は 海軍"
    me.deck = [navy] + [repo.get("OP01-013")] * 20
    me.hand = []

    on_play = _get_eff(overlay, "OP03-089", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-089"), sickness=True))

    assert any(c.card_id == "OP05-052" for c in me.hand), \
        "デッキ上3枚から 海軍キャラが手札に加わっていない"


def test_op03_089_brannew_on_play_human_search_modal():
    """人間 actor: デッキ上3枚に 海軍 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    navy = repo.get("OP05-052")
    me.deck = [navy, repo.get("OP01-013"), navy] + [repo.get("OP01-013")] * 15
    me.hand = []

    on_play = _get_eff(overlay, "OP03-089", "on_play")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP03-089"), sickness=True))

    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (メイナード) を選択
    _drain(st, [])
    assert any(c.card_id == "OP05-052" for c in me.hand), \
        "人間が選んだ 海軍キャラが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP03-090 ブルーノ (CHARACTER 黒 cost5):
#    【ドン!!×1】このキャラは【ブロッカー】を得る。
#    【KO時】自分のトラッシュからコスト4以下の『CP』を含む特徴を持つキャラカード
#      1枚までを、レストで登場させる。
# --------------------------------------------------------------------------- #
def test_op03_090_bruno_on_ko_play_from_trash_ai():
    """【KO時】トラッシュから CP コスト4以下キャラを レストで登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP03-088")]  # フクロウ CP9 cost3 (<=4)
    chars_before = len(me.characters)

    on_ko = _get_eff(overlay, "OP03-090", "on_ko")
    for prim in on_ko["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-090"), sickness=False))

    played = [c for c in me.characters if c.card.card_id == "OP03-088"]
    assert len(played) == 1, "トラッシュから CP キャラが登場していない"
    assert played[0].rested is True, "登場したキャラがレストになっていない"
    assert len(me.characters) == chars_before + 1, "キャラが1体増えていない"


def test_op03_090_bruno_don1_grants_blocker_static():
    """【ドン!!×1】静的: ドン付与1で【ブロッカー】を得る / 0枚では得ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    bruno = InPlay.of(repo.get("OP03-090"), sickness=False)  # 印刷ブロッカーは無い
    me.characters = [bruno]

    bruno.attached_dons = 0
    evaluate_static_effects(st, overlay)
    assert bruno.is_blocker_now is False, "ドン0枚で【ブロッカー】が付与されている"

    bruno.attached_dons = 1
    evaluate_static_effects(st, overlay)
    assert bruno.is_blocker_now is True, "ドン!!×1で【ブロッカー】が付与されていない"


# --------------------------------------------------------------------------- #
#  OP03-091 ヘルメッポ (CHARACTER 黒 cost1):
#    【登場時】相手の元々の効果のないキャラ1枚までを、このターン中、コスト0にする。
# --------------------------------------------------------------------------- #
def test_op03_091_helmeppo_on_play_set_cost0_no_effect_ai():
    """【登場時】相手の元々効果なしキャラ1体を コスト0 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP04-077"), sickness=False)  # イデオ cost2 (効果なし)
    opp.characters = [victim]
    assert victim.base_cost == 2, "テスト前提: イデオの初期コストは2"

    on_play = _get_eff(overlay, "OP03-091", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-091"), sickness=True))

    assert victim.base_cost == 0, \
        f"相手の効果なしキャラが コスト0 になっていない: {victim.base_cost}"


def test_op03_091_helmeppo_on_play_human_pick():
    """人間 + 相手の効果なしキャラ 複数 → target_pick modal が立ち resolve で コスト0。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP04-077"), sickness=False)  # イデオ cost2 (効果なし)
    b = InPlay.of(repo.get("OP05-052"), sickness=False)   # メイナード cost2 (効果なし)
    opp.characters = [a, b]

    on_play = _get_eff(overlay, "OP03-091", "on_play")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP03-091"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b.base_cost == 0, "人間が選んだ相手キャラが コスト0 になっていない"
    assert a.base_cost == a.card.cost, "選ばなかった相手キャラのコストは変わらない"


# --------------------------------------------------------------------------- #
#  OP03-092 ロブ・ルッチ (CHARACTER 黒 cost6):
#    【登場時】自分のトラッシュの『CP』を含む特徴を持つカード2枚を好きな順番で
#      デッキの下に置くことができる：このキャラは、このターン中、【速攻】を得る。
# --------------------------------------------------------------------------- #
def test_op03_092_rob_lucci_on_play_trash_cost_give_rush_ai():
    """【登場時】トラッシュCP2枚をデッキ下に戻す任意コスト → 自身に【速攻】付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP03-088"), repo.get("OP03-088")]  # CP9 ×2
    lucci = InPlay.of(repo.get("OP03-092"), sickness=True)
    me.characters = [lucci]
    deck_before = len(me.deck)

    on_play = _get_eff(overlay, "OP03-092", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp, lucci)

    assert lucci.is_rush_now is True, "任意コスト後に【速攻】が付与されていない"
    assert len(me.trash) == 0, "コストで CP2枚がトラッシュから抜けていない"
    assert len(me.deck) == deck_before + 2, "戻した CP2枚がデッキ下に加わっていない"


def test_op03_092_rob_lucci_no_rush_without_cp_trash():
    """トラッシュに CP が 2 枚無ければ 任意コスト不能 → 【速攻】は付与されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = []  # CP なし
    lucci = InPlay.of(repo.get("OP03-092"), sickness=True)
    me.characters = [lucci]

    on_play = _get_eff(overlay, "OP03-092", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp, lucci)

    assert lucci.is_rush_now is False, "CP2枚が払えないのに【速攻】が付与されている"


def test_op03_092_rob_lucci_on_play_human_optional_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、承諾で【速攻】付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP03-088"), repo.get("OP03-088")]
    lucci = InPlay.of(repo.get("OP03-092"), sickness=True)
    me.characters = [lucci]

    on_play = _get_eff(overlay, "OP03-092", "on_play")
    execute_effect(on_play["do"][0], st, me, opp, lucci)

    assert st.pending_choice is not None, "人間 + 任意コストで確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert lucci.is_rush_now is True, "人間承諾後に【速攻】が付与されていない"


# --------------------------------------------------------------------------- #
#  OP03-093 ワンゼ (CHARACTER 黒 cost2):
#    【登場時】自分の手札1枚を捨てることができる：自分のリーダーが『CP』を含む
#      特徴を持つ場合、相手のコスト1以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op03_093_wanze_on_play_discard_cost_ko_ai():
    """【登場時】(リーダー CP) 手札1捨て → 相手コスト1以下キャラをKO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-076", overlay)  # ロブ・ルッチ (CP9) リーダー
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]  # 捨てるコスト用
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost1 (<=1)
    opp.characters = [victim]
    hand_before = len(me.hand)

    on_play = _get_eff(overlay, "OP03-093", "on_play")
    assert on_play.get("if", {}).get("leader_feature_contains") == "CP", \
        "overlay の リーダー特徴 CP 条件が無い"
    assert eval_condition(on_play["if"], st, me) is True, \
        "テスト前提: リーダーが CP で条件成立していない"
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-093"), sickness=True))

    assert victim not in opp.characters, "相手コスト1以下キャラが KO されていない"
    assert len(me.hand) == hand_before - 1, "任意コストで手札1枚が捨てられていない"


def test_op03_093_wanze_condition_false_when_not_cp_leader():
    """リーダーが『CP』特徴を持たない場合、【登場時】条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ (CPでない)
    me, opp = st.players[0], st.players[1]
    on_play = _get_eff(overlay, "OP03-093", "on_play")
    assert eval_condition(on_play["if"], st, me) is False, \
        "リーダーが CP でないのに条件が成立している"


def test_op03_093_wanze_on_play_human_optional_confirm():
    """人間 actor: 任意コスト (手札1捨て) → optional_cost_confirm modal が立ち、承諾で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-076", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost1
    opp.characters = [victim]

    on_play = _get_eff(overlay, "OP03-093", "on_play")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP03-093"), sickness=True))

    assert st.pending_choice is not None, "人間 + 任意コストで確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert victim not in opp.characters, "人間承諾後 相手キャラが KO されていない"
