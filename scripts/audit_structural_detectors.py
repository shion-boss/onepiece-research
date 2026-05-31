#!/usr/bin/env python3
"""構造検出器: 公式テキスト ↔ overlay primitive の 強い不整合を DB-wide で検出。

[[project_card_effect_100_plan_kickoff]] 順2 prototype で 二重コスト以外にも
「公式 KO なのに overlay は bounce」 (OP08-077) 等の 誤 primitive / action 欠落 を確認。
全 4,518 枚を 1 枚ずつ読むのは非現実的なので、 高 precision な 構造検出器で スケールさせる。

検出器:
  A. action 欠落/誤り: 公式テキストに 強い action keyword があるのに overlay JSON に
     対応 primitive family が 1 つもない (= 完全欠落 or 別 primitive で誤実装)。
  B. 空 effect: do が空 or optional_cost_then.effect が空 なのに テキストに action。
  C. 残存 marker: _unimplemented / _missing_effect。

出力は 16-deck pool (meta 採用) を 優先表示。 false positive 前提で 人間 triage する。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 公式テキスト keyword (= effect としての action) → 対応 primitive family。
# overlay JSON dump に family の どれか が 含まれれば OK、 1 つも無ければ flag。
# 注: cost 節 や 条件節 にしか出ない keyword は 誤検出するので 強い action のみ採用。
KEYWORD_FAMILIES = {
    "KO": (["KOする", "KOできる", "、KO", "をKO"],
           ["ko", "ko_multi", "ko_all_others", "chara_to_self_life", "chara_to_opp_life",
            "replace_ko"]),
    "active": (["アクティブにする"],
               ["untap", "untap_chara", "untap_don", "give_attack_active_chara"]),
    "summon": (["登場させる"],
               ["play_from_hand", "play_from_trash", "summon_from_deck", "play_from_hand_or_trash",
                "summon_stage_from_deck_with_feature", "play_from_hand_named", "reveal_top_play",
                "play_from_deck", "summon", "play_event_from_hand"]),
    "return_hand": (["持ち主の手札に戻す", "を手札に戻す", "を、手札に戻す"],
                    ["return_to_hand", "return_to_hand_multi"]),
    "return_deck": (["デッキの下に置く", "デッキの一番下", "デッキに戻す。", "をデッキに戻す"],
                    ["return_to_deck_bottom", "return_to_deck_bottom_multi", "trash_to_deck",
                     "opp_trash_to_deck_bottom", "return_self_to_deck_bottom_if_condition",
                     "look_top_reorder", "search_top_n", "reveal_top_then", "scry"]),
}


def deck_pool_card_ids() -> set[str]:
    ids: set[str] = set()
    for f in (ROOT / "decks").glob("*.json"):
        if ".analysis" in f.name or ".target_v1" in f.name:
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if d.get("leader"):
            ids.add(d["leader"])
        for e in d.get("main", []):
            if e.get("card_id"):
                ids.add(e["card_id"])
    return ids


def main() -> None:
    cards = {c["card_id"]: c for c in json.loads((ROOT / "db" / "cards.json").read_text("utf-8"))}
    eff = json.loads((ROOT / "db" / "card_effects.json").read_text("utf-8"))
    pool = deck_pool_card_ids()

    findings_a, findings_b, findings_c = [], [], []
    for cid, entries in eff.items():
        if cid == "_meta" or not isinstance(entries, list) or not entries:
            continue
        card = cards.get(cid)
        if not card:
            continue
        text = card.get("text") or ""
        ov_dump = json.dumps(entries, ensure_ascii=False)
        base = cid.split("_")[0]

        # C. 残存 marker
        if "_unimplemented" in ov_dump or "_missing_effect" in ov_dump:
            findings_c.append((cid, base in {p.split("_")[0] for p in pool} or cid in pool))

        # A. action keyword 欠落/誤り
        for label, (keywords, family) in KEYWORD_FAMILIES.items():
            if any(kw in text for kw in keywords):
                if not any(f'"{p}"' in ov_dump for p in family):
                    findings_a.append((cid, label, cid in pool,
                                       next(kw for kw in keywords if kw in text)))

        # B. 空 effect (do 空 or optional_cost_then.effect 空) なのに text に【】action
        for e in entries:
            if not isinstance(e, dict):
                continue
            do = e.get("do", [])
            if do == [] and e.get("when") not in (None, "in_hand"):
                findings_b.append((cid, e.get("when"), "do空", cid in pool))
            for d in do:
                if isinstance(d, dict) and "optional_cost_then" in d:
                    if not d["optional_cost_then"].get("effect"):
                        findings_b.append((cid, e.get("when"), "oct.effect空", cid in pool))

    def show(title, rows, fmt):
        print(f"\n=== {title}: {len(rows)} 件 (★=deck pool) ===")
        rows.sort(key=lambda r: (not r[-1] if isinstance(r[-1], bool) else False))
        for r in rows[:60]:
            print(fmt(r))

    show("A. action keyword 欠落/誤 primitive", findings_a,
         lambda r: f"  {'★' if r[2] else ' '} {r[0]:14} [{r[1]}] text='{r[3]}'")
    show("B. 空 effect", findings_b,
         lambda r: f"  {'★' if r[3] else ' '} {r[0]:14} when={r[1]} ({r[2]})")
    show("C. 残存 _unimplemented/_missing_effect marker", findings_c,
         lambda r: f"  {'★' if r[1] else ' '} {r[0]}")
    print(f"\n総計: A={len(findings_a)} B={len(findings_b)} C={len(findings_c)}")
    print(f"deck pool 内: A={sum(1 for r in findings_a if r[2])} "
          f"B={sum(1 for r in findings_b if r[3])}")


if __name__ == "__main__":
    main()
