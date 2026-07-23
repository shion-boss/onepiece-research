# -*- coding: utf-8 -*-
"""OP05 弾 効果 回帰テスト バックフィル (自動生成 wave 057):
OP05-040 / OP05-042 / OP05-043 / OP05-045 / OP05-046 / OP05-047 /
OP05-048 / OP05-049 / OP05-050 / OP05-051 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_056.py と同一方針):
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
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

# よく使うテスト用カード (テキストの前提固定)
_LEADER_NEUTRAL = "OP01-001"   # ロロノア・ゾロ (赤、 単色)
_LEADER_MULTI = "EB03-001"     # ネフェルタリ・ビビ (赤/青、 多色)
_NAMI = "OP01-016"             # ナミ cost1 power2000
_RED_C3 = "EB02-003"           # トニートニー・チョッパー cost3 power3000
_PLAIN_C2 = "ST01-004"         # サンジ cost2 power4000 (汎用ダミー)
_ISSHO_C6 = "OP05-042"         # イッショウ cost6 power6000 (cost>5 の耐性チェック用)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(_PLAIN_C2)] * 30
    p1.deck = [repo.get(_PLAIN_C2)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果の do (list) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e["do"]
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]["do"]


def _eff(overlay, cid, when):
    """when 一致の効果 dict (do + if を含む) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    return matches[0]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave57_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP05-040", "OP05-042", "OP05-043", "OP05-045", "OP05-046",
           "OP05-047", "OP05-048", "OP05-049", "OP05-050", "OP05-051"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP05-040 鳥カゴ (STAGE 緑 cost5 ドンキホーテ海賊団):
