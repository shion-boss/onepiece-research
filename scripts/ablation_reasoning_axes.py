# -*- coding: utf-8 -*-
"""推論軸(盤面外)が盤面軸を超える新しい予測情報を持つか = ablation。

board-only / board+推論 / 推論-only の 3 combiner を held-out AUC で比較。
board+推論 の AUC が board-only を上回れば、 推論軸は value(盤面)が見られない情報を運んでいる
= 手を変えうる。 同じなら冗長。 + 各推論軸単体の勝敗相関も出す。

  .venv/bin/python scripts/ablation_reasoning_axes.py --in db/_analyst/eval_vectors_reason.jsonl
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parent.parent

# 盤面外(隠匿情報 / 推論 = value が構造的に見られない)
NONBOARD = {
    "opp_counter_threat", "opp_blocker_prob",          # belief(相手隠し手札)
    "forced_defense", "forced_vs_counter",             # 攻撃の強制(game-theoretic)
    "effects_used", "effect_potential_left", "my_effect_sources_idle",  # 効果活用/取りこぼし
    "don_cospa",                                        # DON コスパ(比 = tree 非合成)
}


def auc_of(X, y, cols, tr, ho):
    if not cols:
        return float("nan")
    Xs = X[:, cols]
    m = GradientBoostingClassifier(n_estimators=250, max_depth=3, subsample=0.8,
                                   learning_rate=0.05, random_state=0).fit(Xs[tr], y[tr])
    try:
        return roc_auc_score(y[ho], m.predict_proba(Xs[ho])[:, 1])
    except ValueError:
        return float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="db/_analyst/eval_vectors_reason.jsonl")
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(ROOT / a.inp, encoding="utf-8")]
    axes = list(rows[0]["vec"].keys())
    X = np.array([[r["vec"].get(k, 0.0) for k in axes] for r in rows], dtype=float)
    y = np.array([r["won"] for r in rows], dtype=float)
    print(f"[data] {len(rows)} rec, {len(axes)} 軸, 勝率 {y.mean():.2f}")

    board_cols = [i for i, k in enumerate(axes) if k not in NONBOARD]
    nb_cols = [i for i, k in enumerate(axes) if k in NONBOARD]
    all_cols = list(range(len(axes)))
    print(f"  盤面軸 {len(board_cols)} / 推論軸(盤面外) {len(nb_cols)}")

    rng = np.random.RandomState(0)
    idx = rng.permutation(len(rows)); nho = max(1, len(rows) // 5)
    ho, tr = idx[:nho], idx[nho:]

    auc_board = auc_of(X, y, board_cols, tr, ho)
    auc_all = auc_of(X, y, all_cols, tr, ho)
    auc_nb = auc_of(X, y, nb_cols, tr, ho)
    print("\n=== ablation: held-out AUC ===")
    print(f"  board-only        : {auc_board:.4f}")
    print(f"  board + 推論       : {auc_all:.4f}   (lift {auc_all-auc_board:+.4f})")
    print(f"  推論-only          : {auc_nb:.4f}")
    verdict = "推論軸は新情報を運ぶ(手を変えうる)" if (auc_all - auc_board) > 0.005 else \
              "推論軸は盤面軸と冗長(lift 無)"
    print(f"  → {verdict}")

    # 各推論軸単体の勝敗相関
    print("\n=== 各推論軸 と 勝敗 の相関 ===")
    cors = []
    for i, k in enumerate(axes):
        if k not in NONBOARD:
            continue
        col = X[:, i]
        if col.std() < 1e-9:
            cors.append((k, 0.0, col.mean())); continue
        c = np.corrcoef(col, y)[0, 1]
        cors.append((k, c if not np.isnan(c) else 0.0, col.mean()))
    for k, c, mu in sorted(cors, key=lambda x: -abs(x[1])):
        print(f"  {k:24} r={c:+.3f}  (mean {mu:+.2f})")


if __name__ == "__main__":
    main()
