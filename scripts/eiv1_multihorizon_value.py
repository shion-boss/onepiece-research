"""多ホライズン target value = averaged n-step で分散↓した効率的スカラー value — 2026-07-25。

corpus の各局面 s_t に対し、 同一ゲームの s_{t+K} を lookup → 現 value で bootstrap し、
target(s_t) = mean([ 終局MC y, v_cur(s_{t+2}), v_cur(s_{t+4}) ]) を作る (averaged n-step、
[2402.03903] 分散↓)。 回帰器 value_multihorizon.pkl を学習 (drop-in スカラー、 gbm_score が
predict 経路で自動対応)。 追加 self-play sim ゼロ (既存 corpus のゲーム軌跡のみ)。

⚠ AUC は sanity のみ (強さの指標でない=今季実証)。 採否は arena A/B で判定:
  .venv/bin/python scripts/eiv1_gate_candidate.py --candidate db/eiv1/value_multihorizon.pkl ...

  .venv/bin/python scripts/eiv1_multihorizon_value.py --tail-mb 180 --horizons 2 4
"""
from __future__ import annotations
import argparse
import json
import os
import pickle
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
from sklearn.ensemble import HistGradientBoostingRegressor  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402

from engine.eiv1_features import eiv1_train_vector  # noqa: E402

EIV1 = ROOT / "db" / "eiv1"
CORPUS = EIV1 / "corpus.jsonl"
VALUE = EIV1 / "value.pkl"
OUT = EIV1 / "value_multihorizon.pkl"


def _read_tail(tail_mb: int) -> list:
    fsize = os.path.getsize(CORPUS)
    tb = min(fsize, tail_mb * 1024 * 1024)
    with open(CORPUS, "rb") as f:
        f.seek(fsize - tb)
        raw = f.read().split(b"\n")
    if tb < fsize and raw:
        raw = raw[1:]
    rows = []
    for ln in raw:
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except Exception:
            continue
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tail-mb", type=int, default=180)
    ap.add_argument("--horizons", type=int, nargs="+", default=[2, 4])
    a = ap.parse_args()

    with open(VALUE, "rb") as f:
        model = pickle.load(f)
    exp = int(getattr(model, "n_features_in_", 0) or 0)
    t0 = time.time()
    rows = _read_tail(a.tail_mb)
    print(f"corpus tail: {len(rows):,} 局面 ({time.time()-t0:.0f}s)", flush=True)

    # ゲーム単位に group: (g, turn) → 代表局面 index。 特徴と y は逐次。
    feats, ys, gkey = [], [], []
    for d in rows:
        try:
            v = eiv1_train_vector(d)
            if exp and len(v) != exp:
                feats.append(None); ys.append(0); gkey.append(None); continue
            feats.append(np.asarray(v, dtype=np.float32))
            ys.append(int(d.get("y", 0)))
            st = d.get("state") or {}
            gkey.append((d.get("g"), int(st.get("turn_number") or 0)))
        except Exception:
            feats.append(None); ys.append(0); gkey.append(None)
    print(f"featurize 完了 ({time.time()-t0:.0f}s)", flush=True)

    # (g, turn) → その局面の現 value 予測 (bootstrap 用)。 バッチ predict。
    valid = [i for i, fv in enumerate(feats) if fv is not None]
    X_all = np.stack([feats[i] for i in valid])
    if hasattr(model, "predict_proba"):
        vpred_all = model.predict_proba(X_all)[:, 1]
    else:
        vpred_all = np.clip(model.predict(X_all), 0.0, 1.0)
    vpred = {}
    for j, i in enumerate(valid):
        vpred[i] = float(vpred_all[j])
    gt_to_idx = {}
    for i in valid:
        if gkey[i] is not None:
            gt_to_idx[gkey[i]] = i   # 同 (g,turn) が複数なら後勝ち (代表)
    print(f"bootstrap 予測 完了 ({time.time()-t0:.0f}s)", flush=True)

    # averaged 多ホライズン target
    X, T, Y = [], [], []
    for i in valid:
        g_t = gkey[i]
        if g_t is None:
            continue
        g, t = g_t
        terms = [float(ys[i])]                     # 終局 MC (= 現 value と同じ)
        for k in a.horizons:
            j = gt_to_idx.get((g, t + k))
            if j is not None:
                terms.append(vpred[j])             # k-step bootstrap
        X.append(feats[i]); T.append(float(np.mean(terms))); Y.append(int(ys[i]))
    X = np.stack(X); T = np.array(T, dtype=np.float32); Y = np.array(Y, dtype=np.int32)
    n = len(T)
    print(f"多ホライズン target 構築: {n:,} 局面 (horizons={a.horizons})", flush=True)

    # 学習 (回帰: averaged target)。 容量は eiv1_train と同水準。
    cap = dict(max_iter=min(1000, max(100, n // 400)), max_leaf_nodes=63,
               learning_rate=0.05, l2_regularization=1.0, random_state=0)
    rng = np.random.RandomState(0)
    perm = rng.permutation(n)
    tr, te = perm[: int(n * 0.85)], perm[int(n * 0.85):]
    m = HistGradientBoostingRegressor(**cap)
    m.fit(X[tr], T[tr])
    # sanity: held-out で 実 y に対する AUC (⚠ 強さの指標でない)
    pred_te = np.clip(m.predict(X[te]), 0.0, 1.0)
    try:
        auc = roc_auc_score(Y[te], pred_te)
    except Exception:
        auc = float("nan")
    # baseline: 現 value の held-out AUC (同 y)
    base_te = model.predict_proba(X[te])[:, 1] if hasattr(model, "predict_proba") else np.clip(model.predict(X[te]), 0, 1)
    try:
        base_auc = roc_auc_score(Y[te], base_te)
    except Exception:
        base_auc = float("nan")
    print(f"  sanity held-out AUC vs y: multihorizon={auc:.4f} / 現value baseline={base_auc:.4f} "
          f"(⚠ AUC≠強さ、 採否は arena)", flush=True)

    model_full = HistGradientBoostingRegressor(**cap)
    model_full.fit(X, T)
    with open(OUT, "wb") as f:
        pickle.dump(model_full, f)
    print(f"  saved {OUT} (regressor, {n:,} 局面, cap max_iter={cap['max_iter']})", flush=True)
    print(f"次: arena A/B → .venv/bin/python scripts/eiv1_gate_candidate.py "
          f"--candidate {OUT.relative_to(ROOT)} ...", flush=True)


if __name__ == "__main__":
    main()
