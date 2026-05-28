#!/usr/bin/env python3
"""target entries 多様化 (= 2026-05-28、 ohtsuki さん 「いろいろな entries を作成」 対応)。

各 target の numeric `_ge` 条件 を 段階的 に 強化 した variation を 生成 → entry の targets
配列 に append。 lookup_best_achievable_entry が 「resource-level 別 最適 entry」 を 選べる
ように coverage を 増やす。

例:
  元 target: {if: {min_attacks_this_turn_ge: 2, self_chara_count_ge: 1}, bonus: 960}
  生成 variation 1: {if: {min_attacks_this_turn_ge: 3, self_chara_count_ge: 1}, bonus: 1008}
  生成 variation 2: {if: {min_attacks_this_turn_ge: 4, self_chara_count_ge: 1}, bonus: 1056}
  生成 variation 3: {if: {min_attacks_this_turn_ge: 2, self_chara_count_ge: 2}, bonus: 1008}
  ...

実行:
  .venv/bin/python scripts/diversify_target_entries.py            # 全 deck spec
  .venv/bin/python scripts/diversify_target_entries.py --dry-run  # 試算 のみ
  .venv/bin/python scripts/diversify_target_entries.py --deck cardrush_1392  # 1 deck のみ

設計判断:
- 既存 _diversified flag 付き variation は 重複生成 を skip (= idempotent)
- bonus scaling: 1 step += 5% (= 控えめ、 学習で 後で 校正される 前提)
- step 上限: 各 primitive 別 (= attack=max 6、 chara_count=max 6、 hand=max 10 等)
- _ge 系 のみ 対象 (= "want more" の primitives)。 _le 系 (opp_*_le) は skip (= 後で 検討)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DECKS_DIR = REPO_ROOT / "decks"

# primitive ごと の (max_value, step) — 過剰な variation を 防ぐ 上限
# 値: (max_realistic_value, step_increment)
PRIMITIVE_RANGES: dict[str, tuple[int, int]] = {
    "min_attacks_this_turn_ge": (6, 1),       # 攻撃 最大 ~6
    "min_leader_attacks_this_turn_ge": (1, 1), # leader は 1 のみ (= 通常)
    "self_field_count_ge": (6, 1),             # 場 max ~6
    "self_chara_count_ge": (6, 1),
    "self_hand_ge": (10, 1),                   # 手札 max ~10
    "self_field_power_ge": (30000, 5000),     # 5k step
    "self_finisher_on_field_ge": (3, 1),       # finisher max 2-3
    "self_blocker_count_ge": (4, 1),
    "self_counter_in_hand_ge": (12000, 2000),
    "self_leader_attached_don_ge": (10, 1),    # DON 10 cap
    "self_chara_attached_don_ge": (10, 1),
    "self_trash_count_ge": (20, 2),            # iim trash strategy 用
}

# bonus scaling (1 step あたり)
BONUS_SCALE_PER_STEP = 0.05


def _is_ge_primitive(key: str) -> bool:
    return key in PRIMITIVE_RANGES


def _generate_variations(target: dict) -> list[dict]:
    """1 target を 受けて、 単一 primitive を 1 step 強化 した variation 集 を 返す。

    複数 primitive 強化 (= 多次元 variation) は coverage 爆発するため しない。
    各 _ge primitive に対して N+step, N+2*step, ... を max まで 生成。
    """
    if_cond = target.get("if", {})
    base_bonus = int(target.get("bonus", 0))
    if base_bonus <= 0:
        return []
    base_desc = target.get("description", "")
    base_priority = target.get("priority", 1)

    variations: list[dict] = []
    for key, val in if_cond.items():
        if not _is_ge_primitive(key):
            continue
        if not isinstance(val, int):
            continue
        max_val, step = PRIMITIVE_RANGES[key]
        # N+step, N+2*step, ... max_val
        new_val = val + step
        n_steps = 1
        while new_val <= max_val:
            new_if = dict(if_cond)
            new_if[key] = new_val
            scale = 1.0 + n_steps * BONUS_SCALE_PER_STEP
            variations.append({
                "priority": base_priority,
                "if": new_if,
                "bonus": int(base_bonus * scale),
                "description": f"{base_desc} [diversified: {key}+{n_steps*step}]",
                "_diversified": True,
            })
            new_val += step
            n_steps += 1
    return variations


def _diversify_entry(entry: dict) -> int:
    """1 entry に variations を append。 追加件数 を 返す。"""
    targets = entry.get("targets", [])
    new_targets: list[dict] = []
    for tgt in targets:
        if tgt.get("_diversified"):
            continue  # 既 diversified を 元 に した 再生成 を 防ぐ
        new_targets.extend(_generate_variations(tgt))
    # 重複 排除 (= 同 if + bonus で 既存 と 同じ なら skip)
    existing_keys = set()
    for t in targets:
        existing_keys.add((json.dumps(t.get("if", {}), sort_keys=True), int(t.get("bonus", 0))))
    unique_new = []
    for nt in new_targets:
        k = (json.dumps(nt["if"], sort_keys=True), int(nt["bonus"]))
        if k not in existing_keys:
            unique_new.append(nt)
            existing_keys.add(k)
    targets.extend(unique_new)
    entry["targets"] = targets
    return len(unique_new)


def diversify_spec(spec_path: Path, dry_run: bool = False) -> tuple[int, int]:
    """1 spec file を diversify。 (added_count, total_targets_after) を 返す。"""
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    entries = spec.get("entries", [])
    added_total = 0
    targets_before = 0
    targets_after = 0
    for entry in entries:
        targets_before += len(entry.get("targets", []))
        added = _diversify_entry(entry)
        added_total += added
        targets_after += len(entry["targets"])
    if not dry_run:
        spec_path.write_text(
            json.dumps(spec, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return added_total, targets_after


def find_spec_files(deck_filter: Optional[str] = None) -> list[Path]:
    """全 deck の target_v1.json を 返す。 deck_filter 指定で 1 deck のみ。"""
    if deck_filter:
        p = DECKS_DIR / f"{deck_filter}.target_v1.json"
        return [p] if p.exists() else []
    files = sorted(DECKS_DIR.glob("*.target_v1.json"))
    # _locked / _archive 除外
    return [f for f in files if "_locked" not in f.name and "_archive" not in str(f)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="変更 を 書き戻さず 試算 のみ")
    ap.add_argument("--deck", default=None, help="1 deck slug のみ 対象 (例: cardrush_1392)")
    args = ap.parse_args()

    files = find_spec_files(args.deck)
    if not files:
        print(f"ERROR: spec ファイル が 見つからない (deck={args.deck})", file=sys.stderr)
        sys.exit(1)

    print(f"対象 {len(files)} spec ファイル{' [dry-run]' if args.dry_run else ''}")
    print("-" * 60)
    grand_added = 0
    grand_after = 0
    for f in files:
        added, after = diversify_spec(f, dry_run=args.dry_run)
        grand_added += added
        grand_after += after
        marker = "" if added == 0 else f" (+{added})"
        print(f"  {f.name}: {after} targets{marker}")
    print("-" * 60)
    print(f"全体: +{grand_added} variations、 合計 {grand_after} targets")


if __name__ == "__main__":
    main()
