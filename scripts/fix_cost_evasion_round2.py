#!/usr/bin/env python3
"""cost踏み倒し是正 round2 — detector 再走で残った 9 base (+parallels)。

[[project_human_optional_cost_gate]] の deferred 消化の最終。 discard-trigger-card 型 /
mill-life 型 / rest-leader / trash2→life / play_self wrap / parallel 伝播 を仕上げる。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EFFECTS_PATH = ROOT / "db" / "card_effects.json"


def oct_(cost, effect):
    return {"optional_cost_then": {"cost": cost, "effect": effect}}


DISCARD_TRIG = {"discard_hand_with_filter": {"count": 1, "filter": {"has_trigger": True}}}
KO = lambda spec: {"ko": spec}

# card -> [(when, new_do, new_if)]
ENTRY_SPECS: dict[str, list] = {
    "OP03-115": [("on_play", [oct_([DISCARD_TRIG], [KO("one_opponent_character_cost_le_1cost")])], None)],
    "PRB02-017": [("on_play", [oct_([DISCARD_TRIG], [
        {"set_cannot_attack": {"target": "one_opponent_character_any", "duration": "next_opp_turn_end"}}])], None)],
    "OP04-094": [("trigger", [oct_(
        [{"rest_self_cards_filtered": {"count": 1, "filter": {"category": "LEADER"}}}],
        [KO("one_opponent_character_cost_le_5cost")])], None)],
    "OP05-115": [("trigger", [oct_([{"trash_self_hand_random": 2}], [{"put_top_to_life": 1}])], None)],
    "OP08-111": [("trigger", [oct_([{"trash_self_hand_random": 1}],
        [{"conditional": {"if": {"self_life_le": 2}, "do": [{"play_self": True}]}}])], None)],
    "OP08-117": [
        ("main", [oct_([{"mill_self_life_to_trash": 1}], [KO("one_opponent_character_cost_le_7cost")])], None),
        ("trigger", [oct_([{"life_to_hand": 1}], [{"hand_to_self_life": 1}])], None),
    ],
}

# 全 entries 差し替え (重複 entry の dedupe)
FULL_REPLACE: dict[str, list] = {
    # OP03-105: 同一 on_attack が 2 entry (= 二重発火 risk)。 1 entry に統合。 【ドン!!×1】= if。
    "OP03-105": [{
        "_text": "OP03-105 on_attack(ドン1): トリガー持ち手札捨て(cost)→このキャラ+3000 [r2]",
        "when": "on_attack",
        "if": {"self_attached_don_ge": 1},
        "do": [oct_([DISCARD_TRIG], [{"power_pump": {"target": "self", "amount": 3000, "duration": "battle"}}])],
    }],
}

# base の (変換済) entry を parallel に伝播
PARALLEL_PROP = {
    "OP03-013": "on_ko",
    "OP03-118": "trigger",
}


def _apply_entry(ents, when, new_do, new_if):
    hit = False
    for e in ents:
        if e.get("when") != when:
            continue
        if any(isinstance(d, dict) and ("optional_cost_then" in d or "choice_effect" in d) for d in e.get("do", [])):
            continue
        e["do"] = copy.deepcopy(new_do)
        e.pop("conditions", None)
        if new_if is not None:
            e["if"] = copy.deepcopy(new_if)
        else:
            e.pop("if", None)
        if "_text" in e and "[r2]" not in e["_text"]:
            e["_text"] += " [r2]"
        hit = True
    return hit


def main():
    eff = json.loads(EFFECTS_PATH.read_text(encoding="utf-8"))
    changed = []

    # ENTRY_SPECS (base + parallel)
    exp = {}
    for base, specs in ENTRY_SPECS.items():
        for k in eff:
            if k == base or k.startswith(base + "_"):
                exp[k] = specs
    for cid, specs in exp.items():
        if cid not in eff:
            continue
        if any(_apply_entry(eff[cid], w, d, i) for (w, d, i) in specs):
            changed.append(cid)

    # FULL_REPLACE (base + parallel)
    for base, new_ents in FULL_REPLACE.items():
        for k in [x for x in eff if x == base or x.startswith(base + "_")]:
            eff[k] = json.loads(json.dumps(new_ents))
            changed.append(k)

    # PARALLEL_PROP: base の変換済 when entry を parallel の同 when に複製
    for base, when in PARALLEL_PROP.items():
        base_ent = next((e for e in eff.get(base, []) if e.get("when") == when
                         and any("optional_cost_then" in json.dumps(d, ensure_ascii=False) for d in e.get("do", []))), None)
        if base_ent is None:
            continue
        for k in [x for x in eff if x.startswith(base + "_")]:
            new = []
            replaced = False
            for e in eff[k]:
                if e.get("when") == when and not replaced:
                    new.append(copy.deepcopy(base_ent))
                    replaced = True
                elif e.get("when") == when:
                    continue
                else:
                    new.append(e)
            if not replaced:
                new.append(copy.deepcopy(base_ent))
            eff[k] = new
            changed.append(k)

    EFFECTS_PATH.write_text(json.dumps(eff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"round2 変換 {len(set(changed))} 件: {', '.join(sorted(set(changed)))}")


if __name__ == "__main__":
    main()
