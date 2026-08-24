# -*- coding: utf-8 -*-
"""P-059 「世界のつづき」 — 「任意の枚数」 「てもよい」 の選択権。

公式テキスト: 「【カウンター】自分のリーダーが「ウタ」の場合、 自分の場のキャラを
**任意の枚数** 手札に戻して**もよい**。 自分のリーダーかキャラ1枚までは、 このバトル中、
戻したキャラ1枚につきパワー+2000。」

⚠ 2026-08-24 是正: `return_self_charas_then_pump_per` は **pump 対象以外を問答無用で全戻し**
  していた。 枚数も対象も選べず、 0 枚 (= 総合ルール 1-3-5-1) も選べない。 自分の盤面を
  最大限に壊す方向へ固定されていた = [[feedback_human_ai_option_parity]] 違反。

検出は `scripts/audit_human_choice_coverage.py` の 「〜てもよい」 flag。
"""
from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import execute_effect, load_effect_overlay, resolve_pending_choice

ROOT = Path(__file__).resolve().parent.parent
FILLER = "OP01-013"
SPEC_KEY = "return_self_charas_then_pump_per"


def _setup(n_chara: int = 3):
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-002"), sickness=False))
    for p in (p0, p1):
        p.deck = [repo.get(FILLER)] * 10
        p.life = [repo.get(FILLER)] * 3
        p.life_face_up = [False] * 3
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(7),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    for _ in range(n_chara):
        p0.characters.append(InPlay.of(repo.get(FILLER), sickness=False))
    return repo, st, p0, p1


SPEC = {SPEC_KEY: {"amount": 2000, "duration": "battle", "target": "self_inplay"}}


def test_p059_overlay_uses_the_choice_primitive():
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    eff = next(e for e in overlay.get("P-059").effects if e.get("when") == "counter")
    assert any(SPEC_KEY in d for d in eff.get("do", [])), \
        f"P-059 の counter が {SPEC_KEY} を使っていない: {eff.get('do')}"


def test_p059_ai_mode_keeps_legacy_behaviour():
    """選択を列挙しない (= 従来の AI) モードでは挙動を変えない = self-play / parity 不変。"""
    _repo, st, me, opp = _setup(3)
    hand_before = len(me.hand)
    execute_effect(SPEC, st, me, opp, me.leader)
    assert st.pending_choice is None, "AI モードで選択を立ててはいけない"
    # `self_inplay` の AI 既定はパワー最大 = 自リーダー → キャラは全戻し (従来どおり)
    assert len(me.characters) == 0, (
        f"AI 既定 (= 全戻し) が変わっている: {len(me.characters)}")
    assert len(me.hand) == hand_before + 3
    assert me.leader.battle_buff == 6000, (
        f"3 枚戻しぶんの +6000 が乗っていない: {me.leader.battle_buff}")


def test_p059_human_can_return_zero():
    """⭐ 「任意の枚数」 = **0 枚を選べる** (総合 1-3-5-1)。 従来は強制全戻しだった。"""
    _repo, st, me, opp = _setup(3)
    st.human_player_idx = 0
    hand_before = len(me.hand)
    chara_before = len(me.characters)
    execute_effect(SPEC, st, me, opp, me.leader)
    # 1 段目 = pump 対象の選択
    assert st.pending_choice is not None, "pump 対象の選択が立たない"
    resolve_pending_choice(st, [0])
    # 2 段目 = 戻す枚数の選択 → **0 枚**
    assert st.pending_choice is not None, "手札に戻す枚数の選択が立たない (= 強制全戻し)"
    assert st.pending_choice.get("primitive_kind") == SPEC_KEY
    resolve_pending_choice(st, [])
    assert st.pending_choice is None
    assert len(me.characters) == chara_before, (
        f"0 枚を選んだのにキャラが減っている: {len(me.characters)} (before {chara_before})")
    assert len(me.hand) == hand_before, "0 枚を選んだのに手札が増えている"
    assert all(ip.battle_buff == 0 for ip in [me.leader, *me.characters]), \
        "0 枚戻しなのに pump されている"


def test_p059_human_can_return_one_and_pumps_by_that_count():
    """1 枚だけ戻す → +2000 (= 戻した枚数ぶんだけ)。"""
    _repo, st, me, opp = _setup(3)
    st.human_player_idx = 0
    hand_before = len(me.hand)
    execute_effect(SPEC, st, me, opp, me.leader)
    assert st.pending_choice is not None
    cands = st.pending_choice.get("candidates") or []
    leader_idx = next(i for i, c in enumerate(cands) if c.get("is_leader"))
    resolve_pending_choice(st, [leader_idx])  # pump 対象 = 自リーダー
    assert st.pending_choice is not None
    n_cands = len(st.pending_choice.get("candidates") or [])
    assert n_cands == 3, f"リーダーを pump 対象にしたので候補は自キャラ 3 枚のはず: {n_cands}"
    resolve_pending_choice(st, [0])  # 1 枚だけ戻す
    assert st.pending_choice is None
    assert len(me.characters) == 2, f"1 枚だけ戻っていない: {len(me.characters)}"
    assert len(me.hand) == hand_before + 1
    assert me.leader.battle_buff == 2000, (
        f"戻した 1 枚ぶんの +2000 が乗っていない: {me.leader.battle_buff}")


def _rust_digest_after(st, spec, me_idx=0):
    import json

    import optcg_engine as eng

    from engine.state_snapshot import full_dump

    eng.load_overlay(str(ROOT / "db" / "card_effects.json"))
    return eng.apply_raw_effect_digest(json.dumps(full_dump(st)), json.dumps(spec), me_idx)


def test_p059_python_rust_parity_ai_mode():
    """列挙 OFF (= self-play / matrix が通る経路) は Python と Rust で bit 一致。"""
    from engine.state_snapshot import state_digest

    _repo, st_py, me, opp = _setup(3)
    _repo2, st_rs, _me2, _opp2 = _setup(3)
    rust = _rust_digest_after(st_rs, SPEC)
    execute_effect(SPEC, st_py, me, opp, me.leader)
    assert state_digest(st_py) == rust, "列挙 OFF で Python↔Rust が乖離している"


def test_p059_python_rust_parity_choice_enumeration_suspends():
    """列挙 ON では **両エンジンとも中断** する (= Rust が黙って全戻ししない)。

    ⚠ Rust に 2 段選択を移植しないと、 Python は止まって盤面不変・Rust は全戻し →
      **silent MISMATCH**。 この test はその型を直接踏む。
    """
    from engine.state_snapshot import state_digest

    _repo, st_py, me, opp = _setup(3)
    _repo2, st_rs, _me2, _opp2 = _setup(3)
    st_py.choice_enumeration = True
    st_rs.choice_enumeration = True
    chara_before = len(me.characters)
    rust = _rust_digest_after(st_rs, SPEC)
    execute_effect(SPEC, st_py, me, opp, me.leader)
    assert st_py.pending_choice is not None, "Python が中断していない"
    assert len(me.characters) == chara_before, "中断中なのに盤面が動いている"
    assert state_digest(st_py) == rust, (
        "列挙 ON で Python↔Rust が乖離 (= Rust が中断せず勝手に全戻ししている疑い)"
    )
