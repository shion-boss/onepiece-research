# -*- coding: utf-8 -*-
"""
対策デッキ探索エンジン (Phase B)
================================

入力: 対象デッキ + 入力 3 パターン (リーダー指定 / 必須キャラ指定 / 未指定)
出力: 対策候補デッキ Population (= 50 枚レシピを N 件)

memory `project_counter_deck_pipeline.md` の探索フェーズ。 後続:
- Phase C (改善): 進化的探索で個体を反復最適化
- Phase D (実践): bad_moves + board_eval で勝率検証

公開 API:
- generate_counter_candidates(target_deck, repo, overlay, ...) -> list[CounterCandidate]
- determine_counter_role_priority(target_archetype, target_key_cards) -> list[str]
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

from . import card_role, deck_analyzer, deckbuilder, matchup_model
from .core import CardDef, Category
from .deck import CardRepository, DeckList, _base_id


# ============================================================================ #
# 定数: アーキタイプ → 対策役割 priority
# ============================================================================ #

# 対象 archetype に対して有効な役割を priority 高い順で並べる。
# 各役割で best_cards_against を呼び出してカードを集める。
_COUNTER_ROLE_PRIORITY: dict[str, list[str]] = {
    "アグロ":       ["blocker", "recovery", "removal", "draw"],
    "ミッドレンジ": ["removal", "finisher", "draw", "ramp"],
    "コントロール": ["finisher", "disruption", "negation", "draw"],
    "ランプ":       ["disruption", "removal", "finisher", "blocker"],
}

# 各役割で集めるカード数の上限 (= core 候補プール)
_TOP_K_PER_ROLE = 15


# ============================================================================ #
# データ型
# ============================================================================ #

@dataclass
class CounterCandidate:
    """対策候補デッキ 1 件。"""

    deck: DeckList
    leader_id: str
    archetype: str
    estimated_score: int             # 0..100、 効果性の予測 (= effectiveness 平均 + bonus)
    rationale: list[str] = field(default_factory=list)
    role_distribution: dict[str, int] = field(default_factory=dict)


# ============================================================================ #
# 対策役割の決定
# ============================================================================ #

def determine_counter_role_priority(
    target_archetype: str,
    target_key_cards: list[dict] | None = None,
) -> list[str]:
    """対象アーキタイプ + key_cards から対策役割の priority を返す。

    Args:
        target_archetype: アグロ / ミッドレンジ / コントロール / ランプ
        target_key_cards: deck_analyzer の key_cards (= role 付き dict list) or None

    Returns:
        役割名の list (priority 高い順)。 デフォルト 4 つ。
    """
    base = list(_COUNTER_ROLE_PRIORITY.get(target_archetype, ["removal", "draw", "finisher", "blocker"]))

    if not target_key_cards:
        return base

    # 動的調整: key_cards に finisher が多ければ removal を boost (前に出す)
    role_counts = Counter(kc.get("role") for kc in target_key_cards if kc.get("role"))
    if role_counts.get("finisher", 0) >= 3 and "removal" in base:
        base.remove("removal")
        base.insert(0, "removal")
    # search / draw が多ければ disruption を boost
    if role_counts.get("search", 0) + role_counts.get("draw", 0) >= 4 and "disruption" in base:
        base.remove("disruption")
        base.insert(0, "disruption")

    return base


# ============================================================================ #
# リーダー枚挙
# ============================================================================ #

def _enumerate_leaders(
    repo: CardRepository,
    *,
    leader_filter: Optional[list[str]] = None,
    must_include_colors: Optional[set[str]] = None,
) -> list[CardDef]:
    """全リーダーを列挙 (重複 variant は base_id で集約)。"""
    seen_base_ids: set[str] = set()
    out: list[CardDef] = []
    for cid, card in repo._by_id.items():  # noqa
        if card.category != Category.LEADER:
            continue
        bid = _base_id(card.card_id)
        if bid in seen_base_ids:
            continue
        seen_base_ids.add(bid)
        if leader_filter and card.card_id not in leader_filter and bid not in leader_filter:
            continue
        if must_include_colors:
            # must_include カードの全色を leader が持つ必要あり
            if not must_include_colors.issubset(set(card.color)):
                continue
        out.append(card)
    return out


# ============================================================================ #
# アーキタイプ別振り分け
# ============================================================================ #

def _infer_leader_archetype(
    leader: CardDef, archetype_map: dict[str, str]
) -> str:
    """leader_id → archetype 推定 (= matchup_model のマップ + fallback)。"""
    # 既存マップから取得 (= cardrush 由来 deck の archetype)
    a = archetype_map.get(leader.card_id) or archetype_map.get(_base_id(leader.card_id))
    if a:
        return a
    # fallback: leader の text / cost で簡易推定
    text = leader.text or ""
    if "ドン!! デッキから" in text or "アクティブ" in text:
        return "ランプ"
    if leader.life >= 5:
        return "コントロール"
    if leader.life <= 3:
        return "アグロ"
    return "ミッドレンジ"


def _distribute_by_archetype(
    leaders: list[CardDef],
    archetype_map: dict[str, str],
    n_per_archetype: int,
) -> list[CardDef]:
    """アーキタイプ別に round-robin で N 件取得。 不均衡なら他から補充。"""
    by_arch: dict[str, list[CardDef]] = defaultdict(list)
    for leader in leaders:
        arche = _infer_leader_archetype(leader, archetype_map)
        by_arch[arche].append(leader)

    target_archetypes = ("アグロ", "ミッドレンジ", "コントロール", "ランプ")
    out: list[CardDef] = []
    for arche in target_archetypes:
        out.extend(by_arch[arche][:n_per_archetype])
    # 不足分: 余った leader (= n_per_archetype を超えた分) から補充
    if len(out) < n_per_archetype * len(target_archetypes):
        for arche in target_archetypes:
            extra = by_arch[arche][n_per_archetype:]
            out.extend(extra)
    return out


# ============================================================================ #
# core カード抽出 (per leader)
# ============================================================================ #

# Variation 戦略: leader_filter で同一 leader を多数候補に使う場合、 各 variation で
# core 構成を変えて多様性を出す。 5 種類用意。
_MAX_VARIATIONS = 5

_VARIATION_PROFILES: list[dict] = [
    {  # 0: balanced (= デフォルト、 既存挙動)
        "name": "balanced",
        "synergy_count": 8,
        "role_count_each": 4,
        "feature_index": 0,
        "rotate_priority": 0,
    },
    {  # 1: synergy-heavy (= 特徴シナジー寄り)
        "name": "synergy-heavy",
        "synergy_count": 12,
        "role_count_each": 2,
        "feature_index": 0,
        "rotate_priority": 0,
    },
    {  # 2: role-heavy (= 役割対策寄り)
        "name": "role-heavy",
        "synergy_count": 4,
        "role_count_each": 6,
        "feature_index": 0,
        "rotate_priority": 0,
    },
    {  # 3: secondary feature (= 副次特徴軸)
        "name": "secondary-feature",
        "synergy_count": 8,
        "role_count_each": 4,
        "feature_index": 1,
        "rotate_priority": 0,
    },
    {  # 4: rotated priority (= 役割優先順を入れ替え)
        "name": "rotated-priority",
        "synergy_count": 8,
        "role_count_each": 4,
        "feature_index": 0,
        "rotate_priority": 1,
    },
]


def _collect_core_cards(
    leader: CardDef,
    role_priority: list[str],
    opp_archetype: str,
    *,
    role_db: dict,
    eff_db: dict,
    top_k_per_role: int = _TOP_K_PER_ROLE,
    variation: int = 0,
) -> tuple[list[str], dict[str, int], list[str]]:
    """leader 色制約下で role priority 順にカードを集める。

    variation 0..4 の 5 種類で核 構成を変える (= 同 leader でも異なるレシピを生成可)。

    Returns:
        (core_card_ids, role_count, rationale_lines)
    """
    profile = _VARIATION_PROFILES[variation % len(_VARIATION_PROFILES)]
    synergy_count = profile["synergy_count"]
    role_count_each = profile["role_count_each"]
    feature_index = profile["feature_index"]
    rotate = profile["rotate_priority"]

    # role priority を rotate (= variation 4 で 1 つずらす)
    if rotate > 0 and role_priority:
        role_priority = role_priority[rotate:] + role_priority[:rotate]

    leader_colors = list(leader.color)
    leader_features = list(leader.features)
    collected_ids: list[str] = []
    role_count: dict[str, int] = defaultdict(int)
    rationale: list[str] = []
    used_base_ids: set[str] = set()

    # variation rationale (= UI で variation 識別用)
    if variation > 0:
        rationale.append(f"構成タイプ: {profile['name']}")

    # Step A: leader の特徴 (variation で primary or secondary) シナジーカードを最優先
    if leader_features:
        # secondary 指定時は feature[1]、 無ければ [0] にフォールバック
        feat_idx = min(feature_index, len(leader_features) - 1)
        focus_feature = leader_features[feat_idx]
        synergy_scores = card_role.best_cards_against(
            opp_archetype,
            color_filter=leader_colors,
            feature_filter=[focus_feature],
            top_k=max(20, synergy_count + 5),
            role_db=role_db,
            eff_db=eff_db,
        )
        added_synergy = 0
        for s in synergy_scores:
            bid = _base_id(s.card_id)
            if bid in used_base_ids or s.card_id == leader.card_id:
                continue
            collected_ids.append(s.card_id)
            used_base_ids.add(bid)
            added_synergy += 1
            role_count[s.primary_role] += 1
            if added_synergy >= synergy_count:
                break
        if added_synergy > 0:
            rationale.append(
                f"特徴《{focus_feature}》シナジー {added_synergy} 種採用"
            )

    # Step B: 役割 priority 順に残りを埋める
    for role in role_priority:
        scores = card_role.best_cards_against(
            opp_archetype,
            target_role=role,
            color_filter=leader_colors,
            top_k=top_k_per_role,
            role_db=role_db,
            eff_db=eff_db,
        )
        added_for_role = 0
        for s in scores:
            bid = _base_id(s.card_id)
            if bid in used_base_ids:
                continue
            if s.card_id == leader.card_id:
                continue
            collected_ids.append(s.card_id)
            used_base_ids.add(bid)
            added_for_role += 1
            role_count[role] += 1
            if added_for_role >= role_count_each:
                break
        if added_for_role > 0:
            rationale.append(
                f"{role} {added_for_role} 種採用 (vs {opp_archetype})"
            )

    return collected_ids, dict(role_count), rationale


# ============================================================================ #
# estimated_score 計算
# ============================================================================ #

def _compute_estimated_score(
    role_count: dict[str, int],
    role_priority: list[str],
    opp_archetype: str,
    eff_db: dict,
) -> int:
    """役割充足度 + effectiveness 平均 から 0..100 の予測スコア。"""
    if not role_count:
        return 0

    # 各 priority 役割の effectiveness × 採用枚数 で重み付け
    total_weight = 0
    for i, role in enumerate(role_priority):
        n = role_count.get(role, 0)
        if n == 0:
            continue
        eff = card_role.compute_effectiveness(role, [], opp_archetype, db=eff_db)
        # priority 高い役割ほど重み大 (i=0 が最重要)
        weight = (len(role_priority) - i) / len(role_priority)
        total_weight += eff * weight * n

    # 充足度 boost: 全 priority 役割が ≥ 2 種採用なら +10
    if all(role_count.get(role, 0) >= 2 for role in role_priority):
        total_weight += 100

    # 平均化 → 0..100
    score = int(total_weight / max(1, sum(role_count.values())))
    return min(100, max(0, score))


# ============================================================================ #
# メイン API
# ============================================================================ #

def generate_counter_candidates(
    target_deck: DeckList,
    repo: CardRepository,
    overlay: dict,
    *,
    n_candidates: int = 20,
    leader_filter: Optional[list[str]] = None,
    must_include: Optional[list[str]] = None,
    diversity: str = "archetype",
    role_db: Optional[dict] = None,
    eff_db: Optional[dict] = None,
) -> list[CounterCandidate]:
    """対象デッキへの対策候補を N 件生成。

    Args:
        target_deck: 対策対象 (DeckList)
        repo: CardRepository
        overlay: load_effect_overlay の戻り値
        n_candidates: 生成候補数 (= 出力上限)
        leader_filter: 候補リーダー card_id list (None なら全リーダー)
        must_include: 必須カード card_id list (= 全候補に強制注入)
        diversity: archetype / leader / color のいずれか
        role_db / eff_db: card_role の DB (省略時は default ロード)

    Returns:
        estimated_score 降順の CounterCandidate list (最大 n_candidates 件)
    """
    if role_db is None:
        role_db = card_role.load_card_role_db()
    if eff_db is None:
        eff_db = card_role.load_effectiveness_db()

    # Step 1: 対象デッキ分析
    analysis = deck_analyzer.analyze_deck(target_deck, overlay)
    target_archetype = analysis.archetype
    target_key_cards = [
        {"card_id": kc.card_id, "role": kc.role}
        for kc in analysis.key_cards
    ]
    role_priority = determine_counter_role_priority(target_archetype, target_key_cards)

    # Step 2: must_include 必要色集約
    must_include_colors: set[str] = set()
    must_include = must_include or []
    for cid in must_include:
        try:
            c = repo.get(cid)
            for color in c.color:
                must_include_colors.add(color)
        except KeyError:
            pass

    # Step 3: 候補リーダー枚挙
    leaders = _enumerate_leaders(
        repo,
        leader_filter=leader_filter,
        must_include_colors=must_include_colors if must_include_colors else None,
    )
    if not leaders:
        return []

    # Step 4: アーキタイプ別振り分け
    if diversity == "archetype":
        archetype_map = matchup_model._load_leader_archetype_map()
        n_per_arche = max(1, n_candidates // 4 + 1)
        leaders = _distribute_by_archetype(leaders, archetype_map, n_per_arche)

    # Step 5: 各リーダーで候補生成 (variation あり)
    # leader が少数 (= leader_filter で絞られた等) なら 1 leader につき複数 variation を生成。
    n_leaders = max(1, len(leaders))
    import math
    desired_per_leader = max(1, math.ceil(n_candidates / n_leaders))
    variations_to_try = min(desired_per_leader, _MAX_VARIATIONS)

    candidates: list[CounterCandidate] = []
    seen_hashes: set[str] = set()
    archetype_map = matchup_model._load_leader_archetype_map()

    for leader in leaders:
        if len(candidates) >= n_candidates * 2:  # 2x 候補生成 → 後で dedupe + top n
            break

        for variation in range(variations_to_try):
            # core カード収集 (variation 別に異なる構成戦略)
            core_ids, role_count, rationale = _collect_core_cards(
                leader, role_priority, target_archetype,
                role_db=role_db, eff_db=eff_db,
                variation=variation,
            )

            # must_include 強制注入 (= 先頭に置く = build_with_core で優先採用)
            full_core = list(must_include) + [c for c in core_ids if c not in must_include]

            # deckbuilder で 50 枚に組み立て
            try:
                deck, warnings = deckbuilder.build_with_core(
                    leader.card_id, full_core, repo,
                    name=f"counter_{leader.card_id}_v{variation}_vs_{target_deck.name}",
                )
            except (ValueError, Exception):
                continue

            # validate 通らないものは skip
            try:
                deck.validate()
            except Exception:
                continue

            # 重複排除: leader + main set のハッシュ
            recipe_hash = hashlib.md5(
                (
                    leader.card_id + "|" +
                    ",".join(sorted(c.card_id for c in deck.main))
                ).encode("utf-8")
            ).hexdigest()
            if recipe_hash in seen_hashes:
                continue
            seen_hashes.add(recipe_hash)

            # estimated_score 計算
            leader_archetype = _infer_leader_archetype(leader, archetype_map)
            score = _compute_estimated_score(
                role_count, role_priority, target_archetype, eff_db
            )

            candidates.append(CounterCandidate(
                deck=deck,
                leader_id=leader.card_id,
                archetype=leader_archetype,
                estimated_score=score,
                rationale=rationale,
                role_distribution=role_count,
            ))

    # Step 6: estimated_score 降順、 上位 N 件
    candidates.sort(key=lambda c: -c.estimated_score)
    return candidates[:n_candidates]
