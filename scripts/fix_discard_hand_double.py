#!/usr/bin/env python3
"""二重discard systematic 是正 — cost:{discard_hand:N} (action-cost で実行) と
do:[trash_self_hand_random:N] (重複) が両方発火し N×2 枚捨てていたバグ (233 entry)。

opt型 (= 「手札を捨てることができる：効果」 任意コスト): optional_cost_then 化
  (cost:[trash_self_hand_random:N], effect:[do から trash_random を除いた残り])。
  entry cost の discard_hand を除去 (once_per_turn 等は温存)。 人間 pay/skip gate も付く。
mand型 (= 「引き、捨てる」 強制) は別 script (fix_discard_hand_mandatory.py)。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EFF = ROOT / "db" / "card_effects.json"
CARDS = ROOT / "db" / "cards.json"


def main() -> None:
    eff = json.loads(EFF.read_text(encoding="utf-8"))
    cards = {c["card_id"]: c for c in json.loads(CARDS.read_text(encoding="utf-8"))}
    changed = []
    for cid, ents in eff.items():
        if not isinstance(ents, list) or cid not in cards:
            continue
        text = (cards[cid].get("text") or "") + (cards[cid].get("trigger") or "")
        if "捨てることができる：" not in text and "捨てることができます：" not in text:
            continue
        for e in ents:
            if not isinstance(e, dict):
                continue
            c = e.get("cost")
            if not (isinstance(c, dict) and "discard_hand" in c):
                continue
            do = e.get("do", [])
            tr_idx = [i for i, d in enumerate(do) if isinstance(d, dict) and "trash_self_hand_random" in d]
            if not tr_idx:
                continue
            n = int(c["discard_hand"])
            effect = [d for i, d in enumerate(do) if i not in tr_idx]
            if not effect:
                # do が trash_random のみ = 効果が別所 (cost 内 or 欠落)。 opt型では稀。 skip。
                continue
            e["do"] = [{"optional_cost_then": {
                "cost": [{"trash_self_hand_random": n}], "effect": effect}}]
            rest_cost = {k: v for k, v in c.items() if k != "discard_hand"}
            if rest_cost:
                e["cost"] = rest_cost
            else:
                e.pop("cost", None)
            if "_text" in e and "[dd-fix]" not in e["_text"]:
                e["_text"] += " [dd-fix]"
            changed.append(cid)
    # 後処理: entry に discard 以外の実コスト (pay_don/rest_self/rest_self_don 等) が
    # 残り optional_cost_then と二重になる場合、 entry 実コストを optional_cost_then.cost へ統合。
    REAL = {"rest_self_don", "rest_self", "rest", "pay_don", "return_self_don_to_deck",
            "return_self_don", "trash_self", "return_self_to_trash", "return_self_to_hand"}
    merged = []
    for cid, ents in eff.items():
        if not isinstance(ents, list) or cid == "OP04-111":  # allowlist (意図的)
            continue
        for e in ents:
            if not isinstance(e, dict):
                continue
            cost = e.get("cost")
            if not isinstance(cost, dict):
                continue
            real_keys = [k for k in cost if k in REAL]
            if not real_keys:
                continue
            oct_do = next((d for d in e.get("do", []) if isinstance(d, dict) and "optional_cost_then" in d), None)
            if oct_do is None:
                continue
            oc = oct_do["optional_cost_then"]
            for k in real_keys:
                oc.setdefault("cost", []).insert(0, {k: cost.pop(k)})
            if not cost:
                e.pop("cost", None)
            merged.append(cid)

    EFF.write_text(json.dumps(eff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"opt型 二重discard 是正 {len(set(changed))} card / {len(changed)} entry")
    if merged:
        print(f"entry実コスト統合 (二重コスト解消): {sorted(set(merged))}")


if __name__ == "__main__":
    main()
