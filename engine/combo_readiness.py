# -*- coding: utf-8 -*-
"""combo-readiness 特徴量 (= 2026-06-15、 ohtsuki「デッキのコンボを対戦時にAIが使う」)。

デッキの静的コンボマップ ([[combo_finder.find_deck_combos]]) を使い、 ある盤面で
「実行可能なコンボのピースが手札/場に揃っているか」 を scalar 化して value に渡す。

⭐ 設計の鉄則 (= memory): **固定 plan を AI に食わせるのは dead-end**。 ここで渡すのは
「準備度」 = value への bonus であって、 ラインは search が自分で見つける。 これにより
(a) value にコンボ準備度が無い (b) beam が仕込み手を中間枝刈り の 2 つの診断
([[project_combo_aware_ai]]) を、 探索を歪めず value 側から補正する狙い。

🛑 **2026-06-15 measured DEAD-END → value 配線は revert 済み**。 配備 ExploitBeam の GBM value に
W*readiness を足す A/B (mirror、 N=80、 combo 主体 3 デッキ) は **全敗**:
  W=300/1000/2500 で coby = 48/44/41% (= 単調に悪化、 W→0 で中立)、 1454=46% / bonney=48%。
原因 = **準備度 (= ピースが揃った state) を value 加点すると「組成済みを抱える」 状態を
キャンプする誘因**になり、 calibrated な GBM P(win) を歪めるだけ。 どの W でも net positive に
ならない (= best case 中立)。 ⇒ eval.compute_score / exploit_beam_ai の配線は revert、 配備 AI 無傷。

このモジュールは scaffold として残置 (= find_deck_combos と共に、 人間向け「対戦中の生きてる
コンボ」 表示や、 将来「準備度でなく実行 delta を報酬化」 等の別設計の土台)。 value への
再配線は readiness_bonus を compute_score に足すだけ (= 下記)、 ただし上記理由で非推奨。
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


# デッキ単位の人間向けコンボサマリ (= deck_combo_summary) のキャッシュ。 live 判定で使う。
_SUMMARY_CACHE: dict[frozenset, list] = {}


def live_deck_combos(state: Any, me_idx: int) -> list[dict]:
    """me_idx のデッキの実行型コンボのうち、 **今この盤面で全ピースが手札/場/リーダーに
    揃っている** ものを、 人間向け (= card refs + 説明 + 強度) で返す。

    ⭐ ohtsuki 元質問「対戦時に活用」 の本丸 = 試合中に「今狙えるコンボ」 を人間に提示する。
    AI value でなく人間支援なので hoarding 問題は無い (= 静的表示の live 版)。
    ⚠ 「揃っている」 = ピース在場まで。 DON 支払い可否は人間が判断する (= v1)。"""
    try:
        player = state.players[me_idx]
    except Exception:
        return []
    cards = _deck_distinct_cards(player)
    if not cards:
        return []
    key = frozenset(cards)
    summary = _SUMMARY_CACHE.get(key)
    if summary is None:
        from .combo_finder import deck_combo_summary
        leader = _carddef(player.leader) if getattr(player, "leader", None) is not None else None
        summary = deck_combo_summary(list(cards.values()), leader, top_n=40)
        _SUMMARY_CACHE[key] = summary
    if not summary:
        return []
    avail: set[str] = set()
    for attr in ("hand", "characters", "stages"):
        for c in _zone(player, attr):
            avail.add(_cid(c))
    leader = getattr(player, "leader", None)
    if leader is not None:
        avail.add(_cid(leader))
    name_of = {bid: getattr(cd, "name", "") for bid, cd in cards.items()}
    out: list[dict] = []
    for e in summary:
        if all(cid in avail for cid in e.card_ids):
            out.append({
                "cards": [{"card_id": cid, "name": name_of.get(cid, cid)} for cid in e.card_ids],
                "kind": e.kind, "label": e.label,
                "description": e.description, "score": e.score,
            })
    return out


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
