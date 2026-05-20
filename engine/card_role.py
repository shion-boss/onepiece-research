# -*- coding: utf-8 -*-
"""
カード役割推論 (Card Role Inference)
====================================

全 4,518 カードに primary_role + 補助 tags を deterministic に派生する。
DSL primitive (db/card_effects.json) ベース。

10 種 primary_role (priority 順):
  finisher / removal / negation / disruption / recovery / ramp /
  search / draw / blocker / synergy

補助 tags (複数可):
  tempo_swing / combo_piece / keyword_grant / protection / redirect /
  cost_reduction / discard_engine / removal / draw / ramp / search / ...
  (= primary に昇格しなかった他の role 候補も tag に残す)

公開 API:
- derive_card_role(card, overlay) -> CardRole
- has_role_or_tag(card, overlay, role) -> bool
- load_card_role_db(path=None) -> dict[str, dict]
- get_card_role(card_id) -> dict | None
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

from .core import CardDef, Category
from .effects import CardEffectBundle


_DEFAULT_ROLE_DB_PATH = Path(__file__).resolve().parent.parent / "db" / "card_roles.json"
_DEFAULT_EFFECTIVENESS_PATH = (
    Path(__file__).resolve().parent.parent / "db" / "card_effectiveness.json"
)

# 公式アーキタイプ ID (engine.matchup_model と同じ表記)
ARCHETYPES: tuple[str, ...] = ("アグロ", "ミッドレンジ", "コントロール", "ランプ")


# ============================================================================ #
# データ型
# ============================================================================ #

@dataclass
class CardRole:
    """カード単体の役割プロファイル。"""

    card_id: str
    primary_role: str
    tags: list[str] = field(default_factory=list)
    threat_level: int = 1  # 1-10
    speed_class: str = "mid"  # early / mid / late
    evidence: list[dict] = field(default_factory=list)


# ============================================================================ #
# primitive 集約
# ============================================================================ #

def _collect_primitives(
    card: CardDef, overlay: Optional[dict]
) -> list[dict[str, Any]]:
    """カードの全 effect の do[] 配列を平坦化して返す。

    overlay = dict[card_id, CardEffectBundle] (load_effect_overlay の戻り値)。
    overlay が None や該当 entry なし の場合は空リスト。
    """
    out: list[dict[str, Any]] = []
    if not overlay:
        return out
    bundle = overlay.get(card.card_id)
    if bundle is None:
        return out
    effects = bundle.effects if isinstance(bundle, CardEffectBundle) else bundle
    for eff in effects:
        if not isinstance(eff, dict):
            continue
        for prim in eff.get("do", []):
            if isinstance(prim, dict):
                out.append(prim)
    return out


# ============================================================================ #
# role 検出シグネチャ
# ============================================================================ #

_REMOVAL_KEYS = frozenset({
    "ko", "ko_multi", "ko_all_others",
    "return_to_hand", "return_to_hand_multi",
    "return_to_deck_bottom", "return_to_deck_bottom_multi",
    "chara_to_self_life", "chara_to_opp_life",
    "other_self_charas_to_deck_bottom", "other_self_charas_to_trash",
})

_NEGATION_KEYS = frozenset({
    "negate_effect", "disable_effect",
    "replace_ko", "prevent_ko",
    "set_ko_immune", "set_ko_immune_timed", "set_ko_immune_battle_only",
})

_DISRUPTION_KEYS = frozenset({
    "trash_opp_hand_random",
    "rest_opp_don",
    "keep_opp_rested_don_next_refresh",
    "opp_trash_to_deck_bottom",
    "trash_to_deck",  # 相手依存ケースで使われる
})

_RECOVERY_KEYS = frozenset({
    "life_to_hand", "life_top_or_bottom_to_hand",
    "put_top_to_life", "hand_to_self_life",
    "chara_to_self_life",
})

_RAMP_KEYS = frozenset({
    "add_don", "add_rested_don", "untap_don",
})

_SEARCH_KEYS = frozenset({
    "search", "search_top_n", "summon_from_deck",
    "reveal_top_then", "reveal_top_play",
})


def _has_keys(prim: dict, keys: frozenset) -> bool:
    return any(k in keys for k in prim.keys())


def _has_removal_signature(primitives: list[dict]) -> Optional[str]:
    for p in primitives:
        for k in p.keys():
            if k in _REMOVAL_KEYS:
                return k
    return None


def _has_negation_signature(primitives: list[dict]) -> Optional[str]:
    for p in primitives:
        for k in p.keys():
            if k in _NEGATION_KEYS:
                return k
            if k == "set_immune_attribute_in_battle":
                v = p.get(k)
                if isinstance(v, dict) and v.get("negate"):
                    return k
    return None


def _has_disruption_signature(primitives: list[dict]) -> Optional[str]:
    for p in primitives:
        for k in p.keys():
            if k in _DISRUPTION_KEYS or k.startswith("mill_opp_"):
                return k
    return None


def _has_recovery_signature(primitives: list[dict]) -> Optional[str]:
    for p in primitives:
        for k in p.keys():
            if k in _RECOVERY_KEYS:
                return k
    return None


def _has_ramp_signature(primitives: list[dict]) -> Optional[str]:
    for p in primitives:
        for k in p.keys():
            if k in _RAMP_KEYS:
                return k
    return None


def _has_search_signature(primitives: list[dict]) -> Optional[str]:
    for p in primitives:
        for k in p.keys():
            if k in _SEARCH_KEYS:
                return k
    return None


def _has_draw_signature(primitives: list[dict]) -> Optional[str]:
    for p in primitives:
        for k in p.keys():
            if k == "draw" or k.startswith("draw_per_"):
                return k
    return None


def _has_blocker_signature(card: CardDef, primitives: list[dict]) -> Optional[str]:
    """キーワード ブロッカー or give_keyword: ブロッカー (自分付与)。"""
    text = card.text or ""
    if "ブロッカー" in text:
        return "keyword:ブロッカー"
    for p in primitives:
        gk = p.get("give_keyword")
        if isinstance(gk, dict):
            kw = gk.get("keyword") or gk.get("keywords")
            if isinstance(kw, str) and "ブロッカー" in kw:
                return "give_keyword:ブロッカー"
            if isinstance(kw, list):
                for x in kw:
                    if isinstance(x, str) and "ブロッカー" in x:
                        return "give_keyword:ブロッカー"
    return None


def _has_finisher_signature(
    card: CardDef, primitives: list[dict]
) -> Optional[str]:
    """finisher: cost ≥ 6 character / extra_turn / give_rush / leader pump ≥ 3000 turn。"""
    if card.category == Category.CHARACTER and card.cost >= 6:
        return f"cost_ge_6:{card.cost}"
    for p in primitives:
        for k in p.keys():
            if k in ("extra_turn", "give_rush", "give_attack_active_chara"):
                return k
            if k == "power_pump":
                pp = p.get(k, {})
                if (
                    isinstance(pp, dict)
                    and pp.get("target") in ("self_leader", "leader")
                    and (pp.get("amount") or 0) >= 3000
                    and pp.get("duration") == "turn"
                ):
                    return "power_pump:leader>=3000"
    return None


# ============================================================================ #
# 補助 tag 検出
# ============================================================================ #

def _collect_aux_tags(card: CardDef, primitives: list[dict]) -> set[str]:
    tags: set[str] = set()

    for p in primitives:
        for k in p.keys():
            # redirect
            if k == "redirect_attack":
                tags.add("redirect")
            # keyword_grant (= ブロッカー以外も含む)
            if k == "give_keyword":
                tags.add("keyword_grant")
            # protection
            if (
                k.startswith("set_ko_immune")
                or k.startswith("prevent_self_life")
                or k == "set_opp_protect_static"
            ):
                tags.add("protection")
            # cost reduction
            if (
                k.startswith("reduce_play_cost")
                or k.startswith("set_base_cost")
                or k == "cost_minus"
            ):
                tags.add("cost_reduction")
            # tempo_swing: power_pump amount ≥ 4000 OR set_base_power
            if k == "power_pump":
                pp = p.get(k, {})
                if isinstance(pp, dict) and (pp.get("amount") or 0) >= 4000:
                    tags.add("tempo_swing")
            if k in ("set_base_power", "set_base_power_timed", "set_base_power_copy"):
                tags.add("tempo_swing")
            # combo_piece: optional_cost_then は条件分岐コンボ
            if k == "optional_cost_then":
                tags.add("combo_piece")

    # discard_engine: trash_self_hand_random + draw 系を同時に持つ
    has_discard = any("trash_self_hand_random" in p for p in primitives)
    has_draw = any(
        any(k == "draw" or k.startswith("draw_per_") for k in p.keys())
        for p in primitives
    )
    if has_discard and has_draw:
        tags.add("discard_engine")

    return tags


# ============================================================================ #
# threat_level / speed_class
# ============================================================================ #

def _compute_threat_level(card: CardDef, primary: str) -> int:
    """1〜10 のスコア。 cost ベース + role ボーナス。"""
    base = max(1, min(10, card.cost))
    bonus = 0
    if primary in ("finisher", "removal", "negation"):
        bonus = 1
    return min(10, base + bonus)


def _compute_speed_class(card: CardDef) -> str:
    if card.cost <= 2:
        return "early"
    if card.cost <= 5:
        return "mid"
    return "late"


# ============================================================================ #
# メイン推論
# ============================================================================ #

# primary 採用順 (上にあるほど優先)
_PRIMARY_PRIORITY: tuple[str, ...] = (
    "finisher",
    "removal",
    "negation",
    "disruption",
    "recovery",
    "ramp",
    "search",
    "draw",
    "blocker",
    "synergy",
)


def derive_card_role(
    card: CardDef, overlay: Optional[dict] = None
) -> CardRole:
    """カード単体の役割プロファイルを返す。

    Args:
        card: CardDef
        overlay: load_effect_overlay の戻り値 (dict[card_id, CardEffectBundle])。
                 None の場合は overlay 由来 role 判定はスキップされ、
                 finisher (cost ≥ 6) と blocker (keyword) のみ判定可能。

    Returns:
        CardRole (primary_role + tags + threat_level + speed_class + evidence)
    """
    primitives = _collect_primitives(card, overlay)
    evidence: list[dict] = []

    # Step 1: 全候補 role を集約 (= primary 候補 ∪ tag 候補)
    role_signatures: dict[str, str] = {}

    if (sig := _has_finisher_signature(card, primitives)):
        role_signatures["finisher"] = sig
    if (sig := _has_removal_signature(primitives)):
        role_signatures["removal"] = sig
    if (sig := _has_negation_signature(primitives)):
        role_signatures["negation"] = sig
    if (sig := _has_disruption_signature(primitives)):
        role_signatures["disruption"] = sig
    if (sig := _has_recovery_signature(primitives)):
        role_signatures["recovery"] = sig
    if (sig := _has_ramp_signature(primitives)):
        role_signatures["ramp"] = sig
    if (sig := _has_search_signature(primitives)):
        role_signatures["search"] = sig
    if (sig := _has_draw_signature(primitives)):
        role_signatures["draw"] = sig
    if (sig := _has_blocker_signature(card, primitives)):
        role_signatures["blocker"] = sig

    # Step 2: priority 順で primary を選択
    primary: Optional[str] = None
    for r in _PRIMARY_PRIORITY:
        if r in role_signatures:
            primary = r
            evidence.append({"primitive": role_signatures[r], "rationale": f"primary={r}"})
            break

    # Step 3: primary が無ければ synergy default (= 残り全カード)
    if primary is None:
        primary = "synergy"
        if card.category == Category.CHARACTER and card.features:
            evidence.append({
                "default": "synergy",
                "rationale": f"character with features {list(card.features)[:3]}",
            })
        else:
            evidence.append({
                "default": "synergy_fallback",
                "rationale": "no specific role detected",
            })

    # Step 4: tags = (他の role 候補) ∪ aux_tags
    tag_set = set(role_signatures.keys()) - {primary}
    tag_set |= _collect_aux_tags(card, primitives)

    threat_level = _compute_threat_level(card, primary)
    speed_class = _compute_speed_class(card)

    return CardRole(
        card_id=card.card_id,
        primary_role=primary,
        tags=sorted(tag_set),
        threat_level=threat_level,
        speed_class=speed_class,
        evidence=evidence,
    )


def has_role_or_tag(
    card: CardDef, overlay: Optional[dict], role: str
) -> bool:
    """deck_analyzer.py の `_is_*_card` 互換 wrapper。

    role が primary_role か tags に含まれていれば True。
    """
    cr = derive_card_role(card, overlay)
    return cr.primary_role == role or role in cr.tags


# ============================================================================ #
# JSON DB ロード / 取得
# ============================================================================ #

_card_role_db_cache: Optional[dict[str, dict]] = None


def load_card_role_db(
    path: str | Path | None = None, *, force_reload: bool = False
) -> dict[str, dict]:
    """db/card_roles.json をロード (cache 付き)。

    Returns:
        dict[card_id, role_dict]。 _meta などの underscore キーは除外済。
        ファイル不在の場合は空 dict。
    """
    global _card_role_db_cache
    if _card_role_db_cache is not None and not force_reload and path is None:
        return _card_role_db_cache
    p = Path(path) if path else _DEFAULT_ROLE_DB_PATH
    if not p.exists():
        out: dict[str, dict] = {}
    else:
        raw = json.loads(p.read_text(encoding="utf-8"))
        out = {k: v for k, v in raw.items() if not k.startswith("_") and isinstance(v, dict)}
    if path is None:
        _card_role_db_cache = out
    return out


def get_card_role(card_id: str) -> Optional[dict]:
    """db/card_roles.json から 1 枚分の role 情報を取得。"""
    db = load_card_role_db()
    return db.get(card_id)


def card_role_to_dict(cr: CardRole) -> dict:
    """CardRole を JSON シリアライズ用 dict に変換。"""
    return asdict(cr)


# ============================================================================ #
# effectiveness (R66): 役割 × 相手アーキタイプ の有効性スコア
# ============================================================================ #

_effectiveness_cache: Optional[dict] = None


def load_effectiveness_db(
    path: str | Path | None = None, *, force_reload: bool = False
) -> dict:
    """db/card_effectiveness.json をロード (cache 付き)。

    Returns:
        生 JSON dict (by_role / by_tag_modifier セクション含む)。
    """
    global _effectiveness_cache
    if _effectiveness_cache is not None and not force_reload and path is None:
        return _effectiveness_cache
    p = Path(path) if path else _DEFAULT_EFFECTIVENESS_PATH
    if not p.exists():
        out: dict = {"by_role": {}, "by_tag_modifier": {}}
    else:
        out = json.loads(p.read_text(encoding="utf-8"))
    if path is None:
        _effectiveness_cache = out
    return out


def compute_effectiveness(
    role: str,
    tags: list[str] | tuple[str, ...] | set[str] | None,
    opp_archetype: str,
    *,
    db: Optional[dict] = None,
) -> int:
    """役割 + 補助タグ + 相手アーキタイプから有効性スコア (0..100) を返す。

    最終 score = clamp(by_role[role][opp_arche] + Σ by_tag_modifier[tag][opp_arche], 0, 100)。

    role / opp_archetype が DB に無い場合は中性 50 を返す。
    """
    if db is None:
        db = load_effectiveness_db()
    by_role = db.get("by_role", {})
    by_tag = db.get("by_tag_modifier", {})

    role_entry = by_role.get(role)
    if not isinstance(role_entry, dict):
        return 50
    base = role_entry.get(opp_archetype)
    if not isinstance(base, (int, float)):
        return 50
    score = float(base)

    for t in tags or ():
        mod_entry = by_tag.get(t)
        if not isinstance(mod_entry, dict):
            continue
        m = mod_entry.get(opp_archetype)
        if isinstance(m, (int, float)):
            score += float(m)

    return max(0, min(100, int(round(score))))


# ============================================================================ #
# Phase B 接続点: best_cards_against
# ============================================================================ #

@dataclass
class CardScore:
    """best_cards_against の戻り値 1 件。"""

    card_id: str
    name: str
    primary_role: str
    tags: list[str]
    cost: int
    color: list[str]
    features: list[str]
    effectiveness: int
    threat_level: int


def compute_role_priorities(
    card_ids: list[str] | tuple[str, ...],
    opp_archetype: str,
    *,
    role_db: Optional[dict] = None,
    eff_db: Optional[dict] = None,
) -> dict[str, int]:
    """与えられたカード ID list に対する effectiveness map を返す。

    AI の choose_action で「今プレイ可能な候補を effectiveness 順で並べる」 等に使用。

    Args:
        card_ids: 評価対象 (= 自分の手札 / 場のキャラ / アタック候補 等)
        opp_archetype: アグロ / ミッドレンジ / コントロール / ランプ
        role_db: load_card_role_db() の戻り値 (省略時は default ロード)
        eff_db: load_effectiveness_db() の戻り値 (省略時は default ロード)

    Returns:
        {card_id: effectiveness (0..100)} の dict。
        role_db に無い card_id は 50 (中性) で返す。
    """
    if role_db is None:
        role_db = load_card_role_db()
    if eff_db is None:
        eff_db = load_effectiveness_db()

    out: dict[str, int] = {}
    for cid in card_ids:
        v = role_db.get(cid)
        if not isinstance(v, dict):
            out[cid] = 50
            continue
        out[cid] = compute_effectiveness(
            v.get("primary_role", "synergy"),
            v.get("tags", []),
            opp_archetype,
            db=eff_db,
        )
    return out


def best_cards_against(
    opp_archetype: str,
    *,
    target_role: Optional[str] = None,
    cost_range: Optional[tuple[int, int]] = None,
    color_filter: Optional[list[str]] = None,
    feature_filter: Optional[list[str]] = None,
    category_filter: Optional[list[str]] = None,
    top_k: int = 50,
    role_db: Optional[dict] = None,
    eff_db: Optional[dict] = None,
) -> list[CardScore]:
    """相手アーキタイプに対して有効性が高いカードを top_k 件返す。

    Phase B (探索エンジン) の主要 API。 以下のクエリが書ける:
        best_cards_against("ランプ", target_role="disruption", cost_range=(3, 5))
        best_cards_against("アグロ", target_role="blocker", color_filter=["赤"])

    Args:
        opp_archetype: アグロ / ミッドレンジ / コントロール / ランプ
        target_role: primary_role でフィルタ (None なら全 role)
        cost_range: (min, max) inclusive
        color_filter: いずれかの色を持つカードのみ
        feature_filter: いずれかの特徴を持つカードのみ
        category_filter: ["CHARACTER", "EVENT", "STAGE"] のサブセット
        top_k: 上位 N 件返す

    Returns:
        effectiveness 降順、 同点は threat_level 降順で並ぶ CardScore list。
    """
    if role_db is None:
        role_db = load_card_role_db()
    if eff_db is None:
        eff_db = load_effectiveness_db()

    out: list[CardScore] = []
    for cid, v in role_db.items():
        if not isinstance(v, dict):
            continue
        primary = v.get("primary_role")
        if target_role and primary != target_role:
            continue
        cost = v.get("cost", 0)
        if cost_range:
            lo, hi = cost_range
            if cost < lo or cost > hi:
                continue
        if color_filter:
            cs = v.get("color", [])
            if not any(c in cs for c in color_filter):
                continue
        if feature_filter:
            fs = v.get("features", [])
            if not any(f in fs for f in feature_filter):
                continue
        if category_filter:
            cat = v.get("category")
            if cat not in category_filter:
                continue

        eff = compute_effectiveness(
            primary, v.get("tags", []), opp_archetype, db=eff_db
        )
        out.append(CardScore(
            card_id=cid,
            name=v.get("name", ""),
            primary_role=primary or "synergy",
            tags=list(v.get("tags", [])),
            cost=cost,
            color=list(v.get("color", [])),
            features=list(v.get("features", [])),
            effectiveness=eff,
            threat_level=v.get("threat_level", 1),
        ))

    out.sort(key=lambda s: (-s.effectiveness, -s.threat_level, s.cost))
    return out[:top_k]
