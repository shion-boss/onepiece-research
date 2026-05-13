# -*- coding: utf-8 -*-
"""
変異戦略 (Phase R)
==================

研究セッションの世代交代で使う変異 (mutation) 戦略。 候補デッキ 1 個に対して
1 つの変異を適用し、 新しい候補を返す。

戦略 5 種:
- mutate_swap_card     : 1 枚を同 role/color/cost 代替に置換 (= 局所探索)
- mutate_count_adjust  : ±1 枚調整 (= 軽微変更)
- mutate_role_shift    : 役割比率変更 (例: blocker -1, removal +1)
- mutate_feature_pivot : シナジー特徴を変える (= concept jump、 中変異)
- mutate_leader_change : リーダー変更 (= concept jump、 大変異)

公開 API:
- random_mutation(deck, target_archetype, repo, overlay, role_db, eff_db, rng,
                  must_include=None) -> tuple[DeckList, str]
  - 5 戦略からランダム選択 + 適用
  - must_include カードは保護
  - 戻り値: (新デッキ, 戦略名)
"""

from __future__ import annotations

import random
from collections import Counter
from typing import Optional

from . import card_role, deckbuilder
from .core import CardDef, Category
from .deck import CardRepository, DeckList, _base_id


# ============================================================================ #
# 共通 helper
# ============================================================================ #

def _deck_card_counts(deck: DeckList) -> dict[str, int]:
    """deck.main を {card_id: count} 集計。"""
    out: dict[str, int] = {}
    for c in deck.main:
        out[c.card_id] = out.get(c.card_id, 0) + 1
    return out


def _is_protected(card_id: str, must_include: Optional[set[str]]) -> bool:
    if not must_include:
        return False
    return card_id in must_include or _base_id(card_id) in {_base_id(m) for m in must_include}


def _build_main_from_counts(counts: dict[str, int], repo: CardRepository) -> list[CardDef]:
    """{card_id: count} → list[CardDef] (= 50 枚展開)。"""
    out: list[CardDef] = []
    for cid, n in counts.items():
        try:
            c = repo.get(cid)
            out.extend([c] * n)
        except KeyError:
            continue
    return out


def _to_deck_list(
    leader: CardDef,
    counts: dict[str, int],
    repo: CardRepository,
    name: str,
    regulation: str = "standard",
) -> DeckList:
    return DeckList(
        name=name,
        leader=leader,
        main=_build_main_from_counts(counts, repo),
        regulation=regulation,
    )


# ============================================================================ #
# Mutation 1: swap card (1 枚を代替に置換)
# ============================================================================ #

def mutate_swap_card(
    deck: DeckList,
    target_archetype: str,
    repo: CardRepository,
    role_db: dict,
    eff_db: dict,
    rng: random.Random,
    must_include: Optional[set[str]] = None,
) -> Optional[DeckList]:
    """ランダムに 1 枚を同 role の代替カードに置換。"""
    counts = _deck_card_counts(deck)
    candidates = [cid for cid in counts if not _is_protected(cid, must_include)]
    if not candidates:
        return None

    target_cid = rng.choice(candidates)
    try:
        target_card = repo.get(target_cid)
    except KeyError:
        return None

    role_info = role_db.get(target_cid, {})
    primary_role = role_info.get("primary_role", "synergy")
    leader_colors = list(deck.leader.color)

    alts = card_role.best_cards_against(
        target_archetype,
        target_role=primary_role,
        color_filter=leader_colors,
        cost_range=(max(1, target_card.cost - 1), target_card.cost + 1),
        top_k=20,
        role_db=role_db,
        eff_db=eff_db,
    )
    used_base_ids = {_base_id(cid) for cid in counts}
    alt = next(
        (a for a in alts
         if _base_id(a.card_id) not in used_base_ids
         and a.card_id != deck.leader.card_id
         and a.name != target_card.name),
        None,
    )
    if alt is None:
        return None

    # swap: 全枚置換 (= 部分置換は count_adjust に任せる)
    new_counts = dict(counts)
    n_replace = new_counts.pop(target_cid)
    new_counts[alt.card_id] = n_replace
    return _to_deck_list(deck.leader, new_counts, repo,
                        name=f"{deck.name}_swap_{target_cid}_{alt.card_id}",
                        regulation=deck.regulation)


