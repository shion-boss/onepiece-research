#!/usr/bin/env python3
"""empty_overlay の 「自分のリーダーが特徴《X》を持つ場合、 このキャラのコスト+N」
in_hand cost+ static buff を 補完。

対象例:
- EB03-042: 「自分のリーダーが特徴《革命軍》を持つ場合、 このキャラのコスト+4」
- OP13-081: 「リーダー特徴《革命軍》を持つ場合、 このキャラのコスト+3」
- OP12-085 / OP12-095: 同様

engine 拡張: game.py の _in_hand_cost_minus に in_hand_cost_plus 対応 を 追加済。
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


def main():
    fixed_empty = 0
    fixed_existing = 0
    log = []
    for cid, entries in OVERLAY.items():
        if cid.startswith("_") or not isinstance(entries, list):
            continue
        text = get_text(cid)
        if not text:
            continue
        # Pattern: 「リーダー特徴《X》を持つ場合、 このキャラのコスト+N」
        m = re.search(
            r"自分のリーダーが特徴《(.+?)》(?:か《(.+?)》)?を持つ場合、?\s*このキャラのコスト\+(\d+)",
            text,
        )
        if not m:
            continue
        f1, f2, amount = m.group(1), m.group(2), int(m.group(3))
        if f2:
            if_cond = {"leader_features_any": [f1, f2]}
        else:
            if_cond = {"leader_feature": f1}
        # 既に in_hand entry あれば skip
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if entry.get("when") == "in_hand":
                # 既存に cost_plus 加算 — もし leader_feature の if 一致 なら skip
                existing_if = entry.get("if") or {}
                if isinstance(existing_if, dict) and (
                    existing_if.get("leader_feature") == f1
                    or sorted(existing_if.get("leader_features_any", [])) == sorted([f1, f2] if f2 else [f1])
                ):
                    break
        else:
            new_entry = {
                "_text": f"[auto] in_hand: リーダー特徴《{f1}》 時 コスト+{amount}",
                "when": "in_hand",
                "if": if_cond,
                "do": [{"in_hand_cost_plus": amount}],
            }
            entries.append(new_entry)
            if not any(isinstance(e, dict) and e.get("when") != "in_hand" for e in entries[:-1]):
                fixed_empty += 1
            else:
                fixed_existing += 1
            log.append(f"  {cid}: + in_hand cost+{amount} if={if_cond}")

    return fixed_empty, fixed_existing, log


if __name__ == "__main__":
    result = main()
    fixed_empty, fixed_existing, log = result
    print(f"Fixed {fixed_empty} empty + {fixed_existing} existing overlays")
    (ROOT / "db" / "card_effects.json").write_text(
        json.dumps(OVERLAY, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "db" / "fix_empty_in_hand_cost_plus_log.md").write_text(
        "# in_hand_cost_plus 補完ログ\n\n" + "\n".join(log), encoding="utf-8"
    )
