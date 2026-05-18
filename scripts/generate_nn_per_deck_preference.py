# -*- coding: utf-8 -*-
"""絶対強度測定結果から db/nn_per_deck_preference.json を生成。

delta (= NN - NoNN) > THRESHOLD なら preference=true (= NN-on)、 それ以外 false。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="db/absolute_strength_v5_vs_greedy.json")
    ap.add_argument("--output", default="db/nn_per_deck_preference.json")
    ap.add_argument("--threshold", type=float, default=0.05,
                    help="delta > threshold で NN-on (default 0.05 = +5pt)")
    args = ap.parse_args()

    in_path = ROOT / args.input
    out_path = ROOT / args.output

    if not in_path.exists():
        print(f"  [ERROR] {in_path} not found")
        return 1

    abs_data = json.loads(in_path.read_text(encoding="utf-8"))
    results = abs_data.get("results", [])
    print(f"  読み込み: {len(results)} デッキ")

    prefs: dict[str, bool] = {}
    deltas: dict[str, float] = {}
    nn_count = 0
    nonn_count = 0
    for r in results:
        slug = r["deck"]
        delta = float(r.get("delta", 0))
        deltas[slug] = round(delta * 100, 1)  # pt 単位
        if delta > args.threshold:
            prefs[slug] = True
            nn_count += 1
        else:
            prefs[slug] = False
            nonn_count += 1

    out_doc = {
        "_generated_at": abs_data.get("computed_at", "?"),
        "_source": str(args.input),
        "_threshold_pt": args.threshold * 100,
        "default": False,
        "preferences": prefs,
        "deltas_pt": deltas,
    }
    out_path.write_text(json.dumps(out_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  生成: {out_path}")
    print(f"  NN-on デッキ: {nn_count} / NN-off デッキ: {nonn_count}")
    print()
    print("  NN-on (= 推奨):")
    for slug, d in sorted(deltas.items(), key=lambda x: -x[1]):
        if prefs.get(slug):
            print(f"    {slug}: +{d:.1f}pt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
