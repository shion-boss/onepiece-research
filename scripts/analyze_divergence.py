# -*- coding: utf-8 -*-
"""claude_play.py が記録した divergence jsonl (= 私の手 vs 配備ExploitBeam の手) を集計し、
AI の系統的盲点候補を抽出する。 = heuristic 8修正 (campaign 手作業) の systematic 版。

各 MAIN 決定で「私(強プレイ)が選んだ手」と「配備AIが選ぶ手」を同一 state で比較記録 →
本スクリプトで (1) 全体一致率 (2) action種別の不一致パターン (3) 盤面文脈別の乖離 を出す。
不一致が systematic (= 特定 action種別/文脈で繰り返す) なら、 そこが AI の盲点 = 次の fix 候補。

    .venv/bin/python scripts/analyze_divergence.py
"""
from __future__ import annotations
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGDIR = ROOT / "db" / "claude_play"


def _kind(sig: str) -> str:
    """シグネチャから action 種別だけ取る (= 'AttackLeader(atk=3)' -> 'AttackLeader')。"""
    return sig.split("(")[0]


def main() -> int:
    files = sorted(LOGDIR.glob("divergence_*.jsonl"))
    rows = []
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    if not rows:
        print("divergence データ無し。 scripts/claude_play.py で対戦すると蓄積される。")
        return 0

    n = len(rows)
    agree = sum(1 for r in rows if r.get("agree"))
    print(f"=== divergence 集計 ({len(files)} files, {n} decisions) ===")
    print(f"  一致率: {agree}/{n} = {agree/n*100:.0f}%   (不一致 {n-agree})\n")

    dis = [r for r in rows if not r.get("agree")]

    # (1) 不一致の (私の種別 → AIの種別) ペア top
    pair = Counter((_kind(r["my"]), _kind(r["ai"])) for r in dis)
    print("=== (1) 不一致パターン (私の種別 → AIの種別、 頻度順) ===")
    for (mk, ak), c in pair.most_common(15):
        print(f"  {c:>3}回  私:{mk:<20} ↔ AI:{ak}")

    # (2) 「私は攻めるが AI は攻めない/終了する」 = 配備AIの消極性候補
    aggro_kinds = {"AttackLeader", "AttackCharacter"}
    passive = [r for r in dis if _kind(r["my"]) in aggro_kinds and _kind(r["ai"]) in {"EndPhase"}]
    print(f"\n=== (2) 私=攻撃 ↔ AI=ターン終了 ({len(passive)}件、 配備AIの消極性候補) ===")
    lb = Counter((r["board"]["my_life"], r["board"]["opp_life"]) for r in passive)
    for (ml, ol), c in lb.most_common(8):
        print(f"  {c:>3}回  自life={ml} 相手life={ol}")

    # (3) 盤面文脈別の不一致率 (= どの局面で乖離するか)
    print("\n=== (3) 文脈別 不一致率 ===")
    for key, fn in [("自life", lambda r: r["board"]["my_life"]),
                    ("自DON", lambda r: r["board"]["my_don"]),
                    ("turn", lambda r: r["turn"])]:
        bucket = defaultdict(lambda: [0, 0])
        for r in rows:
            k = fn(r)
            bucket[k][0] += 0 if r.get("agree") else 1
            bucket[k][1] += 1
        cells = sorted(bucket.items())
        s = "  ".join(f"{key}={k}:{d}/{t}({d/t*100:.0f}%)" for k, (d, t) in cells)
        print(f"  [{key}] {s}")

    print("\n次手: 不一致が systematic な種別/文脈 = AI盲点。 該当局面を精読し heuristic fix 化。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
