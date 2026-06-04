# -*- coding: utf-8 -*-
"""効果意味ジャッジ (do 側) の CI ゲート。

audit_effect_conformance.py が「効果が宣言した do を engine が実際に起こしたか」 を検証
(= cost ジャッジ audit_cost_payment.py の do 側姉妹)。 対象 primitive:
  draw / mill_self_top / add_don / add_rested_don / life_to_hand / ko。
発火したのに 期待 footprint (デッキ減/ドン増/ライフ減/相手キャラ減) が 1 枚も動かない =
silent no-op (未実装/誤dispatch/条件で誤って全 block) を検出。 各 primitive は feasibility を
確定 (= 資源注入 / ko は resolver で対象実在を確認) してから照合 → false positive ゼロ。

毎 pytest で保証:
1. 実 DB で silent no-op 0 (= 退行検出)。
2. ジャッジ自身が機能する (= 発火を no-op 化すると draw / ko を検出する) → 非空振り証明。
"""
from __future__ import annotations

from pathlib import Path

import scripts.audit_effect_conformance as judge
from engine.deck import CardRepository
from engine.effects import load_effect_overlay

ROOT = Path(__file__).resolve().parent.parent


def _load():
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    return repo, overlay


def _ids(repo):
    return [c for c in repo._by_id
            if not c.endswith(("_p1", "_p2", "_p3", "_p4", "_r1", "_r2"))]


def test_no_silent_noop_in_db():
    """全カードで モデル化 primitive (draw/mill/add_don/life/ko) が発火したのに
    期待 footprint が動かない (= 空振り) ものが 0。"""
    repo, overlay = _load()
    flags = []
    for cid in _ids(repo):
        flags.extend(judge.audit_card(repo, overlay, cid))
    assert not flags, (
        f"do 空振り {len(flags)} 件: "
        + "; ".join(f"{f['card_id']}({f['miss']})" for f in flags[:8])
    )


def test_judge_detects_noop(monkeypatch):
    """発火 (fire_one_effect) を no-op 化すると draw カードを検出する。

    = 「0 件」 が「検査が空振り」 ではなく 本当に draw が動いている ことの担保。
    """
    repo, overlay = _load()
    # 素直な on_play draw カード (= mdraw でない) を 1 枚探す。
    draw_card = None
    for cid in _ids(repo):
        b = overlay.get(cid)
        if not b:
            continue
        for x in b.effects:
            do = x.get("do", [])
            keys = {k for p in do if isinstance(p, dict) for k in p}
            if x.get("when") == "on_play" and "draw" in keys and not (keys & judge.DECK_ADD):
                draw_card = cid
                break
        if draw_card:
            break
    assert draw_card, "テスト用の素直な draw カードが見つからない"
    # baseline: fix 済の今は flag 0。
    assert not judge.audit_card(repo, overlay, draw_card)
    # 発火を no-op 化 → 「引いたはずが山が減らない」 を検出すること。
    # ⚠ judge は bare import (smoke_test_card_effects) を使う → judge.smoke を patch する
    #   (scripts.smoke_test_card_effects は別モジュールオブジェクトで効かない)。
    monkeypatch.setattr(judge.smoke, "fire_one_effect", lambda *a, **k: None)
    flags = judge.audit_card(repo, overlay, draw_card)
    assert flags and any("draw" in f["miss"] for f in flags), \
        "発火を壊してもジャッジが検出しない (= 空振り)"


def test_judge_detects_ko_noop(monkeypatch):
    """ko を含む効果で 発火を no-op 化すると 相手キャラが減らず検出する (= ko 照合の非空振り)。

    ko は engine resolver で opp 対象実在を確認した時だけ照合する → 対象が解決できた
    ko カードを no-op 発火すると「相手キャラが減っていない」 を必ず検出するはず。
    """
    repo, overlay = _load()
    monkeypatch.setattr(judge.smoke, "fire_one_effect", lambda *a, **k: None)
    found = False
    for cid in _ids(repo):
        b = overlay.get(cid)
        if not b:
            continue
        has_ko = any(
            x.get("when") in judge.FIRED_WHENS and any(
                isinstance(p, dict) and "if" not in p and "ko" in p for p in x.get("do", []))
            for x in b.effects)
        if not has_ko:
            continue
        flags = judge.audit_card(repo, overlay, cid)
        if any("ko" in f["miss"] for f in flags):
            found = True
            break
    assert found, "no-op 発火で ko 踏み倒しを 1 枚も検出しない (= ko 照合が空振り)"
