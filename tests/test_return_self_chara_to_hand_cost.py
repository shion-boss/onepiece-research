# -*- coding: utf-8 -*-
"""発動コスト 「自分の (filter) キャラ N 枚を持ち主の手札に戻す」 が **実際に支払われる**。

⚠ 2026-08-24: `_can_pay_counter_cost` は このコストを **検査していた** のに
  `_pay_counter_cost` に支払い処理が **無く**、 キャラを戻さずに効果だけ発動していた
  (= タダ撃ち)。 EB01-021 【自分のターン終了時】 が該当。

  [[feedback_check_and_apply_must_share_impl]] 「判定と支払いを別実装にするとタダ撃ちに
  なる」 の実例。 **Rust 側に同じコストを実装したら Rust だけが払うようになり露見**した
  (= 片側実装が他方のバグの検出器になる)。
"""
from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (_can_pay_counter_cost, _pay_counter_cost,
                            load_effect_overlay)
from engine.game import _recompute_static

ROOT = Path(__file__).resolve().parent.parent
FILLER = "OP01-013"
COST = {"return_self_chara_to_hand": {"count": 1,
                                      "filter": {"cost_ge": 2, "feature": "インペルダウン"}}}


def _setup(with_target: bool):
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-002"), sickness=False))
    for p in (p0, p1):
        p.deck = [repo.get(FILLER)] * 10
        p.life = [repo.get(FILLER)] * 3
        p.life_face_up = [False] * 3
    p0.characters.append(InPlay.of(repo.get(FILLER), sickness=False))
    if with_target:
        # インペルダウン かつ コスト2以上 のキャラを 1 体
        tgt = next(c for cid, c in sorted(repo._by_id.items())
                   if "インペルダウン" in (c.features or ()) and (c.cost or 0) >= 2
                   and str(getattr(c.category, "value", c.category)) == "CHARACTER")
        p0.characters.append(InPlay.of(tgt, sickness=False))
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(2),
                   effects_overlay=ov)
    st.turn_player_idx = 0
    _recompute_static(st)
    return st, p0, p1


def test_cost_is_actually_paid():
    """⭐ 支払うとキャラが **手札に戻る** (従来は戻らず効果だけ発動していた)。"""
    st, me, opp = _setup(with_target=True)
    n_before, hand_before = len(me.characters), len(me.hand)
    assert _can_pay_counter_cost(st, me, None, COST), "候補が居るのに払えない判定"
    _pay_counter_cost(st, me, opp, None, COST)
    assert len(me.characters) == n_before - 1, (
        f"コストを払ったのにキャラが場に残っている ({n_before} → {len(me.characters)})")
    assert len(me.hand) == hand_before + 1, "戻したキャラが手札に入っていない"


def test_unpayable_when_no_matching_character():
    """候補が居なければ 「払えない」 = 効果は発動しない (公式 4-10)。"""
    st, me, _opp = _setup(with_target=False)
    assert not _can_pay_counter_cost(st, me, None, COST), \
        "候補が居ないのに払える判定になっている"


def test_rust_parity_for_this_cost():
    """Python↔Rust で同じ支払いになる (= 片側だけ払う状態に戻らない)。"""
    import json

    import optcg_engine as eng

    from engine.state_snapshot import full_dump, state_digest

    eng.load_overlay(str(ROOT / "db" / "card_effects.json"))
    st_py, me, opp = _setup(with_target=True)
    st_rs, _me2, _opp2 = _setup(with_target=True)
    # counter cost は raw effect ではないので、 EB01-021 の end_of_turn 効果として撃つ
    dump = json.dumps(full_dump(st_rs))
    out = json.loads(eng.fire_effect_smoke(dump, "EB01-021", "end_of_turn", 0, -1))
    assert out.get("ok"), f"Rust が bail した: {out.get('err')}"
    from engine.effects import execute_effect
    eff = next(e for e in
               load_effect_overlay(ROOT / "db" / "card_effects.json").get("EB01-021").effects
               if e.get("when") == "end_of_turn")
    st_py.current_source_card_id = "EB01-021"
    if _can_pay_counter_cost(st_py, me, None, eff.get("cost") or {}):
        _pay_counter_cost(st_py, me, opp, None, eff.get("cost") or {})
        for prim in (eff.get("do") or []):
            execute_effect(prim, st_py, me, opp, None)
    st_py.current_source_card_id = None
    assert state_digest(st_py) == out.get("digest"), "Python↔Rust が乖離"
