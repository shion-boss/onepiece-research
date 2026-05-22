"""Audit overlay effects for missing DON cost where official text says ドン!!-N.

Pattern: effect has `if: self_don_active_ge: N` (= just a check) but
`cost: {pay_don|rest_self_don: 0}` (= cost not actually paid). Official text
references DON-N cost. Fix proposal: add `rest_self_don: N` to cost block.

Outputs report + suggested fixes.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS_PATH = ROOT / "db" / "cards.json"
OVERLAY_PATH = ROOT / "db" / "card_effects.json"


def main():
    cards = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
    overlay = json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))
    card_map = {c["card_id"]: c for c in cards}

    issues: list[dict] = []
    for cid, eff_list in overlay.items():
        if not isinstance(eff_list, list):
            continue
        for i, eff in enumerate(eff_list):
            if not isinstance(eff, dict):
                continue
            if_block = eff.get("if") or {}
            conds = eff.get("conditions") or []
            check_vals: list[int] = []
            if isinstance(if_block, dict) and "self_don_active_ge" in if_block:
                check_vals.append(int(if_block["self_don_active_ge"]))
            if isinstance(conds, list):
                for c in conds:
                    if isinstance(c, dict) and "self_don_active_ge" in c:
                        check_vals.append(int(c["self_don_active_ge"]))
            if not check_vals:
                continue
            cost = eff.get("cost") or {}
            if not isinstance(cost, dict):
                continue
            pay_don = int(cost.get("pay_don", 0))
            rest_don = int(cost.get("rest_self_don", 0))
            max_check = max(check_vals)
            if pay_don + rest_don >= max_check:
                continue
            text = card_map.get(cid, {}).get("text", "")
            has_don_minus = bool(
                re.search(r"ドン[!‼][!‼]?\s*[-－]\s*\d", text)
                or "ドン‼-" in text
                or "ドン!!-" in text
            )
            issues.append({
                "card_id": cid,
                "name": card_map.get(cid, {}).get("name", "?"),
                "eff_idx": i,
                "when": eff.get("when"),
                "needed_don": max_check,
                "paid": pay_don + rest_don,
                "has_don_minus_text": has_don_minus,
                "text": eff.get("_text", "")[:80],
            })

    print(f"=== Audit: if self_don_active_ge >= N + cost has no pay_don/rest_self_don ===")
    print(f"Total issues: {len(issues)}")
    high_conf = [x for x in issues if x["has_don_minus_text"]]
    print(f"High-confidence (official text has DON-N): {len(high_conf)}")
    print()
    print("Detail (first 50 high-confidence):")
    for x in high_conf[:50]:
        print(f"  {x['card_id']} {x['name'][:18]} eff#{x['eff_idx']} when={x['when']} need=DON-{x['needed_don']} paid={x['paid']} | {x['text']}")
    print()
    # Output JSON for downstream fix
    out_path = ROOT / "db" / "audit_opp_attack_cost.json"
    out_path.write_text(
        json.dumps(issues, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
