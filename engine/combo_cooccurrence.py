# -*- coding: utf-8 -*-
"""実戦デッキの共起 (co-occurrence) による接地 (= 2026-06-14、 combo finder 品質改善)。

静的ルール (= combo_finder) は off-meta カードも拾える反面、 「実際に一緒に使われるか」
という最強の根拠を持たない。 本 module は decks/ + _archive/ の実戦デッキ (= 大会優勝レシピ
含む 142 デッキ) から共起を集計し、

  1. **新シナジー信号**: anchor と実戦で一緒に採用されるカードを提示
  2. **スコア補正**: 静的 heuristic 候補が実戦共起していれば加点 (= ランクを接地)
  3. **評価指標**: 静的 heuristic の suggestion が実戦共起とどれだけ一致するか測る

を提供する。 ランクは lift (= P(Y|X)/P(Y)) × sqrt(cooc) で、 汎用ステープル (= 全デッキ
共通の counter 等) は base_rate 閾値で除外する (= 特定シナジーのみ残す)。

⚠ anchor が実戦デッキに不在 (= off-meta) なら空を返す → 静的 heuristic に委ねる (= 想定通り)。
"""
from __future__ import annotations

import glob
import json
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent


def _base(cid: str) -> str:
    return re.sub(r"_(p\d+|r\d+)$", "", str(cid))


def _deck_sources() -> list[str]:
    return (
        glob.glob(str(_ROOT / "decks" / "*.json"))
        + glob.glob(str(_ROOT / "decks" / "_archive" / "*.json"))
        + glob.glob(str(_ROOT / "decks" / "_archive" / "cardrush_raw" / "*.json"))
    )


def _deck_cardset(path: str) -> Optional[frozenset]:
    """デッキファイルから {leader + main の base card_id} を抽出 (recipe/archive 両形式)。"""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None
    cards: set[str] = set()
    lead = d.get("leader") or d.get("leader_id")
    if lead:
        cards.add(_base(lead))
    main = d.get("main") or d.get("cards") or d.get("recipe")
    if isinstance(main, list):
        for e in main:
            if isinstance(e, dict):
                cid = e.get("card_id") or e.get("id") or e.get("card_number")
                if cid:
                    cards.add(_base(cid))
    return frozenset(cards) if len(cards) >= 5 else None


@lru_cache(maxsize=1)
def _build_index() -> tuple[int, dict, dict]:
    """(n_decks, df: card→#decks, cooc: card→{card→#co-decks}) を構築。 同一デッキは1回。"""
    seen: set[frozenset] = set()
    decksets: list[frozenset] = []
    for s in _deck_sources():
        if s.endswith(".analysis.json"):
            continue
        cs = _deck_cardset(s)
        if cs is None or cs in seen:
            continue
        seen.add(cs)
        decksets.append(cs)
    df: dict[str, int] = defaultdict(int)
    cooc: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for cs in decksets:
        cl = sorted(cs)
        for c in cl:
            df[c] += 1
        for i in range(len(cl)):
            for j in range(i + 1, len(cl)):
                a, b = cl[i], cl[j]
                cooc[a][b] += 1
                cooc[b][a] += 1
    return len(decksets), dict(df), {k: dict(v) for k, v in cooc.items()}


def deck_count(card_id: str) -> int:
    """このカードが何個の実戦デッキに入っているか。"""
    _, df, _ = _build_index()
    return df.get(_base(card_id), 0)


def n_decks() -> int:
    return _build_index()[0]


def cooccurring(
    card_id: str,
    top: int = 12,
    min_cooc: int = 2,
    max_base_rate: float = 0.5,
) -> list[dict]:
    """anchor と実戦で共起するカードを lift×sqrt(cooc) でランク。

    返り値: [{card_id, cooc, anchor_decks, lift, score}] (score 降順)。
    汎用ステープル (= base_rate > max_base_rate) は除外。
    """
    base = _base(card_id)
    n, df, cooc = _build_index()
    if n == 0 or base not in cooc:
        return []
    dfx = df.get(base, 0)
    if dfx == 0:
        return []
    out: list[dict] = []
    for y, c in cooc[base].items():
        if c < min_cooc:
            continue
        dfy = df.get(y, 0)
        if dfy == 0:
            continue
        base_rate = dfy / n
        if base_rate > max_base_rate:
            continue  # 全デッキ共通の汎用札 = 特定シナジーでない
        conf = c / dfx                  # P(Y|X)
        lift = conf / base_rate         # P(Y|X)/P(Y)
        score = lift * (c ** 0.5)
        out.append({
            "card_id": y,
            "cooc": c,
            "anchor_decks": dfx,
            "lift": round(lift, 2),
            "score": round(score, 2),
        })
    out.sort(key=lambda d: -d["score"])
    return out[:top]


def cooc_score_map(card_id: str, max_base_rate: float = 0.5) -> dict[str, float]:
    """anchor に対する {card_id: 共起score} を返す (= heuristic 候補のブースト用、 全件)。"""
    return {
        d["card_id"]: d["score"]
        for d in cooccurring(card_id, top=10_000, min_cooc=1, max_base_rate=max_base_rate)
    }
