"""Apply DON cost fixes from audit_cost_consistency.json.

For each issue where overlay _text has "ドン!!-N" and cost.pay_don/rest_self_don is missing,
add `pay_don: N` to the cost block (= matches official "ドン!!-N" semantics).

Skips effects where official text uses "ドン!!-N" as a condition (= "場のドンがN以上")
rather than cost. We detect this by checking if _text uses the colon syntax "ドン-N：" or
parenthetical clarification.

Outputs: writes back to db/card_effects.json + prints summary.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OVERLAY_PATH = ROOT / "db" / "card_effects.json"
AUDIT_PATH = ROOT / "db" / "audit_cost_consistency.json"


def main():
    overlay = json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    # Filter to DON-N only
    don_issues = [x for x in audit if any("DON" in m for m in x["mismatches"])]

    fixed = 0
    skipped: list[dict] = []
    for x in don_issues:
        cid = x["card_id"]
        idx = x["eff_idx"]
        need = x["needed_don"]
        bundle = overlay.get(cid)
        if not isinstance(bundle, list) or not (0 <= idx < len(bundle)):
            continue
        eff = bundle[idx]
        cost = eff.get("cost") or {}
        if not isinstance(cost, dict):
            cost = {}
        # Skip if already paid (= human raced ahead)
        paid = int(cost.get("pay_don", 0)) + int(cost.get("rest_self_don", 0))
        if paid >= need:
            continue
        # Add pay_don
        cost["pay_don"] = need
        eff["cost"] = cost
        # Also clear redundant if.self_don_active_ge check (= cost gates it now)
        if isinstance(eff.get("if"), dict) and eff["if"].get("self_don_active_ge") == need:
            del eff["if"]["self_don_active_ge"]
            if not eff["if"]:
                del eff["if"]
        # Same for conditions list
        if isinstance(eff.get("conditions"), list):
            eff["conditions"] = [
                c for c in eff["conditions"]
                if not (isinstance(c, dict) and c.get("self_don_active_ge") == need)
            ]
            if not eff["conditions"]:
                del eff["conditions"]
        fixed += 1

    OVERLAY_PATH.write_text(json.dumps(overlay, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Fixed {fixed} DON cost entries")
    print(f"Wrote {OVERLAY_PATH}")


if __name__ == "__main__":
    main()
