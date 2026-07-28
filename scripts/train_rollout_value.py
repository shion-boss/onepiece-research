# -*- coding: utf-8 -*-
"""rollout-value 教師で rich value を学習 (2026-07-28、 条件(b) 蒸留)。

collect_rollout_value_data の (rich 特徴, rollout 帰結 0/1) を学習 → beam の value として使い、
arena で agnostic(現配備 value)を超えるか。 超えれば「rollout の move-quality を value に蒸留できた
= 成長ループの (b) クリア」。 dim は data から自動、 beam は dim で feature 版を自動判別。

  .venv/bin/python scripts/train_rollout_value.py --out db/_selfplay/value_rollout.pkl
"""
import argparse, json, pickle, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

CORPUS = ROOT / "db" / "_selfplay" / "rollout_value_corpus.jsonl"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(CORPUS))
    ap.add_argument("--out", default="db/_selfplay/value_rollout.pkl")
    a = ap.parse_args()
    t0 = time.time()
    X, y, g = [], [], []
    for line in open(a.corpus, encoding="utf-8"):
        try:
            d = json.loads(line)
            X.append(d["f"]); y.append(int(d["y"])); g.append(d.get("g", str(len(y))))
        except Exception:
            continue
    X = np.asarray(X, dtype=np.float32); y = np.asarray(y, dtype=np.int32); g = np.asarray(g)
    dim = X.shape[1]
    print(f"loaded {len(y):,} samples, dim={dim}, win率 {y.mean()*100:.1f}%, "
          f"groups={len(np.unique(g)):,} ({time.time()-t0:.0f}s)", flush=True)

    cap = dict(max_iter=800, max_leaf_nodes=31, learning_rate=0.05, l2_regularization=1.0,
               random_state=0, early_stopping=True, validation_fraction=0.1, n_iter_no_change=20)

    # held-out AUC (group=(局面,手) 単位 split、 leak 防止)
    uniq = np.unique(g); rng = np.random.RandomState(0)
    perm = rng.permutation(len(uniq))
    te = set(uniq[perm[int(len(uniq) * 0.8):]].tolist())
    is_te = np.fromiter((x in te for x in g), dtype=bool, count=len(y))
    tr, tei = np.flatnonzero(~is_te), np.flatnonzero(is_te)
    if len(np.unique(y[tr])) > 1 and len(tei) > 0 and len(np.unique(y[tei])) > 1:
        m = HistGradientBoostingClassifier(**cap); m.fit(X[tr], y[tr])
        auc = roc_auc_score(y[tei], m.predict_proba(X[tei])[:, 1])
        print(f"  held-out AUC = {auc:.4f} (⚠ 強さは arena で判定)", flush=True)

    model = HistGradientBoostingClassifier(**cap); model.fit(X, y)
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as f:
        pickle.dump(model, f)
    print(f"saved {out} (dim={dim}, {time.time()-t0:.0f}s)", flush=True)
    print(f"次: .venv/bin/python scripts/eiv1_arena.py --arm {a.out} --refs agnostic --pairs 80 --workers 12", flush=True)


if __name__ == "__main__":
    main()
