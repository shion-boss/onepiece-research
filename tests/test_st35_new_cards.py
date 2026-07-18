# -*- coding: utf-8 -*-
"""ST-35 (赤黒サボ スタートデッキ) ST35-001〜005 の効果 永続 regression test。

新弾 5 カードの効果が (1) 盤面で正しく発火し、 (2) 人間 actor で対象/任意コストの
pending_choice が正しく立って解決でき、 (3) AI 文脈で crash せず自動解決される ことを
回帰保証する。 公式テキスト忠実主義 (CLAUDE.md) の overlay を engine 経由で検証する。

対象:
- ST35-001 ハック   : 【登場時】相手の元々のパワー2000以下のキャラ1枚までKO (【ブロッカー】intrinsic)
- ST35-002 リンドバーグ: 【登場時】相手キャラ1枚まで このターン中パワー-3000
- ST35-003 カラス    : 【アタック時】デッキ上2枚トラッシュ(任意):相手手札7枚以上なら相手discard
- ST35-004 コアラ    : 静的ブロッカー付与+コスト+1 / 【登場時】リーダーにレストドン1 + 革命軍4000以下登場
- ST35-005 バーソロミュー・くま: 静的コスト+3 / 【登場時】リーダーにレストドン1 + 革命軍4000以下登場
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    TriggerEvent,
    _execute_event,
    evaluate_static_effects,
    load_effect_overlay,
    resolve_pending_choice,
    trigger_on_attack,
    trigger_on_play,
)

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _mk_state(repo, overlay, *, human_idx=None):
    """P0 = ST-35 デッキ側 (leader = 赤黒サボ相当は不要なので汎用 leader) の 2 人盤面。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP13-002"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP13-002"), sickness=False))
    p0.deck = [repo.get("OP01-013")] * 30
    p1.deck = [repo.get("OP01-013")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    p0.don_active = 10
    if human_idx is not None:
        st.human_player_idx = human_idx
    return st, p0, p1


def _drain_choices(st, guard=8):
    """AI 文脈: pending_choice を index0 で順次解決 (= crash せず解決を確認)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, [0])
        n += 1
    return n


# ---------------------------------------------------------------------------
# overlay 存在 & 忠実性 (簡略実装でないこと)
# ---------------------------------------------------------------------------

def test_st35_overlay_entries_present_and_faithful():
    """5 カード全てに overlay があり、 _unimplemented / 簡略 マーカーが無いこと。"""
    eff = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    for cid in ["ST35-001", "ST35-002", "ST35-003", "ST35-004", "ST35-005"]:
        assert cid in eff, f"{cid} の overlay が欠落"
        bundle = eff[cid]
        assert isinstance(bundle, list) and bundle, f"{cid} の overlay が空"
        blob = json.dumps(bundle, ensure_ascii=False)
        assert "_unimplemented" not in blob, f"{cid} に _unimplemented マーカー"

    # 主要 primitive の存在チェック (= 簡略 override でないこと)
    def keys(cid):
        ks = set()
        for e in eff[cid]:
            for d in e.get("do", []):
                if isinstance(d, dict):
                    ks |= set(d)
        return ks

    assert "ko" in keys("ST35-001")
    assert "power_pump" in keys("ST35-002")
    assert "optional_cost_then" in keys("ST35-003")
    for cid in ("ST35-004", "ST35-005"):
        assert "attach_rested_don" in keys(cid), f"{cid} レストドン付与 欠落"
        assert "play_from_hand_or_trash" in keys(cid), f"{cid} 革命軍登場 欠落"


# ---------------------------------------------------------------------------
# ST35-001 ハック : 登場時 元々パワー2000以下 KO
# ---------------------------------------------------------------------------

def test_st35_001_kos_only_base_power_le_2000_ai():
    """AI 文脈: 元々2000のキャラは KO、 元々4000のキャラは残る (base 判定)。"""
    repo, overlay = _repo(), _overlay()
    st, p0, p1 = _mk_state(repo, overlay)  # human_idx なし = AI 文脈

    low = InPlay.of(repo.get("OP01-016"), sickness=False)   # 元々 2000
    high = InPlay.of(repo.get("ST21-005"), sickness=False)  # 元々 4000
    low.turn_buff = 5000   # 現在 7000 でも base=2000 なので KO 対象
    p1.characters = [low, high]

    hack = InPlay.of(repo.get("ST35-001"), sickness=True)
    p0.characters = [hack]
    trigger_on_play(st, p0, p1, hack, overlay)
    _drain_choices(st)

    remaining = [c.card.card_id for c in p1.characters]
    assert remaining == ["ST21-005"], f"元々2000だけKOのはず: {remaining}"


def test_st35_001_human_target_pick():
    """人間 actor: 2000以下キャラが 2 体 → target_pick modal が立ち、 選んだ 1 体が KO。
    「1枚まで」 なので 0 枚選択 (= 撃たない) も出来る。"""
    repo, overlay = _repo(), _overlay()
    st, p0, p1 = _mk_state(repo, overlay, human_idx=0)

    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # 元々 2000
    b = InPlay.of(repo.get("EB04-045"), sickness=False)  # 元々 2000
    p1.characters = [a, b]

    hack = InPlay.of(repo.get("ST35-001"), sickness=True)
    p0.characters = [hack]
    trigger_on_play(st, p0, p1, hack, overlay)

    assert st.pending_choice is not None, "human で target_pick modal が立つべき"
    assert st.pending_choice.get("kind") == "target_pick"
    cand_iids = [c["iid"] for c in st.pending_choice["candidates"]]
    assert a.instance_id in cand_iids and b.instance_id in cand_iids
    pick = cand_iids.index(b.instance_id)
    resolve_pending_choice(st, [pick])
    _drain_choices(st)

    remaining = [c.instance_id for c in p1.characters]
    assert b.instance_id not in remaining, "選んだ b が KO されていない"
    assert a.instance_id in remaining, "選ばなかった a まで KO された"


# ---------------------------------------------------------------------------
# ST35-002 リンドバーグ : 登場時 相手キャラ1枚まで パワー-3000 (turn)
# ---------------------------------------------------------------------------

def test_st35_002_debuff_ai():
    """AI 文脈: 相手キャラ 1 体が -3000 される。"""
    repo, overlay = _repo(), _overlay()
    st, p0, p1 = _mk_state(repo, overlay)

    tgt = InPlay.of(repo.get("OP11-015"), sickness=False)  # 6000
    p1.characters = [tgt]
    base = tgt.power

    lb = InPlay.of(repo.get("ST35-002"), sickness=True)
    p0.characters = [lb]
    trigger_on_play(st, p0, p1, lb, overlay)
    _drain_choices(st)

    assert tgt.power == base - 3000, f"パワー-3000 が未適用: {tgt.power} (base {base})"


def test_st35_002_human_target_pick():
    """人間 actor: 相手キャラ 2 体 → target_pick で 1 体選択、 選んだ側だけ -3000。"""
    repo, overlay = _repo(), _overlay()
    st, p0, p1 = _mk_state(repo, overlay, human_idx=0)

    a = InPlay.of(repo.get("OP11-015"), sickness=False)  # 6000
    b = InPlay.of(repo.get("ST21-005"), sickness=False)  # 4000
    p1.characters = [a, b]
    a_base, b_base = a.power, b.power

    lb = InPlay.of(repo.get("ST35-002"), sickness=True)
    p0.characters = [lb]
    trigger_on_play(st, p0, p1, lb, overlay)

    assert st.pending_choice is not None
    assert st.pending_choice.get("kind") == "target_pick"
    cand_iids = [c["iid"] for c in st.pending_choice["candidates"]]
    resolve_pending_choice(st, [cand_iids.index(b.instance_id)])
    _drain_choices(st)

    assert b.power == b_base - 3000, "選んだ b が -3000 されていない"
    assert a.power == a_base, "選ばなかった a まで -3000 された"


# ---------------------------------------------------------------------------
# ST35-003 カラス : アタック時 デッキ上2枚トラッシュ(任意) → 相手手札7以上なら discard
# ---------------------------------------------------------------------------

def test_st35_003_discards_when_opp_hand_ge_7_ai():
    """AI 文脈: 相手手札 7 枚 → 任意コスト(自デッキ上2枚トラッシュ) 発動 → 相手 discard。"""
    repo, overlay = _repo(), _overlay()
    st, p0, p1 = _mk_state(repo, overlay)

    p1.hand = [repo.get("OP01-013")] * 7  # 7 枚
    p0.deck = [repo.get("OP01-016")] * 10
    deck_before = len(p0.deck)
    trash_before = len(p0.trash)
    opp_hand_before = len(p1.hand)

    karasu = InPlay.of(repo.get("ST35-003"), sickness=False)
    p0.characters = [karasu]
    trigger_on_attack(st, p0, p1, karasu, overlay)
    _drain_choices(st)

    assert len(p0.deck) == deck_before - 2, "デッキ上2枚がトラッシュに移っていない"
    assert len(p0.trash) == trash_before + 2, "トラッシュ +2 になっていない"
    assert len(p1.hand) == opp_hand_before - 1, "相手手札 7以上で discard が起きていない"


def test_st35_003_no_discard_when_opp_hand_lt_7_ai():
    """相手手札 6 枚 (7未満) → 条件不成立で相手 discard は起きない。"""
    repo, overlay = _repo(), _overlay()
    st, p0, p1 = _mk_state(repo, overlay)

    p1.hand = [repo.get("OP01-013")] * 6  # 6 枚 (< 7)
    p0.deck = [repo.get("OP01-016")] * 10
    opp_hand_before = len(p1.hand)

    karasu = InPlay.of(repo.get("ST35-003"), sickness=False)
    p0.characters = [karasu]
    trigger_on_attack(st, p0, p1, karasu, overlay)
    _drain_choices(st)

    assert len(p1.hand) == opp_hand_before, "手札7未満なのに discard が起きた"


def test_st35_003_human_optional_cost_confirm():
    """人間 actor: 任意コスト confirm modal が立ち、 pay で discard、 skip でノーコスト。"""
    repo, overlay = _repo(), _overlay()

    # --- pay 経路 ---
    st, p0, p1 = _mk_state(repo, overlay, human_idx=0)
    p1.hand = [repo.get("OP01-013")] * 7
    p0.deck = [repo.get("OP01-016")] * 10
    karasu = InPlay.of(repo.get("ST35-003"), sickness=False)
    p0.characters = [karasu]
    trigger_on_attack(st, p0, p1, karasu, overlay)

    assert st.pending_choice is not None, "human で任意コスト confirm が立つべき"
    assert st.pending_choice.get("kind") == "optional_cost_confirm"
    resolve_pending_choice(st, [1])  # pay
    _drain_choices(st)
    assert len(p1.hand) == 6, "pay したのに相手 discard が起きていない"
    assert len(p0.trash) == 2, "pay したのに自デッキ2枚トラッシュが起きていない"

    # --- skip 経路 ---
    st2, q0, q1 = _mk_state(repo, overlay, human_idx=0)
    q1.hand = [repo.get("OP01-013")] * 7
    q0.deck = [repo.get("OP01-016")] * 10
    karasu2 = InPlay.of(repo.get("ST35-003"), sickness=False)
    q0.characters = [karasu2]
    trigger_on_attack(st2, q0, q1, karasu2, overlay)
    assert st2.pending_choice is not None
    assert st2.pending_choice.get("kind") == "optional_cost_confirm"
    resolve_pending_choice(st2, [0])  # skip
    _drain_choices(st2)
    assert len(q1.hand) == 7, "skip したのに相手 discard が起きた"
    assert len(q0.trash) == 0, "skip したのに自デッキがトラッシュされた"


# ---------------------------------------------------------------------------
# ST35-004 コアラ : 静的ブロッカー付与+コスト+1 / 登場時 レストドン+革命軍登場
# ---------------------------------------------------------------------------

def test_st35_004_static_blocker_and_cost_plus_1():
    """静的効果: コアラは【ブロッカー】を得て base_cost = 印刷7 +1 = 8。"""
    repo, overlay = _repo(), _overlay()
    st, p0, p1 = _mk_state(repo, overlay)

    koala = InPlay.of(repo.get("ST35-004"), sickness=False)
    p0.characters = [koala]
    evaluate_static_effects(st, overlay)

    assert koala.base_cost == repo.get("ST35-004").cost + 1 == 8, \
        f"コスト+1 静的が未適用: base_cost={koala.base_cost}"
    assert koala.is_blocker_now, "ブロッカー付与静的が未適用"


def test_st35_005_static_cost_plus_3():
    """静的効果: くまは base_cost = 印刷5 +3 = 8。"""
    repo, overlay = _repo(), _overlay()
    st, p0, p1 = _mk_state(repo, overlay)

    kuma = InPlay.of(repo.get("ST35-005"), sickness=False)
    p0.characters = [kuma]
    evaluate_static_effects(st, overlay)

    assert kuma.base_cost == repo.get("ST35-005").cost + 3 == 8, \
        f"コスト+3 静的が未適用: base_cost={kuma.base_cost}"


def test_st35_004_on_play_attach_don_and_summon_ai():
    """AI 文脈: 登場時 リーダーにレストドン1付与 + 手札の革命軍(≤4000)を登場。"""
    repo, overlay = _repo(), _overlay()
    st, p0, p1 = _mk_state(repo, overlay)
    p0.don_active = 0
    p0.don_rested = 3  # レストドン供給あり
    p0.hand = [repo.get("EB04-045")]  # ジニー (革命軍 cost1 power2000)

    koala = InPlay.of(repo.get("ST35-004"), sickness=True)
    p0.characters = [koala]
    trigger_on_play(st, p0, p1, koala, overlay)
    _drain_choices(st)

    assert p0.leader.attached_dons >= 1, "リーダーにレストドンが付与されていない"
    assert p0.don_rested == 2, "レストドンが 1 消費されていない"
    assert any(c.card.card_id == "EB04-045" for c in p0.characters), \
        "手札の革命軍キャラが登場していない"
    assert not any(c.card_id == "EB04-045" for c in p0.hand), \
        "登場したのに手札に残っている"


def test_st35_005_on_play_summon_from_trash_ai():
    """AI 文脈 (くま): トラッシュからも 革命軍(≤4000) を登場できる。"""
    repo, overlay = _repo(), _overlay()
    st, p0, p1 = _mk_state(repo, overlay)
    p0.don_active = 0
    p0.don_rested = 2
    p0.hand = []
    p0.trash = [repo.get("EB04-045")]  # トラッシュに 革命軍

    kuma = InPlay.of(repo.get("ST35-005"), sickness=True)
    p0.characters = [kuma]
    trigger_on_play(st, p0, p1, kuma, overlay)
    _drain_choices(st)

    assert p0.leader.attached_dons >= 1, "レストドン付与が起きていない"
    assert any(c.card.card_id == "EB04-045" for c in p0.characters), \
        "トラッシュの革命軍が登場していない"


def test_st35_004_on_play_human_summon_pick():
    """人間 actor: 革命軍候補が複数 (手札+トラッシュ) → play_from_hand_or_trash_pick modal
    が立ち、 選んだ 1 枚が登場する。"""
    repo, overlay = _repo(), _overlay()
    st, p0, p1 = _mk_state(repo, overlay, human_idx=0)
    p0.don_active = 0
    p0.don_rested = 3
    p0.hand = [repo.get("EB04-045"), repo.get("OP05-015")]  # 革命軍 2 枚 (手札)
    p0.trash = [repo.get("P-069")]                          # 革命軍 1 枚 (トラッシュ)

    koala = InPlay.of(repo.get("ST35-004"), sickness=True)
    p0.characters = [koala]
    trigger_on_play(st, p0, p1, koala, overlay)

    # まずレストドン付与 (count=1, up_to 無し) は modal 無しで確定。 次に登場の pick modal。
    # (念のため任意の中間 choice を潰しつつ、 登場 pick を掴む)
    guard = 0
    while st.pending_choice is not None and \
            st.pending_choice.get("kind") != "play_from_hand_or_trash_pick" and guard < 4:
        resolve_pending_choice(st, [0])
        guard += 1

    assert st.pending_choice is not None, "登場対象の pick modal が立っていない"
    assert st.pending_choice.get("kind") == "play_from_hand_or_trash_pick"
    cands = st.pending_choice["candidates"]
    # EB04-045 (ジニー) を選ぶ
    pick = next(i for i, c in enumerate(cands) if c["card_id"] == "EB04-045")
    resolve_pending_choice(st, [pick])
    _drain_choices(st)

    assert any(c.card.card_id == "EB04-045" for c in p0.characters), \
        "選んだ革命軍キャラが登場していない"
    assert p0.leader.attached_dons >= 1, "レストドン付与が抜けている"


def test_st35_004_no_summon_target_no_crash_ai():
    """革命軍候補が無くても crash せず、 レストドン付与だけ起きる (「1枚まで」)。"""
    repo, overlay = _repo(), _overlay()
    st, p0, p1 = _mk_state(repo, overlay)
    p0.don_active = 0
    p0.don_rested = 2
    p0.hand = []
    p0.trash = []

    koala = InPlay.of(repo.get("ST35-004"), sickness=True)
    p0.characters = [koala]
    trigger_on_play(st, p0, p1, koala, overlay)
    _drain_choices(st)

    assert p0.leader.attached_dons >= 1, "候補無しでもレストドン付与はされるべき"
    # コアラ本体だけが場に残る (登場は起きない)
    assert [c.card.card_id for c in p0.characters] == ["ST35-004"]
