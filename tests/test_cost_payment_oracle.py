# -*- coding: utf-8 -*-
"""コスト支払いオラクルの CI ゲート (= コスト踏み倒しを機械が継続的に発見)。

ohtsuki 指摘「言われれば直せるのに発見できないのはおかしい」 を受けた発見の機械化。
scripts/audit_cost_payment.py が「効果は発火したのに コストの行き先 (trash/ドンデッキ/
自レスト/自離脱) が動かない」 カードを全件 sweep する。 ここで毎 pytest 2 つを保証:

1. 実 DB に コスト踏み倒し 0 (= 退行検出)。
2. オラクル自身が機能している (= _pay_counter_cost を無効化すると ちゃんと検出する)。
   → 「0 件」 が「検査が空振り」 ではなく「本当に踏み倒しが無い」 ことを担保。
"""
from __future__ import annotations

from pathlib import Path

import engine.effects as E
import scripts.audit_cost_payment as oracle
from engine.deck import CardRepository
from engine.effects import load_effect_overlay

ROOT = Path(__file__).resolve().parent.parent


def _load():
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    return repo, overlay


def test_no_cost_skips_in_db():
    """全カードの cost 効果で、 発火したのにコストが払われていないものが 0。"""
    repo, overlay = _load()
    ids = [c for c in repo._by_id
           if not c.endswith(("_p1", "_p2", "_p3", "_p4", "_r1", "_r2"))]
    flags = []
    for cid in ids:
        flags.extend(oracle.audit_card(repo, overlay, cid))
    assert not flags, (
        f"コスト踏み倒し {len(flags)} 件: "
        + "; ".join(f"{f['card_id']}({','.join(f['unpaid'])})" for f in flags[:8])
    )


def test_oracle_detects_injected_skip(monkeypatch):
    """_pay_counter_cost を no-op にすると OP14-080 の discard 踏み倒しを検出する。

    = オラクルが「0 件」 を出すのは 本当に払われているから であって 空振りではない、 の証明。
    """
    repo, overlay = _load()
    # 修正前は OP14-080 が flag されていた。 fix 済の今 [] を確認 (baseline)。
    assert not oracle.audit_card(repo, overlay, "OP14-080"), \
        "fix 済なのに OP14-080 が flag されている"
    # コスト支払いを無効化 → 踏み倒し再現 → オラクルが検出すること。
    monkeypatch.setattr(E, "_pay_counter_cost", lambda *a, **k: None)
    flags = oracle.audit_card(repo, overlay, "OP14-080")
    assert flags and any("discard_hand" in f["unpaid"] for f in flags), \
        "コスト支払いを壊してもオラクルが検出しない (= 空振り)"
