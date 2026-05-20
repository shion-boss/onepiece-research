#!/usr/bin/env python3
"""overlay 不足 ko / return_to_hand / rest を 公式テキスト から 自動生成。

Run: .venv/bin/python scripts/fix_overlay_missing_targets.py [--dry]
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


WHEN_TO_SECTION = {
    "activate_main": "【起動メイン】",
    "main": "【メイン】",
    "counter": "【カウンター】",
    "on_play": "【登場時】",
    "on_attack": "【アタック時】",
    "on_ko": "【KO時】",
    "on_block": "【ブロック時】",
    "on_turn_end": "【ターン終了時】",
    "opp_attack": "【相手のアタック時】",
    "trigger": "【トリガー】",
}


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


def parse_ko_filter(section: str) -> dict | None:
    """section から KO 対象 filter を 抽出。 「相手の (cost N 以下) (パワー M 以下) キャラ 1 枚 を KO」 等。"""
    if not re.search(r"相手の.*?キャラ.*?(?:KO|ＫＯ)する", section):
        return None
    filt = {}
    m = re.search(r"コスト\s*(\d+)\s*以下", section)
    if m:
        filt["cost_le"] = int(m.group(1))
    m = re.search(r"パワー\s*(\d+)\s*以下", section)
    if m:
        filt["truly_original_power_le"] = int(m.group(1))
    # 「元々のパワー X 以下」
    m = re.search(r"元々のパワー\s*(\d+)\s*以下", section)
    if m:
        filt["truly_original_power_le"] = int(m.group(1))
    return filt


def parse_return_filter(section: str, kind: str = "opp") -> dict | None:
    """section から return_to_hand 対象 filter を 抽出。 「(相手の)? (cost N 以下) キャラ 1 枚を 持ち主の手札に戻す」 等。"""
    if not re.search(r"キャラ.*?持ち主の手札に戻す", section):
        return None
    filt = {}
    m = re.search(r"コスト\s*(\d+)\s*以下", section)
    if m:
        filt["cost_le"] = int(m.group(1))
    m = re.search(r"パワー\s*(\d+)\s*以下", section)
    if m:
        filt["truly_original_power_le"] = int(m.group(1))
    return filt


def has_ko_in_do(entry: dict) -> bool:
    for op in entry.get("do") or []:
        if isinstance(op, dict) and ("ko" in op or "ko_multi" in op):
            return True
    return False


def has_return_to_hand_in_do(entry: dict) -> bool:
    for op in entry.get("do") or []:
        if isinstance(op, dict) and ("return_to_hand" in op or "return_to_hand_multi" in op):
            return True
    return False


def fix_missing_ko_return(dry: bool = False) -> int:
    """audit 結果 を 元 に 該当 entry に ko / return_to_hand を 追加。"""
    issues = json.load(open(ROOT / "db" / "effect_text_vs_overlay_audit.json"))
    fixed = 0
    for iss in issues:
        kind = iss.get("kind")
        cid = iss["card_id"]
        if cid not in OVERLAY:
            continue
        text = (CARDS.get(cid, {}).get("text") or "").strip()
        if not text:
            base = cid.split("_")[0]
            text = (CARDS.get(base, {}).get("text") or "").strip()
        if not text:
            continue
        sections = split_by_section(text)
        if kind == "missing_ko":
            # 該当 section を 検索 (= 「KO する」 を 含む section)
            for header, content in sections:
                if not re.search(r"相手の.*?キャラ.*?(?:KO|ＫＯ)する", content):
                    continue
                filt = parse_ko_filter(content)
                if filt is None:
                    continue
                # which when?
                when = next(
                    (w for w, h in WHEN_TO_SECTION.items() if h == header), None
                )
                if when is None:
                    continue
                # 既 entry が ある か
                existing = next(
                    (e for e in OVERLAY[cid] if isinstance(e, dict) and e.get("when") == when),
                    None,
                )
                if existing is None:
                    # 新規 entry 追加
                    new_e = {
                        "_text": f"{header}相手キャラ KO (filter={filt})",
                        "when": when,
                        "do": [{"ko": {"type": "one_opponent_character_filtered", "filter": filt}}],
                    }
                    OVERLAY[cid].append(new_e)
                    fixed += 1
                    print(f'  {cid} [{when}]: added ko {filt}')
                elif not has_ko_in_do(existing):
                    # 既存 entry に ko 追加
                    existing.setdefault("do", []).append(
                        {"ko": {"type": "one_opponent_character_filtered", "filter": filt}}
                    )
                    fixed += 1
                    print(f'  {cid} [{when}]: appended ko {filt}')
                break  # 1 issue per card で 十分
        elif kind == "missing_return_to_hand":
            for header, content in sections:
                if not re.search(r"キャラ.*?持ち主の手札に戻す", content):
                    continue
                filt = parse_return_filter(content)
                if filt is None:
                    continue
                when = next(
                    (w for w, h in WHEN_TO_SECTION.items() if h == header), None
                )
                if when is None:
                    continue
                existing = next(
                    (e for e in OVERLAY[cid] if isinstance(e, dict) and e.get("when") == when),
                    None,
                )
                # 相手 / 自 区別 - 「相手の」 が 文脈 で あるか
                is_opp_target = "相手の" in content
                target_type = "one_opponent_character_filtered" if is_opp_target else "one_self_chara_filtered"
                if existing is None:
                    new_e = {
                        "_text": f"{header}{'相手' if is_opp_target else '自'}キャラ 手札戻し (filter={filt})",
                        "when": when,
                        "do": [{"return_to_hand": {"type": target_type, "filter": filt}}],
                    }
                    OVERLAY[cid].append(new_e)
                    fixed += 1
                    print(f'  {cid} [{when}]: added return_to_hand ({"opp" if is_opp_target else "self"}) {filt}')
                elif not has_return_to_hand_in_do(existing):
                    existing.setdefault("do", []).append(
                        {"return_to_hand": {"type": target_type, "filter": filt}}
                    )
                    fixed += 1
                    print(f'  {cid} [{when}]: appended return_to_hand ({"opp" if is_opp_target else "self"}) {filt}')
                break

    if not dry:
        with open(OVERLAY_PATH, "w", encoding="utf-8") as f:
            json.dump(OVERLAY, f, ensure_ascii=False, indent=2)
    print(f"\n{'Dry' if dry else 'Applied'}: {fixed} fixes")
    return fixed


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    raise SystemExit(0 if fix_missing_ko_return(dry) == 0 else 0)
