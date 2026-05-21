#!/usr/bin/env python3
"""empty_overlay の 「このキャラが KO される場合、代わりに <cost>」 シンプル replace_ko を 補完。

対象 pattern (= empty overlay、 text に 「KOされる場合、代わりに 〜 捨てる」 含む):
- EB01-008: 【ターン1回】効果KO代わりに 手札のイベント or ステージ 1枚 捨てる
- OP13-046: 【ターン1回】KO/場離れ代わりに 手札の『白ひげ海賊団』含む特徴 1枚 捨てる
- 他 simple self-KO-replace cases

replace_ko / replace_leave + once_per_turn cost + discard_hand_with_filter で 補完。
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


def parse_discard_filter(cost_text: str) -> dict | None:
    """text の cost 句から discard_hand_with_filter の filter を 抽出。

    Examples:
    - 「自分の手札のイベントかステージカード1枚を捨てる」 → category in [EVENT, STAGE]
    - 「自分の手札から『X』を含む特徴を持つカード1枚を捨てる」 → feature_contains X
    - 「自分の手札のN枚を捨てる」 → no filter, count=N
    """
    # 「『X』を含む特徴を持つ」
    m = re.search(r"『(.+?)』を含む特徴を持つ", cost_text)
    if m:
        return {"feature_contains": m.group(1)}
    # 「イベントかステージ」
    if "イベントかステージ" in cost_text:
        return {"category_in": ["EVENT", "STAGE"]}
    # 「特徴《X》を持つ」
    m = re.search(r"特徴《(.+?)》を持つ", cost_text)
    if m:
        return {"feature": m.group(1)}
    return None


def main():
    fixed = 0
    log = []
    for cid, entries in OVERLAY.items():
        if cid.startswith("_") or not isinstance(entries, list):
            continue
        if entries:
            continue
        text = get_text(cid)
        if not text:
            continue
        # Pattern A: 【ターン1回】このキャラが効果によってKOされる場合、代わりに <X> 1枚を捨てることができる
        # Pattern B: 【ターン1回】このキャラがKOされる(か相手の効果で場を離れる)?場合、代わりに <X> 1枚を捨てることができる
        m = re.search(
            r"【ターン1回】このキャラが(?:効果によって)?KOされる(?:か相手の効果で場を離れる)?場合、?\s*代わりに(.+?)1枚を捨てることができる",
            text,
        )
        if not m:
            continue
        cost_clause = m.group(1)
        filt = parse_discard_filter(cost_clause)
        # leave_kind: 「KO」 のみ → replace_ko、 「場を離れる」 含む → replace_leave
        when = "replace_leave" if "場を離れる" in m.group(0) else "replace_ko"
        if_cond = {"target": "self"}
        if "効果によって" in m.group(0) or "相手の効果で" in m.group(0):
            if_cond["by_opp_effect"] = True
        cost_block = [{"once_per_turn": True}]
        if filt:
            cost_block.append({"discard_hand_with_filter": {"filter": filt, "count": 1}})
        else:
            cost_block.append({"discard_hand": 1})
        entries.append({
            "_text": f"[auto] {when}: {cost_clause[:60]} → cost 解消",
            "when": when,
            "if": if_cond,
            "cost": cost_block,
            "do": [],
        })
        log.append(f"  {cid}: + {when} if={if_cond} cost={cost_block}")
        fixed += 1

    print(f"Fixed {fixed} cards")
    (ROOT / "db" / "card_effects.json").write_text(
        json.dumps(OVERLAY, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "db" / "fix_empty_replace_ko_log.md").write_text(
        "# empty_overlay replace_ko 補完ログ\n\n" + "\n".join(log), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
