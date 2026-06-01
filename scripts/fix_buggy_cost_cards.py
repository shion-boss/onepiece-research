#!/usr/bin/env python3
"""コスト以外のバグを併発していた cost踏み倒しカード 7枚を個別に正しく再構築。

[[project_human_optional_cost_gate]] deferred 31 のカテゴリ2。 単純な optional_cost_then
ラップでは是正できない (= do が効果違い / 重複 / if の gate 位置間違い / 複合コスト) ため
公式テキストどおり do を全置換する。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EFFECTS_PATH = ROOT / "db" / "card_effects.json"

# card_id -> [(when, new_do)]
SPECS: dict[str, list] = {
    # 旧 do が効果違い (self_leader+1000)。 FILM捨て(cost)→相手-2000 + レストドン追加。
    "OP06-001": [("on_attack", [{"optional_cost_then": {
        "cost": [{"discard_hand_with_filter": {"count": 1, "filter": {"feature": "FILM"}}}],
        "effect": [
            {"power_pump": {"target": "one_opponent_character_any", "amount": -2000, "duration": "turn"}},
            {"add_rested_don": 1},
        ]}}])],
    # 旧 do が spurious power_pump + ko/return 重複。 PHキャラ戻す(cost)→相手パワー4000以下KO。
    # 【ドン‼×2】 = 付与ドン2枚以上で発動可 (entry-level if)。
    "OP10-002": [("on_attack", [{"optional_cost_then": {
        "cost": [{"return_self_chara_to_hand": {"count": 1, "filter": {"cost_ge": 2, "feature": "パンクハザード"}}}],
        "effect": [{"ko": {"type": "one_opponent_character_filtered", "filter": {"truly_original_power_le": 4000}}}],
    }}], {"self_attached_don_ge": 2})],
    # if が draw でなく entry 全体を gate していた。 トリガー捨て(cost)→相手コスト5以下KO、
    # その後手札3枚以下ならドロー。
    "OP08-106": [("on_play", [{"optional_cost_then": {
        "cost": [{"discard_hand_with_filter": {"count": 1, "filter": {"has_trigger": True}}}],
        "effect": [
            {"ko": "one_opponent_character_cost_le_5cost"},
            {"conditional": {"if": {"self_hand_count_le": 3}, "do": [{"draw": 1}]}},
        ]}}])],
    # 複合コスト: このキャラ + B・Wキャラ1枚トラッシュ → ドン1枚アクティブ追加。
    "OP04-073": [("activate_main", [{"optional_cost_then": {
        "cost": [
            {"return_self_to_trash": True},
            {"ko_self_chara": {"count": 1, "filter": {"feature_contains": "B・W"}, "exclude_self": True}},
        ],
        "effect": [{"add_don": 1}]}}])],
    # 複合コスト: ドレスローザ リーダー/ステージ1枚レスト + コスト4以上ドレスローザキャラ手札戻す
    # → 相手コスト4以下キャラ手札戻す。
    "OP10-056": [("on_play", [{"optional_cost_then": {
        "cost": [
            {"rest_self_cards_filtered": {"count": 1, "filter": {"feature": "ドレスローザ", "category_in": ["LEADER", "STAGE"]}}},
            {"return_self_chara_to_hand": {"count": 1, "filter": {"cost_ge": 4, "feature": "ドレスローザ"}}},
        ],
        "effect": [{"return_to_hand": "one_opponent_character_cost_le_4cost"}]}}])],
    # 複合コスト: 手札2枚デッキ下 + ステージレスト → リーダークロスギルドならドロー2。
    "OP09-060": [("activate_main", [{"optional_cost_then": {
        "cost": [{"hand_to_deck_bottom": 2}, {"rest_self": True}],
        "effect": [{"conditional": {"if": {"leader_feature": "クロスギルド"}, "do": [{"draw": 2}]}}]}}])],
    # 複合コスト: ワノ国カード捨て + ステージレスト → ドン1枚アクティブ。
    "OP02-048": [("activate_main", [{"optional_cost_then": {
        "cost": [{"discard_hand_with_filter": {"count": 1, "filter": {"feature": "ワノ国"}}}, {"rest_self": True}],
        "effect": [{"untap_don": 1}]}}])],
}


def main() -> None:
    eff = json.loads(EFFECTS_PATH.read_text(encoding="utf-8"))
    changed: list[str] = []
    expanded: dict[str, list] = {}
    for base, specs in SPECS.items():
        for k in eff:
            if k == base or k.startswith(base + "_"):
                expanded[k] = specs
    for cid, specs in expanded.items():
        ents = eff.get(cid)
        if not ents:
            continue
        hit = False
        for spec in specs:
            when, new_do = spec[0], spec[1]
            new_if = spec[2] if len(spec) > 2 else None
            for e in ents:
                if e.get("when") != when:
                    continue
                if any(isinstance(d, dict) and "optional_cost_then" in d for d in e.get("do", [])):
                    continue
                e["do"] = copy.deepcopy(new_do)
                e.pop("conditions", None)
                if new_if is not None:
                    e["if"] = copy.deepcopy(new_if)
                else:
                    e.pop("if", None)
                if "_text" in e and "[bug-fix]" not in e["_text"]:
                    e["_text"] += " [bug-fix]"
                hit = True
        if hit:
            changed.append(cid)
    EFFECTS_PATH.write_text(json.dumps(eff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"併発バグ是正 {len(changed)} 件: {', '.join(sorted(changed))}")


if __name__ == "__main__":
    main()
