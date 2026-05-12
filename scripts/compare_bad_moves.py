#!/usr/bin/env python3
"""
2 つの bad_moves レポート (= scripts/report_bad_moves.py の出力 JSON) を比較。

主に R67 統合前後の AI 行動の質変化 (悪手率 / 平均 delta) を測定。

使い方:
    .venv/bin/python scripts/report_bad_moves.py \\
        --deck-a decks/cardrush_1342.json --deck-b decks/cardrush_1308.json \\
        --n-games 20 --seed 42 --out /tmp/baseline.json

    # コード変更後、 同じ条件で計測:
    .venv/bin/python scripts/report_bad_moves.py \\
        --deck-a decks/cardrush_1342.json --deck-b decks/cardrush_1308.json \\
        --n-games 20 --seed 42 --out /tmp/r67.json

    # 比較
    .venv/bin/python scripts/compare_bad_moves.py /tmp/baseline.json /tmp/r67.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _bad_count(report: dict) -> int:
    bp = report.get("bad_per_player", {})
    return bp.get("0", {}).get("count", 0) + bp.get("1", {}).get("count", 0)


def _avg_delta(report: dict) -> float:
    bp = report.get("bad_per_player", {})
    p0 = bp.get("0", {})
    p1 = bp.get("1", {})
    n0, d0 = p0.get("count", 0), p0.get("avg_delta", 0.0)
    n1, d1 = p1.get("count", 0), p1.get("avg_delta", 0.0)
    total = n0 + n1
    if total == 0:
        return 0.0
    return (n0 * d0 + n1 * d1) / total


def _bad_rate(report: dict) -> float:
    total_actions = report.get("total_evaluated_actions", 0)
    if total_actions == 0:
        return 0.0
    return _bad_count(report) / total_actions * 100


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("baseline", type=Path, help="baseline (R64 等) の bad_moves JSON")
    ap.add_argument("after", type=Path, help="比較対象 (R67 等) の bad_moves JSON")
    args = ap.parse_args()

    a = _load(args.baseline)
    b = _load(args.after)

    if a.get("deck_a") != b.get("deck_a") or a.get("deck_b") != b.get("deck_b"):
        print(
            f"⚠ デッキペアが一致しない: baseline {a.get('deck_a')} vs {a.get('deck_b')}, "
            f"after {b.get('deck_a')} vs {b.get('deck_b')}",
            file=sys.stderr,
        )

    a_actions = a.get("total_evaluated_actions", 0)
    b_actions = b.get("total_evaluated_actions", 0)
    a_bad = _bad_count(a)
    b_bad = _bad_count(b)
    a_rate = _bad_rate(a)
    b_rate = _bad_rate(b)
    a_avg = _avg_delta(a)
    b_avg = _avg_delta(b)

    print(f"=== 悪手レポート比較 ({a.get('deck_a')} vs {a.get('deck_b')}) ===")
    print(f"  threshold: baseline={a.get('threshold')} after={b.get('threshold')}")
    print()
    print(f"{'metric':<24} {'baseline':>12} {'after':>12} {'delta':>12}")
    print("-" * 64)
    print(f"{'evaluated_actions':<24} {a_actions:>12} {b_actions:>12} {b_actions - a_actions:>+12}")
    print(f"{'bad_count':<24} {a_bad:>12} {b_bad:>12} {b_bad - a_bad:>+12}")
    print(f"{'bad_rate (%)':<24} {a_rate:>12.2f} {b_rate:>12.2f} {b_rate - a_rate:>+12.2f}")
    print(f"{'avg_delta':<24} {a_avg:>12.0f} {b_avg:>12.0f} {b_avg - a_avg:>+12.0f}")

    # action type breakdown
    print()
    print("=== action_type 別 bad 件数 ===")
    a_at = a.get("action_type_breakdown", {})
    b_at = b.get("action_type_breakdown", {})
    types = sorted(set(a_at.keys()) | set(b_at.keys()))
    print(f"{'action_type':<24} {'baseline':>12} {'after':>12} {'delta':>12}")
    print("-" * 64)
    for t in types:
        av = a_at.get(t, 0)
        bv = b_at.get(t, 0)
        print(f"{t:<24} {av:>12} {bv:>12} {bv - av:>+12}")

    # per-player
    print()
    print("=== player 別 ===")
    for pidx in ("0", "1"):
        ap_info = a.get("bad_per_player", {}).get(pidx, {})
        bp_info = b.get("bad_per_player", {}).get(pidx, {})
        a_n = ap_info.get("count", 0)
        b_n = bp_info.get("count", 0)
        a_d = ap_info.get("avg_delta", 0.0)
        b_d = bp_info.get("avg_delta", 0.0)
        deck_name = a.get("deck_a") if pidx == "0" else a.get("deck_b")
        print(
            f"  P{pidx} ({deck_name}): {a_n} → {b_n} ({b_n - a_n:+d}), "
            f"avg_delta {a_d:.0f} → {b_d:.0f}"
        )

    # 評価
    print()
    if b_rate <= a_rate:
        print(f"✓ 悪手率改善: {a_rate:.2f}% → {b_rate:.2f}% (-{a_rate - b_rate:.2f}pt)")
    else:
        print(f"✗ 悪手率悪化: {a_rate:.2f}% → {b_rate:.2f}% (+{b_rate - a_rate:.2f}pt)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
