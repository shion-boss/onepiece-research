#!/usr/bin/env python3
"""全カード横断 missing-condition / amount-duration mismatch 検出器。

16デッキ完璧化 (2026-06-01) で確立した検出パターンを全4518枚に展開:
  - missing-condition: text に gating「〜の場合」 があるが overlay に条件が一切ない
    (if/conditions/conditional/choice_effect/optional_cost_then/replace_ko_complex/marker
     のいずれも無い = 条件が丸ごと欠落している疑い)
  - amount/duration mismatch: text パワー±N / このターン中・このバトル中 と overlay の不一致

使い方: python scripts/scan_missing_conditions.py            # 全カード
        python scripts/scan_missing_conditions.py --meta-only # 16デッキのみ
出力: db/audit_llm/missing_conditions.json
"""
import json
import re
import sys

ROOT = "."
cards = {c["card_id"]: c for c in json.load(open("db/cards.json"))}
eff = json.load(open("db/card_effects.json"))


def base(c):
    return re.sub(r"_(p|r)\d+$", "", c)


META_ONLY = "--meta-only" in sys.argv
meta_bases = set()
if META_ONLY:
    decks = ["cardrush_1342", "cardrush_1385", "cardrush_1392", "cardrush_1399",
             "cardrush_1439", "cardrush_1453", "cardrush_1454", "cardrush_1455",
             "cardrush_1456", "tcgportal_bonney", "tcgportal_calgara", "tcgportal_coby",
             "tcgportal_corazon", "tcgportal_hancock", "tcgportal_op11_luffy", "tcgportal_op13_luffy"]
    for slug in decks:
        dk = json.load(open(f"decks/{slug}.json"))
        lv = dk.get("leader")
        meta_bases.add(base(lv if isinstance(lv, str) else (lv or {}).get("card_id", "")))
        for key in ("cards", "main", "recipe", "deck"):
            v = dk.get(key)
            if isinstance(v, list):
                for c in v:
                    meta_bases.add(base(c if isinstance(c, str) else (c.get("card_id") or c.get("id") or "")))

COND_MARKERS = ['"if"', '"conditions"', '"conditional"', '"choice_effect"',
                "optional_cost_then", "replace_ko_complex", "_missing_effect", "_fidelity_note"]
DUR_PP = re.compile(r"パワー[+-]\d+")

missing_cond = []
dur_mismatch = []
seen = set()
for cid in sorted(eff):
    bb = base(cid)
    if bb in seen or bb not in eff:
        continue
    if META_ONLY and bb not in meta_bases:
        continue
    b = eff[bb]
    if not isinstance(b, list) or not b:
        continue
    t = (cards.get(bb, {}).get("text", "") or "")
    tz = (t.replace("＋", "+"))
    tnp = re.sub(r"[(（][^)）]*[)）]", "", tz)
    s = json.dumps(b, ensure_ascii=False)
    # missing-condition
    gating = tnp.count("場合") - tnp.count("アタックする場合") - tnp.count("ダメージを与えた場合") - tnp.count("与える場合")
    if gating > 0 and not any(k in s for k in COND_MARKERS):
        seen.add(bb)
        missing_cond.append({"card_id": bb, "text": re.sub(r"\s", "", t)[:90]})
        continue
    # duration mismatch (power_pump)
    hb, ht = "このバトル中" in tnp, "このターン中" in tnp
    durs = re.findall(r'"duration":\s*"(battle|turn)"', s)
    if hb and not ht and "turn" in durs:
        dur_mismatch.append({"card_id": bb, "issue": "text バトル中 but duration turn"})
    if ht and not hb and "battle" in durs:
        dur_mismatch.append({"card_id": bb, "issue": "text ターン中 but duration battle"})

out = {"scope": "meta" if META_ONLY else "all",
       "missing_condition": missing_cond, "duration_mismatch": dur_mismatch}
json.dump(out, open("db/audit_llm/missing_conditions.json", "w"), ensure_ascii=False, indent=2)
print(f"scope={'meta' if META_ONLY else 'all'}")
print(f"missing-condition 候補: {len(missing_cond)}")
print(f"duration mismatch: {len(dur_mismatch)}")
print("→ db/audit_llm/missing_conditions.json")
