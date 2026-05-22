"""Refined audit: detect overlay effects where the effect's _text mentions a cost
but the cost block in the spec is missing or insufficient.

Per-effect basis (= avoids false positives from multi-effect cards).

Patterns checked:
  A. _text has "ドン!!-N" or "ドン-N" or "[DON-N]" → cost should have
     rest_self_don: N OR pay_don: N OR return_self_don_to_deck: N.
  B. _text has "手札N枚捨て" → cost should have discard_hand: N OR trash_self_hand: N.
  C. _text has 【ターン1回】 OR "ターン1回" → cost.once_per_turn or eff.once_per_turn True.

Only flags if cost mentioned IN THIS EFFECT's _text (= avoids cross-effect noise).

Outputs: db/audit_cost_consistency.json with detected mismatches.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS_PATH = ROOT / "db" / "cards.json"
OVERLAY_PATH = ROOT / "db" / "card_effects.json"


def parse_don_minus(text: str) -> int:
    m = re.search(r"(?:ドン[!‼][!‼]?|DON)\s*[-－]\s*(\d+)", text)
    return int(m.group(1)) if m else 0


def parse_hand_discard(text: str) -> int:
    # Match 手札N枚...捨て (= as a cost, not "make opp discard")
    m = re.search(r"自分の手札(\d+)枚.*?(捨て|トラッシュ)", text)
    if m:
        return int(m.group(1))
    m = re.search(r"手札(\d+)枚.*?(捨て|トラッシュ)", text)
    return int(m.group(1)) if m else 0


def has_once_per_turn_text(text: str) -> bool:
    return "ターン1回" in text or "【ターン1回】" in text


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
            eff_text = str(eff.get("_text", ""))
            if not eff_text:
                continue
            need_don = parse_don_minus(eff_text)
            need_hand = parse_hand_discard(eff_text)
            need_opt = has_once_per_turn_text(eff_text)
            if need_don == 0 and need_hand == 0 and not need_opt:
                continue
            cost = eff.get("cost") or {}
            if not isinstance(cost, dict):
                cost = {}
            paid_don = int(cost.get("pay_don", 0)) + int(cost.get("rest_self_don", 0)) + int(cost.get("return_self_don_to_deck", 0))
            paid_hand = int(cost.get("discard_hand", 0)) + int(cost.get("trash_self_hand", 0))
            paid_opt = bool(cost.get("once_per_turn")) or bool(eff.get("once_per_turn"))
            mismatches = []
            if need_don > 0 and paid_don < need_don:
                mismatches.append(f"DON-{need_don} 未支払 (paid={paid_don})")
            if need_hand > 0 and paid_hand < need_hand:
                mismatches.append(f"手札{need_hand}枚捨て 未実装 (paid={paid_hand})")
            if need_opt and not paid_opt:
                mismatches.append("【ターン1回】 未指定")
            if not mismatches:
                continue
            issues.append({
                "card_id": cid,
                "name": card_map.get(cid, {}).get("name", "?"),
                "eff_idx": i,
                "when": eff.get("when"),
                "needed_don": need_don,
                "needed_hand": need_hand,
                "needed_opt": need_opt,
                "paid_don": paid_don,
                "paid_hand": paid_hand,
                "paid_opt": paid_opt,
                "mismatches": mismatches,
                "overlay_text": eff_text[:120],
            })

    print(f"Issues (refined): {len(issues)}")
    by_type = {"DON": 0, "HAND": 0, "OPT": 0}
    for x in issues:
        for m in x["mismatches"]:
            if "DON" in m: by_type["DON"] += 1
            if "手札" in m: by_type["HAND"] += 1
            if "ターン1回" in m: by_type["OPT"] += 1
    print(f"  DON cost missing: {by_type['DON']}")
    print(f"  Hand discard missing: {by_type['HAND']}")
    print(f"  once_per_turn missing: {by_type['OPT']}")
    print()
    out_path = ROOT / "db" / "audit_cost_consistency.json"
    out_path.write_text(json.dumps(issues, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")
    print()
    print("Sample 10:")
    for x in issues[:10]:
        print(f"  {x['card_id']} {x['name'][:18]} eff#{x['eff_idx']} when={x['when']}")
        print(f"    {x['mismatches']}")
        print(f"    {x['overlay_text']}")


if __name__ == "__main__":
    main()
