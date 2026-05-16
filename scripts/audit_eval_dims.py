#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""評価関数の dim 精査: 16 deck の fine-tune 結果から各 dim の学習量 を集計。

下位 dim = base から動かない = 削除 or 学習データ不足候補。
冗長性 = 重み相関で検出。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_base_params() -> dict:
    return json.loads((ROOT / "db" / "ai_params.json").read_text())["params"]


def load_archetype_absolutes() -> dict[str, dict]:
    """archetype.json は absolute 値で保存されてる (= base + archetype 平均)。"""
    out = {}
    archetype_dir = ROOT / "db" / "ai_params_archetypes"
    if not archetype_dir.exists():
        return {}
    for f in archetype_dir.glob("*.json"):
        a = f.stem
        out[a] = json.loads(f.read_text())["params"]
    return out


def main() -> None:
    base = load_base_params()
    archetypes = load_archetype_absolutes()

    # 全 dim = base + archetype 全部 の union (= 73 dim 全部)
    all_w_keys = set(k for k in base if k.startswith("w_"))
    for p in archetypes.values():
        all_w_keys.update(k for k in p if k.startswith("w_"))
    all_w_keys = sorted(all_w_keys)

    print(f"=== 評価関数 dim 精査 ({len(all_w_keys)} dim) ===\n")

    # 各 dim の archetype 別 |変動|
    print(f"{'dim':40s} {'BASE':>8s} {'aggro':>7s} {'mid':>7s} {'ctrl':>7s} {'trash':>7s} {'max|d|':>8s} {'spread':>8s}")
    print('-' * 110)

    rows = []
    for k in all_w_keys:
        b = base.get(k, 0)
        diffs = {}
        for a, p in archetypes.items():
            v = p.get(k, b)
            diffs[a] = v - b
        max_abs = max(abs(d) for d in diffs.values()) if diffs else 0
        spread = (max(diffs.values()) - min(diffs.values())) if diffs else 0
        rows.append({
            "dim": k,
            "base": b,
            "diffs": diffs,
            "max_abs": max_abs,
            "spread": spread,
        })

    # spread (= archetype 間の差) で sort、 大きい dim = 学習価値高い、 小さい = 不要候補
    rows.sort(key=lambda r: -r["spread"])
    for r in rows:
        d = r["diffs"]
        print(f"  {r['dim']:38s} {r['base']:>8d} "
              f"{d.get('aggro',0):>+7d} {d.get('midrange',0):>+7d} "
              f"{d.get('control',0):>+7d} {d.get('trash',0):>+7d} "
              f"{r['max_abs']:>8d} {r['spread']:>8d}")

    # === 削除候補 (= spread <= 5 = ほぼ動かない) ===
    print("\n=== 削除候補 (= spread <= 5、 archetype 間で差が小さい dim) ===\n")
    candidates = [r for r in rows if r["spread"] <= 5]
    for r in candidates:
        print(f"  {r['dim']:40s} (base={r['base']}, max|d|={r['max_abs']}, spread={r['spread']})")
    print(f"\n削除候補数: {len(candidates)}/{len(rows)}")

    # === 重み相関 (= 冗長性) ===
    # 各 dim を 4 archetype の diff vector として、 cosine similarity 計算
    print("\n=== 高相関 dim ペア (= 冗長性候補) ===\n")
    import math

    def cos_sim(va: list[float], vb: list[float]) -> float:
        dot = sum(a * b for a, b in zip(va, vb))
        na = math.sqrt(sum(a * a for a in va))
        nb = math.sqrt(sum(b * b for b in vb))
        if na == 0 or nb == 0:
            return 0
        return dot / (na * nb)

    arche_keys = ["aggro", "midrange", "control", "trash"]
    pairs = []
    for i, ra in enumerate(rows):
        if ra["spread"] <= 5:
            continue
        va = [ra["diffs"].get(a, 0) for a in arche_keys]
        for rb in rows[i + 1:]:
            if rb["spread"] <= 5:
                continue
            vb = [rb["diffs"].get(a, 0) for a in arche_keys]
            sim = cos_sim(va, vb)
            if sim > 0.95 or sim < -0.95:
                pairs.append((sim, ra["dim"], rb["dim"]))
    pairs.sort(key=lambda p: -abs(p[0]))
    for sim, a, b in pairs[:20]:
        sign = "+" if sim > 0 else "-"
        print(f"  {sign} {sim:+.3f}  {a:38s} <-> {b}")
    if not pairs:
        print("  (高相関 dim なし)")


if __name__ == "__main__":
    main()
