# -*- coding: utf-8 -*-
"""Plan B PoC: 小 NN(MLP)で rollout-value 回帰 (2026-07-28、 CPU torch)。

既存 rollout データ(collect_rl_data の (特徴, 割引 rollout-value))を小 MLP で学習。 GBM(feature 天井で
34-39% 飽和)を NN が超えるか = 「ボトルネックは model か input(特徴)か」の切り分け。
出力 = sklearn 互換 predict を持つ wrapper(pickle)→ ValuePolicyAI がそのまま使える。

  .venv/bin/python scripts/train_nn_value.py --corpus db/_selfplay/rl_iter0.jsonl [--corpus ...] \
      --out db/_selfplay/nn_value.pkl --hidden 256 --epochs 40
"""
import argparse, json, pickle, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np
import torch
import torch.nn as nn
from engine.nn_value_wrapper import MLP, NNWrapper


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", action="append", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--hidden", type=int, default=256)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--bs", type=int, default=512)
    a = ap.parse_args()
    t0 = time.time()
    torch.set_num_threads(8)
    X, y, g = [], [], []
    for c in a.corpus:
        for line in open(ROOT / c if not Path(c).is_absolute() else c, encoding="utf-8"):
            try:
                d = json.loads(line); X.append(d["f"]); y.append(float(d["y"])); g.append(d.get("g", str(len(y))))
            except Exception:
                continue
    X = np.asarray(X, dtype=np.float32); y = np.asarray(y, dtype=np.float32); g = np.asarray(g)
    dim = X.shape[1]
    mean = X.mean(0); std = X.std(0) + 1e-6
    Xn = (X - mean) / std
    # group split
    uniq = np.unique(g); rng = np.random.RandomState(0); perm = rng.permutation(len(uniq))
    te = set(uniq[perm[int(len(uniq) * 0.9):]].tolist())
    is_te = np.fromiter((x in te for x in g), dtype=bool, count=len(y))
    tri, tei = np.flatnonzero(~is_te), np.flatnonzero(is_te)
    Xt = torch.from_numpy(Xn[tri]); yt = torch.from_numpy(y[tri])
    Xv = torch.from_numpy(Xn[tei]); yv = torch.from_numpy(y[tei])
    print(f"loaded {len(y):,} samples, dim={dim}, mean_y={y.mean():.3f}, train {len(tri):,}/val {len(tei):,} "
          f"({time.time()-t0:.0f}s)", flush=True)

    m = MLP(dim, a.hidden)
    opt = torch.optim.Adam(m.parameters(), lr=1e-3, weight_decay=1e-5)
    lossf = nn.MSELoss()
    n = len(tri); best_rmse, best_sd = 9.9, None
    for ep in range(a.epochs):
        m.train(); idx = torch.randperm(n)
        for i in range(0, n, a.bs):
            b = idx[i:i + a.bs]
            opt.zero_grad(); out = m(Xt[b]); loss = lossf(out, yt[b]); loss.backward(); opt.step()
        m.eval()
        with torch.no_grad():
            rmse = float(((m(Xv) - yv) ** 2).mean() ** 0.5)
        if rmse < best_rmse:
            best_rmse = rmse; best_sd = {k: v.clone() for k, v in m.state_dict().items()}
        if ep % 5 == 0 or ep == a.epochs - 1:
            print(f"  ep{ep} val_rmse={rmse:.4f} (best {best_rmse:.4f}) {time.time()-t0:.0f}s", flush=True)
    base = float(((yv - y[tri].mean()) ** 2).mean() ** 0.5)
    print(f"  最良 val RMSE = {best_rmse:.4f} (baseline mean {base:.4f}) → {'改善' if best_rmse<base else '悪化'}", flush=True)

    wrap = NNWrapper(best_sd, dim, a.hidden, mean, std)
    out = ROOT / a.out; out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as f:
        pickle.dump(wrap, f)
    print(f"saved {out} ({time.time()-t0:.0f}s)  次: arena_policy AR_NEW={a.out}", flush=True)


if __name__ == "__main__":
    main()
