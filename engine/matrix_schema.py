# -*- coding: utf-8 -*-
"""
matchup_matrix.json v2 schema utilities (Phase 7F-4 / 2026-05-14)
==================================================================

各 cell に timestamp + hash + ai_version を持つことで、
deck recipe 変更や AI 更新時に **stale だけ再計算** できる仕組み。

詳細仕様は [docs/META_POOL_SPEC.md](../docs/META_POOL_SPEC.md) を参照。

## v1 → v2 schema 差分

```
v1 cell: {deck_b, winrate, wins, losses, draws, avg_turns}
v2 cell: v1 + {deck_a_recipe_hash, deck_b_recipe_hash, ai_version, computed_at, stale}
```

v1 互換: v2 schema は v1 の全フィールドを保持。 v1 リーダーは新フィールドを単に無視するだけ。

## stale 判定

cell が以下のいずれかなら stale (= 再計算必要):
- `cell.stale == True` (= 手動 flag)
- `cell.deck_a_recipe_hash != current_a_hash` (= deck A の recipe 変更)
- `cell.deck_b_recipe_hash != current_b_hash` (= deck B の recipe 変更)
- `cell.ai_version != current_ai_version` (= AI ロジック変更)
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


MATRIX_SCHEMA_VERSION = "2.0"


def compute_recipe_hash(recipe_dict: dict) -> str:
    """deck recipe (= JSON dict) の hash を計算 (= 変更検知用)。

    main (= card list) と leader だけを hash 対象に含める。
    metadata (= score / date / source) は除外して 「recipe 自体の変化」 のみを検知。

    Returns: SHA-256 hash の最初 16 文字 (= 衝突確率 ~1e-19、 実用範囲)
    """
    main = recipe_dict.get("main", [])
    # canonical 化: card_id でソート、 count 含め JSON 文字列化
    main_canon = json.dumps(
        sorted(
            [{"card_id": e.get("card_id", ""), "count": e.get("count", 0)} for e in main],
            key=lambda x: x["card_id"],
        ),
        sort_keys=True,
        ensure_ascii=False,
    )
    leader = recipe_dict.get("leader") or ""
    payload = f"{leader}|{main_canon}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def compute_recipe_hash_from_file(deck_path: Path) -> Optional[str]:
    """deck JSON ファイルから recipe hash を計算。 失敗時 None。"""
    try:
        d = json.loads(deck_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return compute_recipe_hash(d)


def now_utc_iso() -> str:
    """ISO 8601 UTC タイムスタンプ。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_cell_v2(
    deck_b_slug: str,
    winrate: Optional[float],
    wins: int,
    losses: int,
    draws: int,
    avg_turns: float,
    *,
    deck_a_hash: str = "",
    deck_b_hash: str = "",
    ai_version: str = "",
    computed_at: Optional[str] = None,
    stale: bool = False,
) -> dict:
    """v2 schema の cell dict を構築。"""
    return {
        "deck_b": deck_b_slug,
        "winrate": winrate,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "avg_turns": avg_turns,
        "deck_a_recipe_hash": deck_a_hash,
        "deck_b_recipe_hash": deck_b_hash,
        "ai_version": ai_version,
        "computed_at": computed_at or now_utc_iso(),
        "stale": stale,
    }


def is_cell_stale(
    cell: dict,
    expected_deck_a_hash: str,
    expected_deck_b_hash: str,
    expected_ai_version: str,
) -> bool:
    """既存 cell が stale (= 再計算必要) か判定。

    どれか 1 つでも一致しなければ stale。 v1 schema (= hash フィールド無し) も
    stale 扱い (= 旧データなので再計算)。
    """
    if cell.get("stale", False):
        return True
    # v1 (= hash フィールド無し) は再計算必要扱い
    if "deck_a_recipe_hash" not in cell or "ai_version" not in cell:
        return True
    if cell.get("deck_a_recipe_hash") != expected_deck_a_hash:
        return True
    if cell.get("deck_b_recipe_hash") != expected_deck_b_hash:
        return True
    if cell.get("ai_version") != expected_ai_version:
        return True
    return False


def find_stale_cells(
    matrix_doc: dict,
    deck_hashes: dict[str, str],
    expected_ai_version: str,
) -> list[tuple[int, int]]:
    """matrix doc 内の stale cell を全列挙。

    Args:
        matrix_doc: matchup_matrix.json をロードした dict
        deck_hashes: {slug: current_hash}
        expected_ai_version: 現在の AI version

    Returns:
        list[(row_idx, col_idx)]: stale cell 座標のリスト (= self-pair 除く)
    """
    stale: list[tuple[int, int]] = []
    for row_idx, row_data in enumerate(matrix_doc.get("matrix", [])):
        slug_a = row_data.get("deck_a")
        hash_a = deck_hashes.get(slug_a, "")
        for col_idx, cell in enumerate(row_data.get("row", [])):
            slug_b = cell.get("deck_b")
            if slug_a == slug_b:
                continue  # self-pair は skip
            hash_b = deck_hashes.get(slug_b, "")
            if is_cell_stale(cell, hash_a, hash_b, expected_ai_version):
                stale.append((row_idx, col_idx))
    return stale


def collect_deck_hashes(decks_dir: Path) -> dict[str, str]:
    """decks/ 配下の全 recipe について {slug: hash} を計算。"""
    out: dict[str, str] = {}
    for p in sorted(decks_dir.glob("*.json")):
        if ".analysis" in p.name:
            continue
        h = compute_recipe_hash_from_file(p)
        if h:
            out[p.stem] = h
    return out
