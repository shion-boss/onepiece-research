#!/usr/bin/env python3
"""公式 「相手の...をレストにする」 が overlay 欠落している 16 件 を 修正。

実例:
  OP14-031: 「コスト8以下キャラ2 レスト + ドン5アクティブ」 → overlay [untap_don:5] のみ
  OP15-078: 「パワー5000以下キャラ1 レスト」 → overlay [draw:1] のみ
  OP06-035: 「相手キャラかドン合計2 レスト」 → overlay [life_to_hand:1] のみ
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OVERLAY = json.load(open(ROOT / "db" / "card_effects.json"))
CARDS = {c["card_id"]: c for c in json.load(open(ROOT / "db" / "cards.json"))}


def get_text(cid: str) -> str:
    text = (CARDS.get(cid, {}).get("text") or "").strip()
    if not text:
        base = cid.split("_")[0]
        text = (CARDS.get(base, {}).get("text") or "").strip()
    return text


def parse_rest_primitives(text: str) -> list[dict]:
    primitives = []
    t = text.replace("‼", "!!").replace("！", "!")

    # 「相手のリーダーかキャラ N 枚 までを、 レストにする」
    m = re.search(r"相手のリーダーかキャラ\s*(\d+)?\s*枚?(?:まで)?を?、?\s*レストにする", t)
    if m:
        n = int(m.group(1)) if m.group(1) else 1
        if n == 1:
            primitives.append({"rest": "one_opponent_inplay_any"})
        else:
            primitives.append({"rest": {"target": "one_opponent_inplay_any", "count": n}})
        return primitives

    # 「相手のコスト N 以下のキャラ M 枚 までを、 レストにする」
    m = re.search(r"相手の(?:.{0,5})?コスト\s*(\d+)\s*以下のキャラ\s*(\d+)?\s*枚?(?:まで)?を?、?\s*レストにする", t)
    if m:
        cost_n = int(m.group(1))
        cnt = int(m.group(2)) if m.group(2) else 1
        target = f"one_opponent_character_cost_le_{cost_n}"
        if cnt == 1:
            primitives.append({"rest": target})
        else:
            primitives.append({"rest": {"target": target, "count": cnt}})
        return primitives

    # 「相手のパワー N 以下のキャラ M 枚 までを、 レストにする」
    m = re.search(r"相手の.{0,5}パワー\s*(\d+)\s*以下のキャラ\s*(\d+)?\s*枚?(?:まで)?を?、?\s*レストにする", t)
    if m:
        pw_n = int(m.group(1))
        cnt = int(m.group(2)) if m.group(2) else 1
        if pw_n == 5000:
            target = "one_opponent_character_le_5000" if cnt == 1 else "any_opponent_character_le_5000"
        else:
            target = f"one_opponent_character_power_le_{pw_n}"
        if cnt == 1:
            primitives.append({"rest": target})
        else:
            primitives.append({"rest": {"target": target, "count": cnt}})
        return primitives

    # 「相手のキャラかドン!! 合計 N 枚 までを、 レストにする」
    m = re.search(r"相手のキャラかドン!!\s*合計\s*(\d+)\s*枚までを?、?\s*レストにする", t)
    if m:
        n = int(m.group(1))
        primitives.append({"rest": {"target": "one_opponent_character_any", "count": n}})
        # ドン!! レスト も 追加
        primitives.append({"rest_opp_don": n})
        return primitives

    # 「相手の(レストの)?コスト N 以下のキャラ M 枚」 (一般)
    m = re.search(r"相手の.{0,15}キャラ\s*(\d+)?\s*枚?(?:まで)?を?、?\s*レストにする", t)
    if m:
        cnt = int(m.group(1)) if m.group(1) else 1
        if cnt == 1:
            primitives.append({"rest": "one_opponent_character_any"})
        else:
            primitives.append({"rest": {"target": "one_opponent_character_any", "count": cnt}})
        return primitives

    return primitives


def main():
    fixed = 0
    log = []
    for cid, entries in OVERLAY.items():
        if cid.startswith("_") or not isinstance(entries, list) or not entries:
            continue
        text = get_text(cid)
        if not text or not re.search(r"相手の.{0,30}レストにする", text):
            continue
        flat = json.dumps(entries, ensure_ascii=False)
        rest_keys = ('"rest"', "rest_opp_don", "rest_self_cards", "keep_opp_rested",
                     "set_cannot_rest", "stay_rested_next_refresh", "rest_opp_chara")
        if any(k in flat for k in rest_keys):
            continue
        new_prims = parse_rest_primitives(text)
        if not new_prims:
            continue
        when = None
        if "【登場時】" in text:
            when = "on_play"
        elif "【アタック時】" in text:
            when = "on_attack"
        elif "【起動メイン】" in text:
            when = "activate_main"
        elif "【メイン】" in text:
            when = "main"
        elif "【KO時】" in text:
            when = "on_ko"
        else:
            when = "on_play"
        added = False
        for entry in entries:
            if isinstance(entry, dict) and entry.get("when") == when:
                do = entry.setdefault("do", [])
                # placeholder 検出 (= draw のみ で text に draw なし)
                if len(do) == 1 and "draw" in do[0] and "カード" not in text[:30]:
                    log.append(f"  {cid} [{when}]: replaced placeholder")
                    do.clear()
                do.extend(new_prims)
                added = True
                break
        if not added:
            entries.append({
                "_text": f"[auto] {when}: rest 補完",
                "when": when,
                "do": new_prims,
            })
            log.append(f"  {cid}: new {when} entry")
        fixed += 1

    print(f"Fixed {fixed} cards")
    (ROOT / "db" / "card_effects.json").write_text(
        json.dumps(OVERLAY, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "db" / "fix_missing_rest_log.md").write_text(
        "# rest_concept 補完ログ\n\n" + "\n".join(log), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
