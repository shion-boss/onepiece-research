# -*- coding: utf-8 -*-
"""
シンプルなデッキ自動生成
========================

リーダーのカード ID を渡すと、そのリーダーの色に合った 50 枚のキャラ + イベントを
コストカーブを意識して並べた "そこそこ動くデッキ" を返す。

* Phase 5 のフルスペックデッキビルダーの叩き台
* 効果テキスト解析はしない(MVP)
* キャラを中心に、コスト 1〜7 をバランスよく組む
* 同名 4 枚制限を厳守
"""

from __future__ import annotations

import random
from collections import Counter
from pathlib import Path
from typing import Optional

from .core import CardDef, Category
from .deck import CardRepository, DeckList, _base_id
from .effects import load_effect_overlay

_DEFAULT_OVERLAY_PATH = (
    Path(__file__).resolve().parent.parent / "db" / "card_effects.json"
)


def _load_effect_keys() -> set[str]:
    overlay = load_effect_overlay(_DEFAULT_OVERLAY_PATH)
    return set(overlay.keys())


def auto_build_deck(
    leader_id: str,
    repo: CardRepository,
    rng: random.Random | None = None,
    name: str | None = None,
    effect_priority: bool = True,
    effect_keys: Optional[set[str]] = None,
) -> DeckList:
    """リーダーの色合いから 50 枚デッキを自動生成。

    effect_priority=True (default) のとき、各コスト帯のカードを
    「効果オーバーレイあり > パワー > カウンター」の優先度で詰める。
    """
    if rng is None:
        rng = random.Random(0)
    if effect_keys is None and effect_priority:
        effect_keys = _load_effect_keys()
    elif effect_keys is None:
        effect_keys = set()

    leader = repo.get(leader_id)
    if leader.category != Category.LEADER:
        raise ValueError(f"{leader_id} はリーダーではない")

    leader_colors = set(leader.color)

    # 候補カード: リーダーの色に含まれ、キャラ/イベント
    candidates: list[CardDef] = []
    seen: set[str] = set()
    # repo は内部辞書を持つので強引にアクセス
    for cid, c in repo._by_id.items():  # noqa
        if c.card_id in seen:
            continue
        seen.add(c.card_id)
        if c.category not in (Category.CHARACTER, Category.EVENT, Category.STAGE):
            continue
        if not (set(c.color) & leader_colors):
            continue
        # 自前色のみ採用(複合カードはリーダー色に全色含まれるなら可)
        if not set(c.color).issubset(leader_colors):
            continue
        # コスト 0 以下のカード(ラインナップ含むスペシャル)は除外
        if c.cost <= 0:
            continue
        candidates.append(c)

    # コストカーブ目標(50 枚)
    # ざっくり: cost1=8, 2=10, 3=10, 4=8, 5=6, 6=4, 7=4
    curve_target = {1: 8, 2: 10, 3: 10, 4: 8, 5: 6, 6: 4, 7: 4}

    chosen: list[CardDef] = []
    used: Counter[str] = Counter()  # base_id -> count
    by_cost: dict[int, list[CardDef]] = {}
    for c in candidates:
        by_cost.setdefault(c.cost, []).append(c)

    for cost, target in curve_target.items():
        pool = by_cost.get(cost, [])
        # 効果あり > パワー高 > カウンター値高 の優先度
        pool_sorted = sorted(
            pool,
            key=lambda c: (
                1 if c.card_id in effect_keys else 0,
                c.power,
                c.counter,
            ),
            reverse=True,
        )
        added = 0
        for c in pool_sorted:
            if added >= target:
                break
            bid = _base_id(c.card_id)
            allowed = 4 - used[bid]
            need = target - added
            n = min(allowed, need, 4)
            if n <= 0:
                continue
            chosen.extend([c] * n)
            used[bid] += n
            added += n

    # 50 枚に届かなければ汎用カウンターカードで補充
    counter_pool = sorted(
        [c for c in candidates if c.counter > 0],
        key=lambda c: (-c.counter, c.cost),
    )
    while len(chosen) < 50 and counter_pool:
        for c in counter_pool:
            if used[_base_id(c.card_id)] >= 4:
                continue
            chosen.append(c)
            used[_base_id(c.card_id)] += 1
            if len(chosen) >= 50:
                break
        else:
            break

    # それでも足りなければ何か追加(色さえ合えば何でも)
    while len(chosen) < 50:
        for c in candidates:
            if used[_base_id(c.card_id)] >= 4:
                continue
            chosen.append(c)
            used[_base_id(c.card_id)] += 1
            if len(chosen) >= 50:
                break
        else:
            break

    # 多すぎたら削る
    chosen = chosen[:50]
    rng.shuffle(chosen)

    return DeckList(
        name=name or f"AutoDeck<{leader.name}>",
        leader=leader,
        main=chosen,
    )


