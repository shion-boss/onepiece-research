#!/usr/bin/env python3
"""overlay 各 entry の cost が 抜けている / 公式テキスト と 不整合 な もの を 自動修正。

各 entry の `when` から 対応する text section を 抜き出し、
section 内 の cost 句 ("【XXX】... A できる：B") から cost dict を 再構築。

検出 する cost 句:
- 「自分のドン‼N枚をレスト」 → rest_self_don: N
- 「ドン‼-N」 → pay_don: N
- 「このキャラをレスト」 → rest_self: true
- 「このキャラをトラッシュ」 → trash_self: true
- 「自分の手札N枚を捨てる」 → discard_hand: N (filter があれば discard_hand_with_filter)
- 「【ターン1回】」 → once_per_turn: true
- 「このカードを手札に戻す」 → return_self_to_hand: true

run: .venv/bin/python scripts/fix_overlay_missing_costs.py [--dry]
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS = {c["card_id"]: c for c in json.load(open(ROOT / "db" / "cards.json"))}
OVERLAY_PATH = ROOT / "db" / "card_effects.json"
OVERLAY = json.load(open(OVERLAY_PATH))

# 【XXX】 section → when マッピング (= overlay の when と 公式テキスト の section 対応)
WHEN_TO_SECTION = {
    "activate_main": ["【起動メイン】"],
    "main": ["【メイン】"],
    "counter": ["【カウンター】"],
    "on_play": ["【登場時】"],
    "on_attack": ["【アタック時】"],
    "on_ko": ["【KO時】"],
    "on_block": ["【ブロック時】"],
    "on_turn_end": ["【ターン終了時】"],
    "opp_attack": ["【相手のアタック時】"],
    "opp_chara_played": ["【相手のキャラ登場時】"],
    "trigger": ["【トリガー】"],
    "leader_passive": [""],  # 特殊 (= 全 text)
    "main_event": ["【メイン】"],  # EVENT カード の メイン
    "counter_event": ["【カウンター】"],  # EVENT カード の カウンター
}

# 全 section header (= text 分割用)
ALL_SECTION_HEADERS = [
    "【リーダー効果】", "【起動メイン】", "【メイン】", "【カウンター】",
    "【登場時】", "【アタック時】", "【KO時】", "【ブロック時】",
    "【ターン終了時】", "【ターン開始時】", "【相手のアタック時】",
    "【相手のキャラ登場時】", "【相手のターン中】", "【トリガー】",
    "【自分のターン中】",
]

ALL_HEADER_PATTERN = re.compile(
    "(" + "|".join(re.escape(h) for h in ALL_SECTION_HEADERS) + ")"
)


def split_by_section(text: str) -> list[tuple[str, str]]:
    """text を [(header, content), ...] に 分割。 header が ない 先頭部 は ('', content) で 入れる。"""
    parts = ALL_HEADER_PATTERN.split(text)
    result: list[tuple[str, str]] = []
    if parts[0]:
        result.append(("", parts[0]))
    i = 1
    while i < len(parts):
        if i + 1 < len(parts):
            result.append((parts[i], parts[i + 1]))
            i += 2
        else:
            result.append((parts[i], ""))
            i += 1
    return result


def get_section_for_when(text: str, when: str) -> str:
    """指定 when に 対応する text section を 取得。"""
    headers = WHEN_TO_SECTION.get(when)
    if not headers:
        return ""
    sections = split_by_section(text)
    # 該当 header の最初の section を 返す
    for h, content in sections:
        if h in headers:
            return content
    return ""


def parse_cost_from_section(section: str, existing_cost: dict) -> dict:
    """section の 「...できる：」 部分 から cost を 推定。 existing_cost に merge。"""
    cost = dict(existing_cost)

    # 【ターン1回】 (= section 全体 で 検出、 once_per_turn は cost 扱い)
    if "【ターン1回】" in section:
        cost["once_per_turn"] = True

    # 「...できる：」 で 区切り、 前半 を cost 句 として 解析。
    # 注: 「できる：」 が ない 場合 は cost 句 自体 が 存在 しない (= 無条件効果) と 判断 し、
    # cost markers を 一切 抽出 しない (= once_per_turn 以外)。 過剰修正 防止。
    cost_part = None
    if "できる：" in section:
        cost_part = section.split("できる：")[0]
    elif "できる:" in section:
        cost_part = section.split("できる:")[0]
    if cost_part is None:
        return cost

    # 「ドン‼-N」 (= pay_don) → 最初の出現のみ
    m_pay = re.search(r"ドン‼\s*[-－]\s*(\d+)", cost_part)
    if m_pay:
        cost["pay_don"] = int(m_pay.group(1))

    # 「自分のドン‼N枚をレスト」 (= rest_self_don)
    m_rest_don = re.search(r"自分のドン‼\s*(\d+)\s*枚.*?(?:をレスト|、|レストにし)", cost_part)
    if m_rest_don:
        cost["rest_self_don"] = int(m_rest_don.group(1))

    # 「このキャラをレスト」 (= rest_self: true)
    if re.search(r"このキャラを(?:.*?)?レスト", cost_part):
        cost["rest_self"] = True

    # 「このキャラをトラッシュ」 (= trash_self)
    if re.search(r"このキャラを(?:.*?)?トラッシュ", cost_part):
        cost["trash_self"] = True

    # 「自分の手札N枚を捨てる」 (= discard_hand: N) — 特徴 filter は 別 path
    m_disc = re.search(r"自分の手札\s*(\d+)\s*枚を(?:.*?)?捨て", cost_part)
    if m_disc:
        # 特徴 X filter ?
        m_disc_filt = re.search(
            r"自分の手札から特徴《(.+?)》を持つカード\s*(\d+)\s*枚を(?:.*?)?捨て",
            cost_part,
        )
        if m_disc_filt:
            cost["discard_hand_with_filter"] = {
                "filter": {"feature": m_disc_filt.group(1)},
                "count": int(m_disc_filt.group(2)),
            }
        else:
            cost["discard_hand"] = int(m_disc.group(1))

    # 「このカードを手札に戻す」 (= return_self_to_hand)
    if re.search(r"このカードを手札に戻", cost_part) or re.search(
        r"この(?:キャラ|カード)を持ち主の手札", cost_part
    ):
        cost["return_self_to_hand"] = True

    return cost


def fix_overlay(dry: bool = False) -> int:
    """全 overlay を スキャン して cost を 自動補完。 修正件数 を 返す。"""
    fixed_count = 0
    diffs = []
    for cid, entries in OVERLAY.items():
        if not isinstance(entries, list):
            continue
        text = (CARDS.get(cid, {}).get("text") or "").strip()
        if not text:
            base = cid.split("_")[0]
            text = (CARDS.get(base, {}).get("text") or "").strip()
        if not text:
            continue
        for i, e in enumerate(entries):
            if not isinstance(e, dict):
                continue
            when = e.get("when", "")
            section = get_section_for_when(text, when)
            if not section:
                continue
            existing = e.get("cost") or {}
            if not isinstance(existing, dict):
                continue
            new_cost = parse_cost_from_section(section, existing)
            if new_cost != existing:
                diffs.append((cid, i, when, existing, new_cost, section[:100]))
                if not dry:
                    e["cost"] = new_cost
                fixed_count += 1

    if not dry:
        with open(OVERLAY_PATH, "w", encoding="utf-8") as f:
            json.dump(OVERLAY, f, ensure_ascii=False, indent=2)

    print(f"\n=== {'Dry run' if dry else 'Applied'} ===")
    print(f"Modified entries: {fixed_count}")
    for cid, i, when, old, new, section in diffs[:20]:
        print(f"\n{cid} [{when}] entry[{i}]:")
        print(f"  OLD: {old}")
        print(f"  NEW: {new}")
        print(f"  section: {section}...")
    if len(diffs) > 20:
        print(f"\n... ({len(diffs) - 20} more)")
    return fixed_count


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    raise SystemExit(0 if fix_overlay(dry) == 0 else 0)
