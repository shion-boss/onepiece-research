# -*- coding: utf-8 -*-
"""combo-readiness 特徴量 (= 2026-06-15、 ohtsuki「デッキのコンボを対戦時にAIが使う」)。

デッキの静的コンボマップ ([[combo_finder.find_deck_combos]]) を使い、 ある盤面で
「実行可能なコンボのピースが手札/場に揃っているか」 を scalar 化して value に渡す。

⭐ 設計の鉄則 (= memory): **固定 plan を AI に食わせるのは dead-end**。 ここで渡すのは
「準備度」 = value への bonus であって、 ラインは search が自分で見つける。 これにより
(a) value にコンボ準備度が無い (b) beam が仕込み手を中間枝刈り の 2 つの診断
([[project_combo_aware_ai]]) を、 探索を歪めず value 側から補正する狙い。

⚠ 効くとは限らない。 v3 raw-DON 特徴が無改善だった前例があるので、 flag-gated で
A/B し、 回帰0 かつ再現性ある改善が無ければ deploy しない (= measured 判定)。

統合: engine/eval.compute_score が ONEPIECE_COMBO_READINESS=1 の時のみ、 GBM/線形 value に
W * combo_readiness を加算する (= flag off で完全 no-op、 配備AI 無傷)。
"""
from __future__ import annotations

import os
from typing import Any

from .combo_finder import find_deck_combos, DeckComboMap, _base_id

# 「実行コンボ」 として value する種別の重み。 tribal/accelerant は受動的な構築シナジーで
# 「両ピースが手札にあると今強い」 ではないので 0 (= 準備度に数えない)。
_KIND_WEIGHT = {
    "enabler": 1.0,    # KO閾値 × 下げ役 が揃う = 中大型を除去できる状態
    "payoff": 1.0,     # 下げ役 × KO閾値 (= enabler の逆向き)
    "amplifier": 0.7,  # 【アタック時】持ち × 速攻付与 が揃う = 即起動できる
    "accelerant": 0.0,
    "tribal": 0.0,
}
_CHAIN_WEIGHT = 1.0

# deck の distinct card 集合 → DeckComboMap (+ 価値ある edge があるか) のキャッシュ。
# distinct card 集合は 1 ゲーム不変なので、 find_deck_combos は 1 デッキ 1 回で済む。
_MAP_CACHE: dict[frozenset, tuple[DeckComboMap, bool]] = {}


def _carddef(c: Any) -> Any:
    """InPlay は .card に CardDef を持つ。 手札の CardDef はそのまま。"""
    return getattr(c, "card", c)


def _cid(c: Any) -> str:
    return _base_id(getattr(_carddef(c), "card_id", "") or "")


def _zone(player: Any, attr: str) -> list:
    return list(getattr(player, attr, None) or [])


def _deck_distinct_cards(player: Any) -> dict[str, Any]:
    """player の全ゾーンから自デッキの distinct カード (= base_id → CardDef) を集める。"""
    out: dict[str, Any] = {}
    for attr in ("hand", "characters", "stages", "deck", "trash", "life"):
        for c in _zone(player, attr):
            cd = _carddef(c)
            cid = _base_id(getattr(cd, "card_id", "") or "")
            if cid:
                out.setdefault(cid, cd)
    leader = getattr(player, "leader", None)
    if leader is not None:
        cd = _carddef(leader)
        cid = _base_id(getattr(cd, "card_id", "") or "")
        if cid:
            out.setdefault(cid, cd)
    return out


def deck_combo_map(player: Any) -> tuple[DeckComboMap, bool]:
    """player の自デッキの静的コンボマップ (+ value 対象 edge が在るか) を返す。 キャッシュ。"""
    cards = _deck_distinct_cards(player)
    key = frozenset(cards)
    hit = _MAP_CACHE.get(key)
    if hit is None:
        leader = _carddef(player.leader) if getattr(player, "leader", None) is not None else None
        m = find_deck_combos(list(cards.values()), leader)
        has_valued = any(_KIND_WEIGHT.get(e.kind, 0.0) > 0 for e in m.edges) or bool(m.chains)
        hit = (m, has_valued)
        _MAP_CACHE[key] = hit
    return hit


def combo_readiness(state: Any, me_idx: int) -> float:
    """me_idx の盤面で「実行可能コンボのピースが手札/場に揃っている度合い」 を返す。

    edge の両端 (= 2枚コンボ) / chain の全ピースが、 今プレイ/起動できるゾーン (= 手札+場+
    リーダー) に揃っていれば、 その強度 score を重み付きで加算する。 揃っていない (= 片方が
    山札/トラッシュ) コンボは 0 (= まだ「準備できていない」)。"""
    try:
        player = state.players[me_idx]
    except Exception:
        return 0.0
    m, has_valued = deck_combo_map(player)
    if not has_valued:
        return 0.0  # 価値あるコンボが無いデッキは常に 0 (= tribal 主体デッキ等、 高速 skip)

    avail: set[str] = set()
    for attr in ("hand", "characters", "stages"):
        for c in _zone(player, attr):
            avail.add(_cid(c))
    leader = getattr(player, "leader", None)
    if leader is not None:
        avail.add(_cid(leader))

    score = 0.0
    for e in m.edges:
        w = _KIND_WEIGHT.get(e.kind, 0.0)
        if w <= 0.0:
            continue
        if e.a_id in avail and e.b_id in avail:
            score += w * e.score
    for ch in m.chains:
        if all(_base_id(s.card_id) in avail for s in ch.steps):
            score += _CHAIN_WEIGHT * ch.score
    return score


def is_enabled() -> bool:
    return os.environ.get("ONEPIECE_COMBO_READINESS") == "1"


def readiness_bonus(state: Any, me_idx: int) -> float:
    """compute_score に加算する value bonus (= flag off / 終局で 0)。 W は env で調整可能。

    ⚠ 終局 (= game_over) では value は ±W_GAME_OVER の確定値。 bonus を足すと壊れるので 0。
    ⚠ v1 は自分 (me_idx) の準備度のみ (= 相手の手札/デッキは隠匿情報で信頼できる map を組めない、
    かつ beam は自分のラインを最適化するので自己組成 nudge で十分)。"""
    if not is_enabled() or getattr(state, "game_over", False):
        return 0.0
    try:
        w = float(os.environ.get("ONEPIECE_COMBO_READINESS_W", "1000"))
    except (TypeError, ValueError):
        w = 1000.0
    return w * combo_readiness(state, me_idx)
