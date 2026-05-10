# -*- coding: utf-8 -*-
"""
overlay 書き直し対象カードを優先度順に出力。

優先度:
  1. cardrush メタデッキに採用されているか (= 影響度大)
  2. 公式テキストの長さ (= 複雑度)
  3. 現 overlay が simplification marker を含むか

出力:
  db/overlay_rewrite_targets.md (Markdown レポート、 上位 N 件)
  db/overlay_rewrite_targets.json (機械向け、 全件)
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS_JSON = ROOT / "db" / "cards.json"
OVERLAY_JSON = ROOT / "db" / "card_effects.json"
DECKS_DIR = ROOT / "decks"
OUT_MD = ROOT / "db" / "overlay_rewrite_targets.md"
OUT_JSON = ROOT / "db" / "overlay_rewrite_targets.json"

SIMPLIFIED_MARKERS = ("fallback", "簡略", "auto", "省略", "近似", "自動抽出")


def is_simplified(eff: dict) -> bool:
    text = eff.get("_text", "") or ""
    return any(m in text for m in SIMPLIFIED_MARKERS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=200)
    args = ap.parse_args()

    cards = json.loads(CARDS_JSON.read_text(encoding="utf-8"))
    by_id = {c["card_id"]: c for c in cards}
    overlay = json.loads(OVERLAY_JSON.read_text(encoding="utf-8"))

    # cardrush メタデッキの採用カードを集計
    meta_card_count: Counter = Counter()
    meta_leaders: set[str] = set()
    for f in DECKS_DIR.glob("cardrush_*.json"):
        if f.name.endswith(".analysis.json"):
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if d.get("leader"):
                meta_leaders.add(d["leader"])
                meta_card_count[d["leader"]] += 1
            for entry in d.get("main", []):
                cid = entry.get("card_id")
                if cid:
                    meta_card_count[cid] += 1
        except Exception:
            continue

    # 各 card の修正対象判定
    rows: list[dict] = []
    for cid, card in by_id.items():
        text = (card.get("text") or "").strip()
        if not text or text == "-":
            continue
        current = overlay.get(cid, [])
        if not isinstance(current, list):
            continue
        # 簡略化フラグ
        has_simplified = any(is_simplified(e) for e in current)
        # メタリーダーは既に手書き品質高いはずなので除外
        is_meta_leader = cid in meta_leaders
        # 完全 vanilla (= 効果なし) で公式テキスト持ちは「未実装」 扱い
        is_unimplemented = len(current) == 0

        if not has_simplified and not is_unimplemented:
            continue
        if is_meta_leader:
            continue  # 手書き済 (cardrush_*.json リーダー)

        meta_uses = meta_card_count.get(cid, 0)
        # priority score: meta 採用が最重要、 次に長さ、 最後に実装状況
        priority = (
            meta_uses * 100
            + min(len(text), 300) // 10
            + (5 if is_unimplemented else 0)
        )
        rows.append({
            "card_id": cid,
            "name": card.get("name", ""),
            "category": card.get("category", ""),
            "cost": card.get("cost"),
            "power": card.get("power"),
            "color": card.get("color", []),
            "features": card.get("features", []),
            "text": text,
            "current_effects_count": len(current),
            "is_simplified": has_simplified,
            "is_unimplemented": is_unimplemented,
            "meta_uses": meta_uses,
            "priority": priority,
        })

    rows.sort(key=lambda r: -r["priority"])

    OUT_JSON.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 統計
    total = len(rows)
    in_meta = sum(1 for r in rows if r["meta_uses"] > 0)
    leaders = sum(1 for r in rows if r["category"] == "LEADER")

    out = OUT_MD.open("w", encoding="utf-8")
    out.write("# Overlay 書き直し対象カード (優先度順)\n\n")
    out.write(f"- 対象カード総数: {total}\n")
    out.write(f"  - メタ採用: {in_meta}\n")
    out.write(f"  - リーダー: {leaders}\n")
    out.write(f"- 除外: メタリーダー {len(meta_leaders)} 枚 (手書き品質高)\n\n")
    out.write(f"## 上位 {args.top} 件 (優先度 = メタ採用×100 + テキスト長 + 未実装ボーナス)\n\n")
    out.write("| # | card_id | name | cat | meta | 簡略 | 未実装 | text |\n")
    out.write("|---|---|---|---|---|---|---|---|\n")
    for i, r in enumerate(rows[: args.top]):
        out.write(
            f"| {i+1} | `{r['card_id']}` | {r['name']} | {r['category'][:3]} | "
            f"{r['meta_uses']} | {'○' if r['is_simplified'] else ''} | "
            f"{'○' if r['is_unimplemented'] else ''} | "
            f"{r['text'][:80]} |\n"
        )
    out.close()
    print(f"対象: {total} 件 (メタ採用 {in_meta}, リーダー {leaders})")
    print(f"→ {OUT_MD}")
    print(f"→ {OUT_JSON}")


if __name__ == "__main__":
    main()