# ============================================================================ #
# Mutation 2: count adjust (= 1 枚を ±1 + 別カード反対方向)
# ============================================================================ #

def mutate_count_adjust(
    deck: DeckList,
    target_archetype: str,
    repo: CardRepository,
    role_db: dict,
    eff_db: dict,
    rng: random.Random,
    must_include: Optional[set[str]] = None,
) -> Optional[DeckList]:
    """1 枚 -1、 1 枚 +1 (= 50 枚維持)。 -1 候補は protected 除外、 +1 は best から。"""
    counts = _deck_card_counts(deck)
    decrease_pool = [cid for cid, n in counts.items()
                     if n >= 2 and not _is_protected(cid, must_include)]
    if not decrease_pool:
        return None
    inc_pool = [cid for cid, n in counts.items()
                if n < 4 and not _is_protected(cid, must_include)]
    if not inc_pool:
        # 全カード 4 枚なら +1 候補なし。 best_cards_against で外部から探す
        leader_colors = list(deck.leader.color)
        alts = card_role.best_cards_against(
            target_archetype,
            color_filter=leader_colors,
            top_k=30,
            role_db=role_db,
            eff_db=eff_db,
        )
        used_bids = {_base_id(c) for c in counts}
        external_inc = next(
            (a.card_id for a in alts
             if _base_id(a.card_id) not in used_bids
             and a.card_id != deck.leader.card_id),
            None,
        )
        if external_inc is None:
            return None
        target_dec = rng.choice(decrease_pool)
        new_counts = dict(counts)
        new_counts[target_dec] -= 1
        if new_counts[target_dec] == 0:
            del new_counts[target_dec]
        new_counts[external_inc] = 1
        return _to_deck_list(deck.leader, new_counts, repo,
                            name=f"{deck.name}_cnt_{target_dec}-_{external_inc}+",
                            regulation=deck.regulation)

    target_dec = rng.choice(decrease_pool)
    target_inc = rng.choice([c for c in inc_pool if c != target_dec] or inc_pool)
    new_counts = dict(counts)
    new_counts[target_dec] -= 1
    if new_counts[target_dec] == 0:
        del new_counts[target_dec]
    new_counts[target_inc] = new_counts.get(target_inc, 0) + 1
    return _to_deck_list(deck.leader, new_counts, repo,
                        name=f"{deck.name}_cnt_{target_dec}-_{target_inc}+",
                        regulation=deck.regulation)


# ============================================================================ #
# Mutation 3: role shift (= 役割比率変更)
# ============================================================================ #

_ROLE_PAIRS: list[tuple[str, str]] = [
    ("blocker", "removal"),
    ("draw", "finisher"),
    ("recovery", "disruption"),
    ("ramp", "search"),
    ("blocker", "finisher"),
]


