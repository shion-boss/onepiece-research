#!/usr/bin/env python3
"""16代表デッキの unique カードに 学習済バグパターン検出器を一斉適用 (systematic スイープ)。

検出パターン (今セッションで確立したもの):
  A) search_top_n filter が text の cost/power/trigger/category 制約を {}空 で落とす
  B) spurious self_leader+1000 battle on_attack stub (text 【アタック時】 に +1000 無し)
  C) 円番号(②③④)=コストエリアのドンをレスト を pay_don 実装
  D) 無効 target type (self_chara_filtered 等 = _resolve_target/primitive 未対応)
  E) scry_life 欠落 (text『見て…置く。その後…パワー+』 だが entry に scry無)
  F) 『このリーダーをアクティブにする』 を untap_don 実装
  G) 真に未処理 primitive (in_hand_cost_plus / auto_attach_to_leader 等)
"""
import json
import re
import glob

DECKS = ["cardrush_1342", "cardrush_1385", "cardrush_1392", "cardrush_1399",
         "cardrush_1439", "cardrush_1453", "cardrush_1454", "cardrush_1455",
         "cardrush_1456", "tcgportal_bonney", "tcgportal_calgara", "tcgportal_coby",
         "tcgportal_corazon", "tcgportal_hancock", "tcgportal_op11_luffy", "tcgportal_op13_luffy"]
cards = {c["card_id"]: c for c in json.load(open("db/cards.json"))}
eff = json.load(open("db/card_effects.json"))


def base(c):
    return re.sub(r"_(p|r)\d+$", "", c)


def deck_cards():
    out = set()
    for slug in DECKS:
        dk = json.load(open(f"decks/{slug}.json"))
        if dk.get("leader"):
            lv = dk["leader"]
            out.add(lv if isinstance(lv, str) else lv.get("card_id", ""))
        for key in ("cards", "main", "recipe", "deck"):
            v = dk.get(key)
            if isinstance(v, list):
                for c in v:
                    out.add(c if isinstance(c, str) else (c.get("card_id") or c.get("id") or ""))
    return {c for c in out if c}


META = deck_cards()
# 監査対象 = メタカード + その全 parallel variant (overlay は variant 別)
TARGETS = set()
for c in META:
    b = base(c)
    for k in eff:
        if base(k) == b:
            TARGETS.add(k)

# engine handled primitive keys
src = open("engine/effects.py", encoding="utf-8").read()
PRIM = set(re.findall(r'k == "([a-z_0-9]+)"', src))
for grp in re.findall(r'k in \(([^)]+)\)', src):
    PRIM |= set(re.findall(r'"([a-z_0-9]+)"', grp))
PRIM |= set(re.findall(r'"([a-z_0-9]+)" in primitive', src))
META_KEYS = {"_text", "_doc", "_missing_effect", "_fidelity_note"}
STUB = {"power_pump": {"target": "self_leader", "amount": 1000, "duration": "battle"}}
CIRC = {"①": 1, "②": 2, "③": 3, "④": 4, "⑤": 5, "➀": 1, "➁": 2, "➂": 3, "➃": 4, "➄": 5}
CIRC_PAT = re.compile(r"([①②③④⑤➀➁➂➃➄])\(コストエリアのドン[‼!]*を指定の数レストにできる\)")

findings = {k: [] for k in "ABCDEFG"}
for cid in sorted(TARGETS):
    b = eff.get(cid)
    if not isinstance(b, list):
        continue
    t = cards.get(cid, {}).get("text", "")
    for e in b:
        when = e.get("when")
        do = e.get("do", []) or []
        keys = [list(p.keys())[0] for p in do if isinstance(p, dict) and p]
        # A search filter
        for p in do:
            if isinstance(p, dict) and "search_top_n" in p:
                f = p["search_top_n"].get("filter", {})
                if not f and re.search(r"(コスト[0-9０-９]+(から|以上|以下)|パワー[0-9０-９]+|【トリガー】|イベント[0-9０-９]*枚)", t):
                    findings["A"].append((cid, when, "search filter空 but text制約あり"))
        # B stub
        if when == "on_attack" and any(p == STUB for p in do):
            if not re.search(r"アタック時】[^【]{0,60}パワー[+＋]1000", t) and "+1000" not in t.replace("＋", "+"):
                findings["B"].append((cid, when, "spurious +1000 stub"))
        # C circled-rest as pay_don
        m = CIRC_PAT.search(t)
        if m and isinstance(e.get("cost"), dict) and e["cost"].get("pay_don") == CIRC[m.group(1)]:
            findings["C"].append((cid, when, f"円番号{CIRC[m.group(1)]}=rest を pay_don"))
        # D invalid target type
        def chk_type(o):
            if isinstance(o, dict):
                if o.get("type") == "self_chara_filtered":
                    return True
                return any(chk_type(v) for v in o.values())
            if isinstance(o, list):
                return any(chk_type(x) for x in o)
            return False
        if chk_type(do):
            findings["D"].append((cid, when, "invalid type self_chara_filtered"))
        # E scry missing
        if when in ("on_attack", "counter", "main") and re.search(r"ライフの上[^。]{0,20}見て[^。]{0,20}(上か下|上下)", t):
            if not any("scry_life" in p or "scry" in str(list(p.keys())[0]) for p in do if isinstance(p, dict) and p):
                if any("power_pump" in p for p in do):
                    findings["E"].append((cid, when, "scry_life 欠落 (見て上下に置く)"))
        # F untap leader as untap_don
        if "このリーダーをアクティブ" in t and any(isinstance(p, dict) and "untap_don" in p for p in do):
            findings["F"].append((cid, when, "リーダーをアクティブ→untap_don誤"))
        # G unhandled primitive
        for k in keys:
            if k not in PRIM and k not in META_KEYS:
                findings["G"].append((cid, when, f"未処理primitive {k}"))

print(f"16デッキ unique カード: {len(META)} / 監査対象(parallel込): {len(TARGETS)}")
print("=" * 60)
total = 0
labels = {"A": "search filter欠落", "B": "+1000 stub", "C": "円番号=rest誤pay_don",
          "D": "無効type self_chara_filtered", "E": "scry欠落", "F": "untap leader誤", "G": "未処理primitive"}
for k in "ABCDEFG":
    fs = findings[k]
    if fs:
        print(f"[{k}] {labels[k]}: {len(fs)}")
        for cid, when, msg in fs:
            print(f"     {cid:14} {when:14} {msg}")
        total += len(fs)
print(f"\n総検出: {total}")
