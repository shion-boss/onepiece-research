# -*- coding: utf-8 -*-
"""2 つ以上の matchup_matrix.json を比較してデッキ別勝率と差分を出力。

実行例:
    .venv/bin/python scripts/compare_matrices.py \\
        --label baseline db/matchup_matrix.r60.json \\
        --label A_off db/matchup_matrix.step7_a_nn_off.json \\
        --label B_on db/matchup_matrix.step7_b_nn_on.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _deck_avg_winrate(doc: dict) -> dict[str, float]:
    """deck_a 毎の平均勝率 (= self vs self 除く)。"""
    out: dict[str, float] = {}
    for cell in doc.get("matrix", []):
        slug = cell.get("deck_a")
        wrs = [r["winrate"] for r in cell.get("row", []) if r.get("winrate") is not None]
        if wrs:
            out[slug] = sum(wrs) / len(wrs)
    return out


def _completeness(doc: dict) -> tuple[int, int]:
    """(完了 cell 数, 期待 cell 数)。"""
    rows = doc.get("matrix", [])
    n = len(doc.get("decks", []))
    done = sum(
        1
        for r in rows
        for c in r.get("row", [])
        if c.get("winrate") is not None or r.get("deck_a") == c.get("deck_b")
    )
    return done, n * n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--label",
        nargs=2,
        action="append",
        metavar=("LABEL", "PATH"),
        required=True,
        help="比較する matrix (= 複数指定可)",
    )
    args = ap.parse_args()

    docs: dict[str, dict] = {}
    wrs: dict[str, dict[str, float]] = {}
    for label, path in args.label:
        p = Path(path)
        if not p.exists():
            print(f"  [SKIP] {label}: {path} not found")
            continue
        doc = json.loads(p.read_text(encoding="utf-8"))
        docs[label] = doc
        wrs[label] = _deck_avg_winrate(doc)
        done, total = _completeness(doc)
        ai_ver = doc.get("ai_version", "?")
        ng = doc.get("n_games", "?")
        print(f"  [{label}] {path}  done={done}/{total} ai_version={ai_ver} n_games={ng}")

    if len(wrs) < 1:
        return 1

    all_slugs = sorted({s for w in wrs.values() for s in w})
    labels = list(wrs.keys())

    print()
    header = f"{'deck':<28}" + "".join(f"  {lab:>10}" for lab in labels)
    print(header)
    print("-" * len(header))
    for slug in all_slugs:
        row_vals = [wrs[lab].get(slug) for lab in labels]
        cells = []
        for v in row_vals:
            cells.append(f"  {v*100:>9.1f}%" if v is not None else f"  {'N/A':>10}")
        print(f"{slug:<28}" + "".join(cells))

    # delta 表示 (= 2 つ以上の label がある場合、 最初を基準にして差分を表示)
    if len(labels) >= 2:
        base = labels[0]
        print()
        print(f"=== delta vs '{base}' (= 基準) ===")
        header = f"{'deck':<28}"
        for lab in labels[1:]:
            header += f"  {lab+' delta':>14}"
        print(header)
        print("-" * len(header))
        deltas_summary: dict[str, list[float]] = {lab: [] for lab in labels[1:]}
        for slug in all_slugs:
            base_v = wrs[base].get(slug)
            line = f"{slug:<28}"
            for lab in labels[1:]:
                v = wrs[lab].get(slug)
                if base_v is None or v is None:
                    line += f"  {'N/A':>14}"
                else:
                    d = (v - base_v) * 100
                    line += f"  {d:>+13.1f}pt"
                    deltas_summary[lab].append(d)
            print(line)
        print()
        print(f"=== 平均 delta vs '{base}' ===")
        for lab, vals in deltas_summary.items():
            if vals:
                print(f"  {lab}: avg={sum(vals)/len(vals):+.2f}pt, max={max(vals):+.2f}pt, min={min(vals):+.2f}pt (= {len(vals)} decks)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
