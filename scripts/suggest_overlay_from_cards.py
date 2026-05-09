# -*- coding: utf-8 -*-
"""
カードのテキスト/トリガー欄から effect overlay 候補を半自動生成。

- cards.json + 必要なら cardqa の Q&A を読む
- ルール:
  * トリガー検出: 【登場時】【KO時】【自分のターン終了時】【トリガー】【アタック時】【起動メイン】
  * 効果検出: 「カードN枚を引く」「コストN以下のキャラ1枚をKO」「パワー+N」「ライフ1枚を手札に」
- 既に `db/card_effects.json` にあるカードはスキップ
- 出力: `db/card_effects.suggestions.json`
- 人が目視で確認して `card_effects.json` にマージする運用

実行:
    .venv/bin/python scripts/suggest_overlay_from_cards.py
    .venv/bin/python scripts/suggest_overlay_from_cards.py --limit 200
    .venv/bin/python scripts/suggest_overlay_from_cards.py --colors 赤 青   # 色指定
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS_JSON = ROOT / "db" / "cards.json"
OVERLAY_JSON = ROOT / "db" / "card_effects.json"
OUT_PATH = ROOT / "db" / "card_effects.suggestions.json"


# トリガー: テキスト中の【...】タグを when にマップ
TRIGGER_MAP = {
    "登場時": "on_play",
    "KO時": "on_ko",
    "自分のターン終了時": "end_of_turn",
    "相手のターン終了時": "opp_end_of_turn",
    "アタック時": "on_attack",
    "起動メイン": "activate_main",
}


def extract_triggers(text: str) -> list[str]:
    """テキスト中の【XXX】を全部見つけて、TRIGGER_MAP にあるものだけ返す。"""
    found = []
    for m in re.finditer(r"【(.+?)】", text):
        kw = m.group(1)
        if kw in TRIGGER_MAP:
            found.append(TRIGGER_MAP[kw])
    return found


# 効果: 段階的にパターン match して primitive を抽出
DRAW_RE = re.compile(r"カード\s*(\d+)\s*枚(?:まで)?を引く")
# KO: 「N 枚まで」「すべて」を区別 (デフォルトは 1 枚まで = one_*)
KO_RE = re.compile(
    r"(?:コスト|パワー)?\s*(?P<n>[0-9０-９]+)\s*(?:以下|未満)?\s*の(?:キャラ|相手のキャラ)"
    r"(?P<count>\s*\d*\s*枚(?:まで)?|すべて)?\s*.*?を、?\s*KOする"
)
POWER_PUMP_RE = re.compile(r"パワー\s*([+\-＋−]?\s*\d+)\s*(?:を得る|になる)?")
LIFE_TO_HAND_RE = re.compile(r"ライフ\s*(\d+)\s*枚(?:まで)?を、?\s*手札")
SEARCH_RE = re.compile(r"デッキの上から\s*(\d+)\s*枚を見")
RETURN_RE = re.compile(
    r"(?:相手の)?(?:キャラ|レスト).*?(?P<count>\s*\d*\s*枚(?:まで)?|すべて)?\s*"
    r"を、?\s*持ち主の手札に戻す"
)
REST_RE = re.compile(
    r"(?:相手の)?キャラ\s*(?P<count>\d*)\s*枚(?:まで)?を、?\s*レストにする"
)
ADD_DON_RE = re.compile(r"自分のドン[!！]{1,2}\s*(\d+)\s*枚(?:まで)?を、?\s*アクティブにする")


def _is_all_target(count_text: str | None) -> bool:
    """「すべて」を含むなら全体対象、そうでなければ単体対象 (1 枚まで)。"""
    return bool(count_text and "すべて" in count_text)


def normalize_int(s: str) -> int:
    s = s.strip().translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    s = s.replace("＋", "+").replace("−", "-").replace("ー", "-")
    return int(s)


def extract_primitives(text: str) -> list[dict]:
    """テキストから DSL primitive を生成 (簡略化)。

    対象セレクタはデフォルトで `one_*` (1 枚まで) を使用。
    テキストに「すべて」や「全員」が含まれる場合のみ全体対象 (any_*)。
    """
    primitives: list[dict] = []
    if m := DRAW_RE.search(text):
        primitives.append({"draw": int(m.group(1))})
    if m := LIFE_TO_HAND_RE.search(text):
        primitives.append({"life_to_hand": int(m.group(1))})
    if m := ADD_DON_RE.search(text):
        primitives.append({"add_don": int(m.group(1))})
    if m := KO_RE.search(text):
        target = (
            "any_opponent_character_le_5000"
            if _is_all_target(m.groupdict().get("count"))
            else "one_opponent_character_le_5000"
        )
        primitives.append({"ko": target})
    if m := RETURN_RE.search(text):
        target = (
            "any_opponent_character_le_5000"
            if _is_all_target(m.groupdict().get("count"))
            else "one_opponent_character_le_5000"
        )
        primitives.append({"return_to_hand": target})
    if m := REST_RE.search(text):
        # rest は「すべて」が稀なので one_* デフォルト
        primitives.append({"rest": "one_opponent_character_le_5000"})
    # power_pump: target/sign の自動決定が信頼できないため auto-extract から除外。
    # 手書きで丁寧に追加する運用とする。
    if m := SEARCH_RE.search(text):
        # 細かい filter は手動調整に任せる。ここでは category=CHARACTER のみ
        primitives.append({
            "search": {
                "filter": {"category": "CHARACTER"},
                "limit": 1,
            },
        })
    return primitives


def split_by_trigger(text: str) -> dict[str, str]:
    """テキストを【トリガー】単位に分割し、{when: text部分} を返す。"""
    # 【XXX】で区切る簡易パーサ
    parts: dict[str, str] = {}
    matches = list(re.finditer(r"【(.+?)】", text))
    if not matches:
        return parts
    for i, m in enumerate(matches):
        kw = m.group(1)
        when = TRIGGER_MAP.get(kw)
        if when is None:
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section = text[start:end]
        # 既存に追記 (1 つのカードに同じトリガーが複数ある場合)
        parts[when] = parts.get(when, "") + section
    return parts


def suggest_card(card: dict) -> list[dict] | None:
    """1 枚のカードから effect entries を生成。何も得られなければ None。"""
    text = (card.get("text") or "").strip()
    trigger_text = (card.get("trigger") or "").strip()

    entries: list[dict] = []

    # text の【...】区切りで効果抽出
    if text and text != "-":
        sections = split_by_trigger(text)
        for when, section in sections.items():
            primitives = extract_primitives(section)
            if not primitives:
                continue
            entries.append({
                "_text": f"自動抽出: {section[:80]}",
                "when": when,
                "do": primitives,
            })

    # trigger 欄が独立にある場合 (when=trigger)
    if trigger_text and trigger_text != "-" and trigger_text.startswith("【トリガー】"):
        body = trigger_text[len("【トリガー】"):]
        primitives = extract_primitives(body)
        if primitives:
            entries.append({
                "_text": f"自動抽出 (トリガー): {body[:80]}",
                "when": "trigger",
                "do": primitives,
            })

    return entries or None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="先頭 N 枚で打ち切り")
    ap.add_argument("--colors", nargs="+", default=None, help="色フィルタ (例: 赤 青)")
    ap.add_argument(
        "--include-existing",
        action="store_true",
        help="既に overlay にあるカードも含める (上書きチェック用)",
    )
    args = ap.parse_args()

    cards = json.loads(CARDS_JSON.read_text(encoding="utf-8"))
    overlay = json.loads(OVERLAY_JSON.read_text(encoding="utf-8")) if OVERLAY_JSON.exists() else {}
    existing = {k for k in overlay if not k.startswith("_")}

    color_filter = set(args.colors) if args.colors else None

    suggestions: dict[str, list[dict]] = {}
    skipped_existing = 0
    skipped_no_text = 0
    seen_base: set[str] = set()

    for card in cards:
        cid = card.get("card_id", "")
        base = cid.split("_", 1)[0]
        if base in seen_base:
            continue
        seen_base.add(base)

        if not args.include_existing and base in existing:
            skipped_existing += 1
            continue

        if color_filter and not (set(card.get("color", [])) & color_filter):
            continue

        text = (card.get("text") or "").strip()
        trig = (card.get("trigger") or "").strip()
        if (not text or text == "-") and (not trig or trig == "-"):
            skipped_no_text += 1
            continue

        entries = suggest_card(card)
        if not entries:
            continue

        suggestions[base] = entries
        if args.limit and len(suggestions) >= args.limit:
            break

    out = {
        "_meta": {
            "description": "Auto-generated overlay suggestions. Review and merge to card_effects.json manually.",
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "skipped_existing": skipped_existing,
            "skipped_no_text": skipped_no_text,
            "suggestions_count": len(suggestions),
        },
        **suggestions,
    }
    OUT_PATH.write_text(
        json.dumps(out, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  生成された候補: {len(suggestions)}")
    print(f"  既存 overlay でスキップ: {skipped_existing}")
    print(f"  text/trigger 無しでスキップ: {skipped_no_text}")
    print(f"→ {OUT_PATH}")

    # 上位カードのプレビュー
    print()
    print("=== サンプル (先頭 5 件) ===")
    for cid in list(suggestions.keys())[:5]:
        print(f"  [{cid}]:")
        for e in suggestions[cid]:
            print(f"    when={e['when']:18} do={e['do']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
