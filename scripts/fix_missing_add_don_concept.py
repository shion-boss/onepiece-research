#!/usr/bin/env python3
"""overlay が 「ドン!!デッキから ドン!!N 枚をアクティブで追加」 を 欠落 / 別 primitive (= untap_don) で
代用 している ケース を 修正。

問題例:
- ST10-002: text 「ドン!!デッキから add active 1」 → overlay untap_don 1 (= 既存ドンを 活性化、 別概念)
- OP05-060: text 「ライフ→手札 cost、 ドン!! add active 1」 → overlay do = [life_to_hand 1] (= add_don 欠落)
- OP09-061: empty overlay。 「on event ドン!!2枚以上戻された時、 add 1 active + 1 rested」 + static cost+1

修正:
- 「ドン!!デッキから.{0,30}アクティブで追加」 を text で 検出 → entry の do に add_don 補完
- 「ドン!!デッキから.{0,30}レストで追加」 を text で 検出 → add_rested_don 補完
- 既存 untap_don 1 placeholder が add_don 1 の 誤代用 と 判明 → 入れ替え
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CARDS = {c["card_id"]: c for c in json.load(open(ROOT / "db" / "cards.json"))}
OVERLAY = json.load(open(ROOT / "db" / "card_effects.json"))


def get_text(cid: str) -> str:
    text = (CARDS.get(cid, {}).get("text") or "").strip()
    if not text:
        base = cid.split("_")[0]
        text = (CARDS.get(base, {}).get("text") or "").strip()
    return text


def parse_add_don_primitives(text: str) -> list[dict]:
    """text 全文から add_don / add_rested_don primitive を 抽出。"""
    t = text.replace("‼", "!!")
    primitives = []
    # 「ドン!!デッキから(、)?ドン!!N枚(まで)?を、アクティブで追加」
    for m in re.finditer(r"ドン!!デッキから.{0,15}ドン!!(\d+)枚(?:まで)?(?:を)?、?\s*アクティブで追加", t):
        primitives.append({"add_don": int(m.group(1))})
    # 「ドン!!デッキから(、)?ドン!!N枚(まで)?を、レストで追加」 or 「さらにN枚までをレストで追加」
    for m in re.finditer(r"(?:ドン!!デッキから|さらに).{0,15}ドン!!?(\d+)枚?(?:まで)?(?:を)?、?\s*レストで追加", t):
        primitives.append({"add_rested_don": int(m.group(1))})
    return primitives


def main():
    fixed = 0
    log = []
    for cid, entries in OVERLAY.items():
        if cid.startswith("_") or not isinstance(entries, list):
            continue
        text = get_text(cid)
        if not text:
            continue
        if "アクティブで追加" not in text and "レストで追加" not in text:
            continue
        flat = json.dumps(entries, ensure_ascii=False)
        if "add_don" in flat or "add_don_active" in flat or "add_rested_don" in flat:
            continue
        prims = parse_add_don_primitives(text)
        if not prims:
            continue
        # 該当 entry の when 推定
        if "【起動メイン】" in text:
            when = "activate_main"
        elif "【自分のターン中】" in text and "戻された時" in text:
            when = "on_self_don_returned_to_deck"
        elif "【相手のターン中】" in text and "戻された時" in text:
            when = "on_self_don_returned_to_deck"
        elif "【登場時】" in text:
            when = "on_play"
        elif "【自分のターン終了時】" in text or "【ターン終了時】" in text:
            when = "end_of_turn"
        else:
            when = "activate_main"

        # 既存 entry に when 一致 あれば do を 拡張 / 入れ替え
        target_entry = None
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if entry.get("when") == when:
                target_entry = entry
                break
        if target_entry is not None:
            do = target_entry.setdefault("do", [])
            # untap_don 1 placeholder で 誤代用 されてる ケース → 入れ替え
            replaced = False
            for i, d in enumerate(do):
                if isinstance(d, dict) and "untap_don" in d and d.get("untap_don") == 1:
                    do[i] = prims[0]
                    log.append(f"  {cid} [{when}]: untap_don=1 → add_don={prims[0].get('add_don')}")
                    replaced = True
                    fixed += 1
                    break
            if not replaced:
                # life_to_hand などの 「cost的 do」 後に add_don 追加
                # 実装上 do に add 追加
                do.extend(prims)
                log.append(f"  {cid} [{when}]: do += {prims}")
                fixed += 1
        else:
            # 新規 entry
            new_entry = {
                "_text": f"[auto] {when}: add_don 補完",
                "when": when,
                "do": list(prims),
            }
            if when == "activate_main":
                new_entry["cost"] = {"once_per_turn": True}
            entries.append(new_entry)
            log.append(f"  {cid}: new {when} entry with {prims}")
            fixed += 1

    print(f"Fixed {fixed} entries")
    (ROOT / "db" / "card_effects.json").write_text(
        json.dumps(OVERLAY, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "db" / "fix_missing_add_don_log.md").write_text(
        "# add_don_concept 補完ログ\n\n" + "\n".join(log), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
