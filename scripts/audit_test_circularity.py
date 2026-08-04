#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""バックフィルテストの **循環参照** (= overlay を読んで overlay を assert しているだけ) を測る。

なぜ要るか:
  `tests/test_backfill_auto_*.py` は overlay (`db/card_effects.json`) から効果を取り出して
  実行し、 結果を assert する。 このとき **overlay の JSON 構造そのものを assert** していると、
  overlay が公式テキストと違っていてもテストは green のままになる (= 自作自演)。
  真の検証は **engine を動かして状態が変わったこと** を見ていること。

判定:
  各 test 関数の assert 式だけを AST で取り出し、 engine の状態 (zone / フラグ / 派生値 /
  legal 列挙 / 条件評価 / 置換の戻り値) に触れているかを分類する。

  circular  = overlay の JSON だけを assert  → **要修正**
  coverage  = 「overlay に登録がある」 の存在チェック → 意図的 (公式準拠の主張はしていない)
  behavior  = engine の挙動を assert → 健全

  .venv/bin/python scripts/audit_test_circularity.py
  .venv/bin/python scripts/audit_test_circularity.py --assert   # circular>0 で exit 1
  .venv/bin/python scripts/audit_test_circularity.py --list circular
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# engine の「状態」に触れている印。 zone / InPlay フラグ / Player カウンタ。
STATE = re.compile(
    r"(characters|hand|deck|trash|life|stages|don_active|don_rested|attached_dons|"
    r"rested|base_cost|granted_keywords|pending_choice|"
    r"chara_ko_taken|stay_rested_next_refresh|scheduled_at_self_turn_end|battle_buff|"
    r"ko_immune|cannot_attack|cost_minus|power_buff|known_hand_card_ids|known_bottom_card_ids|"
    r"event_once_used|once_shared_used|don_remaining_in_deck|face_up_life_count|"
    r"blocker_disabled|attack_taunt|base_power_override|reduction|turn_battle_ko_save_discard|opp_on_play_disabled|block_chara_play|block_self_draw)"
    r"|\.power\b|\bleader\."
)
# engine の「判断」に触れている印 (状態は変わらないが engine の実装を検証している)。
BEHAVIOR_CALL = re.compile(
    r"\b(eval_condition|eval_all_conditions|list_activate_main_effects|legal_actions|"
    r"try_replace_ko|is_blocker_now|is_rush_now|is_double_attack_now|keywords_now|"
    r"can_pay|_can_pay|resolve_pending_choice|apply_action|evaluate_static_effects|"
    r"_compute_in_hand_cost_minus|has_keyword_active|effective_cost)\b"
)
COVERAGE_NAME = re.compile(r"(have|has)_overlay")
# overlay が公式テキストの条件節/パラメータを落としていないかを直接見る guard。 これは
# **意図的に** overlay の JSON を assert する (CLAUDE.md 「条件節は省略しない」 の自動チェック)
# ので循環ではない。 必ず同じカードに 挙動を見る companion test が併存している。
# ⚠ 2026-08-04 に 21 件を全部目視で確認し、 すべてこの型だと確認済み。
FAITHFULNESS_NAME = re.compile(
    r"(_in_overlay|overlay_matches_official_text|_overlay_faithful|_overlay_shape|"
    r"_gate|_condition$|_condition_is_|_structure$|_entry_structure$|_cost_is_|_only_cost|"
    r"_implemented$|_has_trigger|_has_both_|overlay_has_)"
)


def classify(fn: ast.FunctionDef, strict: bool = False) -> str | None:
    """既定は 「関数全体が engine に一切触れていない」 を circular とする保守的な定義。

    strict=True は assert 式だけを見る (= 「engine を動かしたが assert は overlay を見ている」
    も拾う)。 ⚠ strict は **ヘルパ関数経由** (`_am(...)` = list_activate_main_effects) や
    ローカル変数に畳んだ比較 (`opt_a = len(opp.life) == ...`) を誤検出するので、
    数字を鵜呑みにせず `--list circular` で 1 件ずつ読むこと。
    """
    asserts = [n for n in ast.walk(fn) if isinstance(n, ast.Assert)]
    if not asserts:
        return None
    src = "\n".join(ast.unparse(a) for a in asserts) if strict else ast.unparse(fn)
    if STATE.search(src):
        return "behavior"
    if COVERAGE_NAME.search(fn.name):
        return "coverage"
    if FAITHFULNESS_NAME.search(fn.name):
        return "faithfulness"
    if BEHAVIOR_CALL.search(ast.unparse(fn)):
        return "behavior"
    return "circular"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--assert", dest="do_assert", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="assert 式だけを見る (ヘルパ経由を誤検出するので目視前提)")
    ap.add_argument("--list", choices=("circular", "coverage", "faithfulness", "behavior"))
    args = ap.parse_args()

    counts: Counter = Counter()
    names = defaultdict(list)
    for f in sorted((ROOT / "tests").glob("test_backfill_auto_*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
            if not fn.name.startswith("test_"):
                continue
            k = classify(fn, strict=args.strict)
            if k is None:
                continue
            counts[k] += 1
            names[k].append(f"{f.name}::{fn.name}")

    total = sum(counts.values())
    print(f"バックフィルテスト {total} 件")
    for k in ("behavior", "coverage", "faithfulness", "circular"):
        print(f"  {k:<9}{counts[k]:>6}  ({counts[k]/max(total,1):.1%})")
    if args.list:
        for n in names[args.list]:
            print("   ", n)
    if args.do_assert and counts["circular"]:
        print("\n⚠ overlay の JSON だけを assert している test がある = overlay が誤っていても green")
        sys.exit(1)


if __name__ == "__main__":
    main()
