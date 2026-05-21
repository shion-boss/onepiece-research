#!/usr/bin/env python3
"""overlay の 各 entry に 不足している if 条件 を 公式テキスト から 自動補完。

audit 検出した missing_if_*:
- missing_if_leader_feature (37件)
- missing_if_opp_turn (42件)
- missing_if_self_power_ge (8件)
- (将来) self_life_le 等

各 entry の `_text` field を 見て、 条件節を 検出 → entry.if に 追加。
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


def merge_if(entry: dict, new_cond: dict) -> None:
    """既存 if / conditions に new_cond を マージ。"""
    cur = entry.get("if")
    if cur is None:
        entry["if"] = dict(new_cond)
        return
    if isinstance(cur, dict):
        cur.update(new_cond)
        return
    # conditions list の場合
    if "conditions" in entry and isinstance(entry["conditions"], list):
        entry["conditions"].append(new_cond)
        return


def infer_conditions(entry_text: str, when: str) -> dict:
    """entry の _text と when から 必要な if 条件を 推定。"""
    result: dict = {}
    if not entry_text:
        return result
    # 「自分のリーダーが特徴《X》を持つ場合」
    m = re.search(r"自分のリーダーが特徴《(.+?)》(?:か《(.+?)》)?を持つ場合", entry_text)
    if m:
        f1, f2 = m.group(1), m.group(2)
        if f2:
            result["leader_features_any"] = [f1, f2]
        else:
            result["leader_feature"] = f1
    # 「相手のターン中」 → opp_turn (= but only if when is not already opp_attack/opp_event)
    if "【相手のターン中】" in entry_text and when not in ("opp_attack", "opp_event_or_trigger_fired", "opp_attack_on_leader", "opp_attack_on_chara"):
        result["opp_turn"] = True
    # 「このキャラのパワーが N 以上の場合」
    m = re.search(r"このキャラのパワーが\s*(\d+)\s*以上の場合", entry_text)
    if m:
        result["self_power_ge"] = int(m.group(1))
    # 「自分のライフが N 以下の場合」
    m = re.search(r"(?:自分の)?ライフが\s*(\d+)\s*(?:枚)?以下の場合", entry_text)
    if m:
        result["self_life_le"] = int(m.group(1))
    # 「自分のライフが N 以上の場合」
    m = re.search(r"(?:自分の)?ライフが\s*(\d+)\s*(?:枚)?以上の場合", entry_text)
    if m:
        result["self_life_ge"] = int(m.group(1))
    return result


def main():
    fixed = 0
    log = []
    for cid, entries in OVERLAY.items():
        if cid.startswith("_") or not isinstance(entries, list):
            continue
        card_text = get_text(cid)
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            entry_text = entry.get("_text", "")
            inferred = infer_conditions(entry_text, entry.get("when", ""))
            if not inferred:
                continue
            existing = entry.get("if") or {}
            # 既に entry.if に これらの key が ある場合 は skip
            new_keys = {k: v for k, v in inferred.items() if k not in existing}
            if not new_keys:
                # conditions に も lookup
                conds_list = entry.get("conditions") or []
                if isinstance(conds_list, list):
                    flat_keys = set()
                    for c in conds_list:
                        if isinstance(c, dict):
                            flat_keys.update(c.keys())
                    new_keys = {k: v for k, v in new_keys.items() if k not in flat_keys}
                if not new_keys:
                    continue
            # merge
            if isinstance(existing, dict):
                existing.update(new_keys)
                entry["if"] = existing
            else:
                entry["if"] = new_keys
            log.append(f"  {cid} [{i}]: if += {new_keys}")
            fixed += 1

    print(f"Fixed {fixed} entries")
    (ROOT / "db" / "card_effects.json").write_text(
        json.dumps(OVERLAY, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "db" / "fix_missing_if_log.md").write_text(
        "# missing_if 修正ログ\n\n" + "\n".join(log), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
