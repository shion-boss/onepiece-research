#!/usr/bin/env python3
"""Plan H cross-leader entries 自動 生成 (= 2026-05-26)。

archetype templating で 各 deck の per-deck spec に cross-leader Tier 1 entries を 追加。

# 目的

現状 各 deck の target_v1.json は **mirror only** (= 自 leader 1 つ の Tier 1 entry のみ)。
16×16=256 matchup の うち 16 mirror cell しか Tier 1 で 動かず、 残 240 cell は
generic Tier 2/3 fallback に 依存。

この script は: deck × 15 cross opp_leader × (turn, condition) を templating で 生成、
generic Tier 2 entries の archetype 一致 pattern を 各 cross-leader 用に specialize
(= opp_leader_id 明示、 weight 0.7 → 1.0 に bump)。

# 設計

- self_deck + opp_deck の archetype を db/deck_archetypes.json から 取得
- generic 内 で opp_archetype 一致 する entry pattern を 各 cross-leader 用 に コピー
- 出力 entry: opp_leader_id 明示、 opp_archetype 除外、 importance=1.0 (= Tier 1 weight)
- bonus は generic 値 を そのまま (= 既存 mirror per-deck と バランス 取れる 範囲)

# 出力

各 decks/<slug>.target_v1.json に cross-leader entries を append。
既存 mirror entries は 触らない (= mirror neutral 維持)。

# 使い方

```bash
.venv/bin/python scripts/generate_cross_leader_entries.py            # 全 16 deck
.venv/bin/python scripts/generate_cross_leader_entries.py --deck cardrush_1456  # 1 deck のみ
.venv/bin/python scripts/generate_cross_leader_entries.py --dry-run  # 試算 のみ
```
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DECKS_DIR = REPO_ROOT / "decks"
DB_DIR = REPO_ROOT / "db"


def load_archetype_map() -> dict[str, str]:
    p = DB_DIR / "deck_archetypes.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    return data.get("map", data)


def load_deck_leader_ids() -> dict[str, str]:
    """deck slug → leader_id map を 返す。"""
    out: dict[str, str] = {}
    for p in sorted(DECKS_DIR.glob("*.json")):
        if "_archive" in str(p) or p.name.endswith(".analysis.json") or ".target_" in p.name:
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if "leader" in d and "slug" in d:
            out[d["slug"]] = d["leader"]
    return out


def load_generic_archetype_entries() -> dict[str, list[dict]]:
    """generic 内 で opp_archetype 指定 がある entry を archetype 別 に group。"""
    p = DB_DIR / "target_generic.json"
    spec = json.loads(p.read_text(encoding="utf-8"))
    by_arch: dict[str, list[dict]] = {}
    for e in spec.get("entries", []):
        arch = e.get("opp_archetype")
        if not arch:
            continue
        by_arch.setdefault(arch, []).append(e)
    return by_arch


def specialize_entry_for_leader(
    generic_entry: dict, opp_leader_id: str, opp_deck_slug: str
) -> dict:
    """generic archetype entry を 特定 opp_leader 用 に specialize。

    変更:
    - opp_archetype 除去 → opp_leader_id 明示 (= Tier 1 leader 厳密一致)
    - importance 1.0 (= per-deck Tier 1 weight、 generic 0.7 から bump)
    - opp_deck_slug メタ 追加 (= debug 用)
    - description 先頭に "[Tier 1]" tag
    """
    new = {
        "turn": generic_entry["turn"],
        "opp_leader_id": opp_leader_id,
        "opp_deck_slug": opp_deck_slug,
        "self_condition": generic_entry["self_condition"],
        "importance": 1.0,
        "description": f"[cross-leader auto, vs {opp_deck_slug}] {generic_entry.get('description', '')}",
        "targets": [],
    }
    # targets は dict copy (= 一応 独立化)
    for tgt in generic_entry.get("targets", []):
        new["targets"].append(dict(tgt))
    return new


def generate_cross_entries_for_deck(
    self_slug: str,
    leader_map: dict[str, str],
    arch_map: dict[str, str],
    generic_by_arch: dict[str, list[dict]],
) -> list[dict]:
    """1 deck の cross-leader entries を 生成 (= 15 opp_deck × 各 archetype の generic patterns)。"""
    self_leader = leader_map.get(self_slug)
    if not self_leader:
        return []

    new_entries: list[dict] = []
    for opp_slug, opp_leader in sorted(leader_map.items()):
        if opp_slug == self_slug:
            continue  # mirror は per-deck 既存 を 使う
        opp_arch = arch_map.get(opp_slug)
        if not opp_arch:
            continue  # archetype 未知 deck は skip
        templates = generic_by_arch.get(opp_arch, [])
        if not templates:
            continue
        for tmpl in templates:
            ne = specialize_entry_for_leader(tmpl, opp_leader, opp_slug)
            new_entries.append(ne)
    return new_entries


def merge_into_spec(spec: dict, new_entries: list[dict]) -> tuple[int, int]:
    """既存 spec.entries に new_entries を append、 重複 (= turn + opp_leader_id + self_condition + 全 targets) は skip。

    Returns (added, skipped_dup) tuple。
    """
    existing = spec.setdefault("entries", [])

    # 既存 entry の dedup key set (= turn + opp_leader_id + self_condition + targets[0].if の string)
    def entry_key(e: dict) -> str:
        targets = e.get("targets", [])
        first_if = json.dumps(targets[0].get("if", {}), sort_keys=True, ensure_ascii=False) if targets else ""
        return f"{e.get('turn')}|{e.get('opp_leader_id')}|{e.get('self_condition')}|{first_if}"

    seen = {entry_key(e) for e in existing}

    added = 0
    skipped = 0
    for ne in new_entries:
        k = entry_key(ne)
        if k in seen:
            skipped += 1
            continue
        seen.add(k)
        existing.append(ne)
        added += 1
    return added, skipped


def write_spec_compact(path: Path, spec: dict) -> None:
    """target_v1.json を 元 formatting (= json.dumps(indent=2)) で 書き戻す。

    既存 spec の formatting と 揃える ことで diff を 追加分 のみ に 抑える。
    """
    path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default=None, help="1 deck のみ 処理")
    ap.add_argument("--dry-run", action="store_true", help="差分 表示 のみ、 file 更新 せず")
    args = ap.parse_args()

    arch_map = load_archetype_map()
    leader_map = load_deck_leader_ids()
    generic_by_arch = load_generic_archetype_entries()

    print(f"archetype map: {len(arch_map)} decks")
    print(f"leader map: {len(leader_map)} decks")
    print(f"generic archetype entries: " + ", ".join(f"{k}={len(v)}" for k, v in generic_by_arch.items()))
    print()

    target_slugs = [args.deck] if args.deck else sorted(leader_map.keys())
    total_added = 0
    total_skipped = 0

    for slug in target_slugs:
        spec_path = DECKS_DIR / f"{slug}.target_v1.json"
        if not spec_path.exists():
            print(f"[skip] {slug}: target_v1.json 不在")
            continue

        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        before = len(spec.get("entries", []))

        new_entries = generate_cross_entries_for_deck(slug, leader_map, arch_map, generic_by_arch)
        added, skipped = merge_into_spec(spec, new_entries)
        after = len(spec["entries"])
        total_added += added
        total_skipped += skipped

        if args.dry_run:
            print(f"  [dry] {slug:35s}  before={before:3d}  generated={len(new_entries):4d}  would_add={added:4d} (dup={skipped})  after={after:4d}")
        else:
            write_spec_compact(spec_path, spec)
            print(f"  [OK ] {slug:35s}  {before:3d} → {after:4d}  (+{added}, dup_skipped={skipped})")

    print()
    print(f"total: +{total_added} entries (skipped_dup={total_skipped})")


if __name__ == "__main__":
    main()
