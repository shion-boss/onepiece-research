# -*- coding: utf-8 -*-
"""
suggestions.json から高優先度候補を選んで card_effects.json にマージする。

スコア:
- 色が red/blue/green に含まれる: +1
- cost <= 5: +1 (auto_build_deck の curve_target に乗る)
- power >= 4000: +1 (auto_build が高パワー優先)
- 単一 primitive (do の長さ 1): +1 (誤抽出リスク低)
- counter > 0: +1 (デッキの汎用カウンタ枠に入りやすい)

実行:
    .venv/bin/python scripts/merge_overlay_suggestions.py --top 50 --apply
    .venv/bin/python scripts/merge_overlay_suggestions.py --top 80 --dry-run
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS_JSON = ROOT / "db" / "cards.json"
SUGGESTIONS_JSON = ROOT / "db" / "card_effects.suggestions.json"
OVERLAY_JSON = ROOT / "db" / "card_effects.json"

TARGET_COLORS = {"赤", "青", "緑"}


def num(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def score_card(card: dict, entries: list[dict]) -> int:
    s = 0
    colors = set(card.get("color", []))
    if colors & TARGET_COLORS:
        s += 1
    if num(card.get("cost"), 99) <= 5:
        s += 1
    if num(card.get("power"), 0) >= 4000:
        s += 1
    if all(len(e.get("do", [])) == 1 for e in entries):
        s += 1
    if num(card.get("counter"), 0) > 0:
        s += 1
    return s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=50, help="上位 N 件を選択")
    ap.add_argument("--apply", action="store_true", help="実際に card_effects.json に書き戻す")
    ap.add_argument("--dry-run", action="store_true", help="--apply 無効化")
    args = ap.parse_args()
    apply = args.apply and not args.dry_run

    cards = json.loads(CARDS_JSON.read_text(encoding="utf-8"))
    by_id: dict[str, dict] = {}
    for c in cards:
        cid = c.get("card_id", "")
        base = cid.split("_", 1)[0]
        # variant が空のものを優先 (素のカード)
        if base not in by_id or not c.get("variant", ""):
            by_id[base] = c

    suggestions = json.loads(SUGGESTIONS_JSON.read_text(encoding="utf-8"))
    overlay = json.loads(OVERLAY_JSON.read_text(encoding="utf-8"))

    # スコア計算
    scored: list[tuple[int, str, list[dict]]] = []
    for cid, entries in suggestions.items():
        if cid.startswith("_"):
            continue
        if cid in overlay:
            continue
        card = by_id.get(cid)
        if card is None:
            continue
        s = score_card(card, entries)
        scored.append((s, cid, entries))

    # 高スコア順 → カード ID 昇順
    scored.sort(key=lambda x: (-x[0], x[1]))
    top = scored[: args.top]

    print(f"全候補: {len(scored)}, 上位 {len(top)} 件をマージ予定")
    print()
    print("=== 採用候補 (上位) ===")
    for s, cid, entries in top[:20]:
        card = by_id.get(cid, {})
        wens = ",".join(e["when"] for e in entries)
        print(f"  score={s} {cid}  cost{card.get('cost'):>2}  P{card.get('power'):>5}  {card.get('color')}  {card.get('name')}")
        print(f"           when={wens}")

    if not apply:
        print()
        print("(--apply を付けるまでは書き戻し無し)")
        return 0

    # マージ
    for s, cid, entries in top:
        overlay[cid] = entries
    OVERLAY_JSON.write_text(
        json.dumps(overlay, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print()
    print(f"✓ {len(top)} 件を card_effects.json にマージしました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
