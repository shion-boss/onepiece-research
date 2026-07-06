"""多軸評価ベクトル → 勝率 の combiner を学習(ohtsuki: 人間=軸、 機械=combiner が weigh を学習)。

収集した eval_vectors から GBM combiner を訓練 → db/_selfplay/eval_combiner.pkl {model, axes}。
beam はこれで候補plan の評価ベクトルを P(win) に変換して最善手を選ぶ(= 生 value の代替)。

  .venv/bin/python scripts/train_eval_combiner.py --in db/_analyst/eval_vectors2.jsonl
"""
from __future__ import annotations
import argparse, json, pickle
from pathlib import Path
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="db/_analyst/eval_vectors2.jsonl")
    ap.add_argument("--out", default="db/_selfplay/eval_combiner.pkl")
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(ROOT / a.inp, encoding="utf-8")]
    axes = list(rows[0]["vec"].keys())
    X = np.array([[r["vec"].get(k, 0.0) for k in axes] for r in rows], dtype=float)
    y = np.array([r["won"] for r in rows], dtype=float)
    print(f"[data] {len(rows)} rec, {len(axes)} 軸, 勝率 {y.mean():.2f}")
    rng = np.random.RandomState(0)
    idx = rng.permutation(len(rows)); nho = max(1, len(rows) // 5)
    ho, tr = idx[:nho], idx[nho:]
    m = GradientBoostingClassifier(n_estimators=250, max_depth=3, subsample=0.8,
                                   learning_rate=0.05, random_state=0).fit(X[tr], y[tr])
    try:
        auc = roc_auc_score(y[ho], m.predict_proba(X[ho])[:, 1])
    except ValueError:
        auc = float("nan")
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as f:
        pickle.dump({"model": m, "axes": axes}, f)
    print(f"[combiner] held-out AUC={auc:.3f} -> {out} (axes={len(axes)})")


if __name__ == "__main__":
    main()
