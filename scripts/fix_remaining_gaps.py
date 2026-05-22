"""残り implementation gap を 自動 / 半自動 修正。

Fixes:
  A. once_per_turn flag 抜け 23 件 → cost.once_per_turn=True 追加
  B. 【メイン】/【カウンター】 dual EVENT 8 件 → main entry 追加 (= counter spec を copy)
  C. 【相手のアタック時】 cost持ち 4 件 → opp_attack entry 追加
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS_PATH = ROOT / "db" / "cards.json"
OVERLAY_PATH = ROOT / "db" / "card_effects.json"


def fix_once_per_turn(overlay):
    """_text に 「ターン1回」 あるが once_per_turn フラグ 無い 場合 追加。"""
    fixed = 0
    for cid, effs in overlay.items():
        if not isinstance(effs, list):
            continue
        for e in effs:
            if not isinstance(e, dict):
                continue
            t = str(e.get("_text", ""))
            if "ターン1回" not in t:
                continue
            cost = e.get("cost")
            if isinstance(cost, dict):
                if cost.get("once_per_turn") or e.get("once_per_turn"):
                    continue
                cost["once_per_turn"] = True
                e["cost"] = cost
                fixed += 1
            elif isinstance(cost, list):
                # replace_ko / replace_leave 形式 (= cost が list)
                if any(isinstance(c, dict) and c.get("once_per_turn") for c in cost):
                    continue
                if e.get("once_per_turn"):
                    continue
                cost.append({"once_per_turn": True})
                fixed += 1
            else:
                # cost なし → 効果 top-level に once_per_turn 追加
                if e.get("once_per_turn"):
                    continue
                e["once_per_turn"] = True
                fixed += 1
    return fixed


def fix_dual_main_counter(overlay, card_map):
    """EVENT 【メイン】/【カウンター】 dual で 片方 (main) のみ 欠落 → 追加。"""
    fixed = 0
    dual_pattern = re.compile(r"【メイン】\s*/\s*【カウンター】|【カウンター】\s*/\s*【メイン】")
    for c_data in card_map.values():
        cid = c_data["card_id"]
        if c_data.get("category") != "EVENT":
            continue
        text = c_data.get("text", "") or ""
        if not dual_pattern.search(text):
            continue
        effs = overlay.get(cid, [])
        if not isinstance(effs, list):
            continue
        has_main = any(isinstance(e, dict) and e.get("when") == "main" for e in effs)
        has_counter = any(isinstance(e, dict) and e.get("when") == "counter" for e in effs)
        if has_main:
            continue
        if not has_counter:
            continue
        # copy counter → main
        counter_entry = next(e for e in effs if isinstance(e, dict) and e.get("when") == "counter")
        main_entry = dict(counter_entry)
        main_entry["when"] = "main"
        old_text = str(main_entry.get("_text", ""))
        main_entry["_text"] = old_text.replace("counter", "main") if "counter" in old_text else f"[main 版] {old_text}"
        effs.append(main_entry)
        fixed += 1
    return fixed


def add_opp_attack_missing(overlay):
    """【相手のアタック時】 cost持ち missing 4 件 → 手動 spec 追加。"""
    specs = {
        # OP11-041 ナミ: 【ドン!!×1】【相手のアタック時】【ターン1回】 手札1捨て: 自リーダー +2000
        "OP11-041": {
            "_text": "OP11-041 ナミ 相手アタック時 [DON×1 + ターン1回 + 手札1捨て]: 自リーダー +2000",
            "when": "opp_attack",
            "if": {"self_attached_don_ge": 1},
            "cost": {"once_per_turn": True, "discard_hand": 1},
            "do": [{"power_pump": {"target": "self_leader", "amount": 2000, "duration": "battle"}}],
        },
        # OP07-024 コアラ: 【相手のアタック時】 このキャラをレストにできる：自コスト5以下魚人族 1枚にブロッカー
        "OP07-024": {
            "_text": "OP07-024 コアラ 相手アタック時 [rest_self]: 自コスト5以下魚人族 キャラ1枚に【ブロッカー】 (このターン)",
            "when": "opp_attack",
            "cost": {"rest_self": True},
            "do": [{
                "give_keyword": {
                    "target": {"type": "one_self_chara_filtered", "filter": {"cost_le": 5, "feature": "魚人族"}},
                    "keyword": "ブロッカー",
                    "duration": "turn",
                }
            }],
        },
        # OP04-071 Mr.4(ベーブ): 【相手のアタック時】 ドン!!-1: 自身に【ブロッカー】+ パワー+1000 (バトル中)
        "OP04-071": {
            "_text": "OP04-071 Mr.4(ベーブ) 相手アタック時 [DON-1]: 自身に【ブロッカー】+ パワー+1000 (バトル中)",
            "when": "opp_attack",
            "cost": {"pay_don": 1},
            "do": [
                {"give_keyword": {"target": "self", "keyword": "ブロッカー", "duration": "turn"}},
                {"power_pump": {"target": "self", "amount": 1000, "duration": "battle"}},
            ],
        },
        # ST22-002_p1 イゾウ: 【相手のアタック時】 自身トラッシュ: 1ドロー + 手札1をデッキの下
        "ST22-002_p1": {
            "_text": "ST22-002_p1 イゾウ 相手アタック時 [trash_self]: 1ドロー + 手札1 デッキ下",
            "when": "opp_attack",
            "cost": {"trash_self": True},
            "do": [
                {"draw": 1},
                {"hand_to_deck_bottom": 1},
            ],
        },
    }
    added = 0
    for cid, spec in specs.items():
        bundle = overlay.setdefault(cid, [])
        if not isinstance(bundle, list):
            continue
        if any(isinstance(e, dict) and e.get("when") == "opp_attack" for e in bundle):
            continue
        bundle.append(spec)
        added += 1
    return added


def main():
    cards = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
    overlay = json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))
    card_map = {c["card_id"]: c for c in cards}

    n_a = fix_once_per_turn(overlay)
    n_b = fix_dual_main_counter(overlay, card_map)
    n_c = add_opp_attack_missing(overlay)

    OVERLAY_PATH.write_text(json.dumps(overlay, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"A. once_per_turn flag 追加: {n_a}")
    print(f"B. 【メイン】 entry 追加 (dual): {n_b}")
    print(f"C. 【相手のアタック時】 entry 追加: {n_c}")
    print(f"Total: {n_a + n_b + n_c}")


if __name__ == "__main__":
    main()
