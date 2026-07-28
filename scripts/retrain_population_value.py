# -*- coding: utf-8 -*-
"""population-diverse value 再学習 (2026-07-28、 Stage 1)。

population_corpus(pilot 多様)を main corpus(deck 多様・pilot homogeneous)にミックスし、
population を upweight して再学習 = 「多様 deck × 多様 pilot」の分布で value を作る。
degeneracy(aggro 局所最適)対策の第一トライ。 arena で強さ、 plan_realization で control 挙動を gate。

  .venv/bin/python scripts/retrain_population_value.py --corpus-rows 300000 --pop-weight 5.0
出力: db/_selfplay/value_population.pkl
"""
import argparse, json, pickle, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

DIM = 21
POP = ROOT / "db" / "_selfplay" / "population_corpus.jsonl"
CORPUS = ROOT / "db" / "eiv1" / "corpus.jsonl"


def _load(path, max_rows, gid_prefix):
    X, y, g = [], [], []
    prev_key, run = None, 0
    for i, line in enumerate(open(path, encoding="utf-8")):
        if max_rows and i >= max_rows:
            break
        try:
            d = json.loads(line)
            f = d.get("f")
            if not f or len(f) < DIM:
                continue
            X.append(f[:DIM]); y.append(int(d["y"]))
            key = (d.get("y"), d.get("hero"), d.get("ph") or d.get("opp"))
            if key != prev_key:
                run += 1; prev_key = key
            g.append(f"{gid_prefix}{run}")
        except Exception:
            continue
    return X, y, g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus-rows", type=int, default=300000, help="混ぜる main corpus 行数(0=無し)")
    ap.add_argument("--pop-weight", type=float, default=5.0, help="population sample の重み")
    ap.add_argument("--pop-path", default=str(POP), help="population corpus path")
    ap.add_argument("--out", default="db/_selfplay/value_population.pkl")
    a = ap.parse_args()
    t0 = time.time()

    Xp, yp, gp = _load(Path(a.pop_path), 0, "pop")
    print(f"population: {len(yp):,} samples, win率 {np.mean(yp)*100:.1f}%", flush=True)
    Xc, yc, gc = ([], [], [])
    if a.corpus_rows > 0:
        Xc, yc, gc = _load(CORPUS, a.corpus_rows, "cor")
        print(f"main corpus: {len(yc):,} samples, win率 {np.mean(yc)*100:.1f}%", flush=True)

    X = np.asarray(Xp + Xc, dtype=np.float32)
    y = np.asarray(yp + yc, dtype=np.int32)
    g = np.asarray(gp + gc)
    w = np.asarray([a.pop_weight] * len(yp) + [1.0] * len(yc), dtype=np.float32)
    print(f"combined: {len(y):,} samples (pop weight={a.pop_weight})", flush=True)

    cap = dict(max_iter=1000, max_leaf_nodes=63, learning_rate=0.05, l2_regularization=1.0,
               random_state=0, early_stopping=True, validation_fraction=0.1, n_iter_no_change=20)

    # held-out AUC (game/run 単位 split)
    uniq = np.unique(g); rng = np.random.RandomState(0)
    perm = rng.permutation(len(uniq))
    te_ids = set(uniq[perm[int(len(uniq) * 0.8):]].tolist())
    is_te = np.fromiter((x in te_ids for x in g), dtype=bool, count=len(y))
    tr, te = np.flatnonzero(~is_te), np.flatnonzero(is_te)
    m = HistGradientBoostingClassifier(**cap)
    m.fit(X[tr], y[tr], sample_weight=w[tr])
    auc = roc_auc_score(y[te], m.predict_proba(X[te])[:, 1])
    print(f"  held-out AUC = {auc:.4f} (⚠ 強さは arena で判定)", flush=True)

    model = HistGradientBoostingClassifier(**cap)
    model.fit(X, y, sample_weight=w)
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as f:
        pickle.dump(model, f)
    print(f"saved {out} ({time.time()-t0:.0f}s)", flush=True)
    print(f"次: .venv/bin/python scripts/eiv1_arena.py --arm {a.out} --refs agnostic --pairs 80 --workers 12", flush=True)


if __name__ == "__main__":
    main()
