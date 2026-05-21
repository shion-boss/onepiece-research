#!/usr/bin/env python3
"""「【相手のターン中】 ... <target>のパワー ±N」 の 静的 buff/debuff を 補完。

audit `missing_if_opp_turn` 32 件 のうち、 シンプル パターン に 限定:

case A: 既存 on_attached_don entry が 「【相手のターン中】 ... 」 を 表してるが
        opp_turn flag 抜け → if に opp_turn: true 補完
case B: 「【相手のターン中】 このキャラのパワー +/-N」 が overlay に なし
        → 新規 on_attached_don entry を 追加 (= opp_turn 条件付き)
case C: 「【相手のターン中】 このリーダーのパワー +/-N」 → 同上 (target=self_leader)

複雑 ケース (= replace_ko / 名前指定 chara / 元々のパワーN にする 等) は スキップ。
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


def parse_opp_turn_static_buff(text: str) -> list[dict]:
    """text から 「【相手のターン中】 [条件] <target>のパワー ±N」 phrase を 抽出。

    Returns: list of {target, amount, condition (optional dict), n (= ドン!! 条件)}
    """
    out = []
    # ドン!!×N の 検出
    don_n_match = re.search(r"【ドン!!×(\d+)】", text.replace("‼", "!!"))
    don_n = int(don_n_match.group(1)) if don_n_match else 0

    # 「【相手のターン中】」 から 次の 【...】 までの 区間
    # でも 簡略: 「【相手のターン中】[^【]+」 で 区切る
    for m in re.finditer(r"【相手のターン中】([^【]+)", text):
        seg = m.group(1)
        # condition: 「自分のライフが N 以下/以上の場合」
        cond = {}
        cm = re.search(r"自分のライフが\s*(\d+)\s*枚?以下の場合", seg)
        if cm:
            cond["self_life_le"] = int(cm.group(1))
        cm = re.search(r"自分のライフが\s*(\d+)\s*枚?以上の場合", seg)
        if cm:
            cond["self_life_ge"] = int(cm.group(1))
        cm = re.search(r"自分のリーダーが特徴《(.+?)》を持つ場合", seg)
        if cm:
            cond["leader_feature"] = cm.group(1)
        cm = re.search(r"自分のデッキが\s*(\d+)\s*枚?以下の場合", seg)
        if cm:
            cond["self_deck_count_le"] = int(cm.group(1))
        cm = re.search(r"自分の手札が\s*(\d+)\s*枚?以下の場合", seg)
        if cm:
            cond["self_hand_count_le"] = int(cm.group(1))
        cm = re.search(r"自分の場にドン!!が\s*(\d+)\s*枚ある場合", seg.replace("‼", "!!"))
        if cm:
            cond["self_don_ge"] = int(cm.group(1))
        # target = このキャラ / このリーダー (緩い regex で "は", "を", "の" 等 許容)
        for tm in re.finditer(r"このキャラ[はもをにのが、]?.{0,20}?パワー\s*([+-])\s*(\d+)", seg):
            sign = -1 if tm.group(1) == "-" else 1
            n = int(tm.group(2)) * sign
            out.append({"target": "self", "amount": n, "condition": dict(cond), "n": don_n})
        for tm in re.finditer(r"このリーダー[はもをにのが、]?.{0,20}?パワー\s*([+-])\s*(\d+)", seg):
            sign = -1 if tm.group(1) == "-" else 1
            n = int(tm.group(2)) * sign
            out.append({"target": "self_leader", "amount": n, "condition": dict(cond), "n": don_n})
        # filter-based: 「自分の特徴《X》(を持つ)?キャラすべてを、 パワー ±N」
        for tm in re.finditer(
            r"自分の特徴《(.+?)》(?:を持つ)?キャラ(?:すべて|全て)を?、?\s*パワー\s*([+-])\s*(\d+)", seg
        ):
            feat = tm.group(1)
            sign = -1 if tm.group(2) == "-" else 1
            n = int(tm.group(3)) * sign
            out.append({
                "target": {"type": "all_self_chara_filtered", "filter": {"feature": feat}},
                "amount": n,
                "condition": dict(cond),
                "n": don_n,
            })
        # filter-based cost+: 「自分の特徴《X》(を持つ)?キャラすべてを、 コスト ±N」
        for tm in re.finditer(
            r"自分の特徴《(.+?)》(?:を持つ)?キャラ(?:すべて|全て)を?、?\s*コスト\s*([+-])\s*(\d+)", seg
        ):
            feat = tm.group(1)
            sign = -1 if tm.group(2) == "-" else 1
            n = int(tm.group(3)) * sign
            out.append({
                "target": {"type": "all_self_chara_filtered", "filter": {"feature": feat}},
                "amount": n,
                "condition": dict(cond),
                "n": don_n,
                "kind": "cost_pump",
            })
    return out


def main():
    fixed_a = 0  # 既存 entry に opp_turn 追加
    fixed_b = 0  # 新規 entry 追加
    log = []
    for cid, entries in OVERLAY.items():
        if cid.startswith("_") or not isinstance(entries, list):
            continue
        text = get_text(cid)
        if not text or "【相手のターン中】" not in text:
            continue
        flat = json.dumps(entries, ensure_ascii=False)
        # 既に opp_turn flag あれば skip
        if '"opp_turn"' in flat:
            continue
        # opp_attack 系 when あれば 自動 opp_turn 扱い → skip
        if any(
            e.get("when") in (
                "opp_attack", "opp_attack_on_leader", "opp_attack_on_chara",
                "on_opp_chara_played", "on_opp_chara_ko", "on_opp_life_taken",
                "on_opp_blocker_use", "opp_event_or_trigger_fired",
            )
            for e in entries
            if isinstance(e, dict)
        ):
            continue

        buffs = parse_opp_turn_static_buff(text)
        if not buffs:
            continue

        # 各 buff に つき: 同じ target/amount の on_attached_don entry あるか?
        for buff in buffs:
            matched = False
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                if entry.get("when") != "on_attached_don":
                    continue
                do = entry.get("do", [])
                # 既存 entry が same target/amount の power_pump を 持つか
                for d in do:
                    if not isinstance(d, dict):
                        continue
                    pp = d.get("power_pump")
                    if not isinstance(pp, dict):
                        continue
                    if pp.get("target") == buff["target"] and pp.get("amount") == buff["amount"]:
                        # → opp_turn flag を 追加
                        existing_if = entry.get("if") or {}
                        if isinstance(existing_if, dict):
                            if "opp_turn" not in existing_if:
                                existing_if["opp_turn"] = True
                                # condition も merge
                                for k, v in buff["condition"].items():
                                    if k not in existing_if:
                                        existing_if[k] = v
                                entry["if"] = existing_if
                                log.append(f"  {cid} [case A]: if += opp_turn (+ {buff['condition']})")
                                fixed_a += 1
                        matched = True
                        break
                if matched:
                    break
            if matched:
                continue
            # case B: 新規 entry 追加
            new_if = {"opp_turn": True}
            new_if.update(buff["condition"])
            kind = buff.get("kind", "power_pump")
            if kind == "cost_pump":
                # cost+/- via set_base_cost_filtered_static (= 静的、 filter-based)
                target_spec = buff["target"]
                if isinstance(target_spec, dict) and target_spec.get("type") == "all_self_chara_filtered":
                    filt = target_spec.get("filter", {})
                else:
                    filt = {}
                do_block = [
                    {
                        "set_base_cost_filtered_static": {
                            "filter": filt,
                            "delta": buff["amount"],
                            "scope": "self",
                        }
                    }
                ]
                label = f"コスト{'+' if buff['amount']>=0 else ''}{buff['amount']}"
            else:
                do_block = [
                    {
                        "power_pump": {
                            "target": buff["target"],
                            "amount": buff["amount"],
                            "duration": "static",
                        }
                    }
                ]
                label = f"パワー{'+' if buff['amount']>=0 else ''}{buff['amount']}"
            new_entry = {
                "_text": f"[auto] 【相手のターン中】 {buff['target']} {label}",
                "when": "on_attached_don",
                "n": buff["n"],
                "if": new_if,
                "do": do_block,
            }
            entries.append(new_entry)
            log.append(f"  {cid} [case B]: + {buff['target']} {label}, if={new_if}")
            fixed_b += 1

    print(f"Case A (flag added): {fixed_a}")
    print(f"Case B (new entry):  {fixed_b}")
    (ROOT / "db" / "card_effects.json").write_text(
        json.dumps(OVERLAY, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "db" / "fix_missing_opp_turn_static_log.md").write_text(
        "# missing_if_opp_turn 静的 buff 補完ログ\n\n" + "\n".join(log), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
