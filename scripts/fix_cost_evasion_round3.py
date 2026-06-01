#!/usr/bin/env python3
"""cost踏み倒し是正 round3 — detector の strict 再評価で残った真の未変換。

前 round の自前集計が limit/up_to を cost-gate と誤判定し見逃していた分 (= optional_cost_then
等の真の cost gate を持たない entry)。 既存 do を effect として保持しコストを補填する wrap、
トリガー play_self、 parallel 伝播 を行う。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EFFECTS_PATH = ROOT / "db" / "card_effects.json"

# 既存 do を effect として wrap: card -> [(when, cost_list, wrap_if|None)]
WRAP_SPECS = {
    "OP03-037": [("main", [{"rest_self_cards_filtered": {"count": 1, "filter": {"feature": "東の海"}}}], None)],
    "OP08-039": [("activate_main", [{"rest_self": True}], {"leader_feature": "ミンク族"})],
    "OP15-088": [("on_play", [{"mill_self_top": 3}], None)],
    "P-029": [("end_of_turn", [{"rest_self": True}], None)],
    "ST11-002": [("end_of_turn", [{"discard_hand_with_filter": {"count": 1, "filter": {"category": "EVENT"}}}], None)],
}

# トリガー play_self (do 全置換): card -> [when]
PLAYSELF_TRIG = {
    "OP03-113": ["trigger"],
    "ST29-004": ["trigger"],
}

# base の変換済 entry を parallel に伝播: card -> when
PARALLEL_PROP = {
    "OP01-047": "on_play",
    "OP13-031": "on_play",
}


def _wrap(ents, when, cost, wrap_if):
    hit = False
    for e in ents:
        if e.get("when") != when:
            continue
        do = e.get("do", [])
        if any(isinstance(d, dict) and "optional_cost_then" in d for d in do):
            continue
        effect = copy.deepcopy(do)
        if wrap_if is not None:
            effect = [{"conditional": {"if": copy.deepcopy(wrap_if), "do": effect}}]
            e.pop("if", None)
            e.pop("conditions", None)
        e["do"] = [{"optional_cost_then": {"cost": copy.deepcopy(cost), "effect": effect}}]
        if "_text" in e and "[r3]" not in e["_text"]:
            e["_text"] += " [r3]"
        hit = True
    return hit


def main():
    eff = json.loads(EFFECTS_PATH.read_text(encoding="utf-8"))
    changed = []

    # WRAP (base + parallel)
    exp = {}
    for base, specs in WRAP_SPECS.items():
        for k in eff:
            if k == base or k.startswith(base + "_"):
                exp[k] = specs
    for cid, specs in exp.items():
        if any(_wrap(eff[cid], w, c, i) for (w, c, i) in specs):
            changed.append(cid)

    # PLAYSELF trigger (base + parallel)
    for base, whens in PLAYSELF_TRIG.items():
        for k in [x for x in eff if x == base or x.startswith(base + "_")]:
            for e in eff[k]:
                if e.get("when") in whens and not any(
                        isinstance(d, dict) and "optional_cost_then" in d for d in e.get("do", [])):
                    e["do"] = [{"optional_cost_then": {
                        "cost": [{"trash_self_hand_random": 1}], "effect": [{"play_self": True}]}}]
                    if "_text" in e and "[r3]" not in e["_text"]:
                        e["_text"] += " [r3]"
                    changed.append(k)

    # PARALLEL_PROP
    for base, when in PARALLEL_PROP.items():
        base_ent = next((e for e in eff.get(base, []) if e.get("when") == when
                         and any("optional_cost_then" in json.dumps(d, ensure_ascii=False) for d in e.get("do", []))), None)
        if base_ent is None:
            continue
        for k in [x for x in eff if x.startswith(base + "_")]:
            new, replaced = [], False
            for e in eff[k]:
                if e.get("when") == when and not replaced:
                    new.append(copy.deepcopy(base_ent)); replaced = True
                elif e.get("when") == when:
                    continue
                else:
                    new.append(e)
            if not replaced:
                new.append(copy.deepcopy(base_ent))
            eff[k] = new
            changed.append(k)

    EFFECTS_PATH.write_text(json.dumps(eff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"round3 変換 {len(set(changed))} 件: {', '.join(sorted(set(changed)))}")


if __name__ == "__main__":
    main()
