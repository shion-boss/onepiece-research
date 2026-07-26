"""カード効果シグネチャ sig(card) を全カード導出 → db/card_sig.json — 2026-07-26。

overlay(db/card_effects.json)+ cards.json から engine/card_sig.build_all() で全4518枚の
効果シグネチャを導出し JSON に dump。 overlay 改善時に再実行すれば sig も同期 (学習不要)。

  .venv/bin/python scripts/build_card_sig.py
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine import card_sig as CS  # noqa: E402

OUT = ROOT / "db" / "card_sig.json"


def main() -> None:
    db = CS.build_all()
    OUT.write_text(json.dumps(db, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    n = len(db)
    # 非ゼロ (=何か効果/特徴を持つ) 枚数
    nonzero = sum(1 for s in db.values() if any(v != 0.0 for v in s.values()))
    print(f"saved {OUT.relative_to(ROOT)} — 全 {n} カード × {CS.SIG_DIM} 次元 "
          f"(効果/特徴あり {nonzero} = {nonzero/max(n,1)*100:.1f}%)")
    # 検証: 代表カードの sig 非ゼロ次元を表示
    print("=== 代表カードの sig (非ゼロ次元のみ) ===")
    for cid, label in [("OP14-119", "9ミホーク(除去)"), ("OP08-045", "サッチ(KO時draw)"),
                       ("OP05-098", "エネル(回復L)"), ("ST01-006", "サーチャー?")]:
        s = db.get(cid)
        if not s:
            print(f"  {cid} ({label}): 不在")
            continue
        nz = {k: round(v, 2) for k, v in s.items() if v != 0.0}
        print(f"  {cid} ({label}): {nz}")


if __name__ == "__main__":
    main()
