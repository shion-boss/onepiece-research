#!/usr/bin/env python3
"""Plan H Phase H-1 (= 2026-05-19): target spec の 自動検証 script。

Claude が 書いた `decks/<slug>.target_v1.json` を 検証:

1. **schema check**: 必須 field の 有無 (= entries / each entry の turn/opp_leader_id/targets...)
2. **primitive check**: 'if' 節 の key が DSL spec の primitive リスト に 含まれるか
3. **bonus range**: 500-2000 範囲
4. **priority range**: 1-3 のみ
5. **opp_leader_id existence**: meta pool 16 deck の leader_id か
6. **(任意) sim check**: target を sample state で 評価可能 か (= 暴走 verify)

# 使い方

```bash
.venv/bin/python scripts/validate_target_spec.py --spec decks/cardrush_1456.target_v1.json
# → 通過 / fail 件数 + 詳細 詳細 stderr
```

# 出力 (= stderr に summary、 stdout に JSON 不可 entry リスト)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from engine.target_dsl import _EXTENDED_KEYS  # noqa: E402

DECKS_DIR = REPO_ROOT / "decks"

# eval_condition で 対応 する primitive 名前 (= engine/effects.py:364-700 から 抽出)
EVAL_CONDITION_KEYS = {
    "leader_feature", "leader_features_any", "leader_color", "leader_multicolor",
    "leader_feature_contains", "leader_name", "leader_name_in",
    "always",
    "self_life_le", "self_life_ge", "self_life_eq",
    "self_power_ge",
    "opp_life_le", "opp_life_ge",
    "self_field_count_ge", "self_field_count_le",
    "self_trash_count_ge", "self_trash_event_count_ge",
    "self_don_ge", "self_don_le",
    "self_don_active_ge", "self_don_active_le",
    "self_chara_count_ge", "self_chara_count_le",
    "self_chara_feature_count_ge",
    "self_chara_filtered_count_ge",
    "self_chara_cost_ge_count",
    "self_chara_power_ge",
    "self_chara_only_feature",
    "self_chara_unique_name",
    "self_attached_don_ge",
    "self_rested_cards_count_ge",
    "self_summoning_sickness",
    "self_rested",
    "self_turn_number_ge",
    "self_hand_count_le",
    "opp_hand_count_ge",
    "opp_turn", "self_turn",
    "don_diff_le",
    "life_zero_either",
    "opp_leader_attribute", "self_leader_attribute",
    "victim_truly_original_power_ge", "victim_feature_in",
    "played_chara_truly_original_cost_ge", "played_self_chara_has_no_effect",
    "actor_source_feature_contains",
    "don_count_ge", "don_count_le",
    "opp_don_count_ge", "opp_don_count_le",
    "opp_leader_feature",
}

ALL_VALID_KEYS = EVAL_CONDITION_KEYS | _EXTENDED_KEYS


def list_opp_leader_ids() -> set[str]:
    """meta pool 16 deck の leader_id 集合 を 返す。"""
    ids: set[str] = set()
    for p in sorted(DECKS_DIR.glob("*.json")):
        if "_archive" in str(p) or p.name.endswith(".analysis.json") or p.name.endswith(".target_v1.json"):
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        lid = d.get("leader")
        if lid:
            ids.add(lid)
    return ids


def validate_if_primitives(if_cond: Any) -> list[str]:
    """'if' 節 の primitive name を 検証、 不正 key の list を 返す。"""
    if not isinstance(if_cond, dict):
        return ["if は dict で 必要"]
    invalid: list[str] = []
    for k in if_cond.keys():
        if k not in ALL_VALID_KEYS:
            invalid.append(k)
    return invalid


def validate_target(target: dict) -> list[str]:
    """1 つの target (= priority 内) を 検証、 error list を 返す。"""
    errors: list[str] = []
    if not isinstance(target, dict):
        return ["target は dict 必要"]
    priority = target.get("priority")
    if priority is None:
        errors.append("priority 必須")
    elif not isinstance(priority, int) or not (1 <= priority <= 3):
        errors.append(f"priority は 1-3 範囲 (got {priority})")
    bonus = target.get("bonus")
    if bonus is None:
        errors.append("bonus 必須")
    elif not isinstance(bonus, (int, float)) or not (500 <= bonus <= 2000):
        errors.append(f"bonus は 500-2000 範囲 (got {bonus})")
    if_cond = target.get("if")
    if if_cond is None:
        errors.append("if 必須")
    else:
        bad_keys = validate_if_primitives(if_cond)
        if bad_keys:
            errors.append(f"unknown primitive(s): {bad_keys}")
    return errors


def validate_entry(entry: dict, valid_opp_leader_ids: set[str]) -> list[str]:
    """1 entry を 検証、 error list を 返す。"""
    errors: list[str] = []
    if not isinstance(entry, dict):
        return ["entry は dict 必要"]
    turn = entry.get("turn")
    if not isinstance(turn, int) or not (1 <= turn <= 12):
        errors.append(f"turn は 1-12 範囲 (got {turn})")
    opp_id = entry.get("opp_leader_id")
    if not opp_id:
        errors.append("opp_leader_id 必須")
    elif opp_id not in valid_opp_leader_ids:
        errors.append(f"opp_leader_id '{opp_id}' は meta pool に 存在 しない")
    self_cond = entry.get("self_condition")
    if self_cond not in ("advantage", "even", "behind"):
        errors.append(f"self_condition は advantage/even/behind のみ (got {self_cond})")
    targets = entry.get("targets")
    if not isinstance(targets, list) or not targets:
        errors.append("targets は 非空 list 必要")
    else:
        for i, tgt in enumerate(targets):
            for e in validate_target(tgt):
                errors.append(f"targets[{i}]: {e}")
    return errors


def validate_spec(spec_path: Path) -> tuple[bool, dict]:
    """target_v1.json を 検証。 (pass_overall, report) を 返す。"""
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    entries = spec.get("entries", [])
    valid_opp_ids = list_opp_leader_ids()

    report: dict = {
        "spec_path": str(spec_path),
        "deck_slug": spec.get("deck_slug"),
        "total_entries": len(entries),
        "failed_entries": 0,
        "error_breakdown": Counter(),
        "failures": [],
    }

    for i, entry in enumerate(entries):
        errors = validate_entry(entry, valid_opp_ids)
        if errors:
            report["failed_entries"] += 1
            for e in errors:
                # error type 抽出 (= 「unknown primitive」 vs 「bonus 範囲」 等)
                m = re.match(r"^([\w_]+|targets\[\d+\]: [^:]+)", e)
                err_type = m.group(1) if m else e[:30]
                report["error_breakdown"][err_type] += 1
            report["failures"].append({"index": i, "turn": entry.get("turn"), "opp_leader_id": entry.get("opp_leader_id"), "errors": errors})

    pass_overall = report["failed_entries"] == 0
    return pass_overall, report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True, help="target_v1.json path")
    args = ap.parse_args()

    spec_path = Path(args.spec)
    if not spec_path.exists():
        print(f"ERROR: spec not found: {spec_path}", file=sys.stderr)
        sys.exit(1)

    ok, report = validate_spec(spec_path)
    print("=" * 60, file=sys.stderr)
    print(f"spec: {report['spec_path']}", file=sys.stderr)
    print(f"deck_slug: {report['deck_slug']}", file=sys.stderr)
    print(f"total entries: {report['total_entries']}", file=sys.stderr)
    print(f"failed entries: {report['failed_entries']}", file=sys.stderr)
    print("-" * 60, file=sys.stderr)
    print(f"error breakdown:", file=sys.stderr)
    for err, cnt in report["error_breakdown"].most_common():
        print(f"  {cnt:4d}  {err}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"OVERALL: {'PASS' if ok else 'FAIL'}", file=sys.stderr)

    # 詳細 failure を stdout に
    if report["failures"]:
        json.dump(report["failures"][:20], sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
