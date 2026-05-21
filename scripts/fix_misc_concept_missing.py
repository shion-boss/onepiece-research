#!/usr/bin/env python3
"""missing_rest_concept / missing_ko_concept / missing_return_to_hand_concept / missing_untap_concept
の 自動 修正可能 ケース を 一括 補完。

主要 pattern:
- 「相手のドン!!N枚までをレストにする」 → rest_opp_don N (= 既存 draw/trash placeholder を 入れ替え or 追加)
- 「特徴《X》(を持つ)?リーダーをアクティブにする」 → untap target=self_leader (filter check 別途)
- 「自分の特徴《X》を持つキャラ1枚 + ドン1枚 アクティブにする」 → untap_chara filter + untap_don 1
- 「コストN以下のキャラ(すべて)をKO」 → ko_multi cost_le or ko cost_le
- 「コストN以上の特徴《Y》キャラ1枚を手札に戻すことができる: cost」 → cost に return_to_hand_with_filter 追加
- 「キャラが相手の効果で場を離れる場合、代わりにこのキャラを手札に戻す」 → replace_leave (= 別 entry)
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


def _has_keyword_in_flat(entries: list, *keys: str) -> bool:
    flat = json.dumps(entries, ensure_ascii=False)
    return any(k in flat for k in keys)


def fix_rest_opp_don(cid: str, entries: list, text: str, log: list) -> int:
    """「相手のドン!!N枚までを、レストにする」 が overlay 欠落 → rest_opp_don N 補完。"""
    t = text.replace("‼", "!!")
    m = re.search(r"相手のドン!!\s*(\d+)\s*枚(?:まで)?を、?\s*レストにする", t)
    if not m:
        return 0
    if _has_keyword_in_flat(entries, '"rest_opp_don"'):
        return 0
    n = int(m.group(1))
    # 該当 when 推定
    if "【アタック時】" in text:
        when = "on_attack"
    elif "【登場時】" in text:
        when = "on_play"
    elif "【起動メイン】" in text:
        when = "activate_main"
    else:
        return 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("when") != when:
            continue
        do = entry.setdefault("do", [])
        # 既存 trash_self_hand_random 1 placeholder → cost 側 移動 + 本体 rest_opp_don
        # ただし cost に discard_hand 既存 なら、 do の trash 削除
        cost = entry.get("cost") or {}
        if isinstance(cost, dict) and cost.get("discard_hand") and len(do) == 1 and do[0].get("trash_self_hand_random") == 1:
            do[0] = {"rest_opp_don": n}
            log.append(f"  {cid} [{when}]: do trash → rest_opp_don {n}")
            return 1
        do.append({"rest_opp_don": n})
        log.append(f"  {cid} [{when}]: do += rest_opp_don {n}")
        return 1
    return 0


def fix_untap_leader_or_chara(cid: str, entries: list, text: str, log: list) -> int:
    """「自分の特徴《X》(を持つ)?リーダーを、 アクティブにする」 → untap self_leader (filter check)。"""
    t = text.replace("‼", "!!")
    m = re.search(r"自分の(?:特徴《(.+?)》(?:を持つ)?)?リーダーを、?\s*アクティブにする", t)
    if not m:
        return 0
    if _has_keyword_in_flat(entries, '"untap"'):
        return 0
    feat = m.group(1)
    # 該当 when 推定
    if "【登場時】" in text:
        when = "on_play"
    elif "【起動メイン】" in text:
        when = "activate_main"
    else:
        return 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("when") != when:
            continue
        do = entry.setdefault("do", [])
        prim = {"untap": "self_leader"}
        do.insert(0, prim)
        # condition 補完
        if feat:
            existing_if = entry.get("if") or {}
            if isinstance(existing_if, dict) and "leader_feature" not in existing_if:
                existing_if["leader_feature"] = feat
                entry["if"] = existing_if
        log.append(f"  {cid} [{when}]: do += untap self_leader (leader_feature={feat})")
        return 1
    return 0


def fix_untap_chara_filter_plus_don(cid: str, entries: list, text: str, log: list) -> int:
    """「自分の(...)キャラ N 枚までとドン!!M 枚までを、 アクティブにする」 → untap_chara filter + untap_don M。

    既存 entry の do に [draw 1] placeholder 等 入ってる ケースを 入れ替え。
    """
    t = text.replace("‼", "!!")
    m = re.search(
        r"自分の(?:、)?(?:特徴《(.+?)》(?:か《(.+?)》)?(?:を持つ)?)?キャラ\s*(\d+)\s*枚(?:まで)?と"
        r"ドン!!\s*(\d+)\s*枚(?:まで)?を、?\s*アクティブにする",
        t,
    )
    if not m:
        return 0
    if _has_keyword_in_flat(entries, '"untap_chara"', '"untap_don"'):
        return 0
    f1, f2, chara_n, don_n = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
    # condition: 「自分の手札が N 以下/以上の場合」
    cond = None
    cm = re.search(r"自分の手札が\s*(\d+)\s*枚?以下の場合", t)
    if cm:
        cond = {"self_hand_count_le": int(cm.group(1))}
    if "【自分のターン終了時】" in text or "【ターン終了時】" in text:
        when = "end_of_turn"
    elif "【登場時】" in text:
        when = "on_play"
    else:
        return 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("when") != when:
            continue
        do = entry.setdefault("do", [])
        # 既存 draw 1 placeholder 入れ替え
        for i, d in enumerate(do):
            if isinstance(d, dict) and "draw" in d and d.get("draw") == 1:
                do.pop(i)
                break
        # untap_chara filter 構成
        flt = {}
        if f1 and f2:
            flt["or_clauses"] = [{"feature": f1}, {"feature": f2}]
        elif f1:
            flt["feature"] = f1
        if flt:
            do.append({"untap_chara": {"target": "self_chara_filtered", "filter": flt, "count": chara_n}})
        else:
            do.append({"untap_chara": {"count": chara_n}})
        do.append({"untap_don": don_n})
        if cond:
            existing_if = entry.get("if") or {}
            if isinstance(existing_if, dict):
                for k, v in cond.items():
                    if k not in existing_if:
                        existing_if[k] = v
                entry["if"] = existing_if
        log.append(f"  {cid} [{when}]: do += untap_chara filter={flt} count={chara_n} + untap_don {don_n}")
        return 1
    return 0


def fix_ko_cost_le_all(cid: str, entries: list, text: str, log: list) -> int:
    """「コスト N 以下のキャラすべてを、 KO する」 → ko_multi cost_le N + 全体。"""
    t = text.replace("‼", "!!")
    m = re.search(r"コスト\s*(\d+)\s*以下のキャラすべてを、?\s*KOする", t)
    if not m:
        return 0
    if _has_keyword_in_flat(entries, '"ko"', '"ko_multi"', '"ko_all_others"', '"chara_to_opp_life"'):
        return 0
    n = int(m.group(1))
    # 該当 when 推定 (= cost あれば そのまま 残す)
    if "【登場時】" in text:
        when = "on_play"
    elif "【メイン】" in text:
        when = "main"
    elif "【アタック時】" in text:
        when = "on_attack"
    else:
        return 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("when") != when:
            continue
        do = entry.setdefault("do", [])
        # board wipe primitive: ko_multi for "all_inplay (= both sides) cost_le_N"
        do.append({
            "ko_multi": {
                "target": "all_chara_filtered",
                "scope": "both",
                "filter": {"cost_le": n},
            }
        })
        log.append(f"  {cid} [{when}]: do += ko_multi all_chara cost_le_{n}")
        return 1
    return 0


def main():
    fixed_total = 0
    log = []
    for cid, entries in OVERLAY.items():
        if cid.startswith("_") or not isinstance(entries, list):
            continue
        text = get_text(cid)
        if not text:
            continue
        fixed_total += fix_rest_opp_don(cid, entries, text, log)
        fixed_total += fix_untap_leader_or_chara(cid, entries, text, log)
        fixed_total += fix_untap_chara_filter_plus_don(cid, entries, text, log)
        fixed_total += fix_ko_cost_le_all(cid, entries, text, log)

    print(f"Fixed {fixed_total} entries")
    (ROOT / "db" / "card_effects.json").write_text(
        json.dumps(OVERLAY, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "db" / "fix_misc_concept_log.md").write_text(
        "# misc concept_missing 補完ログ\n\n" + "\n".join(log), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
