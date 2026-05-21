#!/usr/bin/env python3
"""Step B: 自動生成 marker entries で power+N が 公式テキスト に あるのに overlay で 抜けている
7 cards を 一括修正。

Targets (= 元 自動生成 entry を 内容と整合させる):
- OP15-011: ブロッカー + power+2000 (opp_turn + leader_feature 東の海) on_attached_don n=0
- OP03-016: main 効果に give_keyword(self_leader, ダブルアタック turn) + power_pump(+3000 turn) 統合
- P-113: ブロッカー + power+2000 on_attached_don n=2 + opp_turn
- OP03-108(_p1/_p2/_r1): ダブルアタック + power+1000 on_attached_don n=1 + self_life_lt_opp

run: .venv/bin/python scripts/fix_auto_gen_power_deficient.py
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OV_PATH = ROOT / "db" / "card_effects.json"
ov = json.load(open(OV_PATH, encoding="utf-8"))


def replace_entry_by_text_keyword(cid: str, keyword: str, new_entry: dict) -> bool:
    """cid の entries 中、 _text に 自動生成 + 該当 keyword を含む entry を new_entry で置換。"""
    if cid not in ov or not isinstance(ov[cid], list):
        return False
    for i, e in enumerate(ov[cid]):
        if not isinstance(e, dict):
            continue
        t = e.get("_text") or ""
        if "自動生成" in t and keyword in t:
            ov[cid][i] = new_entry
            return True
    return False


def remove_auto_gen_entry(cid: str, keyword: str) -> bool:
    if cid not in ov or not isinstance(ov[cid], list):
        return False
    for i, e in enumerate(ov[cid]):
        if not isinstance(e, dict):
            continue
        t = e.get("_text") or ""
        if "自動生成" in t and keyword in t:
            ov[cid].pop(i)
            return True
    return False


def extend_main_entry(cid: str, extra_actions: list) -> bool:
    """cid の when=='main' な entry の do に extra_actions を 追記。"""
    if cid not in ov or not isinstance(ov[cid], list):
        return False
    for e in ov[cid]:
        if isinstance(e, dict) and e.get("when") == "main":
            e["do"] = (e.get("do") or []) + extra_actions
            return True
    return False


# --- OP15-011 ---
op15_011 = {
    "_text": "OP15-011 【相手のターン中】自分のリーダーが特徴《東の海》を持つ場合、このキャラは【ブロッカー】を得て、パワー+2000。",
    "when": "on_attached_don",
    "n": 0,
    "if": {"opp_turn": True, "leader_feature": "東の海"},
    "do": [
        {"give_keyword": {"target": "self", "keyword": "ブロッカー"}},
        {"power_pump": {"target": "self", "amount": 2000}},
    ],
}
print("OP15-011:", "OK" if replace_entry_by_text_keyword("OP15-011", "ブロッカー", op15_011) else "FAIL")

# --- OP03-016: main entry を 拡張、 自動生成 entry 削除 ---
op03_016_extras = [
    {"give_keyword": {"target": "self_leader", "keyword": "ダブルアタック", "duration": "turn"}},
    {"power_pump": {"target": "self_leader", "amount": 3000, "duration": "turn"}},
]
r1 = extend_main_entry("OP03-016", op03_016_extras)
r2 = remove_auto_gen_entry("OP03-016", "ダブルアタック")
print(f"OP03-016: extend_main={r1} remove_auto={r2}")

# main entry の _text も 公式準拠に書き直す
for e in ov.get("OP03-016", []):
    if isinstance(e, dict) and e.get("when") == "main":
        e["_text"] = "OP03-016 【メイン】自分のリーダーが「ポートガス・D・エース」の場合、相手のパワー8000以下のキャラ1枚までを、KOし、自分のリーダーは、このターン中、【ダブルアタック】を得て、パワー+3000。"
        break

# --- P-113 ---
p_113 = {
    "_text": "P-113 【ドン‼×2】【相手のターン中】このキャラは【ブロッカー】を得て、パワー+2000。",
    "when": "on_attached_don",
    "n": 2,
    "if": {"opp_turn": True},
    "do": [
        {"give_keyword": {"target": "self", "keyword": "ブロッカー"}},
        {"power_pump": {"target": "self", "amount": 2000}},
    ],
}
print("P-113:", "OK" if replace_entry_by_text_keyword("P-113", "ブロッカー", p_113) else "FAIL")

# --- OP03-108 系 ---
for cid in ["OP03-108", "OP03-108_p1", "OP03-108_p2", "OP03-108_r1"]:
    entry = {
        "_text": f"{cid} 【ドン!!×1】自分のライフの枚数が相手より少ない場合、このキャラは【ダブルアタック】を得て、パワー+1000。",
        "when": "on_attached_don",
        "n": 1,
        "if": {"self_life_lt_opp": True},
        "do": [
            {"give_keyword": {"target": "self", "keyword": "ダブルアタック"}},
            {"power_pump": {"target": "self", "amount": 1000}},
        ],
    }
    print(f"{cid}:", "OK" if replace_entry_by_text_keyword(cid, "ダブルアタック", entry) else "FAIL")

# 書き出し
OV_PATH.write_text(json.dumps(ov, ensure_ascii=False, indent=2), encoding="utf-8")
print("\nwrote", OV_PATH)
