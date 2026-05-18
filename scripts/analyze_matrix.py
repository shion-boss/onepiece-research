# -*- coding: utf-8 -*-
"""matrix A/B から 10 軸の詳細 insight を抽出してレポート。

実行例:
    .venv/bin/python scripts/analyze_matrix.py \\
        --a db/matchup_matrix.step7_a_nn_off.json \\
        --b db/matchup_matrix.step7_b_nn_on.json
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def _load(p: str) -> dict:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _cell_index(doc: dict) -> dict[tuple[str, str], dict]:
    """(deck_a, deck_b) → cell dict。"""
    out = {}
    for row in doc.get("matrix", []):
        slug_a = row.get("deck_a")
        for cell in row.get("row", []):
            out[(slug_a, cell.get("deck_b"))] = cell
    return out


def _decks(doc: dict) -> list[str]:
    return [d["slug"] for d in doc.get("decks", [])]


def _deck_names(doc: dict) -> dict[str, str]:
    return {d["slug"]: d.get("name", d["slug"]) for d in doc.get("decks", [])}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="db/matchup_matrix.step7_a_nn_off.json")
    ap.add_argument("--b", default="db/matchup_matrix.step7_b_nn_on.json")
    ap.add_argument("--output-json", default="db/matrix_analysis_report.json")
    args = ap.parse_args()

    A = _load(args.a)
    B = _load(args.b)
    A_idx = _cell_index(A)
    B_idx = _cell_index(B)
    decks = _decks(A)
    names = _deck_names(A)

    print("=" * 80)
    print(f"matrix 詳細分析レポート")
    print("=" * 80)
    print(f"A (= NN off): {args.a} {A.get('ai_version')}")
    print(f"B (= NN on):  {args.b} {B.get('ai_version')}")
    print(f"decks: {len(decks)}")
    print()

    # ---------------------------------------------------------------- #
    # 1. 相性 heatmap (= 16×16 全表)
    # ---------------------------------------------------------------- #
    print("【1】 相性 heatmap A (= 線形 eval 同士、 行 vs 列 の勝率%)")
    print("    " + " ".join(f"{s[-4:]:>5}" for s in decks))
    for sa in decks:
        row = [sa[-4:]]
        for sb in decks:
            cell = A_idx.get((sa, sb))
            if cell is None or cell.get("winrate") is None:
                row.append("  -  ")
            else:
                row.append(f"{cell['winrate']*100:>4.0f}%")
        print(" ".join(row))
    print()

    # ---------------------------------------------------------------- #
    # 2. Tier 内序列 + 全体 ranking
    # ---------------------------------------------------------------- #
    def deck_avg(idx, decks):
        out = {}
        for sa in decks:
            wrs = [idx[(sa, sb)]["winrate"] for sb in decks
                   if (sa, sb) in idx and idx[(sa, sb)].get("winrate") is not None]
            if wrs:
                out[sa] = sum(wrs) / len(wrs)
        return out

    A_avg = deck_avg(A_idx, decks)
    B_avg = deck_avg(B_idx, decks)

    print("【2】 各 deck Tier (= A 線形 eval 順)")
    print(f"  {'rank':<5}{'deck':<22}{'A wr':>8}{'B wr':>8}{'delta':>8}")
    for rank, (slug, awr) in enumerate(sorted(A_avg.items(), key=lambda x: -x[1]), 1):
        bwr = B_avg.get(slug, 0)
        delta = (bwr - awr) * 100
        print(f"  {rank:<5}{slug:<22}{awr*100:>7.1f}%{bwr*100:>7.1f}%{delta:>+7.1f}")
    print()

    # ---------------------------------------------------------------- #
    # 3. NN 引き起こす 相性逆転 cell top
    # ---------------------------------------------------------------- #
    print("【3】 NN 引き起こす 相性逆転 cell top 15 (= |delta| 大きい順)")
    deltas = []
    for k in A_idx:
        a_cell = A_idx.get(k)
        b_cell = B_idx.get(k)
        if not a_cell or not b_cell:
            continue
        a_wr = a_cell.get("winrate")
        b_wr = b_cell.get("winrate")
        if a_wr is None or b_wr is None:
            continue
        delta = (b_wr - a_wr) * 100
        deltas.append((k, a_wr, b_wr, delta))
    deltas.sort(key=lambda x: -abs(x[3]))
    print(f"  {'deck_a':<22}{'deck_b':<22}{'A wr':>8}{'B wr':>8}{'delta':>9}")
    for (sa, sb), aw, bw, d in deltas[:15]:
        marker = "↑" if d > 0 else "↓"
        print(f"  {sa:<22}{sb:<22}{aw*100:>7.0f}%{bw*100:>7.0f}%{d:>+7.0f}pt {marker}")
    print()

    # ---------------------------------------------------------------- #
    # 4. 対角線対称性 check (= 先攻有利)
    # ---------------------------------------------------------------- #
    print("【4】 対角線対称性 (= wr(A,B) + wr(B,A) が 100% から外れる cell top 10)")
    print(f"  小さい sum = 引き分け多い、 大きい sum = 計算誤り 疑い")
    print(f"  {'deck pair':<46}{'A(A,B)':>8}{'A(B,A)':>8}{'sum':>8}")
    sym_issues = []
    seen = set()
    for sa in decks:
        for sb in decks:
            if sa == sb or (sb, sa) in seen:
                continue
            seen.add((sa, sb))
            c1 = A_idx.get((sa, sb))
            c2 = A_idx.get((sb, sa))
            if not c1 or not c2 or c1.get("winrate") is None or c2.get("winrate") is None:
                continue
            sum_wr = (c1["winrate"] + c2["winrate"]) * 100
            sym_issues.append((sa, sb, c1["winrate"], c2["winrate"], sum_wr))
    sym_issues.sort(key=lambda x: abs(x[4] - 100))
    sym_issues.reverse()  # 外れが大きい順
    for sa, sb, w1, w2, ss in sym_issues[:10]:
        print(f"  {sa+' vs '+sb:<46}{w1*100:>7.0f}%{w2*100:>7.0f}%{ss:>7.0f}%")
    print()

    # ---------------------------------------------------------------- #
    # 5. avg_turns 分布
    # ---------------------------------------------------------------- #
    print("【5】 avg_turns 分布 (= A vs B 比較)")
    a_turns = [c["avg_turns"] for c in A_idx.values() if c.get("avg_turns", 0) > 0]
    b_turns = [c["avg_turns"] for c in B_idx.values() if c.get("avg_turns", 0) > 0]
    if a_turns and b_turns:
        import statistics
        print(f"  A: mean={statistics.mean(a_turns):.1f}, median={statistics.median(a_turns):.1f}, range [{min(a_turns):.1f}, {max(a_turns):.1f}]")
        print(f"  B: mean={statistics.mean(b_turns):.1f}, median={statistics.median(b_turns):.1f}, range [{min(b_turns):.1f}, {max(b_turns):.1f}]")
        print(f"  NN を入れると平均 {(statistics.mean(b_turns) - statistics.mean(a_turns)):+.1f} ターン")
    print()

    # ---------------------------------------------------------------- #
    # 6. draw 率分析
    # ---------------------------------------------------------------- #
    print("【6】 draw 率 top 10 (= 引き分けが多い相性)")
    draws = []
    for k, c in A_idx.items():
        total = (c.get("wins", 0) or 0) + (c.get("losses", 0) or 0) + (c.get("draws", 0) or 0)
        if total == 0:
            continue
        dr = (c.get("draws", 0) or 0) / total
        if dr > 0:
            draws.append((k, dr, c.get("avg_turns", 0)))
    draws.sort(key=lambda x: -x[1])
    print(f"  {'pair':<46}{'draw%':>8}{'avg_t':>8}")
    for (sa, sb), dr, at in draws[:10]:
        print(f"  {sa+' vs '+sb:<46}{dr*100:>7.0f}%{at:>7.1f}")
    print()

    # ---------------------------------------------------------------- #
    # 7. NN delta top 10 (= 救済 vs 弱体化)
    # ---------------------------------------------------------------- #
    print("【7】 deck 別 NN delta (= A→B 平均勝率の変化)")
    deck_deltas = []
    for slug in decks:
        if slug in A_avg and slug in B_avg:
            d = (B_avg[slug] - A_avg[slug]) * 100
            deck_deltas.append((slug, A_avg[slug], B_avg[slug], d))
    deck_deltas.sort(key=lambda x: -x[3])
    print(f"  ↑ NN が救う:")
    for slug, aw, bw, d in deck_deltas:
        if d > 5:
            print(f"    {slug:<22} {aw*100:>5.1f}% → {bw*100:>5.1f}%  {d:+.1f}pt")
    print(f"  ↓ NN が弱体化:")
    for slug, aw, bw, d in deck_deltas:
        if d < -5:
            print(f"    {slug:<22} {aw*100:>5.1f}% → {bw*100:>5.1f}%  {d:+.1f}pt")
    print()

    # ---------------------------------------------------------------- #
    # 8. archetype (= color) cluster (= 暫定: leader_color で簡易分類)
    # ---------------------------------------------------------------- #
    print("【8】 leader_color 別 平均勝率 (= A 線形 eval)")
    # decks/<slug>.analysis.json からカラー取得
    root = Path(__file__).resolve().parent.parent
    color_groups: dict[str, list[float]] = defaultdict(list)
    for slug in decks:
        ap = root / "decks" / f"{slug}.analysis.json"
        if not ap.exists():
            continue
        try:
            anl = json.loads(ap.read_text(encoding="utf-8"))
            color = "/".join(anl.get("leader_color") or ["unknown"])
            if slug in A_avg:
                color_groups[color].append(A_avg[slug])
        except Exception:
            continue
    print(f"  {'color':<14}{'n decks':>8}{'avg wr':>10}")
    for color, vals in sorted(color_groups.items(), key=lambda x: -sum(x[1])/len(x[1])):
        avg = sum(vals) / len(vals)
        print(f"  {color:<14}{len(vals):>8}{avg*100:>9.1f}%")
    print()

    # ---------------------------------------------------------------- #
    # 9. 救済対象 解析 (= NN が大きく救った deck の対戦相手)
    # ---------------------------------------------------------------- #
    print("【9】 救済 cell 詳細 (= delta +20pt 以上 の cell)")
    salvation = [(k, a, b, d) for k, a, b, d in deltas if d >= 20]
    salvation.sort(key=lambda x: -x[3])
    print(f"  {'救った deck':<22}{'相手':<22}{'A wr':>8}{'B wr':>8}{'delta':>8}")
    for (sa, sb), aw, bw, d in salvation:
        print(f"  {sa:<22}{sb:<22}{aw*100:>7.0f}%{bw*100:>7.0f}%{d:>+7.0f}")
    print()

    # ---------------------------------------------------------------- #
    # 10. strategy mismatch (= NN が大きく弱体化させた cell)
    # ---------------------------------------------------------------- #
    print("【10】 弱体化 cell 詳細 (= delta -20pt 以下)")
    weak = [(k, a, b, d) for k, a, b, d in deltas if d <= -20]
    weak.sort(key=lambda x: x[3])
    print(f"  {'弱体化 deck':<22}{'相手':<22}{'A wr':>8}{'B wr':>8}{'delta':>8}")
    for (sa, sb), aw, bw, d in weak:
        print(f"  {sa:<22}{sb:<22}{aw*100:>7.0f}%{bw*100:>7.0f}%{d:>+7.0f}")
    print()

    # JSON 出力
    report = {
        "A_path": args.a,
        "B_path": args.b,
        "deck_count": len(decks),
        "deck_avg_A": {k: v for k, v in A_avg.items()},
        "deck_avg_B": {k: v for k, v in B_avg.items()},
        "deck_deltas": [{"deck": s, "A_wr": a, "B_wr": b, "delta_pt": d} for s, a, b, d in deck_deltas],
        "top_reversal_cells": [
            {"deck_a": sa, "deck_b": sb, "A_wr": a, "B_wr": b, "delta_pt": d}
            for (sa, sb), a, b, d in deltas[:30]
        ],
        "color_groups": {k: {"n": len(v), "avg": sum(v)/len(v)} for k, v in color_groups.items()},
        "salvation_cells": [
            {"deck_a": sa, "deck_b": sb, "A_wr": a, "B_wr": b, "delta_pt": d}
            for (sa, sb), a, b, d in salvation
        ],
        "weakened_cells": [
            {"deck_a": sa, "deck_b": sb, "A_wr": a, "B_wr": b, "delta_pt": d}
            for (sa, sb), a, b, d in weak
        ],
    }
    Path(args.output_json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON 出力: {args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
