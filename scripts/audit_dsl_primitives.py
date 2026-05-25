# -*- coding: utf-8 -*-
"""
DSL primitive 網羅 audit
========================

目的:
    db/card_effects.json で 使用されている 全 DSL primitive (do/cost/if の key)
    を 列挙し、 engine/effects.py で 実装されているか 突合。

    未実装 / 部分実装 primitive を 検出し、 使用 carded count 付き で 報告。

出力:
    db/dsl_primitive_audit.json (= 全 primitive list + status)
    db/dsl_primitive_audit.md (= 統計 + missing primitives)

ロジック:
    1. 全 overlay 走査 → do/cost/if の key を 集計
    2. engine/effects.py を grep して `elif k == "..."` / `if k == "..."`
       および eval_condition 内 の primitive key を 抽出
    3. 突合 → missing primitives + count
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OVERLAY_JSON = ROOT / "db" / "card_effects.json"
EFFECTS_PY = ROOT / "engine" / "effects.py"
OUTPUT_JSON = ROOT / "db" / "dsl_primitive_audit.json"
OUTPUT_MD = ROOT / "db" / "dsl_primitive_audit.md"


def collect_overlay_primitives() -> dict[str, dict]:
    """overlay から primitive 使用統計 を 集計。

    Returns:
        {primitive_name: {category, count, sample_cards}}
        category = "do" | "cost" | "if" | "when"
    """
    overlay = json.load(open(OVERLAY_JSON, encoding="utf-8"))
    stats: dict[str, dict] = defaultdict(
        lambda: {"do": 0, "cost": 0, "if": 0, "when": 0, "sample_cards": []}
    )

    def add(category: str, key: str, card_id: str):
        s = stats[key]
        s[category] += 1
        if card_id not in s["sample_cards"] and len(s["sample_cards"]) < 5:
            s["sample_cards"].append(card_id)

    for cid, entries in overlay.items():
        if cid == "_meta" or not isinstance(entries, list):
            continue
        for e in entries:
            # when
            w = e.get("when")
            if w:
                add("when", w, cid)
            # if
            cond = e.get("if")
            if isinstance(cond, dict):
                for k in cond:
                    add("if", k, cid)
            # cost
            cost = e.get("cost")
            if isinstance(cost, dict):
                for k in cost:
                    add("cost", k, cid)
            # do
            do_list = e.get("do") or []
            if isinstance(do_list, list):
                for d in do_list:
                    if isinstance(d, dict):
                        for k in d:
                            add("do", k, cid)
    return dict(stats)


def collect_engine_primitives() -> dict[str, set[str]]:
    """engine/effects.py から 実装 primitive を 抽出。

    Returns:
        {category: set of primitive_names}
    """
    src = EFFECTS_PY.read_text(encoding="utf-8")
    # `elif k == "..."` / `if k == "..."` patterns
    do_keys: set[str] = set()
    if_keys: set[str] = set()
    when_keys: set[str] = set()
    cost_keys: set[str] = set()

    # execute_effect 内の elif k == "X"
    # eval_condition 内の elif k == "X"
    # 同じ pattern なので 単一の regex で 抽出
    pat = re.compile(r'(?:elif|if)\s+k\s*==\s*"([^"]+)"')
    for m in pat.finditer(src):
        key = m.group(1)
        do_keys.add(key)  # 実装には do/if 両方 入る、 後で 突合 で 振り分け

    # when patterns: eff.get("when") == "X"
    pat_when = re.compile(r'\.get\("when"\)\s*==\s*"([^"]+)"|when\s*==\s*"([^"]+)"')
    for m in pat_when.finditer(src):
        key = m.group(1) or m.group(2)
        if key:
            when_keys.add(key)

    # cost: eff.get("cost") キー読み (= cost["once_per_turn"] / cost.get("pay_don") 等)
    pat_cost = re.compile(r'cost\.get\("([^"]+)"\)|cost\["([^"]+)"\]')
    for m in pat_cost.finditer(src):
        key = m.group(1) or m.group(2)
        if key:
            cost_keys.add(key)

    return {
        "do_or_if": do_keys,
        "when": when_keys,
        "cost": cost_keys,
    }


def main():
    overlay_stats = collect_overlay_primitives()
    engine_keys = collect_engine_primitives()

    # 突合
    impl_do_or_if = engine_keys["do_or_if"]
    impl_when = engine_keys["when"]
    impl_cost = engine_keys["cost"]

    # ad-hoc adapter: 既知 alias / handled differently (= elif k 形式 ではない 個別処理)
    # engine src 内 で 個別 if/grep ベース で 処理されている primitives を 明示的 認識
    additional_when = {
        "on_attached_don",  # evaluate_static_effects で 個別 処理
        "on_play",
        "on_attack",
        "on_block",
        "on_ko",
        "on_turn_end",
        "end_of_turn",  # = on_turn_end alias (= _enqueue_field_when "end_of_turn")
        "opp_attack",  # = opp_attack_on_leader / opp_attack_on_chara alias
        "in_hand",  # = 手札 静的 効果 (= 個別処理)
        "game_start",  # = 初期化 個別処理
        "setup_modifier",  # = 内部
        "on_self_life_lost",  # = trigger 個別
        "don_phase_modifier",  # = 内部 don phase 個別
        "activate_main",
        "main",
        "counter",
        "trigger",
        "replace_rest",  # = レスト 置換 個別
        "on_self_chara_leave_by_self_effect",
        "on_opp_chara_returned_to_hand_by_self_effect",
        "on_self_rested",
        "on_self_hand_discarded",
        "on_self_chara_played",
        "on_opp_chara_played",
        "on_self_event_played",
        "on_opp_life_taken",
        "on_self_life_to_hand",
        "on_self_life_to_trash",
        "on_self_don_returned_to_deck",
        "on_opp_blocker_use",
        "on_self_chara_ko",
        "on_opp_chara_ko",
        "opp_attack_on_leader",
        "opp_attack_on_chara",
        "opp_event_or_trigger_fired",
        "opp_event_played",
        "opp_trigger_fired",
        "self_event_played",
        "on_attack_finish",
        "on_attack_start",
    }
    impl_when = impl_when | additional_when

    # 個別処理 do primitives (= elif k 形式 ではなく `if "X" in primitive:` 等で 処理)
    additional_do = {
        "set_ko_immune",  # evaluate_static_effects 個別
        "set_attack_taunt",
        "set_base_cost",
        "set_base_power",
        "set_cannot_attack_static",
        "set_opp_protect_static",
        "set_ko_immune_battle_only",
        "set_immune_attribute_in_battle",
        "set_base_cost_filtered_static",
        "reduce_play_cost_filtered_static",
        "auto_attach_to_leader",
        "summon_stage_from_deck_with_feature",
        "look_top_n_filter_to_hand",  # 未実装 (= EB04-029 で 検出、 search 代用)
        "_if_clause",  # audit syntactic noise
    }
    impl_do_or_if = impl_do_or_if | additional_do

    # 個別処理 if primitives (= conditions 内 sub-field)
    additional_if = {
        "leader_features_any",  # leader_feature alias
        "target",  # target sub-field
        "target_feature",
        "target_color",
        "target_name_exclude",
        "target_power_le",
        "target_power_ge",
        "target_cost_le",
        "target_attribute",
        "target_base_power_le",
        "by_opp_effect",  # condition modifier
        "by_opp_chara_effect",
    }
    impl_do_or_if = impl_do_or_if | additional_if

    # cost field (= cost dict 内 で 個別処理)
    additional_cost = {
        "discard_hand",  # = cost.get("discard_hand")
        "discard_self_hand",  # alias?
        "discard_feature",  # cost modifier
    }
    impl_cost = impl_cost | additional_cost

    results: dict[str, dict] = {}
    for name, s in overlay_stats.items():
        # Determine if implemented
        impl = False
        if s["do"] > 0 or s["if"] > 0:
            impl = name in impl_do_or_if
        elif s["when"] > 0:
            impl = name in impl_when
        elif s["cost"] > 0:
            impl = name in impl_cost
        results[name] = {
            **s,
            "implemented": impl,
            "total_usage": s["do"] + s["cost"] + s["if"] + s["when"],
        }

    # missing
    missing = {k: v for k, v in results.items() if not v["implemented"]}
    implemented = {k: v for k, v in results.items() if v["implemented"]}

    sorted_missing = sorted(missing.items(), key=lambda x: -x[1]["total_usage"])
    sorted_implemented = sorted(
        implemented.items(), key=lambda x: -x[1]["total_usage"]
    )

    out = {
        "summary": {
            "total_primitives": len(results),
            "implemented": len(implemented),
            "missing": len(missing),
        },
        "missing": [{"name": k, **v} for k, v in sorted_missing],
        "implemented": [{"name": k, **v} for k, v in sorted_implemented],
    }

    OUTPUT_JSON.write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    md = ["# DSL Primitive Audit", ""]
    md.append(
        f"全 primitive: {len(results)}, 実装済: {len(implemented)}, 未実装/未検出: {len(missing)}"
    )
    md.append("")
    md.append("## Missing (= 未実装 / 検出不可) primitives")
    md.append("")
    md.append("| primitive | total | do | cost | if | when | sample cards |")
    md.append("|---|---|---|---|---|---|---|")
    for name, v in sorted_missing[:80]:
        samples = ", ".join(v["sample_cards"][:3])
        md.append(
            f"| `{name}` | {v['total_usage']} | {v['do']} | {v['cost']} | {v['if']} | {v['when']} | {samples} |"
        )
    md.append("")
    md.append("## 実装済 primitives (top 50 by usage)")
    md.append("")
    md.append("| primitive | total | category |")
    md.append("|---|---|---|")
    for name, v in sorted_implemented[:50]:
        cats = []
        if v["do"] > 0:
            cats.append("do")
        if v["cost"] > 0:
            cats.append("cost")
        if v["if"] > 0:
            cats.append("if")
        if v["when"] > 0:
            cats.append("when")
        md.append(f"| `{name}` | {v['total_usage']} | {'/'.join(cats)} |")
    OUTPUT_MD.write_text("\n".join(md), encoding="utf-8")

    print(f"Output: {OUTPUT_JSON}")
    print(f"Output: {OUTPUT_MD}")
    print(f"Total primitives: {len(results)}")
    print(f"  implemented: {len(implemented)}")
    print(f"  missing: {len(missing)}")
    print()
    print("Top 20 missing (= 検出不可) primitives:")
    for name, v in sorted_missing[:20]:
        cats = []
        if v["do"]:
            cats.append("do")
        if v["cost"]:
            cats.append("cost")
        if v["if"]:
            cats.append("if")
        if v["when"]:
            cats.append("when")
        print(
            f"  {name}: total={v['total_usage']}, cat={','.join(cats)}, sample={v['sample_cards'][:3]}"
        )


if __name__ == "__main__":
    main()
