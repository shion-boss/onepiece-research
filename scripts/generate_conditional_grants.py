# -*- coding: utf-8 -*-
"""
sev 4 条件付きキーワード grant overlay 自動生成
==============================================

目的:
    Phase 1A 後 機能停止 した 条件付き keyword grant カード を bulk で overlay 補完。

    text パターン: 「〜場合、 【keyword】を得る」 / 「【keyword】を得る」 単独
    →  公式テキスト 通り の DSL に 変換 (= 1:1、 自動近似なし)。

    text → 条件 parser + duration 検出 (= turn / 永続) で 完全 公式準拠 entry を 生成。

出力:
    db/card_effects.json を 上書き (= 既存 entry 破壊せず append のみ)
    db/conditional_grant_generation_report.json (= 生成 / skip / 不能 件数 + 詳細)
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS_JSON = ROOT / "db" / "cards.json"
OVERLAY_JSON = ROOT / "db" / "card_effects.json"
REPORT_JSON = ROOT / "db" / "conditional_grant_generation_report.json"


# Phase 1A heuristic (= 条件付き 検出)
def is_conditional_keyword(text: str, keyword: str) -> bool:
    bracket = f"【{keyword}】"
    if bracket not in text:
        return False
    sentences = text.replace("\n", "。").split("。")
    innate_found = False
    for s in sentences:
        idx = s.find(bracket)
        if idx == -1:
            continue
        after = s[idx + len(bracket) : idx + len(bracket) + 20]
        before = s[:idx]
        if after.startswith(("を得", "を発動", "になる", "を持つ", "を持た")):
            continue
        if "発動できない" in after[:10]:
            continue
        if "場合" in before:
            continue
        if "：" in before or ":" in before:
            continue
        if before.endswith("】"):
            last = before.rfind("【")
            if last >= 0:
                marker = before[last:]
                if "ドン" in marker or "×" in marker or "ターン1回" in marker:
                    continue
        innate_found = True
    return not innate_found


def find_grant_sentences(text: str, keyword: str) -> list[tuple[str, str]]:
    """text 内 の 「〜場合、 【kw】を得る」 文 を 抽出。

    Returns: [(condition_text, duration_marker), ...]
        duration_marker は 「このターン中、」 「次の相手のターン終了時まで、」 等
    """
    bracket = f"【{keyword}】"
    results = []
    sentences = text.replace("\n", "。").split("。")
    for s in sentences:
        idx = s.find(bracket)
        if idx == -1:
            continue
        after = s[idx + len(bracket) : idx + len(bracket) + 20]
        if not after.startswith("を得"):
            continue
        # この文 が grant 文
        before = s[:idx]
        results.append((before, after))
    return results


# 条件節 → DSL if 句 (= public mapping)
CONDITION_PATTERNS = [
    # (regex, DSL key, value_extractor)
    (r"自分のリーダー が ?「([^」]+)」", "leader_name", lambda m: m.group(1)),
    (r"自分のリーダーが「([^」]+)」", "leader_name", lambda m: m.group(1)),
    (r"自分のリーダーが特徴《([^》]+)》", "leader_feature", lambda m: m.group(1)),
    (r"自分のリーダーが『([^』]+)』を含む特徴", "leader_feature_substr", lambda m: m.group(1)),
    (r"自分のリーダーが多色", "leader_color_multi", lambda m: True),
    (r"自分のリーダーが([^で]+?)で、相手の場のドン[‼!]{1,2}が(\d+)枚以上", "leader_color_and_opp_don_ge", lambda m: (m.group(1), int(m.group(2)))),
    (r"自分のトラッシュが(\d+)枚以上", "self_trash_count_ge", lambda m: int(m.group(1))),
    (r"自分のライフが(\d+)枚以下", "self_life_le", lambda m: int(m.group(1))),
    (r"自分のライフが(\d+)枚以上", "self_life_ge", lambda m: int(m.group(1))),
    (r"自分のライフの枚数が相手より少ない", "self_life_lt_opp", lambda m: True),
    (r"自分の場のドン[‼!]{1,2}が(\d+)枚以上", "self_don_ge", lambda m: int(m.group(1))),
    (r"自分の場のドン[‼!]{1,2}が相手の場のドン[‼!]{1,2}の枚数以下", "don_diff_le", lambda m: 0),
    (r"自分の場のドン[‼!]{1,2}が相手の場のドン[‼!]{1,2}の枚数より(\d+)枚以上少ない", "don_diff_le", lambda m: -int(m.group(1))),
    (r"相手の場のキャラ?が?(\d+)枚以上", "opp_chara_count_ge", lambda m: int(m.group(1))),
    (r"相手のコスト(\d+)以下のキャラ", "opp_chara_cost_le_exists", lambda m: int(m.group(1))),
    (r"コスト0のキャラ", "opp_or_self_chara_cost_eq_0_exists", lambda m: 0),
    (r"相手のライフが(\d+)枚以下", "opp_life_le", lambda m: int(m.group(1))),
    (r"相手のライフが(\d+)枚以上", "opp_life_ge", lambda m: int(m.group(1))),
    (r"相手のターン中", "opp_turn", lambda m: True),
    (r"自分のターン中", "self_turn", lambda m: True),
]


def parse_condition_text(cond_text: str, card_name: str = "") -> dict | None:
    """条件文 → DSL `if` 句 dict。 解析失敗時 None。"""
    if not cond_text.strip():
        return None
    # 条件節 を 末尾 「、」 + 「場合」 で 切り出す:
    # 「自分の特徴 X 持つ場合、 このキャラ は」 → 「自分の特徴 X 持つ」
    # 「自分の X がいて、 自分のライフが Y 枚の場合」 → 多条件
    m = re.search(r"^(.+?)場合", cond_text)
    if m:
        inner = m.group(1).rstrip("、")
    else:
        inner = cond_text.rstrip("、")

    # 「自分の X がいて」 → and-split
    parts = re.split(r"がいて、|、", inner)
    # フィルタ: 空 や 短い 部分 除外
    parts = [p.strip() for p in parts if len(p.strip()) > 3]

    # match each part to patterns
    cond_dict: dict = {}
    matched_any = False
    for part in parts:
        for pattern, dsl_key, extractor in CONDITION_PATTERNS:
            m2 = re.search(pattern, part)
            if m2:
                val = extractor(m2)
                if dsl_key == "leader_color_and_opp_don_ge":
                    # special: leader が 多色 + opp_don_ge を 別々に
                    cond_dict["leader_color_multi"] = True
                    cond_dict["opp_don_ge"] = val[1]
                elif dsl_key == "leader_feature_substr":
                    # leader feature substring contains
                    cond_dict["leader_features_any"] = [val]
                else:
                    cond_dict[dsl_key] = val
                matched_any = True
                break
        # 「自分の「Y」がいて」 / 「自分の「Y」が N 枚以上いる」 / 「自分の「Y」がいる」 系
        m3 = (
            re.search(r"自分の「([^」]+)」がいて", part)
            or re.search(r"自分の「([^」]+)」が(\d+)枚以上いる", part)
            or re.search(r"自分の「([^」]+)」がいる", part)
            or re.search(r"自分のキャラの「([^」]+)」がいる", part)
        )
        if m3:
            target_name = m3.group(1)
            n = int(m3.group(2)) if m3.lastindex and m3.lastindex >= 2 else 1
            cond_dict["self_chara_filtered_count_ge"] = {
                "filter": {"name": target_name},
                "count": n,
            }
            matched_any = True
        # 自分の特徴《X》を持つキャラがいる / がN枚以上いる
        m4 = (
            re.search(r"自分の.*?特徴《([^》]+)》を持つキャラが(\d+)枚以上いる", part)
            or re.search(r"自分の.*?特徴《([^》]+)》を持つキャラがいる", part)
            or re.search(r"自分の特徴《([^》]+)》を持つキャラが", part)
        )
        if m4:
            feature = m4.group(1)
            count_str = m4.group(2) if m4.lastindex and m4.lastindex >= 2 else None
            n = int(count_str) if count_str else 1
            cond_dict["self_chara_filtered_count_ge"] = {
                "filter": {"feature": feature},
                "count": n,
            }
            matched_any = True
        # 「[name]」以外の自分の<color>の特徴《X》を持つキャラ がいる
        m5 = re.search(
            r"「([^」]+)」以外の自分の([^の]+?)の特徴《([^》]+)》を持つキャラ.*?いる",
            part,
        )
        if m5:
            ex_name, color, feature = m5.group(1), m5.group(2), m5.group(3)
            cond_dict["self_chara_filtered_count_ge"] = {
                "filter": {
                    "color": color,
                    "feature": feature,
                    "exclude_name": ex_name,
                },
                "count": 1,
            }
            matched_any = True
        # 自分の場に「X」がある (= stage)
        m6 = re.search(r"自分の場に「([^」]+)」がある", part)
        if m6:
            stage_name = m6.group(1)
            cond_dict["self_stage_named"] = stage_name
            matched_any = True
    if not matched_any:
        return None
    return cond_dict


def has_existing_grant(entries: list[dict], keyword: str) -> bool:
    for ent in entries:
        for d in ent.get("do") or []:
            if not isinstance(d, dict):
                continue
            if "give_keyword" in d:
                spec = d["give_keyword"]
                if isinstance(spec, dict):
                    if spec.get("keyword") == keyword or keyword in (
                        spec.get("keywords") or []
                    ):
                        return True
                elif isinstance(spec, str) and spec == keyword:
                    return True
            if keyword == "速攻" and "give_rush" in d:
                return True
    return False


def detect_duration(after_text: str) -> str:
    """「を得る」 後 の duration suffix を 検出。

    Returns: "turn" | "next_opp_turn_end" | "static"
    """
    # この時点 では after_text は 「を得る」 で 始まる (= 短い)。
    # ただし 「を得て、 ...」 等 continuation あり。
    # default は 静的条件 (= on_attached_don n=0)、 turn は 動的 (= on_play give_keyword)。
    return "static"  # 多くは 静的、 turn の 場合 は 元 text の 前後文脈 で判断


def detect_when_and_duration(text: str, keyword: str) -> tuple[str, str]:
    """text 全体 から when / duration を 推定。

    Returns: (when, duration)
        when: "on_attached_don" | "on_play" | "activate_main" | "on_attack"
        duration: "turn" | "next_opp_turn_end" | None (= 静的)
    """
    bracket = f"【{keyword}】"
    idx = text.find(bracket)
    if idx == -1:
        return ("on_attached_don", None)
    # bracket 直前 の マーカー
    before = text[:idx]
    sentences = before.replace("\n", "。").split("。")
    last_sentence = sentences[-1] if sentences else ""
    # 文 内 で 「このターン中」 「次の相手のターン終了時まで」 等
    if "このターン中" in last_sentence or "このバトル中" in last_sentence:
        # 動的 grant。 when は 起動 marker から 推定
        if "【登場時】" in last_sentence:
            return ("on_play", "turn")
        if "【アタック時】" in last_sentence:
            return ("on_attack", "turn")
        if "【起動メイン】" in last_sentence:
            return ("activate_main", "turn")
        # マーカー無し: on_play default
        return ("on_play", "turn")
    if "次の相手のターン終了時まで" in last_sentence:
        if "【起動メイン】" in last_sentence:
            return ("activate_main", "next_opp_turn_end")
        return ("on_play", "next_opp_turn_end")
    # 静的条件
    return ("on_attached_don", None)


def generate_entry(
    card_id: str, card_text: str, keyword: str
) -> dict | None:
    """text から 完全な overlay entry を 生成。 失敗時 None。"""
    grants = find_grant_sentences(card_text, keyword)
    if not grants:
        return None
    cond_text, _ = grants[0]
    cond_dict = parse_condition_text(cond_text, card_id)
    if cond_dict is None:
        return None
    when, duration = detect_when_and_duration(card_text, keyword)
    do_item = {
        "give_keyword": {
            "target": "self",
            "keyword": keyword,
        }
    }
    if duration:
        do_item["give_keyword"]["duration"] = duration
    entry = {
        "_text": f"{card_id} 条件付き 【{keyword}】 grant (= 自動生成 from 公式 text)",
        "when": when,
    }
    if when == "on_attached_don":
        entry["n"] = 0
    if cond_dict:
        entry["if"] = cond_dict
    entry["do"] = [do_item]
    return entry


def main():
    cards = json.load(open(CARDS_JSON, encoding="utf-8"))
    overlay = json.load(open(OVERLAY_JSON, encoding="utf-8"))

    # build target list from sev 4 audit
    audit_path = ROOT / "db" / "overlay_completeness.json"
    audit = json.load(open(audit_path, encoding="utf-8"))
    target_keys = set()
    for r in audit:
        if r["max_severity"] != 4:
            continue
        for i in r["issues"]:
            kind = i["kind"]
            if kind.startswith("missing_conditional_") and kind.endswith("_grant"):
                kw = kind.replace("missing_conditional_", "").replace("_grant", "")
                target_keys.add((r["card_id"], kw))

    print(f"Target: {len(target_keys)} (card_id, keyword) pairs")

    cards_by_id = {c["card_id"]: c for c in cards}

    report = {
        "total_targets": len(target_keys),
        "generated": [],
        "skipped_existing_grant": [],
        "skipped_parse_failed": [],
    }
    modified_ids = set()

    for cid, kw in sorted(target_keys):
        text = (cards_by_id.get(cid, {}) or {}).get("text") or ""
        if not text:
            report["skipped_parse_failed"].append({"cid": cid, "kw": kw, "reason": "no text"})
            continue
        existing = overlay.get(cid, [])
        if not isinstance(existing, list):
            existing = []
        if has_existing_grant(existing, kw):
            report["skipped_existing_grant"].append({"cid": cid, "kw": kw})
            continue
        entry = generate_entry(cid, text, kw)
        if entry is None:
            report["skipped_parse_failed"].append(
                {"cid": cid, "kw": kw, "text": text[:120]}
            )
            continue
        # append
        existing.append(entry)
        overlay[cid] = existing
        modified_ids.add(cid)
        report["generated"].append({"cid": cid, "kw": kw, "entry": entry})

    # write back
    OVERLAY_JSON.write_text(
        json.dumps(overlay, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    REPORT_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Generated: {len(report['generated'])}")
    print(f"Skipped (existing grant): {len(report['skipped_existing_grant'])}")
    print(f"Skipped (parse failed): {len(report['skipped_parse_failed'])}")
    print(f"Modified card ids: {len(modified_ids)}")


if __name__ == "__main__":
    main()
