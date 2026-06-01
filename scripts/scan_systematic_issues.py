#!/usr/bin/env python3
"""全カード横断で既知 systematic バグパターンを検出 (= 等価署名 grind の高レバレッジ化)。

inline 監査で個別に見つけた型 (二重discard / search filter欠落 / on_attack重複 等) を
DB 全体で機械検出し、 バッチ修正の母数を出す。 audited 済は除外。
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
eff = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
cards = {c["card_id"]: c for c in json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))}
prog = json.loads((ROOT / "db" / "audit_llm" / "full_db_progress.json").read_text(encoding="utf-8"))
audited = set(prog.get("audited", [])) | set(prog.get("vanilla_verified", [])) | set(prog.get("equivalence_verified", []))

Z = str.maketrans("０１２３４５６７８９", "0123456789")


def text_of(cid):
    c = cards.get(cid, {})
    return ((c.get("text") or "") + " " + (c.get("trigger") or "")).translate(Z)


def overlay_str(cid):
    return json.dumps(eff.get(cid), ensure_ascii=False)


issues = defaultdict(list)

for cid, ents in eff.items():
    if not isinstance(ents, list) or cid not in cards or cid in audited or not ents:
        continue
    t = text_of(cid)
    ov = overlay_str(cid)

    # 1) search filter 欠落: 「特徴《X》/『X』を含む特徴/「名前」 …公開し手札に加える」 系で
    #    search_top_n/search の filter に feature/feature_contains/name_in が無い
    for e in ents:
        for d in e.get("do", []):
            st = d.get("search_top_n") or d.get("search") if isinstance(d, dict) else None
            if not isinstance(st, dict):
                continue
            filt = st.get("filter", {})
            text_wants_feat = bool(re.search(r"(特徴《[^》]+》|『[^』]+』を含む特徴)", t))
            has_feat = any(k in filt for k in ("feature", "feature_contains", "feature_in", "name", "name_in", "color", "category"))
            if text_wants_feat and not has_feat:
                issues["search_filter_missing"].append(cid)

    # 2) 同 when 重複 entry (一方 if付き / 一方無条件 = 二重発火疑い)
    byw = defaultdict(list)
    for e in ents:
        if isinstance(e, dict):
            byw[e.get("when")].append(e)
    for w, es in byw.items():
        if len(es) >= 2 and w in ("on_attack", "on_play", "on_block"):
            has_if = [bool(e.get("if")) for e in es]
            do_strs = [json.dumps(e.get("do"), ensure_ascii=False, sort_keys=True) for e in es]
            # do が同一 で if有無が割れている → 二重発火
            if len(set(do_strs)) == 1 and True in has_if and False in has_if:
                issues["dup_same_when"].append(cid)

    # 3) missing draw: text「カードN枚を引く」 だが overlay に draw も search(to hand) も無い
    if re.search(r"カード\d+枚を?引[くきい]", t) and "draw" not in ov and "search" not in ov and "reveal_top" not in ov and "look_top" not in ov:
        issues["missing_draw"].append(cid)

    # 4) cost/do 二重 (pay_don): entry cost.pay_don かつ do に add_don/attach 系でなく pay_don 相当の二重
    for e in ents:
        c = e.get("cost")
        if isinstance(c, dict):
            for key in ("pay_don", "rest_self", "rest_self_don"):
                if key in c and any(isinstance(d, dict) and key in d for d in e.get("do", [])):
                    issues["cost_do_dup_" + key].append(cid)

    ov_obj = ents

    # 5) 【ターン1回】 once_per_turn 欠落: text に【ターン1回】 だが overlay に once_per_turn 無し
    if "【ターン1回】" in t and "once_per_turn" not in ov:
        issues["once_per_turn_missing"].append(cid)

    # 6) 【ドン!!×N】 don gate 欠落: 該当 when entry に self_attached_don_ge も on_attached_don も無し
    if re.search(r"【ドン[!！‼]+×(\d+)】", t):
        gated = ("self_attached_don_ge" in ov) or any(
            isinstance(e, dict) and e.get("when") == "on_attached_don" for e in ents)
        if not gated:
            issues["don_gate_missing"].append(cid)

    # 7) duration 誤り: text「次の相手の(ターン|エンドフェイズ)終了時まで」 だが overlay に
    #    next_opp_turn_end が無く、 power_pump/cost_minus/give_keyword の duration が turn/battle
    if re.search(r"次の相手の(ターン|エンドフェイズ)終了時まで", t) and "next_opp_turn_end" not in ov:
        if re.search(r'"duration":\s*"(turn|battle)"', ov):
            issues["duration_next_opp_missing"].append(cid)


print("=== systematic 検出 (audited 除外) ===")
for k, v in sorted(issues.items(), key=lambda x: -len(set(x[1]))):
    u = sorted(set(v))
    print(f"  {k}: {len(u)} card")
    print(f"     {u[:12]}")
