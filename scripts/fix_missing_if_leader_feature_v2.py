#!/usr/bin/env python3
"""fix_missing_if_conditions.py が拾えなかった 25 件 を 公式テキスト 直接 parse で 補完。

問題: v1 は entry._text に 条件節があると 想定したが、
overlay の _text は 「サンジ ターン終了時 (FILM/麦わら): ドン2活性化」 等 略式 で
「自分のリーダーが特徴《X》を持つ場合」 自体 含んでない ケースが 多い。

→ 公式 text 全文 から:
  1. 【...時】 ヘッダ単位 で text segment 分割
  2. 各 segment 内 で 「自分のリーダーが特徴《X》(か《Y》)?を持つ場合」 検出
  3. 該当 segment の when を 推定 (= 【登場時】 → on_play 等)
  4. overlay の 同 when entry に if を マージ
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


HEADER_WHEN_MAP = {
    "【登場時】": "on_play",
    "【自分のターン終了時】": "end_of_turn",
    "【ターン終了時】": "end_of_turn",
    "【自分のターン開始時】": "start_of_turn",
    "【ターン開始時】": "start_of_turn",
    "【アタック時】": "on_attack",
    "【相手のアタック時】": "opp_attack",
    "【ブロック時】": "on_block",
    "【KO時】": "on_self_chara_ko",
    "【起動メイン】": "activate_main",
    "【メイン】": "main",
    "【カウンター】": "counter",
    "【トリガー】": "trigger",
}


def get_text(cid: str) -> str:
    text = (CARDS.get(cid, {}).get("text") or "").strip()
    if not text:
        base = cid.split("_")[0]
        text = (CARDS.get(base, {}).get("text") or "").strip()
    return text


def split_by_headers(text: str) -> list[tuple[str, str]]:
    """text を 【...時】ヘッダ で 分割。 [(header_or_'', segment_text), ...] を 返す。"""
    # 先頭以外で 【...】 が ある場所 を 区切る
    headers = list(HEADER_WHEN_MAP.keys())
    pattern = "|".join(re.escape(h) for h in headers)
    parts = re.split(f"({pattern})", text)
    result = []
    cur_header = ""
    for p in parts:
        if p in HEADER_WHEN_MAP:
            cur_header = p
        else:
            if p.strip():
                result.append((cur_header, p))
    return result


def parse_leader_feature_clause(segment: str) -> dict | None:
    """segment 内 で 「自分のリーダーが特徴《X》(か《Y》)?を持つ場合」 → if dict 返す。"""
    m = re.search(r"自分のリーダーが特徴《(.+?)》(?:か《(.+?)》)?を持つ場合", segment)
    if not m:
        return None
    f1, f2 = m.group(1), m.group(2)
    if f2:
        return {"leader_features_any": [f1, f2]}
    return {"leader_feature": f1}


def main():
    fixed = 0
    log = []
    for cid, entries in OVERLAY.items():
        if cid.startswith("_") or not isinstance(entries, list) or not entries:
            continue
        text = get_text(cid)
        if not text:
            continue
        # 既に leader_feature 系 が flat に あるかチェック
        flat = json.dumps(entries, ensure_ascii=False)
        # text 分割 → 各 segment で leader_feature 条件 抽出
        segments = split_by_headers(text)
        for header, seg in segments:
            cond = parse_leader_feature_clause(seg)
            if not cond:
                continue
            target_when = HEADER_WHEN_MAP.get(header)
            # text 全体 通して 既に この feature が if に あれば skip
            f_check = cond.get("leader_feature") or (cond.get("leader_features_any") or [""])[0]
            if f_check and f'"{f_check}"' in flat:
                # 同じ feature 別 entry に 既に紐付けされてる
                # でも 今 segment の when 別 entry に も 必要 → 続行 (= 厳密 check)
                pass
            # 該当 entry 探す
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                ew = entry.get("when")
                # when 一致 or (target_when=None で header なし → header なしの effect は static、 通常 on_attached_don)
                if target_when and ew != target_when:
                    continue
                if not target_when:
                    # header なし = 先頭文 / 末尾文。 static buff 的なので on_attached_don / leader_passive entry
                    if ew not in ("on_attached_don", "leader_passive", "setup_modifier"):
                        continue
                # 既に entry.if に この key あるか
                existing = entry.get("if") or {}
                if isinstance(existing, dict):
                    if "leader_feature" in existing and "leader_feature" in cond:
                        if existing["leader_feature"] == cond["leader_feature"]:
                            continue
                    if "leader_features_any" in existing and "leader_features_any" in cond:
                        if sorted(existing["leader_features_any"]) == sorted(cond["leader_features_any"]):
                            continue
                # マージ
                if isinstance(existing, dict):
                    existing.update(cond)
                    entry["if"] = existing
                else:
                    entry["if"] = dict(cond)
                log.append(f"  {cid} [{ew}]: if += {cond}")
                fixed += 1
                break  # 同 when 1 entry のみ

    print(f"Fixed {fixed} entries")
    (ROOT / "db" / "card_effects.json").write_text(
        json.dumps(OVERLAY, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "db" / "fix_missing_if_leader_feature_v2_log.md").write_text(
        "# missing_if_leader_feature v2 補完ログ\n\n" + "\n".join(log), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
