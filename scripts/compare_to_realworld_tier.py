# -*- coding: utf-8 -*-
"""
db/matchup_matrix.json の simulation 勝率 と tcg-portal の現環境 Tier ランキング を比較。

AI 品質の検証指標 (= simulation Tier が real-world Tier と相関するか)。

実行:
    .venv/bin/python scripts/compare_to_realworld_tier.py

出力:
- 各デッキの simulation 勝率 + tcg-portal 順位
- Spearman 順位相関 (= 1.0 完全一致、 0.0 無相関)
- 順位ずれ TOP 3 (= AI/engine 改善の優先候補)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# tcg-portal 現環境 Tier (2026-05-12 取得)
# (slug, leader_name, tier, real_rank, usage_pct)
TCGPORTAL_RANKING = [
    ("cardrush_1439",       "青黄ナミ",         1, 1, 16.0),
    ("cardrush_1424",       "紫エネル",         1, 2, 16.0),
    ("tcgportal_op15_lufy", "黄ルフィ（OP15）", 2, 3, 12.0),
    ("cardrush_1437",       "緑ミホーク",       3, 4,  8.0),
    ("cardrush_1399",       "赤青ルーシー",     3, 5,  8.0),
    ("tcgportal_kuriku",    "赤緑クリーク",     3, 6,  8.0),
]


def spearman_correlation(xs: list[int], ys: list[int]) -> float:
    """Spearman 順位相関係数。 ranks が同じなら 1.0、 逆なら -1.0。"""
    n = len(xs)
    if n < 2:
        return 0.0
    d2_sum = sum((x - y) ** 2 for x, y in zip(xs, ys))
    return 1.0 - (6.0 * d2_sum) / (n * (n * n - 1))


def main() -> int:
    matrix_path = ROOT / "db" / "matchup_matrix.json"
    if not matrix_path.exists():
        print(f"ERROR: {matrix_path} not found", file=sys.stderr)
        return 1
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))

    # simulation 勝率 = 各デッキの row 平均勝率
    sim_winrate: dict[str, float] = {}
    for cell in matrix.get("matrix", []):
        slug = cell["deck_a"]
        wrs = [r["winrate"] for r in cell["row"] if r.get("winrate") is not None]
        if wrs:
            sim_winrate[slug] = sum(wrs) / len(wrs)

    # tcg-portal 順位と並べる
    print(f"=== simulation 勝率 vs tcg-portal Tier ===")
    print()
    print(f"{'leader':<24} {'real rank':>10} {'tier':>5} {'usage':>7} {'sim WR':>8} {'sim rank':>10}")
    print("-" * 70)

    # simulation rank 計算
    sim_ranking = sorted(
        [(slug, name, tier, real_rank, usage)
         for slug, name, tier, real_rank, usage in TCGPORTAL_RANKING
         if slug in sim_winrate],
        key=lambda x: -sim_winrate[x[0]],
    )
    sim_rank_map = {slug: i + 1 for i, (slug, *_) in enumerate(sim_ranking)}

    real_ranks = []
    sim_ranks = []
    for slug, name, tier, real_rank, usage in sorted(TCGPORTAL_RANKING, key=lambda x: x[3]):
        wr = sim_winrate.get(slug)
        sim_rank = sim_rank_map.get(slug, "-")
        if wr is None:
            print(f"{name:<24} {real_rank:>10} {tier:>5} {usage:>6.1f}% {'N/A':>8} {'N/A':>10}")
            continue
        real_ranks.append(real_rank)
        sim_ranks.append(sim_rank if isinstance(sim_rank, int) else 99)
        print(f"{name:<24} {real_rank:>10} {tier:>5} {usage:>6.1f}% {wr:>7.2%} {sim_rank:>10}")

    print()
    rho = spearman_correlation(real_ranks, sim_ranks)
    print(f"Spearman 順位相関: {rho:+.3f}")
    if rho >= 0.8:
        print("  → 強い相関 ✓ AI/engine が現環境をよく再現できている")
    elif rho >= 0.5:
        print("  → 中程度の相関 △ 部分的に再現")
    elif rho >= 0.0:
        print("  → 弱い相関 ⚠ AI/engine の改善余地大")
    else:
        print("  → 負の相関 ✗ 順位が反転している。 engine 重大不一致")

    # 順位ずれ TOP 3
    print()
    print("=== 順位ずれ TOP 3 (real_rank - sim_rank) ===")
    diffs = []
    for slug, name, tier, real_rank, usage in TCGPORTAL_RANKING:
        sim_rank = sim_rank_map.get(slug)
        if sim_rank is None:
            continue
        diff = real_rank - sim_rank
        diffs.append((abs(diff), diff, name, real_rank, sim_rank))
    diffs.sort(key=lambda x: -x[0])
    for absdiff, diff, name, rr, sr in diffs[:3]:
        if diff > 0:
            print(f"  {name:<20} real {rr} → sim {sr} (= sim 過大評価 +{diff})")
        elif diff < 0:
            print(f"  {name:<20} real {rr} → sim {sr} (= sim 過小評価 {diff})")
        else:
            print(f"  {name:<20} real {rr} → sim {sr} (一致)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
