# -*- coding: utf-8 -*-
"""2026-05-18: snapshot を actor が プレイ中の deck slug 別に split。

deck-specific NN 学習 (= 各 deck 専用 評価関数) 用。 リーダー効果で プレイ思想が
根本的に違う OPTCG では、 archetype 集約より deck 個別の方が 正確 (= ohtsuki 指摘)。

入力: db/snapshots_*.jsonl (= state_encoded + actor_idx + deck_a + deck_b)
出力: db/snapshots_*_by_deck/<slug>.jsonl × 16

actor_idx == 0 → deck_a が actor の deck
actor_idx == 1 → deck_b が actor の deck

実行例:
  .venv/bin/python scripts/split_snapshots_by_deck.py \\
    --input db/snapshots_oneturn.jsonl \\
    --output-dir db/snapshots_oneturn_by_deck
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output-dir", required=True)
    args = ap.parse_args()

    in_path = Path(args.input)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    assert in_path.exists(), f"{in_path} 不在"
    print(f"=== split {in_path} → {out_dir}/<slug>.jsonl ===", flush=True)

    writers: dict = {}
    counts: dict = defaultdict(int)
    skipped = 0
    total = 0

    with open(in_path, "r", encoding="utf-8") as f:
        for line in f:
            total += 1
            try:
                d = json.loads(line)
            except Exception:
                skipped += 1
                continue
            actor = d.get("actor_idx")
            deck_a = d.get("deck_a")
            deck_b = d.get("deck_b")
            if actor is None or deck_a is None or deck_b is None:
                skipped += 1
                continue
            deck_slug = deck_a if actor == 0 else deck_b
            if deck_slug not in writers:
                writers[deck_slug] = open(out_dir / f"{deck_slug}.jsonl", "w", encoding="utf-8")
            writers[deck_slug].write(line)
            counts[deck_slug] += 1

    for w in writers.values():
        w.close()

    print(f"  total: {total}, skipped: {skipped}", flush=True)
    print(f"  deck breakdown:", flush=True)
    for slug, c in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"    {slug:35s}: {c:6d} snaps", flush=True)
    print(f"\n  → {len(counts)} files in {out_dir}/", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
