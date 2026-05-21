#!/usr/bin/env python3
"""empty_overlay の 「条件 + このキャラのパワー+N」 静的 buff を 補完。

対象 pattern (= text 先頭が 【 で 始まらない static effect):
- 「自分の「<name>」がレストの場合、 このキャラのパワー+N」 → name + rested_required
- 「自分の「<name>」がいる場合、 このキャラのパワー+N」 → name exists
- 「自分の場のドン!!が相手の場のドン!!の枚数以下の場合、 このキャラのパワー+N」 → don_diff_le 0
- 「自分のリーダーが特徴《X》を持つ場合、 このキャラのパワー+N」 → leader_feature

on_attached_don entry で 静的 power_pump として 補完。
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


def parse_condition(cond_text: str) -> dict | None:
    """text condition の "...の場合" 句から if dict 生成。"""
    # 「自分の「X」がレストの場合」
    m = re.search(r"自分の「(.+?)」がレストの場合", cond_text)
    if m:
        return {
            "self_chara_filtered_count_ge": {
                "filter": {"name": m.group(1)},
                "count": 1,
                "rested_required": True,
            }
        }
    # 「自分の「X」がいる場合」
    m = re.search(r"自分の「(.+?)」がいる場合", cond_text)
    if m:
        return {
            "self_chara_filtered_count_ge": {
                "filter": {"name": m.group(1)},
                "count": 1,
            }
        }
    # 「自分の場のドン!!が相手の場のドン!!の枚数以下の場合」
    if re.search(r"自分の場のドン.{0,5}が相手の場のドン.{0,10}枚数以下の場合", cond_text):
        return {"don_diff_le": 0}
    # 「自分のリーダーが特徴《X》を持つ場合」
    m = re.search(r"自分のリーダーが特徴《(.+?)》を持つ場合", cond_text)
    if m:
        return {"leader_feature": m.group(1)}
    return None


def main():
    fixed = 0
    log = []
    for cid, entries in OVERLAY.items():
        if cid.startswith("_") or not isinstance(entries, list):
            continue
        if entries:
            continue  # empty のみ
        text = get_text(cid)
        if not text:
            continue
        # pattern: "<condition>、 このキャラのパワー+N" (先頭、 末尾 ブロッカー 等 許容)
        m = re.match(r"^(.+?)、\s*このキャラのパワー\+(\d+)。?(.*)$", text.strip())
        if not m:
            continue
        cond_text, amount, trailing = m.group(1), int(m.group(2)), m.group(3)
        cond = parse_condition(cond_text)
        if not cond:
            continue
        entries.append({
            "_text": f"[auto] static: {cond_text} → self power+{amount}",
            "when": "on_attached_don",
            "n": 0,
            "if": cond,
            "do": [
                {
                    "power_pump": {
                        "target": "self",
                        "amount": amount,
                        "duration": "static",
                    }
                }
            ],
        })
        log.append(f"  {cid}: + on_attached_don static if={cond} power+{amount}")
        fixed += 1

    print(f"Fixed {fixed} cards")
    (ROOT / "db" / "card_effects.json").write_text(
        json.dumps(OVERLAY, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "db" / "fix_empty_self_power_buff_log.md").write_text(
        "# empty_overlay self_power_buff 補完ログ\n\n" + "\n".join(log), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
