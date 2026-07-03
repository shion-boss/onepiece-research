"""勝ち構成(塊帰結target + v11threat + 残差アンカー + centering)を任意デッキに適用する driver。

docs/block_value_architecture.md の Phase 1 で cardrush_1454 が配備超え(+6.6pt、 3マッチ全正)した
構成を、 配備 value(anchor)を持つ deck に横展開する。 gen(v11 塊帰結)→ train(centered residual)を連鎖。

  .venv/bin/python scripts/build_block_residual_value.py --deck tcgportal_calgara \
      --opponents cardrush_1454 tcgportal_calgara tcgportal_bonney cardrush_1342 cardrush_1439 \
      --n-games 10 --deploy-lam 0.5

出力 = db/_selfplay/mcab_<deck>_v11cent.pkl(A/B 用)。 A/B 通過後に db/value_gbm_<deck>.pkl へ昇格。
anchor(db/value_gbm_<deck>.pkl)が無い deck は --anchor で指定(無ければ skip)。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "bin" / "python")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", required=True)
    ap.add_argument("--opponents", nargs="+", required=True)
    ap.add_argument("--n-games", type=int, default=10)
    ap.add_argument("--lam", type=float, default=0.5, help="塊target blend λ")
    ap.add_argument("--deploy-lam", type=float, default=0.5, help="残差配備 λ")
    ap.add_argument("--anchor", default=None, help="配備 value pkl(既定 db/value_gbm_<deck>.pkl)")
    ap.add_argument("--skip-gen", action="store_true", help="既存 v11 data を再利用")
    a = ap.parse_args()

    anchor = a.anchor or f"db/value_gbm_{a.deck}.pkl"
    if not (ROOT / anchor).exists():
        print(f"!! anchor {anchor} 無し → この deck は残差アンカー不可(base value を先に用意 or --anchor 指定)")
        return 1

    data = ROOT / "db" / "_analyst" / f"blockval_{a.deck}_v11.jsonl"
    if not a.skip_gen or not data.exists():
        print(f"=== [1/2] gen v11 塊帰結 data ({a.deck}) ===", flush=True)
        r = subprocess.run([PY, str(ROOT / "scripts" / "gen_block_value_targets.py"),
                            "--deck", a.deck, "--opponents", *a.opponents,
                            "--n-games", str(a.n_games), "--feat", "v11",
                            "--out", f"db/_analyst/blockval_{a.deck}_v11.jsonl"])
        if r.returncode != 0:
            return r.returncode

    out = f"db/_selfplay/mcab_{a.deck}_v11cent.pkl"
    print(f"=== [2/2] train centered residual (anchor={anchor}, deploy_lam={a.deploy_lam}) ===", flush=True)
    r = subprocess.run([PY, str(ROOT / "scripts" / "train_block_value.py"),
                        "--in", f"db/_analyst/blockval_{a.deck}_v11.jsonl",
                        "--lam", str(a.lam), "--residual", anchor,
                        "--deploy-lam", str(a.deploy_lam), "--center", "--out", out])
    if r.returncode != 0:
        return r.returncode
    print(f"\n[done] {out}  → A/B: matchup_value_deploy_ab.py --deck {a.deck} --arms default,v11cent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
