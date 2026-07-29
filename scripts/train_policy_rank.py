# -*- coding: utf-8 -*-
"""Plan B: policy(is-best 分類)学習 (2026-07-28)。

既存 rollout データ(collect_rl_data の (post-action 特徴, 割引 rollout-value, group=seed_heromove_ci))を
**局面単位で再ラベル**: 各局面(seed_heromove)で候補ごとの avg rollout-value を出し、 argmax 候補を best=1、
他を 0。 分類学習(P(best|特徴))= policy。 value(絶対勝率、 飽和)でなく ranking(which is best、 易しい)を学習。
ValuePolicyAI が predict_proba(classifier)でこれを使い、 P(best) argmax で手選択。

  .venv/bin/python scripts/train_policy_rank.py --corpus db/_selfplay/rl_iter0.jsonl --corpus ... --out db/_selfplay/policy_rank.pkl
"""
import argparse, json, pickle, sys, time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", action="append", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    t0 = time.time()
    # 局面 → 候補(ci) → [rows]。 各 row = (f, y)
    pos = defaultdict(lambda: defaultdict(list))  # (seed,heromove) -> ci -> [(f,y)]
    for c in a.corpus:
        for line in open(ROOT / c if not Path(c).is_absolute() else c, encoding="utf-8"):
            try:
                d = json.loads(line)
                g = d.get("g", "")
                parts = g.rsplit("_", 1)
                if len(parts) != 2:
                    continue
                position, ci = parts[0], parts[1]
                pos[position][ci].append((d["f"], float(d["y"])))
            except Exception:
                continue

    X, y, grp = [], [], []
    n_pos = 0
    for position, cands in pos.items():
        if len(cands) < 2:
            continue
        n_pos += 1
        # 各候補の avg rollout-value
        avg = {ci: (sum(v for _, v in rows) / len(rows)) for ci, rows in cands.items()}
        best_ci = max(avg, key=avg.get)
        for ci, rows in cands.items():
            lbl = 1 if ci == best_ci else 0
            f = rows[0][0]  # 同一候補は同一 f(post-action state)
            X.append(f); y.append(lbl); grp.append(position)
    X = np.asarray(X, dtype=np.float32); y = np.asarray(y, dtype=np.int32); grp = np.asarray(grp)
    print(f"positions={n_pos:,}, samples={len(y):,}(候補), dim={X.shape[1]}, best率={y.mean()*100:.1f}% "
          f"({time.time()-t0:.0f}s)", flush=True)

    cap = dict(max_iter=800, max_leaf_nodes=31, learning_rate=0.05, l2_regularization=1.0,
               random_state=0, early_stopping=True, validation_fraction=0.1, n_iter_no_change=20)
    uniq = np.unique(grp); rng = np.random.RandomState(0)
    perm = rng.permutation(len(uniq))
    te = set(uniq[perm[int(len(uniq) * 0.85):]].tolist())
    is_te = np.fromiter((x in te for x in grp), dtype=bool, count=len(y))
    tr, tei = np.flatnonzero(~is_te), np.flatnonzero(is_te)
    if len(np.unique(y[tr])) > 1 and len(np.unique(y[tei])) > 1:
        m = HistGradientBoostingClassifier(**cap); m.fit(X[tr], y[tr])
        auc = roc_auc_score(y[tei], m.predict_proba(X[tei])[:, 1])
        print(f"  held-out AUC(is-best) = {auc:.4f} (⚠ 強さは arena で判定)", flush=True)

    model = HistGradientBoostingClassifier(**cap); model.fit(X, y)
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as f:
        pickle.dump(model, f)
    print(f"saved {out} ({time.time()-t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
