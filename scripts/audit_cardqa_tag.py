#!/usr/bin/env python3
"""Phase 3 cardqa oracle prototype: tag-based classifier (= 2026-05-28、
docs/AUTO_AUDIT_SYSTEM.md Layer 3、 prototype = 1/3 of phase)。

db/faq/cardqa_*.json (= 公式 Q&A、 50 series × ~50-70 件) を 構造化 tag。
output: db/cardqa_tagged.json (= 全 series 統合 + 自動 tag 付け + oracle 候補 抽出)。

これ を Phase 4 後段 で assertion DSL に 落として overlay/engine と 突合 検証 する。

## 使い方

```bash
.venv/bin/python scripts/audit_cardqa_tag.py
.venv/bin/python scripts/audit_cardqa_tag.py --series eb_01  # 特定 series のみ
```

## tag 一覧

- `optional`           : 「ことができる」 「もよい」 = 任意 効果 言及
- `mandatory`          : 「必ず」 「強制」 = 強制 効果 言及
- `timing`             : 【XX時】 言及
- `target_range`       : 「コスト N 以下」 「パワー N 以下」 「N 枚 まで」 等 範囲 制限
- `answer_yes`         : a が 「はい」 で 始まる
- `answer_no`          : a が 「いいえ」 で 始まる
- `card_reference`     : Q に カード名 (= 「」 で 括られた 名前) 含む
- `effect_category`    : 効果 種別 (KO / draw / power / cost / search 等)

## oracle 候補 例

```json
{
  "q": "ヴェルゴの効果は使わないこともできますか？",
  "a": "はい、任意効果です。",
  "tags": ["optional", "answer_yes"],
  "derived_oracle": {
    "field": "overlay.optional",
    "expected": true,
    "card_hint": "ヴェルゴ"
  }
}
```
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CARDQA_DIR = REPO_ROOT / "db" / "faq"
OUT_PATH = REPO_ROOT / "db" / "cardqa_tagged.json"


# tag 検出 patterns
TIMING_PATTERNS = [
    "【登場時】", "【アタック時】", "【起動メイン】", "【KO時】",
    "【ターン終了時】", "【ブロック時】", "【相手のアタック時】",
    "【トリガー】", "【カウンター】",
    "登場時", "アタック時", "KO時", "ブロック時",
]
OPTIONAL_TOKENS = ("もよい", "ことができる", "ことができます", "してもよい")
MANDATORY_TOKENS = ("必ず", "強制的に", "必須")
EFFECT_CATEGORIES = {
    "ko": ("KO", "ＫＯ"),
    "draw": ("カードを引く", "引く"),
    "power": ("パワー", "ﾊﾟﾜｰ"),
    "cost": ("コスト",),
    "search": ("サーチ", "デッキの上から"),
    "rest": ("レスト", "アクティブ"),
    "life": ("ライフ",),
    "don": ("ドン",),
    "hand": ("手札",),
    "block": ("ブロッカー", "ブロック"),
}


def _tag_item(q: str, a: str) -> dict:
    tags = []
    derived = {}

    # answer polarity
    a_stripped = a.strip()
    if a_stripped.startswith(("はい", "yes", "Yes", "イエス")):
        tags.append("answer_yes")
    elif a_stripped.startswith(("いいえ", "no", "No")):
        tags.append("answer_no")

    # optional / mandatory mention in Q
    if any(t in q for t in OPTIONAL_TOKENS):
        tags.append("optional_mention")
    if any(t in q for t in MANDATORY_TOKENS):
        tags.append("mandatory_mention")

    # timing
    for tp in TIMING_PATTERNS:
        if tp in q:
            tags.append(f"timing:{tp.strip('【】')}")
            break

    # target range
    if re.search(r"コスト\s*\d+\s*以(上|下)", q):
        tags.append("target_cost_range")
    if re.search(r"パワー\s*\d+\s*以(上|下)", q):
        tags.append("target_power_range")
    if re.search(r"\d+\s*枚\s*まで", q):
        tags.append("target_count_limit")

    # card reference (= 「カード名」 in 「」)
    card_refs = re.findall(r"「([^」]+)」", q)
    if card_refs:
        tags.append("card_reference")
        derived["card_refs"] = card_refs

    # effect category
    cats = []
    for cat, kws in EFFECT_CATEGORIES.items():
        if any(kw in q or kw in a for kw in kws):
            cats.append(cat)
    if cats:
        tags.append("effect:" + "/".join(cats))

    # derived oracle: optional+answer_yes はとても有用 signal
    if "optional_mention" in tags and "answer_yes" in tags:
        derived["likely_oracle"] = "optional=true (= 「使わなくても よい」 系)"
    if "optional_mention" in tags and "answer_no" in tags:
        derived["likely_oracle"] = "optional=false (= 「使わない選択 不可」 系)"

    return {"tags": tags, "derived": derived}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", default=None, help="特定 series_slug のみ")
    args = ap.parse_args()

    all_items: list[dict] = []
    files = sorted(CARDQA_DIR.glob("cardqa_*.json"))
    if args.series:
        files = [f for f in files if args.series in f.name]
    print(f"processing {len(files)} files")

    total_items = 0
    series_stats = defaultdict(int)
    tag_counter = Counter()

    for fpath in files:
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  ERROR loading {fpath.name}: {e}")
            continue
        series_slug = data.get("series_slug", fpath.stem)
        items = data.get("items", [])
        for item in items:
            q = item.get("q", "")
            a = item.get("a", "")
            if not q or not a:
                continue
            tag_info = _tag_item(q, a)
            all_items.append({
                "series": series_slug,
                "q": q,
                "a": a,
                "tags": tag_info["tags"],
                "derived": tag_info["derived"],
            })
            total_items += 1
            series_stats[series_slug] += 1
            for t in tag_info["tags"]:
                tag_counter[t] += 1

    # 出力
    out = {
        "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "stats": {
            "total_items": total_items,
            "files_processed": len(files),
            "tag_counts": dict(tag_counter.most_common()),
            "series_counts": dict(series_stats),
        },
        "items": all_items,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"total items tagged: {total_items}")
    print(f"output: {OUT_PATH.relative_to(REPO_ROOT)}")
    print()
    print("top tags:")
    for t, c in tag_counter.most_common(20):
        print(f"  {t}: {c}")

    # oracle 候補 抽出: optional 系
    oracle_candidates = [
        i for i in all_items if "likely_oracle" in i["derived"]
    ]
    print()
    print(f"oracle 候補 (likely_oracle 付き): {len(oracle_candidates)}")
    for c in oracle_candidates[:5]:
        print(f"  Q: {c['q'][:80]}...")
        print(f"    derived: {c['derived']}")


if __name__ == "__main__":
    main()
