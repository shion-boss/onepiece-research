"""評価ベクトルの分析(ohtsuki 期待): (A)「この評価値の時にこう動くと状況が良くなる」パターン、
(B)評価関数同士の相関/組合せ、 + combiner 学習(評価ベクトル→勝率)。

  .venv/bin/python scripts/analyze_eval_vectors.py --in db/_analyst/eval_vectors.jsonl

出力:
1. 各軸 vs 勝敗 の相関(= どの軸が勝ちを予測するか。 解釈可能)
2. 軸同士の相関行列 上位(= 冗長/関連する軸の組合せ)
3. 学習 combiner(logistic = 解釈可能な重み / GBM = 非線形 + AUC)
4. per-turn advantage(next_vec - vec)= 「その塊で改善した軸」と勝敗の関係
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="db/_analyst/eval_vectors.jsonl")
    ap.add_argument("--top", type=int, default=15)
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(ROOT / a.inp, encoding="utf-8")]
    if not rows:
        print("no data"); return
    axes = list(rows[0]["vec"].keys())
    X = np.array([[r["vec"].get(k, 0.0) for k in axes] for r in rows], dtype=float)
    y = np.array([r["won"] for r in rows], dtype=float)
    print(f"[data] {len(rows)} turn-records, {len(axes)} 軸, 勝ちラベル率 {y.mean():.2f}")

    # ── (A) 各軸 vs 勝敗 の相関(解釈可能: どの軸が勝ちに効くか) ──────────────
    print("\n=== (A) 各軸 と 勝敗 の相関(| 相関 | 降順)= 勝ちを予測する軸 ===")
    cors = []
    for i, k in enumerate(axes):
        col = X[:, i]
        if col.std() < 1e-9:
            cors.append((k, 0.0)); continue
        c = np.corrcoef(col, y)[0, 1]
        cors.append((k, c if not np.isnan(c) else 0.0))
    for k, c in sorted(cors, key=lambda x: -abs(x[1]))[:a.top]:
        arrow = "勝ちに正" if c > 0 else "勝ちに負"
        print(f"  {k:24} r={c:+.3f}  ({arrow})")

    # ── (B) 軸同士の相関(冗長/組合せ) ─────────────────────────────────────
    print("\n=== (B) 軸同士の相関 上位(|r|>0.5 = 冗長 or 強い組合せ)===")
    C = np.corrcoef(X.T)
    pairs = []
    for i in range(len(axes)):
        for j in range(i + 1, len(axes)):
            if not np.isnan(C[i, j]):
                pairs.append((abs(C[i, j]), C[i, j], axes[i], axes[j]))
    for _, c, ki, kj in sorted(pairs, reverse=True)[:a.top]:
        if abs(c) < 0.5:
            break
        print(f"  {ki:22} <-> {kj:22} r={c:+.3f}")

    # ── (C) 学習 combiner ────────────────────────────────────────────────
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score
    rng = np.random.RandomState(0)
    idx = rng.permutation(len(rows)); nho = max(1, len(rows) // 5)
    ho, tr = idx[:nho], idx[nho:]
    Xs = StandardScaler().fit_transform(X)
    lr = LogisticRegression(max_iter=1000, C=1.0).fit(Xs[tr], y[tr])
    try:
        auc_lr = roc_auc_score(y[ho], lr.predict_proba(Xs[ho])[:, 1])
    except ValueError:
        auc_lr = float("nan")
    print(f"\n=== (C) combiner: logistic(解釈可能な重み)held-out AUC={auc_lr:.3f} ===")
    coef = list(zip(axes, lr.coef_[0]))
    print("  勝ちに効く軸(係数、 正=勝ちに寄与):")
    for k, w in sorted(coef, key=lambda x: -abs(x[1]))[:a.top]:
        print(f"    {k:24} w={w:+.3f}")
    gb = GradientBoostingClassifier(n_estimators=200, max_depth=3, subsample=0.8,
                                    random_state=0).fit(X[tr], y[tr])
    try:
        auc_gb = roc_auc_score(y[ho], gb.predict_proba(X[ho])[:, 1])
    except ValueError:
        auc_gb = float("nan")
    print(f"  combiner: GBM(非線形)held-out AUC={auc_gb:.3f}")
    imp = sorted(zip(axes, gb.feature_importances_), key=lambda x: -x[1])[:a.top]
    print("  GBM 重要度上位:")
    for k, im in imp:
        print(f"    {k:24} {im:.3f}")

    # ── (D) 塊 advantage: next_vec - vec が勝ちと関係するか ────────────────
    adv_rows = [r for r in rows if r.get("next_vec")]
    if adv_rows:
        print(f"\n=== (D) 塊 advantage(next_vec - vec)と勝敗({len(adv_rows)} rec)===")
        A = np.array([[r["next_vec"].get(k, 0.0) - r["vec"].get(k, 0.0) for k in axes] for r in adv_rows])
        ya = np.array([r["won"] for r in adv_rows], dtype=float)
        advc = []
        for i, k in enumerate(axes):
            col = A[:, i]
            if col.std() < 1e-9:
                continue
            c = np.corrcoef(col, ya)[0, 1]
            advc.append((k, c if not np.isnan(c) else 0.0))
        print("  「その塊でこの軸が改善する」と勝ちの相関(= 良くなる方向):")
        for k, c in sorted(advc, key=lambda x: -abs(x[1]))[:8]:
            print(f"    {k:24} r={c:+.3f}")


if __name__ == "__main__":
    main()
