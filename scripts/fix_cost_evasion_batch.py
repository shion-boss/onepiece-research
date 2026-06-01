#!/usr/bin/env python3
"""cost踏み倒し overlay (= 任意コスト「〜できる：」が未モデル化で beneficial 効果がタダ撃ち)
を optional_cost_then に変換する batch fixer。

[[project_full_db_audit_phase]] の human_choice detector (scripts/audit_human_choice_coverage.py)
が strong-flag した 71 base のうち、 **非トリガー・コスト以外のバグ無し・単一コスト** の
クリーンな subset を 明示マッピング表で確定変換する。 effect は既存 `do` を再利用し、
コスト primitive を補填、 entry 直下の `if`/`conditions` (= リーダー特徴 gate 等) は
optional_cost_then の effect 内 conditional に畳み込む (= cost は払えるが効果は条件付き)。

除外 (= deferred、 db/audit_llm/full_db_progress.json に記録):
- トリガー「手札捨てて登場」型 (= 自己 play-from-trigger semantics が別問題)
- コスト以外の overlay バグ併発 (OP06-001 効果違い / OP10-002 重複 / OP08-106 mis-gate)
- 複合コスト (OP10-056 / OP04-073 = self+filtered chara)
- 蘇生 KO時 (OP03-013 / ST30-008) / 択一 (OP06-033 → choice task)

各変換後 smoke_test_card_effects + behavior 再現で検証する前提。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EFFECTS_PATH = ROOT / "db" / "card_effects.json"

# card_id -> {when, cost, drop, wrap_if}
#   when:    変換する entry の when (複数同 when なら最初の cost 節持ち entry)
#   cost:    optional_cost_then.cost に入れる primitive list
#   drop:    既存 do から除去する primitive キー (= それは effect でなく cost 本体だった)
#   wrap_if: True なら entry 直下 if を effect 内 conditional に畳む
SPECS: dict[str, dict] = {
    # --- mill_deck: デッキ上N枚トラッシュ ---
    "EB01-051": {"when": "main", "cost": [{"mill_self_top": 2}], "drop": ["mill_self_top"]},
    "EB04-042": {"when": "on_play", "cost": [{"mill_self_top": 3}]},
    "EB04-049": {"when": "main", "cost": [{"mill_self_top": 2}], "drop": ["mill_self_top"]},
    "OP07-079": {"when": "on_attack", "cost": [{"mill_self_top": 2}]},
    "OP11-098": {"when": "main", "cost": [{"mill_self_top": 3}]},
    "OP12-090": {"when": "on_attack", "cost": [{"mill_self_top": 2}]},
    # --- mill_life_trash: ライフ上(か下)1枚トラッシュ ---
    "OP03-109": {"when": "on_play", "cost": [{"mill_self_life_to_trash": 1}], "drop": ["mill_self_life_to_trash"]},
    "OP03-121": {"when": "main", "cost": [{"mill_self_life_to_trash": 1}], "drop": ["mill_self_life_to_trash"]},
    "ST13-008": {"when": "on_play", "cost": [{"mill_self_life_to_trash": 1}], "drop": ["mill_self_life_to_trash"]},
    "EB03-054": {"when": "on_play", "cost": [{"mill_self_life_to_trash": 1}], "drop": ["mill_self_life_to_trash"]},
    # --- rest_don: ドン1枚レスト ---
    "ST30-007": {"when": "on_play", "cost": [{"rest_self_don": 1}]},
    "ST30-012": {"when": "on_play", "cost": [{"rest_self_don": 1}]},
    # --- rest_stage: このステージをレスト (leader gate は conditional 化) ---
    "OP03-075": {"when": "activate_main", "cost": [{"rest_self": True}], "wrap_if": True},
    "OP03-098": {"when": "activate_main", "cost": [{"rest_self": True}], "wrap_if": True},
    "OP09-021": {"when": "activate_main", "cost": [{"rest_self": True}], "wrap_if": True},
    "OP10-021": {"when": "activate_main", "cost": [{"rest_self": True}], "wrap_if": True},
    "ST04-017": {"when": "activate_main", "cost": [{"rest_self": True}], "wrap_if": True},
    "ST06-017": {"when": "activate_main", "cost": [{"rest_self": True}], "wrap_if": True},
    # --- rest_leader: リーダー1枚レスト ---
    "OP04-088": {"when": "activate_main", "cost": [{"rest_self_cards_filtered": {"count": 1, "filter": {"category": "LEADER"}}}]},
    "OP04-091": {"when": "on_play", "cost": [{"rest_self_cards_filtered": {"count": 1, "filter": {"category": "LEADER"}}}], "wrap_if": True},
    "OP04-081": {"when": "on_attack", "cost": [{"rest_self_cards_filtered": {"count": 1, "filter": {"category": "LEADER"}}}]},
    "P-038": {"when": "on_play", "cost": [{"rest_self_cards_filtered": {"count": 1, "filter": {"category": "LEADER"}}}]},
    # --- chara_to_trash: 自キャラ1枚トラッシュ ---
    "OP07-085": {"when": "on_play", "cost": [{"ko_self_chara": {"count": 1}}]},
    "OP03-012": {"when": "on_attack", "cost": [{"ko_self_chara": {"count": 1, "filter": {"color": "赤", "power_ge": 4000}}}]},
    "OP13-053": {"when": "on_attack", "cost": [{"ko_self_chara": {"count": 1, "filter": {"feature": "白ひげ海賊団"}}}]},
    # --- return_chara_hand: 自キャラ1枚を手札に戻す ---
    "OP07-056": {"when": "counter", "cost": [{"return_self_chara_to_hand": {"count": 1, "filter": {"cost_ge": 2}}}]},
    "OP10-047": {"when": "on_attack", "cost": [{"return_self_chara_to_hand": {"count": 1, "filter": {"cost_ge": 3, "feature": "革命軍"}}}]},
    # --- rest_chara / rest_card ---
    "OP01-055": {"when": "main", "cost": [{"rest_self_cards_filtered": {"count": 2, "filter": {"category": "CHARACTER"}}}]},
    "OP08-037": {"when": "main", "cost": [{"rest_self_cards_filtered": {"count": 1, "filter": {"category": "CHARACTER", "feature": "ミンク族"}}}]},
    "EB04-019": {"when": "main", "cost": [{"rest_self_cards_filtered": {"count": 1}}], "wrap_if": True},
    # --- discard_hand_filtered: 手札から filter 1(or N)枚捨てる ---
    "EB03-041": {"when": "on_play", "cost": [{"discard_hand_with_filter": {"count": 1, "filter": {"feature": "海軍"}}}]},
    "OP03-018": {"when": "main", "cost": [{"discard_hand_with_filter": {"count": 1, "filter": {"category": "EVENT"}}}]},
    "OP15-045": {"when": "on_play", "cost": [{"discard_hand_with_filter": {"count": 1, "filter": {"category": "EVENT"}}}]},
    "OP15-048": {"when": "on_play", "cost": [{"discard_hand_with_filter": {"count": 1, "filter": {"category": "EVENT"}}}]},
    "P-083": {"when": "on_attack", "cost": [{"discard_hand_with_filter": {"count": 1, "filter": {"category": "CHARACTER"}}}]},
    "PRB02-003": {"when": "on_play", "cost": [{"discard_hand_with_filter": {"count": 1, "filter": {"category": "CHARACTER", "power_ge": 6000}}}]},
    "ST30-006": {"when": "on_play", "cost": [{"discard_hand_with_filter": {"count": 1, "filter": {"category": "CHARACTER", "power_ge": 6000}}}]},
    "OP04-098": {"when": "on_play", "cost": [{"discard_hand_with_filter": {"count": 2, "filter": {"feature": "ワノ国"}}}], "wrap_if": True},
    "OP12-074": {"when": "on_play", "cost": [{"discard_hand_with_filter": {"count": 1, "filter": {"category": "EVENT"}}}], "wrap_if": True},
    "ST19-002": {"when": "on_play", "cost": [{"discard_hand_with_filter": {"count": 2, "filter": {"color": "黒", "feature": "海軍"}}}], "wrap_if": True},
}


def main() -> None:
    eff = json.loads(EFFECTS_PATH.read_text(encoding="utf-8"))
    changed: list[str] = []
    skipped: list[str] = []

    # base + parallel 変種 (_p1/_p2/_r1 ...) を 同一 spec で 変換 (= 効果構造は同一)
    expanded: dict[str, dict] = {}
    for base, spec in SPECS.items():
        expanded[base] = spec
        for k in eff:
            if k.startswith(base + "_"):
                expanded[k] = spec

    for cid, spec in expanded.items():
        if cid not in eff:
            skipped.append(f"{cid}: not in overlay")
            continue
        entries = eff[cid]
        when = spec["when"]
        # 対象 entry: when 一致 かつ まだ optional_cost_then 化されていない 最初の 1 件
        target = None
        for e in entries:
            if e.get("when") != when:
                continue
            do = e.get("do", [])
            if any(isinstance(d, dict) and "optional_cost_then" in d for d in do):
                continue
            target = e
            break
        if target is None:
            skipped.append(f"{cid}: when={when} entry 見当たらず or 既変換")
            continue

        do = target.get("do", [])
        drop = set(spec.get("drop", []))
        effect = [d for d in do if not (isinstance(d, dict) and any(k in drop for k in d))]
        if not effect:
            skipped.append(f"{cid}: effect 空 (drop 後)")
            continue

        # entry 直下 if/conditions を effect 内 conditional に畳む
        if spec.get("wrap_if"):
            cond = target.get("if") or {}
            if not cond and target.get("conditions"):
                # conditions list -> 単一 dict にマージ (全 AND)
                merged: dict = {}
                for c in target["conditions"]:
                    if isinstance(c, dict):
                        merged.update(c)
                cond = merged
            if cond:
                effect = [{"conditional": {"if": cond, "do": effect}}]
                target.pop("if", None)
                target.pop("conditions", None)

        target["do"] = [{"optional_cost_then": {"cost": spec["cost"], "effect": effect}}]
        # _text に変換マーク (= 監査トレース)
        if "_text" in target and "[opt-cost化]" not in target["_text"]:
            target["_text"] = target["_text"] + " [opt-cost化]"
        changed.append(cid)

    EFFECTS_PATH.write_text(
        json.dumps(eff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"変換 {len(changed)} 件: {', '.join(changed)}")
    if skipped:
        print(f"\nskip {len(skipped)} 件:")
        for s in skipped:
            print(f"  - {s}")


if __name__ == "__main__":
    main()