#    【自分のターン終了時】自分の場のドン!!が10枚ある場合、レストのコスト5以下の
#      キャラすべてを、KOする。 (overlay: ko any_opponent_character_cost_le_5、
#      条件 if self_don_ge=10)
# --------------------------------------------------------------------------- #
def test_op05_040_end_of_turn_ko_all_cost_le_5_ai():
    """ターン終了時 (ドン10枚条件): 相手のコスト5以下キャラすべてを KO。
    コスト6キャラは対象外で残る。 AI 文脈で自動解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP05-041", overlay)  # ドフラミンゴ leader (ドンキホーテ海賊団)
    me, opp = st.players[0], st.players[1]
    v1 = InPlay.of(repo.get(_NAMI), sickness=False)     # cost1 (<=5)
    v3 = InPlay.of(repo.get(_RED_C3), sickness=False)   # cost3 (<=5)
    v6 = InPlay.of(repo.get(_ISSHO_C6), sickness=False)  # cost6 (>5、 対象外)
    opp.characters = [v1, v3, v6]

    eff = _eff(overlay, "OP05-040", "end_of_turn")
    assert eff.get("if", {}).get("self_don_ge") == 10, \
        "overlay の 発火条件 self_don_ge=10 が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-040"), sickness=False))
    _drain(st)

    assert v1 not in opp.characters, "コスト1キャラが KO されていない"
    assert v3 not in opp.characters, "コスト3キャラが KO されていない"
    assert v6 in opp.characters, "コスト6キャラ (>5) は対象外で残るべき"


# --------------------------------------------------------------------------- #
#  OP05-042 イッショウ (CHARACTER 青 cost6 power6000 海軍):
#    【登場時】相手のコスト7以下のキャラ1枚までは、次の自分のターン開始時まで、
#      アタックできない。 (set_cannot_attack、 duration next_opp_turn_end)
# --------------------------------------------------------------------------- #
def test_op05_042_on_play_set_cannot_attack_ai():
    """登場時: 相手のコスト7以下キャラ1枚をアタック不可にする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_RED_C3), sickness=False)  # cost3 (<=7)
    opp.characters = [victim]

    for prim in _do(overlay, "OP05-042", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-042"), sickness=False))
    _drain(st, pick=[0])

    assert victim.cannot_attack_through_opp_turn is True, \
        "相手キャラが 次の相手ターン終了までアタック不可 になっていない"


def test_op05_042_on_play_human_pick():
    """人間 + 相手のコスト7以下キャラ複数 → set_cannot_attack の target_pick modal。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_NAMI), sickness=False)    # cost1
    b = InPlay.of(repo.get(_RED_C3), sickness=False)  # cost3
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP05-042", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP05-042"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[b_idx])
    assert b.cannot_attack_through_opp_turn is True, \
        "人間が選んだキャラがアタック不可になっていない"
    assert a.cannot_attack_through_opp_turn is False, \
        "選ばなかったキャラはアタック不可にならないべき"


# --------------------------------------------------------------------------- #
#  OP05-043 うるティ (CHARACTER 青 cost4 power5000 百獣海賊団):
#    【登場時】自分のリーダーが多色の場合、自分のデッキの上から3枚を見て、
#      1枚までを手札に加える。 その後、残りを並び替えデッキの上か下に置く。
# --------------------------------------------------------------------------- #
def test_op05_043_on_play_search_top_ai():
    """登場時 (多色リーダー): デッキ上3枚を見て1枚を手札へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MULTI, overlay)  # 多色リーダー
    me, opp = st.players[0], st.players[1]
    target = repo.get(_ISSHO_C6)  # 上に仕込む
    me.deck = [target] + [repo.get(_PLAIN_C2)] * 20
    me.hand = []

    for prim in _do(overlay, "OP05-043", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-043"), sickness=False))
    _drain(st, pick=[0])

    assert len(me.hand) == 1, "デッキ上3枚から1枚が手札に加わっていない"


def test_op05_043_on_play_human_search_flow():
    """人間 + 多色リーダー → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MULTI, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_ISSHO_C6), repo.get(_RED_C3), repo.get(_PLAIN_C2)] \
        + [repo.get(_PLAIN_C2)] * 15
    me.hand = []

    execute_effect(_do(overlay, "OP05-043", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP05-043"), sickness=False))

    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭を手札に
    _drain(st)
    assert len(me.hand) == 1, "人間が選んだ1枚が手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP05-045 ステンレス (CHARACTER 青 cost4 power5000 海軍):
#    【起動メイン】自分の手札1枚を捨て、このキャラをレストにできる：
#      コスト2以下のキャラ1枚までを、持ち主のデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op05_045_activate_return_deck_bottom_ai():
    """起動メイン: 手札1捨て + 自レスト (コスト) → 相手のコスト2以下キャラ1枚を
    デッキの下に戻す (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    sten = InPlay.of(repo.get("OP05-045"), sickness=False)
    me.characters = [sten]
    me.hand = [repo.get(_PLAIN_C2)]  # 捨てるコスト
    victim = InPlay.of(repo.get(_NAMI), sickness=False)  # cost1 (<=2)
    opp.characters = [victim]
    opp_deck_before = len(opp.deck)

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP05-045"]
    assert len(opts) == 1, f"OP05-045 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, pick=[0])

    assert victim not in opp.characters, "相手のコスト2以下キャラがデッキに戻されていない"
    assert len(opp.deck) == opp_deck_before + 1, "対象が持ち主のデッキの下に戻っていない"
    assert sten.rested is True, "起動メインコストで ステンレス がレストされるべき"
    assert len(me.hand) == 0, "起動メインコストで手札1枚が捨てられるべき"


def test_op05_045_activate_human_pick():
    """人間 + 相手のコスト2以下キャラ複数 → 手札捨て後に target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    sten = InPlay.of(repo.get("OP05-045"), sickness=False)
    me.characters = [sten]
    me.hand = [repo.get(_PLAIN_C2)]
    a = InPlay.of(repo.get(_NAMI), sickness=False)    # cost1
    b = InPlay.of(repo.get(_PLAIN_C2), sickness=False)  # cost2
    opp.characters = [a, b]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP05-045"]
    fire_activate_main(st, me, opp, *opts[0])

    # まず 手札捨て modal (candidates 1) → 解決
    assert st.pending_choice is not None, "起動メインコストの手札捨て modal が立たない"
    assert st.pending_choice.get("kind") == "activate_main_discard_pick", \
        f"kind が activate_main_discard_pick でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])

    # 続いて 対象の target_pick modal (candidates 2)
    assert st.pending_choice is not None, "手札捨て後 target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[b_idx])
    assert b not in opp.characters, "人間が選んだキャラがデッキに戻されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP05-046 ダルメシアン (CHARACTER 青 cost4 power5000 海軍):
#    【KO時】カード1枚を引き、自分の手札1枚をデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op05_046_on_ko_draw_and_hand_to_deck_ai():
    """KO時: 1枚引く → 手札1枚をデッキの下に置く (AI 自動)。 手札 net は ±0、
    デッキ底に1枚積まれる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_ISSHO_C6)]  # cost6 (AI は コスト最高を デッキ底 へ)
    me.deck = [repo.get(_RED_C3)] + [repo.get(_PLAIN_C2)] * 10
    hand_before = len(me.hand)

    for prim in _do(overlay, "OP05-046", "on_ko"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-046"), sickness=False))
    _drain(st, pick=[0])

    # 1 ドロー (+1) → 手札1枚デッキ底 (-1) = net ±0
    assert len(me.hand) == hand_before, \
        f"手札 net (ドロー+1 / デッキ底-1) が合わない: {len(me.hand)}"
    assert me.deck[-1].card_id == _ISSHO_C6, \
        "AI は 最高コストの手札 (OP05-042) を デッキの下に置くべき"


def test_op05_046_on_ko_human_hand_pick():
    """人間 + 手札複数 → self_hand_to_deck_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_ISSHO_C6), repo.get(_RED_C3)]
    me.deck = [repo.get(_PLAIN_C2)] * 10

    # draw はスキップして hand→deck の human 選択のみを検証
    execute_effect({"self_hand_to_deck_bottom": 1}, st, me, opp,
                   InPlay.of(repo.get("OP05-046"), sickness=False))

    assert st.pending_choice is not None, "人間 + 手札複数で hand→deck modal が立たない"
    assert st.pending_choice.get("kind") == "self_hand_to_deck_pick", \
        f"kind が self_hand_to_deck_pick でない: {st.pending_choice.get('kind')}"
    hand_before = len(me.hand)
    resolve_pending_choice(st, [0])  # 先頭を デッキ底 へ
    _drain(st)
    assert len(me.hand) == hand_before - 1, "選んだ手札1枚が デッキの下に置かれていない"


# --------------------------------------------------------------------------- #
#  OP05-047 バジル・ホーキンス (CHARACTER 青 cost4 power5000 百獣/ホーキンス):
#    【ブロック時】自分の手札が3枚以下の場合、カード1枚を引く。
#      その後、このキャラは、このバトル中、パワー+1000。
# --------------------------------------------------------------------------- #
def test_op05_047_on_block_draw_and_pump():
    """ブロック時 (手札3以下): 1枚引き → このキャラ +1000 (このバトル中)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    hawkins = InPlay.of(repo.get("OP05-047"), sickness=False)  # power5000
    me.characters = [hawkins]
    me.hand = [repo.get(_PLAIN_C2)]  # 手札1 (<=3)
    me.deck = [repo.get(_PLAIN_C2)] * 10

    eff = _eff(overlay, "OP05-047", "on_block")
    assert eff.get("if", {}).get("self_hand_count_le") == 3, \
        "overlay の 発火条件 self_hand_count_le=3 が無い"
    power_before = hawkins.power
    hand_before = len(me.hand)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, hawkins)

    assert len(me.hand) == hand_before + 1, "ブロック時の 1 ドローが起きていない"
    assert hawkins.power == power_before + 1000, \
        f"ブロック時 自己 +1000 が反映されていない: {hawkins.power}"


