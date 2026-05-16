#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 2 集約: 16 deck の fine-tune 結果 を 4 archetype に集約。

1. 各 archetype の deck 群で重みを平均 → ai_params_archetypes/<archetype>.json
2. 各 deck の offset = deck 重み - archetype 平均 → ai_params_decks/<slug>.json (上書き)

これにより eval.py の lookup chain (= deck offset → archetype base → global base)
が完全に hierarchical で動作する。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# 16 deck の archetype 分類 (= 学習結果と OPTCG 一般知識から)
ARCHETYPE_MAP = {
    "aggro": ["cardrush_1399", "tcgportal_op11_luffy"],
    "midrange": [
        "cardrush_1385", "cardrush_1453", "cardrush_1454", "cardrush_1456",
        "tcgportal_bonney", "tcgportal_calgara", "tcgportal_op13_luffy",
    ],
    "control": ["cardrush_1342", "cardrush_1455", "tcgportal_hancock"],
    "trash": ["cardrush_1392", "cardrush_1439", "tcgportal_coby", "tcgportal_corazon"],
}


def load_deck_params(slug: str) -> dict:
    p = ROOT / "db" / "ai_params_decks" / f"{slug}.json"
    return json.loads(p.read_text(encoding="utf-8"))["params"]


def main() -> None:
    archetypes_dir = ROOT / "db" / "ai_params_archetypes"
    archetypes_dir.mkdir(parents=True, exist_ok=True)

    print("=== Phase 2 集約: 16 deck → 4 archetype ===\n")

    # 1. 各 archetype の平均重みを計算
    archetype_means: dict[str, dict[str, float]] = {}
    for archetype, slugs in ARCHETYPE_MAP.items():
        sum_p: dict[str, float] = {}
        n = 0
        for slug in slugs:
            try:
                p = load_deck_params(slug)
                for k, v in p.items():
                    if not k.startswith("w_"):
                        continue
                    sum_p[k] = sum_p.get(k, 0.0) + float(v)
                n += 1
            except FileNotFoundError:
                print(f"  [WARN] {slug} の json が見つからず skip")
                continue
        if n == 0:
            print(f"  [SKIP] archetype={archetype}: deck なし")
            continue
        avg_p = {k: v / n for k, v in sum_p.items()}
        archetype_means[archetype] = avg_p

        # archetype json 保存
        out_path = archetypes_dir / f"{archetype}.json"
        doc = {
            "version": "1",
            "archetype": archetype,
            "decks": slugs,
            "n_decks": n,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "note": f"Phase 2 集約: {n} deck の平均",
            "params": {k: int(round(v)) for k, v in avg_p.items()},
        }
        out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  ✔ {archetype} ({n} deck): {out_path.name}")

    # 2. 各 deck の offset を計算 → deck json 上書き
    print("\n=== deck offset (= deck - archetype 平均) ===\n")
    for archetype, slugs in ARCHETYPE_MAP.items():
        if archetype not in archetype_means:
            continue
        avg_p = archetype_means[archetype]
        for slug in slugs:
            try:
                p = load_deck_params(slug)
            except FileNotFoundError:
                continue
            offset_p: dict[str, int] = {}
            for k in avg_p:
                deck_v = float(p.get(k, 0))
                avg_v = avg_p[k]
                diff = deck_v - avg_v
                # 微小な offset (= |diff| < 1) は 0 に切り捨て (= ノイズ削減)
                if abs(diff) < 1.0:
                    offset_p[k] = 0
                else:
                    offset_p[k] = int(round(diff))
            # 既存 deck json を offset で上書き
            deck_path = ROOT / "db" / "ai_params_decks" / f"{slug}.json"
            doc = json.loads(deck_path.read_text(encoding="utf-8"))
            doc["base_archetype"] = archetype
            doc["params_type"] = "offset_from_archetype"
            doc["params"] = offset_p
            doc["saved_at"] = datetime.now(timezone.utc).isoformat()
            doc["note"] = f"deck offset (= {slug} - archetype/{archetype} 平均)"
            deck_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

            # 主要 offset を 表示 (= 0 でない top 5)
            sig = sorted(offset_p.items(), key=lambda kv: -abs(kv[1]))
            tops = [f"{k.replace('w_','')}={v:+d}" for k, v in sig if v != 0][:5]
            print(f"  {slug:30s} ({archetype}): {'  '.join(tops) if tops else '(no offset)'}")

    print("\n=== 集約完了 ===")
    print(f"archetypes saved: {archetypes_dir}/")
    print(f"deck offsets saved (上書き): db/ai_params_decks/")


if __name__ == "__main__":
    main()
