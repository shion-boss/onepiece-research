# -*- coding: utf-8 -*-
"""打倒1位 campaign: vs-1位セルだけ差し替えて ranking を高速再計算 (ohtsuki 提案)。

全 matrix 再計算 (240 cell, 数時間) は不要。 self-play で counter が #1 戦を改善したら、
その (challenger, #1) / (#1, challenger) セルだけ更新 → row-avg 再計算 → #1 陥落したか即判定。

  # 現状の ranking を再現 (= 機械の検証、 override 無し):
  .venv/bin/python scripts/recompute_rank_vs_top.py
  # 改善を反映 (= challenger の vs-#1 勝率を上書きして再計算):
  .venv/bin/python scripts/recompute_rank_vs_top.py --override cardrush_1467=0.55,cardrush_1342=0.60
  # gauntlet 結果ファイルから一括反映:
  .venv/bin/python scripts/recompute_rank_vs_top.py --gauntlet db/gauntlet_tcgportal_calgara.json
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_matrix():
    return json.loads((ROOT / "db" / "matchup_matrix.json").read_text(encoding="utf-8"))


def _row_avgs(m):
    """各 deck の row-avg (= vs 全相手の平均勝率)。 mirror(None)は除外。"""
    out = {}
    names = {}
    for e in m["matrix"]:
        wr = [c["winrate"] for c in e["row"] if c.get("winrate") is not None]
        out[e["deck_a"]] = statistics.mean(wr) if wr else 0.0
        names[e["deck_a"]] = e["deck_a_name"]
    return out, names


def _cell(m, a, b):
    for e in m["matrix"]:
        if e["deck_a"] == a:
            for c in e["row"]:
                if c["deck_b"] == b:
                    return c
    return None


def _apply_override(m, top, overrides):
    """challenger の vs-top 勝率を override → (challenger,top) と (top,challenger) を整合更新。"""
    for ch, wr_vs_top in overrides.items():
        c1 = _cell(m, ch, top)      # challenger が top に勝つ率
        c2 = _cell(m, top, ch)      # top が challenger に勝つ率 = 1 - 上記
        if c1 is not None:
            c1["winrate"] = wr_vs_top
        if c2 is not None:
            c2["winrate"] = 1.0 - wr_vs_top


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", default=None, help="#1 slug (既定 = 現 row-avg 1位)")
    ap.add_argument("--override", default="", help="slug=wr,slug=wr (challenger の vs-#1 勝率)")
    ap.add_argument("--gauntlet", default="", help="gauntlet_<top>.json から vs-#1 を一括反映")
    a = ap.parse_args()

    m = _load_matrix()
    avg0, names = _row_avgs(m)
    rank0 = sorted(avg0.items(), key=lambda x: -x[1])
    top = a.top or rank0[0][0]
    print(f"=== 現 ranking (#1 = {top} {names.get(top,'')} {avg0[top]*100:.1f}%) ===")
    for i, (s, v) in enumerate(rank0[:5]):
        print(f"  {i+1}. {names.get(s,s):18} {v*100:.1f}%")

    overrides = {}
    if a.override:
        for kv in a.override.split(","):
            if "=" in kv:
                k, v = kv.split("=")
                overrides[k.strip()] = float(v)
    if a.gauntlet:
        g = json.loads(Path(a.gauntlet).read_text(encoding="utf-8"))
        for ch, wld in g.get("cum", {}).items():
            w, l, d = (list(wld) + [0, 0, 0])[:3]
            n = w + l + d
            if n:
                overrides[ch] = w / n
    if not overrides:
        print("\n(override 無し → 機械検証: 現 ranking を再現するだけ)")
        return

    _apply_override(m, top, overrides)
    avg1, _ = _row_avgs(m)
    rank1 = sorted(avg1.items(), key=lambda x: -x[1])
    print(f"\n=== 差し替え後 (override {len(overrides)} 件: "
          f"{', '.join(f'{k}→{v:.0%}' for k, v in overrides.items())}) ===")
    for i, (s, v) in enumerate(rank1[:5]):
        d = (v - avg0.get(s, v)) * 100
        flag = " ⭐#1陥落!" if s == top and i > 0 else (" ⭐新#1" if i == 0 and s != top else "")
        print(f"  {i+1}. {names.get(s,s):18} {v*100:.1f}%  ({d:+.1f}pt){flag}")
    new_top = rank1[0][0]
    if new_top != top:
        print(f"\n⭐⭐ #1 が {names.get(top,top)} → {names.get(new_top,new_top)} に交代! 打倒成功、 次の標的へ。")
    else:
        print(f"\n#1 は {names.get(top,top)} のまま (row-avg {avg0[top]*100:.1f}→{avg1[top]*100:.1f}%)。")


if __name__ == "__main__":
    main()