def mutate_role_shift(
    deck: DeckList,
    target_archetype: str,
    repo: CardRepository,
    role_db: dict,
    eff_db: dict,
    rng: random.Random,
    must_include: Optional[set[str]] = None,
) -> Optional[DeckList]:
    """ランダムな role pair を選び、 一方を -1 / 他方を +1 して比率を変える。"""
    counts = _deck_card_counts(deck)
    role_a, role_b = rng.choice(_ROLE_PAIRS)
    if rng.random() < 0.5:
        role_a, role_b = role_b, role_a
    # role_a の card を 1 枚減らす (= 採用 ≥ 2 のカード)
    candidates_dec = [
        cid for cid, n in counts.items()
        if n >= 2
        and role_db.get(cid, {}).get("primary_role") == role_a
        and not _is_protected(cid, must_include)
    ]
    if not candidates_dec:
        return None
    target_dec = rng.choice(candidates_dec)
    # role_b の card を + 1 (= 既存採用 < 4 or 外部から)
    leader_colors = list(deck.leader.color)
    alts = card_role.best_cards_against(
        target_archetype,
        target_role=role_b,
        color_filter=leader_colors,
        top_k=20,
        role_db=role_db,
        eff_db=eff_db,
    )
    new_counts = dict(counts)
    new_counts[target_dec] -= 1
    if new_counts[target_dec] == 0:
        del new_counts[target_dec]
    # 既存採用 < 4 のものを優先
    inc_target = next(
        (a.card_id for a in alts
         if a.card_id in new_counts and new_counts[a.card_id] < 4),
        None,
    )
    if inc_target is None:
        # 外部 から
        used_bids = {_base_id(c) for c in new_counts}
        inc_target = next(
            (a.card_id for a in alts
             if _base_id(a.card_id) not in used_bids
             and a.card_id != deck.leader.card_id),
            None,
        )
    if inc_target is None:
        return None
    new_counts[inc_target] = new_counts.get(inc_target, 0) + 1
    return _to_deck_list(deck.leader, new_counts, repo,
                        name=f"{deck.name}_roleshift_{role_a}-_{role_b}+",
                        regulation=deck.regulation)


# ============================================================================ #
# Mutation 4: feature pivot (= シナジー特徴を変える)
# ============================================================================ #

def mutate_feature_pivot(
    deck: DeckList,
    target_archetype: str,
    repo: CardRepository,
    role_db: dict,
    eff_db: dict,
    rng: random.Random,
    must_include: Optional[set[str]] = None,
) -> Optional[DeckList]:
    """deck の上位特徴を別特徴に shift。 = 4 枚を別特徴の card に swap。"""
    leader_features = list(deck.leader.features)
    if len(leader_features) < 2:
        return None

    # 特徴別出現数を集計
    feat_counter: Counter[str] = Counter()
    for c in deck.main:
        for f in c.features:
            feat_counter[f] += 1
    main_feats = [f for f, _ in feat_counter.most_common(3)]
    if not main_feats:
        return None

    # 「現在主特徴」 → 「別 leader 特徴」 に pivot
    current = main_feats[0]
    target_feat = next((f for f in leader_features if f != current), None)
    if target_feat is None:
        return None

    # 現主特徴のカードを 1 枚 -1
    counts = _deck_card_counts(deck)
    decrease_candidates = [
        cid for cid, n in counts.items()
        if n >= 2
        and current in {f for f in repo._by_id.get(cid, repo.get(cid)).features}  # noqa
        and not _is_protected(cid, must_include)
    ]
    if not decrease_candidates:
        return None
    target_dec = rng.choice(decrease_candidates)
    # 新特徴のカードを +1
    leader_colors = list(deck.leader.color)
    alts = card_role.best_cards_against(
        target_archetype,
        color_filter=leader_colors,
        feature_filter=[target_feat],
        top_k=20,
        role_db=role_db,
        eff_db=eff_db,
    )
    used_bids = {_base_id(c) for c in counts}
    inc_target = next(
        (a.card_id for a in alts
         if _base_id(a.card_id) not in used_bids
         and a.card_id != deck.leader.card_id),
        None,
    )
    if inc_target is None:
        return None
    new_counts = dict(counts)
    new_counts[target_dec] -= 1
    if new_counts[target_dec] == 0:
        del new_counts[target_dec]
    new_counts[inc_target] = new_counts.get(inc_target, 0) + 1
    return _to_deck_list(deck.leader, new_counts, repo,
                        name=f"{deck.name}_pivot_{current}->{target_feat}",
                        regulation=deck.regulation)


# ============================================================================ #
# Mutation 5: leader change (= 大変異、 別リーダーで再構築)
# ============================================================================ #

