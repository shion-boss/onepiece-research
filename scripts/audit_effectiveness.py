# -*- coding: utf-8 -*-
"""
db/card_effectiveness.json の audit。

各 (role, opp_archetype) ペアで、 該当 role の カード top10 を出力。
スポットレビューで「effectiveness 値が直感に合うか」 を確認する。

実行:
    .venv/bin/python scripts/audit_effectiveness.py
    .venv/bin/python scripts/audit_effectiveness.py --opp アグロ
    .venv/bin/python scripts/audit_effectiveness.py --role removal --top 20
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.card_role import (  # noqa: E402
    ARCHETYPES,
    best_cards_against,
    load_effectiveness_db,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--opp", type=str, default=None,
                        help="特定の opp_archetype のみ表示")
    parser.add_argument("--role", type=str, default=None,
                        help="特定 role のみ表示")
    parser.add_argument("--top", type=int, default=10, help="表示件数")
    args = parser.parse_args()

    eff_db = load_effectiveness_db()
    by_role = eff_db.get("by_role", {})

    target_archs = [args.opp] if args.opp else list(ARCHETYPES)
    target_roles = [args.role] if args.role else list(by_role.keys())

    # sanity 検査: 全 (role, arche) で score ∈ [10, 90]、 違反は警告
    print("=== sanity range check (10 <= score <= 90) ===")
    sanity_violations = 0
    for role, entry in by_role.items():
        if not isinstance(entry, dict):
            continue
        for arche in ARCHETYPES:
            v = entry.get(arche)
            if not isinstance(v, (int, float)):
                continue
            if v < 10 or v > 90:
                print(f"  ⚠ {role:12} vs {arche:8} = {v}")
                sanity_violations += 1
    if sanity_violations == 0:
        print("  OK (全 40 セル ∈ [10, 90])")

    # sanity 不等式
    print()
    print("=== sanity 不等式 ===")
    inequalities = [
        ("removal", "アグロ", "ランプ", ">"),
        ("blocker", "アグロ", "コントロール", ">"),
        ("finisher", "コントロール", "アグロ", ">"),
        ("disruption", "ランプ", "アグロ", ">"),
        ("recovery", "アグロ", "コントロール", ">"),
    ]
    for role, a, b, op in inequalities:
        va = by_role.get(role, {}).get(a, 0)
        vb = by_role.get(role, {}).get(b, 0)
        result = (va > vb) if op == ">" else (va < vb)
        mark = "✓" if result else "✗"
        print(f"  {mark} {role:12} vs {a} ({va}) {op} vs {b} ({vb})")

    # 各 (role, arche) の top カード
    for arche in target_archs:
        for role in target_roles:
            print()
            print(f"=== role={role:12} vs {arche} の top {args.top} ===")
            scores = best_cards_against(arche, target_role=role, top_k=args.top)
            if not scores:
                print("  (該当カード無し)")
                continue
            for s in scores:
                print(
                    f"  {s.card_id:14} cost={s.cost:>2} "
                    f"eff={s.effectiveness:>3} threat={s.threat_level:>2} "
                    f"tags={s.tags} {s.name[:25]}"
                )


if __name__ == "__main__":
    main()
