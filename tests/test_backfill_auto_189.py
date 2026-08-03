# -*- coding: utf-8 -*-
"""ST30 弾 効果 回帰テスト バックフィル (自動生成 wave 189):
ST30-017 の 1 枚 (= 効果ありカードのテスト バックフィル 最終枚)。

  ST30-017 無茶ばっかりしやがって!!! (EVENT 赤 cost1 白ひげ海賊団) =
     【メイン】自分のデッキの上から5枚を見て、パワー6000のキャラカード1枚までを
       公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く
       (main search_top_n depth5 power_eq6000 CHARACTER destination=hand rest=bottom) /
     【トリガー】このカードの【メイン】効果を発動する
       (trigger fire_self_effect when_kind=main)

目的 (= test_backfill_auto_001〜188.py と同一方針):
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
from engine.deck import CardRepository
from engine.effects import (
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

_LEADER_PLAIN = "OP01-001"   # ロロノア・ゾロ (LEADER 赤, base power5000) — 汎用
_FILLER = "OP01-013"         # サンジ cost2 power3000 CHARACTER (= power6000 でない)
_P6000 = "PRB02-008"         # マルコ cost4 power6000 CHARACTER (= 対象)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id=_LEADER_PLAIN,
           turn_player=0):
    """P0 = テスト対象デッキ、 P1 = ダミー。 MAIN / turn_number=3。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(_FILLER)] * 30
    p1.deck = [repo.get(_FILLER)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn_player
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _eff(overlay, cid, when):
    """指定 card_id の overlay から when 一致の効果 (dict) を返す (先頭)。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    return matches[0]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [0])
        n += 1


def _resolve_search(st):
    """search_top_n modal → 候補 index 0 を選択 → 残る reorder modal を空順で drain。"""
    resolve_pending_choice(st, [0])
    guard = 0
    while st.pending_choice is not None and guard < 6:
        resolve_pending_choice(st, [])
        guard += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave189_cards_have_overlay():
    """ST30-017 が cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    card = repo.get("ST30-017")
    assert card is not None, "ST30-017 が cards.json に存在しない"
    bundle = overlay.get("ST30-017")
    assert bundle is not None and len(bundle.effects) > 0, \
        "ST30-017 の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  ST30-017 【メイン】: デッキ上5枚 → パワー6000のキャラ1枚まで手札、残りをデッキ下
# --------------------------------------------------------------------------- #
def test_st30_017_main_search_power6000_ai():
    """メイン: デッキ上5枚から パワー6000のキャラを1枚 手札に加える (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_P6000)] + [repo.get(_FILLER)] * 20  # 先頭に power6000 char
    me.hand = []

    hand_before = len(me.hand)
    execute_effect(_eff(overlay, "ST30-017", "main")["do"][0], st, me, opp, None)
    _drain(st, [])
    assert any(c.card_id == _P6000 for c in me.hand), \
        "デッキ上5枚から パワー6000のキャラが手札に加わっていない"
    assert len(me.hand) == hand_before + 1, \
        "手札が1枚だけ増える (パワー6000キャラ1枚まで) であるべき"


def test_st30_017_main_search_human_pick():
    """人間: search_top_n modal が立ち、 選択で パワー6000キャラが手札に加わる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_P6000)] + [repo.get(_FILLER)] * 20
    me.hand = []

    execute_effect(_eff(overlay, "ST30-017", "main")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    _resolve_search(st)
    assert any(c.card_id == _P6000 for c in me.hand), \
        "人間が選んだ パワー6000キャラが手札に加わっていない"


def test_st30_017_main_search_no_hit_when_absent():
    """デッキ上5枚に パワー6000キャラが無ければ 手札に加わらない (対象外は取れない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 20  # power3000 のみ
    me.hand = []

    execute_effect(_eff(overlay, "ST30-017", "main")["do"][0], st, me, opp, None)
    _drain(st, [])
    assert not any(c.card_id == _P6000 for c in me.hand), \
        "パワー6000キャラが不在なのに手札に加わってはいけない"


def test_st30_017_main_rest_returned_to_deck_bottom():
    """メイン発動後、 見た5枚のうち手札に加えた1枚を除く残りがデッキに戻る
    (= rest_remain=bottom、 デッキ枚数は「手札に加えた分」だけ減る)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_P6000)] + [repo.get(_FILLER)] * 20
    me.hand = []

    deck_before = len(me.deck)
    execute_effect(_eff(overlay, "ST30-017", "main")["do"][0], st, me, opp, None)
    _drain(st, [])
    # power6000 キャラ 1 枚を手札に取り、 残り4枚はデッキ下に戻る = デッキは1枚減
    assert len(me.deck) == deck_before - 1, \
        f"見た残りがデッキに戻らずデッキ枚数が想定外: {len(me.deck)} (期待 {deck_before - 1})"


# --------------------------------------------------------------------------- #
#  ST30-017 【トリガー】: このカードの【メイン】効果を発動する (fire_self_effect)
# --------------------------------------------------------------------------- #
def test_st30_017_trigger_fires_main_ai():
    """トリガー: fire_self_effect で【メイン】(上5枚→パワー6000サーチ) が発動する (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PLAIN, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_P6000)] + [repo.get(_FILLER)] * 20
    me.hand = []

    # fire_self_effect は self_inplay の card_id (もしくは current_source_card_id) を参照
    self_card = InPlay.of(repo.get("ST30-017"), sickness=False)
    st.current_source_card_id = "ST30-017"
    for prim in _eff(overlay, "ST30-017", "trigger")["do"]:
        execute_effect(prim, st, me, opp, self_card)
    _drain(st, [])
    assert any(c.card_id == _P6000 for c in me.hand), \
        "トリガー経由で メイン効果 (パワー6000サーチ) が発動していない"