def build_with_core(
    leader_id: str,
    core_card_ids: list[str],
    repo: CardRepository,
    core_counts: Optional[dict[str, int]] = None,
    rng: random.Random | None = None,
    name: str | None = None,
) -> tuple[DeckList, list[str]]:
    """「使いたいコアカード」を固定した上で、リーダー色合致カードで 50 枚に埋めるビルダー。

    Phase 5: コアカード固定型デッキビルダーの本番実装。

    Args:
        leader_id: リーダーカード ID
        core_card_ids: 必ず採用したいカードの list (1 枚ずつ採用)。
        core_counts: 個別に採用枚数を指定したい場合の dict {card_id: count}。
                     未指定キャラは 4 枚採用 (上限まで)。
        rng: シャッフル用乱数
        name: デッキ名

    Returns:
        (DeckList, warnings) — warnings は色合致しなかったカードや採用できなかったコア。
    """
    if rng is None:
        rng = random.Random(0)
    core_counts = core_counts or {}

    leader = repo.get(leader_id)
    if leader.category != Category.LEADER:
        raise ValueError(f"{leader_id} はリーダーではない")
    leader_colors = set(leader.color)

    warnings: list[str] = []
    effect_keys = _load_effect_keys()

    # コアカードを最優先で採用
    chosen: list[CardDef] = []
    used: Counter[str] = Counter()

    for cid in core_card_ids:
        try:
            c = repo.get(cid)
        except KeyError:
            warnings.append(f"core: {cid} はカードDB に無い")
            continue
        if c.category == Category.LEADER:
            warnings.append(f"core: {cid} はリーダー (main に入れられない)")
            continue
        if not (set(c.color) & leader_colors):
            warnings.append(f"core: {cid} の色 {c.color} はリーダー色 {leader_colors} と合わない")
            continue
        if not set(c.color).issubset(leader_colors):
            warnings.append(f"core: {cid} は多色だがリーダー色に全部含まれない")
            continue
        wanted = core_counts.get(cid, 4)
        bid = _base_id(c.card_id)
        # 既に採用枚数を消費していれば残数のみ
        cap = 4 - used[bid]
        n = max(0, min(wanted, cap, 50 - len(chosen)))
        if n <= 0:
            warnings.append(f"core: {cid} は採用上限に達した (already {used[bid]} 枚)")
            continue
        chosen.extend([c] * n)
        used[bid] += n

    # 残り (50 - core) を effect-rich + counter 札で埋める
    candidates: list[CardDef] = []
    seen: set[str] = set()
    for cid, c in repo._by_id.items():  # noqa
        if c.card_id in seen:
            continue
        seen.add(c.card_id)
        if c.category not in (Category.CHARACTER, Category.EVENT, Category.STAGE):
            continue
        if not (set(c.color) & leader_colors):
            continue
        if not set(c.color).issubset(leader_colors):
            continue
        if c.cost <= 0:
            continue
        candidates.append(c)

    # コストカーブ目標 (残り枚数を均等に分布)
    remaining = 50 - len(chosen)
    if remaining > 0:
        # 既に core で埋まったコスト分布を考慮し、不足コスト帯を優先
        curve_target = {1: 8, 2: 10, 3: 10, 4: 8, 5: 6, 6: 4, 7: 4}
        # core で消費したコスト分を curve_target から差し引く
        for c in chosen:
            if c.cost in curve_target and curve_target[c.cost] > 0:
                curve_target[c.cost] -= 1

        by_cost: dict[int, list[CardDef]] = {}
        for c in candidates:
            by_cost.setdefault(c.cost, []).append(c)

        for cost, target in curve_target.items():
            if target <= 0:
                continue
            pool = by_cost.get(cost, [])
            pool_sorted = sorted(
                pool,
                key=lambda c: (
                    1 if c.card_id in effect_keys else 0,
                    c.power,
                    c.counter,
                ),
                reverse=True,
            )
            added = 0
            for c in pool_sorted:
                if added >= target or len(chosen) >= 50:
                    break
                bid = _base_id(c.card_id)
                allowed = 4 - used[bid]
                if allowed <= 0:
                    continue
                n = min(allowed, target - added, 50 - len(chosen))
                chosen.extend([c] * n)
                used[bid] += n
                added += n

    # 補完 1: counter 札で埋める
    counter_pool = sorted(
        [c for c in candidates if c.counter > 0],
        key=lambda c: (-c.counter, c.cost),
    )
    while len(chosen) < 50:
        progress = False
        for c in counter_pool:
            if len(chosen) >= 50:
                break
            bid = _base_id(c.card_id)
            if used[bid] >= 4:
                continue
            chosen.append(c)
            used[bid] += 1
            progress = True
        if not progress:
            break

    # 補完 2: 何でも色合致なら入れる (50 枚到達優先)
    while len(chosen) < 50:
        progress = False
        for c in candidates:
            if len(chosen) >= 50:
                break
            bid = _base_id(c.card_id)
            if used[bid] >= 4:
                continue
            chosen.append(c)
            used[bid] += 1
            progress = True
        if not progress:
            break

    chosen = chosen[:50]
    rng.shuffle(chosen)

    return (
        DeckList(
            name=name or f"CoreBuild<{leader.name}>",
            leader=leader,
            main=chosen,
        ),
        warnings,
    )
