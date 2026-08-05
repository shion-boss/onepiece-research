# -*- coding: utf-8 -*-
"""OP15 弾 効果 回帰テスト バックフィル (自動生成 wave 143):
OP15-057 / OP15-063 / OP15-064 / OP15-065 / OP15-067 /
OP15-068 / OP15-070 / OP15-071 / OP15-072 / OP15-073 の 10 枚。

目的 (= test_backfill_auto_001〜142.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 を 持つカードは 人間 actor で pending_choice が
      正しい kind + 候補で立ち、 resolve_pending_choice で解決できる (= 人間が選べる)
  (3) 同じ効果を AI 文脈 (human_player_idx=None) で回しても crash せず自動解決する
      (= AI が選べる)
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.effects import (
    eval_condition,
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)
from engine.deck import CardRepository

ROOT = Path(__file__).resolve().parent.parent


def _cond_of(eff: dict) -> dict:
    """効果の発動条件を取り出す (top-level `if` / `conditional` の両対応)。

    ⚠ 2026-08-05: 公式は 「〜できる：<条件>の場合、<効果>」 のコロン後の条件を **効果のみ** の
    gate とする (cardqa_op_02 / cardqa_st_04)。 top-level `if` に置くと **任意コストの支払いごと
    消える** ので、 overlay ではこの形の条件を `conditional` の中に移した。
    条件そのものは変わっていないので、 テストはどちらの位置でも読めればよい。
    """
    if isinstance(eff.get("if"), dict):
        return eff["if"]
    for _prim in eff.get("do") or []:
        if isinstance(_prim, dict) and "conditional" in _prim:
            return (_prim.get("conditional") or {}).get("if") or {}
    return {}


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001",
           turn_player=0):
    """P0 = テスト対象デッキ、 P1 = ダミー。 MAIN / turn_number=3。
    デッキは効果の薄いカード (OP01-016 ナミ) で埋める。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("OP01-016")] * 30
    p1.deck = [repo.get("OP01-016")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn_player
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果の (do 配列, eff) を返す。"""
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


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op15_wave143_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP15-057", "OP15-063", "OP15-064", "OP15-065", "OP15-067",
           "OP15-068", "OP15-070", "OP15-071", "OP15-072", "OP15-073"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP15-057 ドレスローザ王国 (STAGE 青 cost1):
#    【登場時】自分のリーダーが特徴《ドレスローザ》を持つ場合、カード1枚を引く。
#    【相手のアタック時】このステージをレストにし、自分の手札からイベントか
#      ステージカード1枚を捨てることができる：自分のリーダーかキャラ1枚までを、
#      このバトル中、パワー+2000。
# --------------------------------------------------------------------------- #
def test_op15_057_on_play_condition_dressrosa_leader():
    """登場時 条件: 《ドレスローザ》リーダーで if 成立、 非ドレスローザで不成立。"""
    repo = _repo()
    overlay = _overlay()
    _, eff = _do(overlay, "OP15-057", "on_play")
    st_ok = _state(repo, "OP15-039", overlay)   # レベッカ (ドレスローザ)
    st_ng = _state(repo, "OP01-001", overlay)   # ゾロ (非ドレスローザ)
    assert eval_condition(_cond_of(eff), st_ok, st_ok.players[0]) is True, \
        "《ドレスローザ》リーダーで登場時条件が成立していない"
    assert eval_condition(_cond_of(eff), st_ng, st_ng.players[0]) is False, \
        "非《ドレスローザ》リーダーで登場時条件が成立してはいけない"


def test_op15_057_on_play_draw_when_dressrosa_ai():
    """《ドレスローザ》リーダー下で 登場時 1ドロー (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP15-039", overlay)  # ドレスローザ leader
    me, opp = st.players[0], st.players[1]
    me.hand = []
    deck_before = len(me.deck)
    do, _ = _do(overlay, "OP15-057", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-057"), sickness=False))
    _drain(st, [0])
    assert len(me.deck) == deck_before - 1, "登場時 1ドローが起きていない"
    assert len(me.hand) == 1, f"手札が1枚増えていない: {len(me.hand)}"


# --------------------------------------------------------------------------- #
#  OP15-063 ゲダツ (CHARACTER 紫 cost1 power2000):
#    【登場時】ドン‼-1：カード1枚を引く。
#    【KO時】自分の場のドン‼が6枚以下の場合、相手のパワー2000以下のキャラ1枚までを、
#      KOする。
# --------------------------------------------------------------------------- #
def test_op15_063_on_play_draw_ai():
    """登場時 (ドン‼-1) 効果 = カード1枚を引く (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    deck_before = len(me.deck)
    do, _ = _do(overlay, "OP15-063", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-063"), sickness=True))
    _drain(st, [0])
    assert len(me.deck) == deck_before - 1, "登場時 1ドローが起きていない"


def test_op15_063_on_ko_condition_self_don_le_6():
    """【KO時】条件: 自場ドン6以下で if 成立、 7枚では不成立。"""
    repo = _repo()
    overlay = _overlay()
    _, eff = _do(overlay, "OP15-063", "on_ko")
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    me.don_active = 6
    assert eval_condition(_cond_of(eff), st, me) is True, \
        "自場ドン6枚で KO時条件が成立していない"
    me.don_active = 7
    assert eval_condition(_cond_of(eff), st, me) is False, \
        "自場ドン7枚で KO時条件が成立してはいけない"


def test_op15_063_on_ko_ko_opp_power_le_2000_ai():
    """【KO時】相手のパワー2000以下のキャラ1枚をKO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # power2000
    opp.characters = [victim]
    do, _ = _do(overlay, "OP15-063", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-063"), sickness=False))
    _drain(st, [0])
    assert victim not in opp.characters, \
        "パワー2000以下の相手キャラがKOされていない"


def test_op15_063_on_ko_human_pick():
    """人間 + 相手パワー2000以下 複数 → target_pick modal → 選んだ1枚のみKO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # power2000
    b = InPlay.of(repo.get("OP15-066"), sickness=False)  # サトリ power2000
    opp.characters = [a, b]
    do, _ = _do(overlay, "OP15-063", "on_ko")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP15-063"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b not in opp.characters, "人間が選んだ相手キャラがKOされていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP15-064 コトリ (CHARACTER 紫 cost1 power2000):
#    【起動メイン】ドン‼-2,このキャラをレストにできる：自分の「サトリ」と「ホトリ」が
#      いる場合、相手のパワー5000以下のキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_op15_064_condition_needs_satori_and_hotori():
    """条件: 自場に「サトリ」と「ホトリ」両方いれば成立、 欠けると不成立。"""
    repo = _repo()
    overlay = _overlay()
    _, eff = _do(overlay, "OP15-064", "activate_main")
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    me.characters = [InPlay.of(repo.get("OP15-064"), sickness=False)]  # コトリのみ
    assert eval_condition(_cond_of(eff), st, me) is False, \
        "「サトリ」「ホトリ」不在で条件が成立してはいけない"
    me.characters += [
        InPlay.of(repo.get("OP15-066"), sickness=False),  # サトリ
        InPlay.of(repo.get("OP15-072"), sickness=False),  # ホトリ
    ]
    assert eval_condition(_cond_of(eff), st, me) is True, \
        "「サトリ」「ホトリ」在で条件が成立していない"


def test_op15_064_activate_rest_opp_le_5000_ai():
    """起動メイン: ドン‼-2 + 自レスト → 相手パワー5000以下1枚をレスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    kotori = InPlay.of(repo.get("OP15-064"), sickness=False)
    me.characters = [
        kotori,
        InPlay.of(repo.get("OP15-066"), sickness=False),  # サトリ
        InPlay.of(repo.get("OP15-072"), sickness=False),  # ホトリ
    ]
    me.don_active = 5
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # power3000 ≤5000
    opp.characters = [victim]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP15-064"]
    assert len(opts) == 1, f"OP15-064 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert victim.rested is True, "相手パワー5000以下キャラがレストされていない"
    assert kotori.rested is True, "コスト (自レスト) でこのキャラがレストされていない"


# --------------------------------------------------------------------------- #
#  OP15-065 ゴロー (CHARACTER 紫 cost3):
#    【登場時】自分のデッキの上から1枚を公開する。公開したカードがコスト2以下の場合、
#      ドン‼デッキからドン‼1枚までを、レストで追加する。
# --------------------------------------------------------------------------- #
def test_op15_065_on_play_reveal_low_cost_adds_rested_don_ai():
    """デッキ上1枚がコスト2以下 → レストドン+1 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP01-016")] + [repo.get("OP01-013")] * 5  # 上=cost1
    me.don_remaining_in_deck = 10
    rested_before = me.don_rested
    do, _ = _do(overlay, "OP15-065", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-065"), sickness=True))
    _drain(st, [0])
    assert me.don_rested == rested_before + 1, \
        f"コスト2以下公開で レストドン+1 が起きていない: {me.don_rested}"


def test_op15_065_on_play_reveal_high_cost_no_don_ai():
    """デッキ上1枚がコスト3 (>2) → ドン追加なし (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP15-050")] + [repo.get("OP01-013")] * 5  # 上=cost3
    me.don_remaining_in_deck = 10
    rested_before = me.don_rested
    do, _ = _do(overlay, "OP15-065", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-065"), sickness=True))
    _drain(st, [0])
    assert me.don_rested == rested_before, \
        f"コスト3公開で ドンが追加されてはいけない: {me.don_rested}"


# --------------------------------------------------------------------------- #
#  OP15-067 シュラ (CHARACTER 紫 cost1 power2000):
#    自分の場のドン‼が6枚以下の場合、このキャラは【速攻】を得る。
#    【登場時】ドン‼-1：カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op15_067_static_rush_when_don_le_6():
    """自場ドン6以下で【速攻】を得る、 7枚では得ない (静的)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    shura = InPlay.of(repo.get("OP15-067"), sickness=True)
    me.characters = [shura]

    me.don_active = 6
    evaluate_static_effects(st, overlay)
    assert shura.is_rush_now is True, "自場ドン6枚で【速攻】を得ていない"

    me.don_active = 7
    evaluate_static_effects(st, overlay)
    assert shura.is_rush_now is False, "自場ドン7枚で【速攻】を得てはいけない"


def test_op15_067_on_play_draw_ai():
    """登場時 (ドン‼-1) 効果 = カード1枚を引く (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    deck_before = len(me.deck)
    do, _ = _do(overlay, "OP15-067", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-067"), sickness=True))
    _drain(st, [0])
    assert len(me.deck) == deck_before - 1, "登場時 1ドローが起きていない"


# --------------------------------------------------------------------------- #
#  OP15-068 神兵 (CHARACTER 紫 cost1 power1000):
#    自分の場のドン‼が6枚以下の場合、このキャラは【ブロッカー】を得る。
# --------------------------------------------------------------------------- #
def test_op15_068_static_blocker_when_don_le_6():
    """自場ドン6以下で【ブロッカー】を得る、 7枚では得ない (静的)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    hei = InPlay.of(repo.get("OP15-068"), sickness=False)
    me.characters = [hei]

    me.don_active = 6
    evaluate_static_effects(st, overlay)
    assert hei.is_blocker_now is True, "自場ドン6枚で【ブロッカー】を得ていない"

    me.don_active = 7
    evaluate_static_effects(st, overlay)
    assert hei.is_blocker_now is False, "自場ドン7枚で【ブロッカー】を得てはいけない"


# --------------------------------------------------------------------------- #
#  OP15-070 フザ (CHARACTER 紫 cost3 power4000):
#    自分の「シュラ」すべてとこのキャラは【ブロック不可】を得る。
#    【相手のターン中】自分の「シュラ」すべてとこのキャラを、元々のパワー6000にする。
# --------------------------------------------------------------------------- #
def test_op15_070_static_no_block_self_and_shura():
    """フザ自身と自軍「シュラ」全てが【ブロック不可】を得る (静的)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    fuza = InPlay.of(repo.get("OP15-070"), sickness=False)
    shura = InPlay.of(repo.get("OP15-067"), sickness=False)
    me.characters = [fuza, shura]
    evaluate_static_effects(st, overlay)
    assert fuza.has_no_block_now is True, "フザ自身が【ブロック不可】を得ていない"
    assert shura.has_no_block_now is True, "自軍「シュラ」が【ブロック不可】を得ていない"


def test_op15_070_static_set_base_power_6000_opp_turn():
    """【相手のターン中】フザと「シュラ」を元々のパワー6000にする (静的)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, turn_player=1)  # 相手ターン
    me = st.players[0]
    fuza = InPlay.of(repo.get("OP15-070"), sickness=False)
    shura = InPlay.of(repo.get("OP15-067"), sickness=False)  # 元P2000
    me.characters = [fuza, shura]
    evaluate_static_effects(st, overlay)
    assert fuza.base_power == 6000, f"相手ターンでフザが6000でない: {fuza.base_power}"
    assert shura.base_power == 6000, f"相手ターンで「シュラ」が6000でない: {shura.base_power}"


def test_op15_070_static_base_power_unchanged_self_turn():
    """自分ターン中は パワー6000化しない (= 元々のパワーのまま)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, turn_player=0)  # 自分ターン
    me = st.players[0]
    fuza = InPlay.of(repo.get("OP15-070"), sickness=False)  # 元P4000
    me.characters = [fuza]
    evaluate_static_effects(st, overlay)
    assert fuza.base_power == 4000, \
        f"自分ターンで6000化してはいけない: {fuza.base_power}"


# --------------------------------------------------------------------------- #
#  OP15-071 ホーリー (CHARACTER 紫 cost3 power4000):
#    自分の「オーム」すべてとこのキャラは【ダブルアタック】を得る。
#    【相手のターン中】自分の「オーム」すべてとこのキャラを、元々のパワー6000にする。
# --------------------------------------------------------------------------- #
def test_op15_071_static_double_attack_self_and_ohm():
    """ホーリー自身と自軍「オーム」全てが【ダブルアタック】を得る (静的)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    holy = InPlay.of(repo.get("OP15-071"), sickness=False)
    ohm = InPlay.of(repo.get("OP15-061"), sickness=False)
    me.characters = [holy, ohm]
    evaluate_static_effects(st, overlay)
    assert holy.is_double_attack_now is True, \
        "ホーリー自身が【ダブルアタック】を得ていない"
    assert ohm.is_double_attack_now is True, \
        "自軍「オーム」が【ダブルアタック】を得ていない"


def test_op15_071_static_set_base_power_6000_opp_turn():
    """【相手のターン中】ホーリーと「オーム」を元々のパワー6000にする (静的)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, turn_player=1)  # 相手ターン
    me = st.players[0]
    holy = InPlay.of(repo.get("OP15-071"), sickness=False)
    ohm = InPlay.of(repo.get("OP15-061"), sickness=False)  # 元P2000
    me.characters = [holy, ohm]
    evaluate_static_effects(st, overlay)
    assert holy.base_power == 6000, f"相手ターンでホーリーが6000でない: {holy.base_power}"
    assert ohm.base_power == 6000, f"相手ターンで「オーム」が6000でない: {ohm.base_power}"


# --------------------------------------------------------------------------- #
#  OP15-072 ホトリ (CHARACTER 紫 cost1 power2000):
#    【起動メイン】ドン‼-2,このキャラをレストにできる：自分の「コトリ」と「サトリ」が
#      いる場合、相手のキャラ1枚までを、このターン中、パワー-3000。
# --------------------------------------------------------------------------- #
def test_op15_072_condition_needs_kotori_and_satori():
    """条件: 自場に「コトリ」と「サトリ」両方いれば成立、 欠けると不成立。"""
    repo = _repo()
    overlay = _overlay()
    _, eff = _do(overlay, "OP15-072", "activate_main")
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    me.characters = [InPlay.of(repo.get("OP15-072"), sickness=False)]  # ホトリのみ
    assert eval_condition(_cond_of(eff), st, me) is False, \
        "「コトリ」「サトリ」不在で条件が成立してはいけない"
    me.characters += [
        InPlay.of(repo.get("OP15-064"), sickness=False),  # コトリ
        InPlay.of(repo.get("OP15-066"), sickness=False),  # サトリ
    ]
    assert eval_condition(_cond_of(eff), st, me) is True, \
        "「コトリ」「サトリ」在で条件が成立していない"


def test_op15_072_activate_debuff_opp_minus_3000_ai():
    """起動メイン: ドン‼-2 + 自レスト → 相手キャラ1枚を このターン中 パワー-3000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    hotori = InPlay.of(repo.get("OP15-072"), sickness=False)
    me.characters = [
        hotori,
        InPlay.of(repo.get("OP15-064"), sickness=False),  # コトリ
        InPlay.of(repo.get("OP15-066"), sickness=False),  # サトリ
    ]
    me.don_active = 5
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # power3000
    power_before = victim.power
    opp.characters = [victim]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP15-072"]
    assert len(opts) == 1, f"OP15-072 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert victim.power == power_before - 3000, \
        f"相手キャラへの -3000 が反映されていない: {victim.power} (before {power_before})"
    assert hotori.rested is True, "コスト (自レスト) でこのキャラがレストされていない"


def test_op15_072_do_human_target_pick():
    """人間: 相手キャラ 複数 → power_pump の target_pick modal が立ち 選択できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # power3000
    b = InPlay.of(repo.get("OP15-066"), sickness=False)  # power2000
    opp.characters = [a, b]
    # ⚠ 2026-08-05: 公式は 「ドン‼-2,このキャラをレストにできる：**自分の「コトリ」と「サトリ」が
    #   いる場合**、…-3000」。 コロン後の条件は効果のみを gate するので overlay では `conditional`
    #   の中にある。 以前は top-level `if` で、 テストが `do` を直接実行して **条件を満たさずに
    #   効果だけ検証** していた (= 条件が壊れても緑になる)。
    me.characters = [InPlay.of(repo.get("OP15-064"), sickness=False),   # コトリ
                     InPlay.of(repo.get("OP15-066"), sickness=False)]   # サトリ
    do, _ = _do(overlay, "OP15-072", "activate_main")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP15-072"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b.power == 2000 - 3000, f"選んだ相手キャラに -3000 が乗っていない: {b.power}"


# --------------------------------------------------------------------------- #
#  OP15-073 ヤマ (CHARACTER 紫 cost3 power4000):
#    【ブロッカー】
#    【登場時】自分の手札からコスト1の、「神兵」か特徴《神官》を持つキャラカード
#      1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op15_073_on_play_summon_hei_from_hand_ai():
    """手札のコスト1「神兵」を登場させる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP15-068")]  # 神兵 cost1
    hand_before = len(me.hand)
    do, _ = _do(overlay, "OP15-073", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-073"), sickness=True))
    _drain(st, [0])
    assert any(c.card.card_id == "OP15-068" for c in me.characters), \
        "手札の「神兵」が登場していない"
    assert len(me.hand) == hand_before - 1, "登場した分だけ手札が減っていない"


def test_op15_073_on_play_no_target_noop_ai():
    """手札に対象 (コスト1「神兵」/《神官》) が無ければ 何も登場しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP15-050")]  # ボビー・ファンク cost3 (対象外)
    do, _ = _do(overlay, "OP15-073", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-073"), sickness=True))
    _drain(st, [0])
    assert not any(c.card.card_id == "OP15-050" for c in me.characters), \
        "対象外のカードが登場している"


def test_op15_073_on_play_human_play_pick():
    """人間 + 手札にコスト1「神兵」複数 → play_from_hand modal → resolve で1枚登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP15-068"), repo.get("OP15-068")]  # 神兵 ×2
    do, _ = _do(overlay, "OP15-073", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP15-073"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert any(c.card.card_id == "OP15-068" for c in me.characters), \
        "人間が選んだ「神兵」が登場していない"
