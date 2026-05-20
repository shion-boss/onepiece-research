# -*- coding: utf-8 -*-
"""
Phase 2.7 sev 3 fix: 11 cards の once_per_turn 漏れ + replace_leave 未実装 を 修正。

公式テキスト 通り に entry を 追加 or 既存 entry の cost に once_per_turn を 追加。
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OVERLAY_JSON = ROOT / "db" / "card_effects.json"

overlay = json.load(open(OVERLAY_JSON, encoding="utf-8"))


def ensure_once_per_turn(card_id: str, when: str) -> None:
    """指定 cid + when の entry に cost.once_per_turn を追加。"""
    entries = overlay.get(card_id, [])
    for e in entries:
        if e.get("when") == when:
            cost = e.get("cost") or {}
            if not isinstance(cost, dict):
                cost = {}
            cost["once_per_turn"] = True
            e["cost"] = cost


def append_entry(card_id: str, entry: dict) -> None:
    entries = overlay.get(card_id, [])
    if not isinstance(entries, list):
        entries = []
    entries.append(entry)
    overlay[card_id] = entries


# 1. 既存 entry に once_per_turn 追加
ensure_once_per_turn("OP05-109", "trigger")
ensure_once_per_turn("OP07-019", "opp_attack")
ensure_once_per_turn("OP11-041", "on_attached_don")  # 「【ドン×1】【相手のアタック時】【ターン1回】」 部分
ensure_once_per_turn("OP11-041", "on_attack")  # 「【自分のターン中】【ターン1回】 ライフが離れた時」
ensure_once_per_turn("OP13-002", "opp_attack")  # 「【相手のアタック時】【ターン1回】」
ensure_once_per_turn("OP13-002", "on_attack")  # 「【ドン×1】【ターン1回】 ダメージor KO」
ensure_once_per_turn("OP13-100", "trigger")
ensure_once_per_turn("OP13-100_p1", "trigger")
ensure_once_per_turn("OP14-060", "opp_attack")

# 2. replace_leave entry を 追加 (OP07-029 系 と ST15-005)
op07_029_replace = {
    "_text": "【ターン1回】このキャラが相手の効果で場を離れる場合、代わりに相手のキャラ1枚をレストにできる。",
    "when": "replace_leave",
    "if": {"target": "self", "by_opp_effect": True},
    "cost": {"once_per_turn": True},
    "do": [{"rest": "one_opponent_character_any"}],
}
append_entry("OP07-029", op07_029_replace)
append_entry("OP07-029_p1", op07_029_replace.copy())
append_entry("OP07-029_r1", op07_029_replace.copy())

st15_005_replace = {
    "_text": "【ターン1回】このキャラが相手の効果で場を離れる場合、 代わりにこのキャラを、 このターン中、 パワー-2000できる。",
    "when": "replace_leave",
    "if": {"target": "self", "by_opp_effect": True},
    "cost": {"once_per_turn": True},
    "do": [{"power_pump": {"target": "self", "amount": -2000, "duration": "turn"}}],
}
append_entry("ST15-005", st15_005_replace)

OVERLAY_JSON.write_text(
    json.dumps(overlay, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("sev 3 fix applied")
