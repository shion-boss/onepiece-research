# -*- coding: utf-8 -*-
"""hand-prior 線形 combiner: データで各軸の scale を得つつ、 逆因果で誤符号になる戦略軸を
知識で正符号に矯正する(ohtsuki: 除去/手札破壊/盤面差/カード優位は "良い手" = 正、 self-play の
勝敗ラベルは「不利な時に除去するから負」の交絡を持つ)。

logistic を standardized 空間で fit → raw 軸単位の線形係数に展開 → 矯正対象の符号を +|w| に固定 →
{"kind":"linear","weights":{axis:w_raw},"bias":b} を保存。 combiner_pwin が sigmoid で P(win) 化。

  .venv/bin/python scripts/build_hand_prior_combiner.py --in db/_analyst/eval_vectors_29.jsonl \
      --out db/_selfplay/eval_combiner_handprior.pkl
"""
from __future__ import annotations
import argparse, json, pickle
from pathlib import Path
import numpy as np
from sklearn.linear_model import LogisticRegression

ROOT = Path(__file__).resolve().parent.parent

# 逆因果で負に出るが、 知識では "良い手" = 正であるべき戦略軸(符号を +|w| に固定)
FORCE_POSITIVE = {
    "threat_removed_power",  # 大きい脅威の除去(数でなく質)
    "opp_hand_removed",      # 手札破壊(ohtsuki weakness ③)
    "opp_field_removed",     # 盤面除去
    "opp_life_removed",      # ライフ削り
    "board_count_diff",      # 盤面枚数差(展開優位)
    "card_advantage",        # カード優位
    "my_avail_blocker",      # 防御駒
}
# 活動量そのものは価値でない(効率が価値)→ ほぼ 0 に抑える
SUPPRESS = {"plan_length", "cards_played", "don_used_this_turn"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="db/_analyst/eval_vectors_29.jsonl")
    ap.add_argument("--out", default="db/_selfplay/eval_combiner_handprior.pkl")
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(ROOT / a.inp, encoding="utf-8")]
    axes = list(rows[0]["vec"].keys())
    X = np.array([[r["vec"].get(k, 0.0) for k in axes] for r in rows], dtype=float)
    y = np.array([r["won"] for r in rows], dtype=float)
    mean = X.mean(axis=0); std = X.std(axis=0); std[std < 1e-9] = 1.0
    Xs = (X - mean) / std
    lr = LogisticRegression(max_iter=2000, C=1.0).fit(Xs, y)
    w_std = lr.coef_[0]
    b_std = float(lr.intercept_[0])

    # standardized → raw 軸単位: z = b_std + Σ w_std_i*(x_i-mean_i)/std_i
    w_raw = w_std / std
    b_raw = b_std - float(np.sum(w_std * mean / std))

    weights = {}
    for i, k in enumerate(axes):
        w = float(w_raw[i])
        if k in FORCE_POSITIVE:
            w = abs(w)            # 逆因果矯正: 良い手は正
        if k in SUPPRESS:
            w *= 0.1              # 活動量は価値でない
        weights[k] = w

    out = {"kind": "linear", "weights": weights, "bias": b_raw, "axes": axes}
    p = ROOT / a.out
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as f:
        pickle.dump(out, f)
    print(f"[hand-prior] saved -> {p}")
    print("  矯正した軸(符号を正に固定):")
    for k in axes:
        tag = ""
        if k in FORCE_POSITIVE:
            tag = " [FORCE+]"
        elif k in SUPPRESS:
            tag = " [suppress]"
        if tag:
            print(f"    {k:24} w={weights[k]:+.4f}{tag}")


if __name__ == "__main__":
    main()
