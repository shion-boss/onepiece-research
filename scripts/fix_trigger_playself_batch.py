#!/usr/bin/env python3
"""トリガー「手札1枚捨てて登場」/【KO時】蘇生 等の cost踏み倒し是正 batch。

[[project_human_optional_cost_gate]] の deferred 31 のうちカテゴリ1 (= トリガー自己登場/蘇生)。
旧 overlay は trash_self_hand_random のみで **このカードを登場させる (play_self) が欠落**、
または蘇生 (play_self from trash) のコスト discard が欠落していた。 既存の確立パターン
(OP04-104 等の {optional_cost_then:{cost:[trash_self_hand_random:1], effect:[play_self:true]}})
に揃える。 entry 直下 if (ライフ≤2/多色 等) は effect 内 conditional に畳む。

各カードの effect は公式テキストどおり再構築 (= 単純 play_self / +追加効果 / 条件付き)。
非トリガー側の未モデル cost (OP13-114 ライフ表向き / OP03-110 ライフ手札) も同時是正。
さらに earlier batch (fix_cost_evasion_batch.py) の ST30-006 power_ge→power_eq fidelity fix。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EFFECTS_PATH = ROOT / "db" / "card_effects.json"

TR = lambda n=1: {"trash_self_hand_random": n}
PLAY = {"play_self": True}

# card_id -> list[(when, new_do)]  (同 when 複数 entry は全置換)
SPECS: dict[str, list] = {
    # --- 単純 play_self (cost 手札捨て) ---
    "OP05-105": [("trigger", [{"optional_cost_then": {"cost": [TR()], "effect": [PLAY]}}])],
    "OP03-108": [("trigger", [{"optional_cost_then": {"cost": [TR()], "effect": [PLAY]}}])],
    "OP04-108": [("trigger", [{"optional_cost_then": {"cost": [TR()], "effect": [PLAY]}}])],
    # --- play_self + 追加効果 ---
    "OP08-104": [("trigger", [{"optional_cost_then": {"cost": [TR()], "effect": [PLAY, {"draw": 1}]}}])],
    "OP08-113": [("trigger", [{"optional_cost_then": {"cost": [TR()], "effect": [
        {"conditional": {"if": {"self_life_le": 2}, "do": [PLAY, {"ko": "one_opponent_character_cost_le_3cost"}]}}]}}])],
    "OP08-114": [("trigger", [{"optional_cost_then": {"cost": [TR()], "effect": [
        {"conditional": {"if": {"self_life_le": 2}, "do": [PLAY]}}]}}])],
    # --- play_self + リーダー多色 gate ---
    "OP05-016": [("trigger", [{"optional_cost_then": {"cost": [TR()], "effect": [
        {"conditional": {"if": {"leader_multicolor": True}, "do": [PLAY]}}]}}])],
    "OP05-017": [("trigger", [{"optional_cost_then": {"cost": [TR()], "effect": [
        {"conditional": {"if": {"leader_multicolor": True}, "do": [PLAY]}}]}}])],
    # --- 非 play_self トリガー ---
    "ST09-014": [("trigger", [{"optional_cost_then": {"cost": [TR(2)], "effect": [{"put_top_to_life": 1}]}}])],
    "OP07-055": [("trigger", [{"optional_cost_then": {
        "cost": [{"return_self_chara_to_hand": {"count": 1}}],
        "effect": [{"return_to_hand": "one_opponent_character_cost_le_5cost"}]}}])],
    # --- 【KO時】蘇生 (cost = パワー6000キャラ手札捨て) ---
    "ST30-008": [("on_ko", [{"optional_cost_then": {
        "cost": [{"trash_self_hand_filtered": {"filter": {"category": "CHARACTER", "power_eq": 6000}, "n": 1}}],
        "effect": [{"play_self": {"from": "trash", "rested": True}}]}}])],
    # --- トリガー + 非トリガー両方を是正 ---
    "OP13-114": [
        ("trigger", [{"optional_cost_then": {"cost": [TR()], "effect": [PLAY]}}]),
        ("on_play", [{"optional_cost_then": {"cost": [{"peek_self_life_top": 1}], "effect": [
            {"power_pump": {"target": "one_opponent_character_any", "amount": -2000, "duration": "turn"}}]}}]),
        ("on_attack", [{"optional_cost_then": {"cost": [{"peek_self_life_top": 1}], "effect": [
            {"power_pump": {"target": "one_opponent_character_any", "amount": -2000, "duration": "turn"}}]}}]),
    ],
    "OP03-110": [
        ("trigger", [{"optional_cost_then": {"cost": [TR()], "effect": [PLAY]}}]),
        ("on_attack", [{"optional_cost_then": {"cost": [{"life_top_or_bottom_to_hand": 1}], "effect": [
            {"power_pump": {"target": "self", "amount": 2000, "duration": "battle"}}]}}]),
    ],
}

# earlier batch fidelity fix: 「パワー6000の」 = exactly 6000 (≥ ではない)
POWER_EQ_FIX = ["ST30-006"]


def _apply(entries: list, when: str, new_do: list) -> bool:
    hit = False
    for e in entries:
        if e.get("when") != when:
            continue
        if any(isinstance(d, dict) and "optional_cost_then" in d for d in e.get("do", [])):
            continue  # 既変換 skip
        e["do"] = copy.deepcopy(new_do)
        e.pop("if", None)
        e.pop("conditions", None)
        if "_text" in e and "[trig-fix]" not in e["_text"]:
            e["_text"] += " [trig-fix]"
        hit = True
    return hit


def main() -> None:
    eff = json.loads(EFFECTS_PATH.read_text(encoding="utf-8"))
    changed: list[str] = []
    # base + parallel
    expanded: dict[str, list] = {}
    for base, specs in SPECS.items():
        for k in eff:
            if k == base or k.startswith(base + "_"):
                expanded[k] = specs
    for cid, specs in expanded.items():
        ents = eff.get(cid)
        if not ents:
            continue
        any_hit = False
        for when, new_do in specs:
            if _apply(ents, when, new_do):
                any_hit = True
        if any_hit:
            changed.append(cid)

    # power_ge -> power_eq fidelity fix
    pf = []
    for base in POWER_EQ_FIX:
        for cid in [k for k in eff if k == base or k.startswith(base + "_")]:
            for e in eff[cid]:
                for d in e.get("do", []):
                    oct_ = d.get("optional_cost_then") if isinstance(d, dict) else None
                    if not oct_:
                        continue
                    for c in oct_.get("cost", []):
                        dh = c.get("discard_hand_with_filter") if isinstance(c, dict) else None
                        filt = (dh or {}).get("filter", {})
                        if "power_ge" in filt:
                            filt["power_eq"] = filt.pop("power_ge")
                            pf.append(cid)

    EFFECTS_PATH.write_text(json.dumps(eff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"trigger/revive 変換 {len(changed)} 件: {', '.join(sorted(changed))}")
    print(f"power_eq fidelity fix: {sorted(set(pf))}")


if __name__ == "__main__":
    main()