def mutate_leader_change(
    deck: DeckList,
    target_archetype: str,
    repo: CardRepository,
    role_db: dict,
    eff_db: dict,
    rng: random.Random,
    must_include: Optional[set[str]] = None,
    leader_filter: Optional[list[str]] = None,
) -> Optional[DeckList]:
    """別リーダーに変更 + must_include 互換 + 同 deck role を再現する 50 枚を再生成。"""
    # 候補リーダー (= leader_filter 指定なら絞り込み、 そうでなければ全)
    seen_bids: set[str] = set()
    leader_candidates: list[CardDef] = []
    must_include_colors: set[str] = set()
    if must_include:
        for cid in must_include:
            try:
                c = repo.get(cid)
                for col in c.color:
                    must_include_colors.add(col)
            except KeyError:
                pass
    for cid, c in repo._by_id.items():  # noqa
        if c.category != Category.LEADER:
            continue
        bid = _base_id(c.card_id)
        if bid in seen_bids or bid == _base_id(deck.leader.card_id):
            continue
        seen_bids.add(bid)
        if leader_filter and c.card_id not in leader_filter and bid not in leader_filter:
            continue
        if must_include_colors and not must_include_colors.issubset(set(c.color)):
            continue
        leader_candidates.append(c)
    if not leader_candidates:
        return None

    new_leader = rng.choice(leader_candidates)
    leader_colors = list(new_leader.color)

    # 50 枚 を再生成: must_include + best_cards_against で
    must_list = list(must_include) if must_include else []
    # build_with_core で 50 枚に
    try:
        new_deck, _warnings = deckbuilder.build_with_core(
            new_leader.card_id,
            must_list,
            repo,
            name=f"{deck.name}_leader->{new_leader.card_id}",
        )
        return new_deck
    except Exception:
        return None


# ============================================================================ #
# 公開 API: random_mutation
# ============================================================================ #

_STRATEGIES = [
    ("swap_card",      mutate_swap_card,      0.40),
    ("count_adjust",   mutate_count_adjust,   0.25),
    ("role_shift",     mutate_role_shift,     0.15),
    ("feature_pivot",  mutate_feature_pivot,  0.12),
    ("leader_change",  mutate_leader_change,  0.08),
]


def random_mutation(
    deck: DeckList,
    target_archetype: str,
    repo: CardRepository,
    role_db: dict,
    eff_db: dict,
    rng: random.Random,
    must_include: Optional[set[str]] = None,
    leader_filter: Optional[list[str]] = None,
    allowed_strategies: Optional[list[str]] = None,
) -> Optional[tuple[DeckList, str]]:
    """5 戦略からランダム重み付き選択 + 適用。

    Returns:
        (新デッキ, 戦略名) または None (= 失敗時)
    """
    # 重み付きシャッフル → 順に試行
    available = [
        (name, fn, w) for name, fn, w in _STRATEGIES
        if allowed_strategies is None or name in allowed_strategies
    ]
    if not available:
        return None

    # 重み正規化
    total_w = sum(w for _, _, w in available)
    rnd = rng.random() * total_w
    cum = 0.0
    chosen_idx = 0
    for i, (_, _, w) in enumerate(available):
        cum += w
        if rnd <= cum:
            chosen_idx = i
            break

    # 選択戦略から試行 → 失敗なら別戦略にフォールバック
    order = [chosen_idx] + [i for i in range(len(available)) if i != chosen_idx]
    for i in order:
        name, fn, _ = available[i]
        try:
            if name == "leader_change":
                result = fn(deck, target_archetype, repo, role_db, eff_db, rng,
                           must_include=must_include, leader_filter=leader_filter)
            else:
                result = fn(deck, target_archetype, repo, role_db, eff_db, rng,
                           must_include=must_include)
        except Exception:
            continue
        if result is not None:
            try:
                result.validate()
            except Exception:
                continue
            return result, name
    return None
