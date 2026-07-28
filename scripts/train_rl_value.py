# -*- coding: utf-8 -*-
"""RL ループ: 割引 rollout-value を regressor 学習 (2026-07-28)。

collect_rl_data の (rich 特徴, 割引 value γ^手数) を HistGradientBoostingRegressor で学習。
複数 jsonl を渡せば累積学習(DAgger: 過去 iter + 今 iter)。 ValuePolicyAI が predict でこれを使う。

  .venv/bin/python scripts/train_rl_value.py --corpus db/_selfplay/rl_iter0.jsonl [--corpus ...] --out db/_selfplay/rl_value0.pkl
"""
import argparse, json, pickle, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_squared_error


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", action="append", required=True, help="jsonl(複数可=累積)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    t0 = time.time()
    X, y, g = [], [], []
    for c in a.corpus:
        for line in open(ROOT / c if not Path(c).is_absolute() else c, encoding="utf-8"):
            try:
                d = json.loads(line)
                X.append(d["f"]); y.append(float(d["y"])); g.append(d.get("g", str(len(y))))
            except Exception:
                continue
    X = np.asarray(X, dtype=np.float32); y = np.asarray(y, dtype=np.float32); g = np.asarray(g)
    print(f"loaded {len(y):,} samples, dim={X.shape[1]}, mean_y={y.mean():.3f}, "
          f"groups={len(np.unique(g)):,} ({time.time()-t0:.0f}s)", flush=True)

    cap = dict(max_iter=800, max_leaf_nodes=31, learning_rate=0.05, l2_regularization=1.0,
               random_state=0, early_stopping=True, validation_fraction=0.1, n_iter_no_change=20)

    uniq = np.unique(g); rng = np.random.RandomState(0)
    perm = rng.permutation(len(uniq))
    te = set(uniq[perm[int(len(uniq) * 0.85):]].tolist())
    is_te = np.fromiter((x in te for x in g), dtype=bool, count=len(y))
    tr, tei = np.flatnonzero(~is_te), np.flatnonzero(is_te)
    if len(tei) > 0:
        m = HistGradientBoostingRegressor(**cap); m.fit(X[tr], y[tr])
        rmse = mean_squared_error(y[tei], m.predict(X[tei])) ** 0.5
        # baseline = 常に mean を予測した場合の RMSE
        base = mean_squared_error(y[tei], np.full(len(tei), y[tr].mean())) ** 0.5
        print(f"  held-out RMSE = {rmse:.4f} (baseline mean {base:.4f}) → {'改善' if rmse<base else '悪化'} "
              f"(⚠ 強さは arena で判定)", flush=True)

    model = HistGradientBoostingRegressor(**cap); model.fit(X, y)
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as f:
        pickle.dump(model, f)
    print(f"saved {out} ({time.time()-t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
