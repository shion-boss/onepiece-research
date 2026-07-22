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
    ap.add_argument("--deploy-lam", type=float, default=0.5,
                    help="残差配備 λ (単一。 複数候補は --deploy-lams)")
    ap.add_argument("--deploy-lams", type=float, nargs="+", default=None,
                    help="複数 deploy-lam。 各 lam で候補 pkl を出力(A/B の arm 別)。 例: 0.15 0.3 0.5")
    ap.add_argument("--anchor", default=None, help="配備 value pkl(既定 db/value_gbm_<deck>.pkl)")
    ap.add_argument("--feat", default="v11", choices=["v11", "v12", "v13"],
                    help="残差 feature version (v13 = v6 + reserve×lethal 4 = パターンA 修正)")
    ap.add_argument("--out-prefix", default=None,
                    help="出力 pkl の basename prefix (既定 mcab_<deck>_<feat>cent)。 lam ごとに "
                         "'_res<lam>' を suffix 付与 (--deploy-lams 時)")
    ap.add_argument("--skip-gen", action="store_true", help="既存 data を再利用")
    a = ap.parse_args()

    anchor = a.anchor or f"db/value_gbm_{a.deck}.pkl"
    if not (ROOT / anchor).exists():
        print(f"!! anchor {anchor} 無し → この deck は残差アンカー不可(base value を先に用意 or --anchor 指定)")
        return 1

    feat = a.feat
    data = ROOT / "db" / "_analyst" / f"blockval_{a.deck}_{feat}.jsonl"
    if not a.skip_gen or not data.exists():
        print(f"=== [1/2] gen {feat} 塊帰結 data ({a.deck}) ===", flush=True)
        r = subprocess.run([PY, str(ROOT / "scripts" / "gen_block_value_targets.py"),
                            "--deck", a.deck, "--opponents", *a.opponents,
                            "--n-games", str(a.n_games), "--feat", feat,
                            # anchor value を生成ポリシー(--my-gbm-path)と target 値(--value-path)にも渡す。
                            # per-deck pkl 不在時に None フォールバック(bootstrap 無し)になる bug を防ぐ。
                            "--value-path", anchor, "--my-gbm-path", anchor,
                            "--out", f"db/_analyst/blockval_{a.deck}_{feat}.jsonl"])
        if r.returncode != 0:
            return r.returncode

    lams = a.deploy_lams if a.deploy_lams is not None else [a.deploy_lam]
    prefix = a.out_prefix or f"mcab_{a.deck}_{feat}cent"
    outs = []
    for i, lam in enumerate(lams):
        if len(lams) > 1:
            # lam タグ (0.15 -> res015, 0.3 -> res03, 0.5 -> res05) = A/B の arm 名に一致。
            # 小数点以下 2 桁 zero-pad ("0.15"->"015", "0.3"->"03") で衝突しない一意 tag に。
            frac = f"{lam:.2f}".split(".")[1]  # "15" / "30" / "50"
            frac = frac.rstrip("0") or "0"     # "15" / "3" / "5"
            tag = f"res0{frac}"                # res015 / res03 / res05
            out = f"db/_selfplay/mcab_{a.deck}_{tag}.pkl"
        else:
            out = f"db/_selfplay/{prefix}.pkl"
        print(f"=== [2/2] train centered residual [{i+1}/{len(lams)}] "
              f"(anchor={anchor}, feat={feat}, deploy_lam={lam}) ===", flush=True)
        r = subprocess.run([PY, str(ROOT / "scripts" / "train_block_value.py"),
                            "--in", f"db/_analyst/blockval_{a.deck}_{feat}.jsonl",
                            "--lam", str(a.lam), "--residual", anchor,
                            "--deploy-lam", str(lam), "--center", "--out", out])
        if r.returncode != 0:
            return r.returncode
        outs.append(out)

    print(f"\n[done] {len(outs)} candidate(s):")
    for o in outs:
        print(f"  {o}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
