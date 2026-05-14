# -*- coding: utf-8 -*-
"""
マッチアップ推定 + 戦略プロファイル
==================================

相手リーダーから opp の archetype を推定し、 (my, opp) マッチアップ別に
GreedyAI のパラメータ (defense_thresholds / attack_gap_tolerance /
finisher_hold_life) を上書きする。

公開 API:
- `infer_opponent_archetype(state, opp_idx) -> str`:
    opp.leader.card_id を decks/*.analysis.json で逆引き。
    未知リーダーは leader color + プレイ済カードの cost curve から
    {aggro, midrange, control, ramp} を推定。
- `MatchupProfile`: my_archetype / opp_archetype / role を集約
- `build_matchup_profile(state, me_idx, my_archetype) -> MatchupProfile`
- `load_matchup_strategies() -> dict`:
    db/matchup_strategies.json を読み込み (cache 付き)。
- `lookup_matchup_overrides(my, opp) -> Optional[dict]`:
    {attack_gap_tolerance, defense_thresholds, finisher_hold_life} or None

アーキタイプ ID は engine/ai.py と同じ日本語表記:
    "アグロ" / "ミッドレンジ" / "コントロール" / "ランプ"
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .core import GameState


_ROOT = Path(__file__).resolve().parent.parent
_DECKS_DIR = _ROOT / "decks"
_MATCHUP_STRATEGIES_PATH = _ROOT / "db" / "matchup_strategies.json"

ARCHETYPES = ("アグロ", "ミッドレンジ", "コントロール", "ランプ")


@dataclass
class MatchupProfile:
    """マッチアップ識別子と派生ラベル。

    role: マッチアップ全体の役回り
      "beatdown" : 自分が攻撃側 (相手より早く詰める)
      "control"  : 自分が守備側 (相手の攻めを耐え長期戦)
      "race"     : 両者攻撃的 (ダメージレース)
      "balance"  : ミラー / 拮抗
    """

    my_archetype: str
    opp_archetype: str
    role: str


# === 内部キャッシュ ===
_leader_to_archetype_cache: Optional[dict[str, str]] = None
_deck_name_to_archetype_cache: Optional[dict[str, str]] = None
_strategies_cache: Optional[dict] = None


def _load_leader_archetype_map() -> dict[str, str]:
    """decks/cardrush_*.json + analysis.json をスキャンし leader_id → archetype を生成。

    結果は module 内 cache に保持 (= 初回呼出後はファイル I/O 不要)。
    """
    global _leader_to_archetype_cache
    if _leader_to_archetype_cache is not None:
        return _leader_to_archetype_cache
    mapping: dict[str, str] = {}
    # 全 deck JSON を scan (cardrush_*, tcgportal_*, 他の prefix を区別しない)。
    # analysis.json は対応分のみ別途読む。
    for p in sorted(_DECKS_DIR.glob("*.json")):
        if "analysis" in p.name:
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        leader = d.get("leader")
        if not leader:
            continue
        apath = p.with_suffix(".analysis.json")
        if not apath.exists():
            continue
        try:
            ad = json.loads(apath.read_text(encoding="utf-8"))
        except Exception:
            continue
        arche = ad.get("archetype")
        if arche in ARCHETYPES:
            mapping[leader] = arche
    _leader_to_archetype_cache = mapping
    return mapping


def _load_deck_name_archetype_map() -> dict[str, str]:
    """deck の name フィールド (= 「紫エネル」 等) → strategy archetype (= 「ミッドレンジ」)。

    deck_classifier (Phase 7C) は deck 名で archetype を返すため、
    strategy archetype に変換する逆引き map が必要 (Phase 7D)。

    結果は module 内 cache に保持。
    """
    global _deck_name_to_archetype_cache
    if _deck_name_to_archetype_cache is not None:
        return _deck_name_to_archetype_cache
    mapping: dict[str, str] = {}
    for p in sorted(_DECKS_DIR.glob("*.json")):
        if "analysis" in p.name:
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        deck_name = d.get("name")
        if not deck_name:
            continue
        apath = p.with_suffix(".analysis.json")
        if not apath.exists():
            continue
        try:
            ad = json.loads(apath.read_text(encoding="utf-8"))
        except Exception:
            continue
        arche = ad.get("archetype")
        if arche in ARCHETYPES:
            mapping[deck_name] = arche
    _deck_name_to_archetype_cache = mapping
    return mapping


def _fallback_archetype_from_state(state: GameState, opp_idx: int) -> str:
    """analysis.json に未登録のリーダー向け fallback。

    leader.color + opp 場のキャラ cost curve からヒューリスティック判定。
    低コスト多 → aggro、 高コスト多 → ramp/control、 中央 → midrange。
    DON 加速系特徴 (= "DON" など) があれば ramp 寄り。

    確実な値が出ない場合は "ミッドレンジ" を default として返す。
    """
    opp = state.players[opp_idx]
    placed = list(opp.characters)
    # 場が空 / 1 体程度なら 推定不可、 ミッドレンジで返す
    if len(placed) <= 1:
        return "ミッドレンジ"
    costs = [c.card.cost for c in placed]
    avg_cost = sum(costs) / len(costs)
    # 低 cost 集中 = aggro, 高 cost 集中 = ramp/control
    if avg_cost <= 2.0:
        return "アグロ"
    if avg_cost >= 5.5:
        return "ランプ"
    if avg_cost >= 4.0:
        return "コントロール"
    return "ミッドレンジ"


def infer_opponent_archetype(
    state: GameState,
    opp_idx: int,
    use_classifier: bool = True,
    min_confidence: float = 0.4,
) -> str:
    """相手の archetype (= strategy archetype) を推定 (Phase 7D 改修)。

    優先順位:
    1. deck_classifier (Phase 7C) で deck 名を確率推定 → strategy archetype に変換
    2. classifier 信頼度 < min_confidence なら leader_id static map (旧経路)
    3. static map にも無ければ cost curve からヒューリスティック判定

    use_classifier=False で旧挙動 (= static map のみ) に戻せる (test 互換性用)。
    """
    if use_classifier:
        try:
            from . import deck_classifier
            clf = deck_classifier.get_default_classifier()
            probs = clf.classify_from_state(state, opp_idx)
            if probs:
                deck_name_map = _load_deck_name_archetype_map()
                # 信頼度上位 deck から strategy archetype を取得
                top_deck, top_prob = max(probs.items(), key=lambda x: x[1])
                if top_prob >= min_confidence:
                    strategy = deck_name_map.get(top_deck)
                    if strategy:
                        return strategy
                # 低信頼度: strategy 別に確率を集計して最大を取る
                strategy_probs: dict[str, float] = {}
                for deck_name, p in probs.items():
                    strategy = deck_name_map.get(deck_name)
                    if not strategy:
                        continue
                    strategy_probs[strategy] = strategy_probs.get(strategy, 0.0) + p
                if strategy_probs:
                    return max(strategy_probs, key=strategy_probs.get)
        except Exception:
            pass
    # Fallback: 旧 static map
    opp = state.players[opp_idx]
    leader_id = opp.leader.card.card_id
    mapping = _load_leader_archetype_map()
    arche = mapping.get(leader_id)
    if arche:
        return arche
    return _fallback_archetype_from_state(state, opp_idx)


def infer_opponent_archetype_with_confidence(
    state: GameState,
    opp_idx: int,
) -> tuple[str, float]:
    """archetype 推定 + 信頼度 (Phase 7D 追加)。

    Returns: (archetype, confidence in [0.0, 1.0])
      classifier 経由なら deck-level 確率を strategy 単位に集計した値、
      static fallback なら 0.5 を返す。
    """
    try:
        from . import deck_classifier
        clf = deck_classifier.get_default_classifier()
        probs = clf.classify_from_state(state, opp_idx)
        if probs:
            deck_name_map = _load_deck_name_archetype_map()
            strategy_probs: dict[str, float] = {}
            for deck_name, p in probs.items():
                strategy = deck_name_map.get(deck_name)
                if not strategy:
                    continue
                strategy_probs[strategy] = strategy_probs.get(strategy, 0.0) + p
            if strategy_probs:
                top_strategy, top_prob = max(strategy_probs.items(), key=lambda x: x[1])
                return top_strategy, top_prob
    except Exception:
        pass
    arche = infer_opponent_archetype(state, opp_idx, use_classifier=False)
    return arche, 0.5


def _derive_role(my: str, opp: str) -> str:
    """(my, opp) ペアからマッチアップ役回りを決定。

    ミラーマッチ: アグロ同士は race、 その他のミラーは balance。
    異なる archetype 同士: my が攻撃系/守備系 と opp の組合せで決定。
    """
    if my == opp:
        return "race" if my == "アグロ" else "balance"
    aggressive = ("アグロ",)
    defensive = ("コントロール", "ランプ")
    # 自分アグロ vs 守備系 = beatdown (= 押し切る)
    if my in aggressive and opp in defensive:
        return "beatdown"
    # 自分守備系 vs アグロ = control (= 耐える)
    if my in defensive and opp in aggressive:
        return "control"
    # ミッドレンジ vs アグロ = control 寄り、 vs コン/ランプ = beatdown 寄り
    if my == "ミッドレンジ" and opp in aggressive:
        return "control"
    if my == "ミッドレンジ" and opp in defensive:
        return "beatdown"
    if opp == "ミッドレンジ" and my in aggressive:
        return "beatdown"
    if opp == "ミッドレンジ" and my in defensive:
        return "control"
    return "balance"


def build_matchup_profile(
    state: GameState, me_idx: int, my_archetype: str
) -> MatchupProfile:
    """state の opp.leader から MatchupProfile を組み立てる。"""
    opp_archetype = infer_opponent_archetype(state, 1 - me_idx)
    role = _derive_role(my_archetype, opp_archetype)
    return MatchupProfile(
        my_archetype=my_archetype,
        opp_archetype=opp_archetype,
        role=role,
    )


def load_matchup_strategies() -> dict:
    """db/matchup_strategies.json をロード (cache 付き)。

    ファイル未存在時は空 dict を返す (= 上書き無し)。
    """
    global _strategies_cache
    if _strategies_cache is not None:
        return _strategies_cache
    if not _MATCHUP_STRATEGIES_PATH.exists():
        _strategies_cache = {"matchups": {}}
        return _strategies_cache
    try:
        _strategies_cache = json.loads(
            _MATCHUP_STRATEGIES_PATH.read_text(encoding="utf-8")
        )
    except Exception:
        _strategies_cache = {"matchups": {}}
    return _strategies_cache


def lookup_matchup_overrides(
    my_archetype: str, opp_archetype: str
) -> Optional[dict]:
    """(my, opp) ペアに対応する上書き値を返す。

    matchup_strategies.json の構造:
      {"matchups": {"<my>": {"<opp>": {"attack_gap_tolerance": ...,
                                       "defense_thresholds": {...},
                                       "finisher_hold_life": ...}}}}
    """
    strategies = load_matchup_strategies()
    by_my = strategies.get("matchups", {}).get(my_archetype, {})
    overrides = by_my.get(opp_archetype)
    if not overrides:
        return None
    return overrides


def _reset_caches_for_testing() -> None:
    """テスト用: cache を強制リセット (= ファイル変更後に再ロード)。"""
    global _leader_to_archetype_cache, _deck_name_to_archetype_cache, _strategies_cache
    _leader_to_archetype_cache = None
    _deck_name_to_archetype_cache = None
    _strategies_cache = None
    # Phase 7C 連動: deck_classifier の cache も同時リセット (= 学習データ再読込)
    try:
        from . import deck_classifier
        deck_classifier.reset_default_classifier()
    except Exception:
        pass