# --------------------------------------------------------------------------- #
#  OP05-048 バスティーユ (CHARACTER 青 cost5 power6000 海軍):
#    【ドン!!×1】【アタック時】コスト2以下のキャラ1枚までを、持ち主のデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op05_048_on_attack_return_deck_bottom_ai():
    """アタック時 (ドン1ゲート): 相手のコスト2以下キャラ1枚を デッキの下に置く (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_NAMI), sickness=False)  # cost1 (<=2)
    opp.characters = [victim]
    opp_deck_before = len(opp.deck)

    eff = _eff(overlay, "OP05-048", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-048"), sickness=False))
    _drain(st, pick=[0])

    assert victim not in opp.characters, "相手のコスト2以下キャラがデッキに戻されていない"
    assert len(opp.deck) == opp_deck_before + 1, "対象が持ち主のデッキの下に戻っていない"


def test_op05_048_on_attack_human_pick():
    """人間 + 相手のコスト2以下キャラ複数 → target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_NAMI), sickness=False)    # cost1
    b = InPlay.of(repo.get(_PLAIN_C2), sickness=False)  # cost2
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP05-048", "on_attack")[0], st, me, opp,
                   InPlay.of(repo.get("OP05-048"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[b_idx])
    assert b not in opp.characters, "人間が選んだキャラがデッキに戻されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP05-049 八茶 (CHARACTER 青 cost6 power7000 巨人族/百獣海賊団):
#    【ドン!!×1】【アタック時】コスト3以下のキャラ1枚までを、持ち主の手札に戻す。
# --------------------------------------------------------------------------- #
def test_op05_049_on_attack_return_hand_ai():
    """アタック時 (ドン1ゲート): 相手のコスト3以下キャラ1枚を 手札に戻す (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_RED_C3), sickness=False)  # cost3 (<=3)
    opp.characters = [victim]

    eff = _eff(overlay, "OP05-049", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-049"), sickness=False))
    _drain(st, pick=[0])

    assert victim not in opp.characters, "相手のコスト3以下キャラが手札に戻されていない"
    assert any(c.card_id == _RED_C3 for c in opp.hand), \
        "対象が持ち主 (相手) の手札に戻っていない"


def test_op05_049_on_attack_human_pick():
    """人間 + 相手のコスト3以下キャラ複数 → return_to_hand の target_pick modal。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_NAMI), sickness=False)    # cost1
    b = InPlay.of(repo.get(_RED_C3), sickness=False)  # cost3
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP05-049", "on_attack")[0], st, me, opp,
                   InPlay.of(repo.get("OP05-049"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[b_idx])
    assert b not in opp.characters, "人間が選んだキャラが手札に戻されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP05-050 ヒナ (CHARACTER 青 cost3 power4000 海軍):
#    【登場時】自分の手札が5枚以下の場合、カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op05_050_on_play_draw():
    """登場時 (手札5以下): カード1枚を引く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_PLAIN_C2)] * 3  # 手札3 (<=5)
    me.deck = [repo.get(_RED_C3)] + [repo.get(_PLAIN_C2)] * 10

    eff = _eff(overlay, "OP05-050", "on_play")
    assert eff.get("if", {}).get("self_hand_count_le") == 5, \
        "overlay の 発火条件 self_hand_count_le=5 が無い"
    hand_before = len(me.hand)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-050"), sickness=False))

    assert len(me.hand) == hand_before + 1, "登場時の 1 ドローが起きていない"


# --------------------------------------------------------------------------- #
#  OP05-051 ボルサリーノ (CHARACTER 青 cost7 power8000 海軍):
#    【登場時】コスト4以下のキャラ1枚までを、持ち主のデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op05_051_on_play_return_deck_bottom_ai():
    """登場時: (自分/相手いずれかの) コスト4以下キャラ1枚を デッキの下に置く (AI)。
    コスト5以上は対象外。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_RED_C3), sickness=False)   # cost3 (<=4)
    survivor = InPlay.of(repo.get(_ISSHO_C6), sickness=False)  # cost6 (>4)
    opp.characters = [victim, survivor]
    opp_deck_before = len(opp.deck)

    for prim in _do(overlay, "OP05-051", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-051"), sickness=False))
    _drain(st, pick=[0])

    assert victim not in opp.characters, "相手のコスト4以下キャラがデッキに戻されていない"
    assert survivor in opp.characters, "コスト6キャラ (>4) は対象外で残るべき"
    assert len(opp.deck) == opp_deck_before + 1, "対象が持ち主のデッキの下に戻っていない"


def test_op05_051_on_play_human_pick():
    """人間 + コスト4以下キャラ複数 → return_to_deck_bottom の target_pick modal。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_NAMI), sickness=False)    # cost1
    b = InPlay.of(repo.get(_RED_C3), sickness=False)  # cost3
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP05-051", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP05-051"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[b_idx])
    assert b not in opp.characters, "人間が選んだキャラがデッキに戻されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"
