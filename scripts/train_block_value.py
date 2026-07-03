"""塊帰結 target で value を訓練 — 単発 MC を捨てる本丸(docs/block_value_architecture.md Phase 1)。

blockval_<deck>.jsonl の各 round-sample を、 target = λ·mc + (1-λ)·v_next で回帰:
  - λ=1.0 : 純 Monte Carlo(= 現状の単発ラベル。 ベースライン比較用)
  - λ=0.0 : 純 TD(1-round)= 塊の帰結値だけ(低分散だが配備 value の bias を継承)
  - λ=0.5 : TD(λ) ブレンド(bias-variance トレードオフ、 標準)

held-out で AUC(mc を正解ラベルに)+ 分散を出し、 GradientBoostingRegressor を
value_gbm_<deck>_block.pkl に保存。 A/B は gbm_path 強制の配備ミラーで別途。

  .venv/bin/python scripts/train_block_value.py --in db/_analyst/blockval_cardrush_1454.jsonl \
      --lam 0.5 --out db/value_gbm_cardrush_1454_block.pkl
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--lam", type=float, default=0.5, help="target = lam*mc + (1-lam)*v_next")
    ap.add_argument("--out", required=True)
    ap.add_argument("--holdout", type=float, default=0.2)
    ap.add_argument("--residual", default=None,
                    help="残差アンカー mode: 配備 value pkl path。 resid = 塊target - v_self を学習し "
                         "{kind:block_residual, anchor, resid, lam} を保存(小サンプルでも補正だけ学ぶ)")
    ap.add_argument("--deploy-lam", type=float, default=1.0,
                    help="残差 mode の配備時 λ (V_new = V_配備 + deploy_lam*resid、 0=厳密配備 floor)")
    ap.add_argument("--center", action="store_true",
                    help="残差 target から一律 calibration シフトを除き feature条件付き補正だけ残す")
    a = ap.parse_args()

    rows = [json.loads(l) for l in open(ROOT / a.inp, encoding="utf-8")]
    # v_next / v_self が None(bootstrap value 無し)の行は除外
    rows = [r for r in rows if r.get("v_next") is not None]
    X = np.array([r["feat"] for r in rows], dtype=float)
    mc = np.array([r["mc"] for r in rows], dtype=float)
    v_next = np.array([r["v_next"] for r in rows], dtype=float)
    v_self = np.array([r.get("v_self") if r.get("v_self") is not None else 0.5 for r in rows],
                      dtype=float)
    y = a.lam * mc + (1.0 - a.lam) * v_next

    print(f"[data] {len(rows)} round-samples, feat dim={X.shape[1]}, mc勝率={mc.mean():.2f}")
    # target 質の比較: mc(単発, 分散大) vs v_next(塊帰結, 低分散)
    print(f"[target] mc var={mc.var():.4f}  v_next var={v_next.var():.4f}  "
          f"blend(lam={a.lam}) var={y.var():.4f}")
    # per-round advantage(v_next - v_self)= その塊が盤面を改善/悪化させたか(Plan②検出の芽)
    adv = v_next - v_self
    print(f"[round-advantage] mean={adv.mean():+.4f} std={adv.std():.4f}  "
          f"悪化round(adv<-0.05)={100*np.mean(adv<-0.05):.0f}%  改善round(adv>+0.05)={100*np.mean(adv>0.05):.0f}%")

    # held-out split
    rng = np.random.RandomState(42)
    idx = rng.permutation(len(rows))
    n_ho = max(1, int(len(rows) * a.holdout))
    ho, tr = idx[:n_ho], idx[n_ho:]

    import pickle
    out = ROOT / a.out

    if a.residual:
        # 残差アンカー: resid = 塊target - v_self を v11 feat で学習。 配備 value を base に補正だけ。
        anchor = pickle.load(open(ROOT / a.residual, "rb"))
        resid_target = y - v_self  # y=塊target, v_self=配備 value P(win)
        shift = float(resid_target.mean())
        if a.center:
            # 一律の calibration シフトを除き feature条件付きの補正だけ残す(配備 value の水準を保つ)。
            # aggro 悪化の原因が「一律楽観シフト」なら、 これで消えるはず。
            resid_target = resid_target - shift
        print(f"[residual] anchor={a.residual} (dim={getattr(anchor,'n_features_in_','?')})  "
              f"resid_target: mean={resid_target.mean():+.3f} std={resid_target.std():.3f} "
              f"(center={a.center}, 除去シフト={shift:+.3f})")
        # 過学習を抑えるため浅く・強正則化(補正は小さいはず)
        resid = GradientBoostingRegressor(n_estimators=200, max_depth=2, learning_rate=0.03,
                                          subsample=0.7, random_state=0)
        resid.fit(X[tr], resid_target[tr])
        # holdout: V_new = clip(v_self + deploy_lam*resid) の AUC(vs mc)
        pred_resid = resid.predict(X[ho])
        p_new = np.clip(v_self[ho] + a.deploy_lam * pred_resid, 0, 1)
        p_base = np.clip(v_self[ho], 0, 1)
        try:
            auc_new = roc_auc_score(mc[ho], p_new)
            auc_base = roc_auc_score(mc[ho], p_base)
        except ValueError:
            auc_new = auc_base = float("nan")
        print(f"[holdout] n={n_ho}  AUC 配備base={auc_base:.3f} -> block_residual={auc_new:.3f} "
              f"(deploy_lam={a.deploy_lam})")
        with open(out, "wb") as f:
            pickle.dump({"kind": "block_residual", "anchor": anchor, "resid": resid,
                         "lam": a.deploy_lam}, f)
        print(f"[saved] {out}  (block_residual, resid dim={X.shape[1]}, deploy_lam={a.deploy_lam})")
        return

    model = GradientBoostingRegressor(n_estimators=300, max_depth=3, learning_rate=0.05,
                                      subsample=0.8, random_state=0)
    model.fit(X[tr], y[tr])

    pred_ho = np.clip(model.predict(X[ho]), 0, 1)
    # AUC は mc(真の勝敗)を正解に(value の ranking 力を測る)
    try:
        auc = roc_auc_score(mc[ho], pred_ho)
    except ValueError:
        auc = float("nan")
    mse = float(np.mean((pred_ho - y[ho]) ** 2))
    print(f"[holdout] n={n_ho}  AUC(vs mc)={auc:.3f}  MSE(vs target)={mse:.4f}")

    with open(out, "wb") as f:
        pickle.dump(model, f)
    print(f"[saved] {out}  (dim={X.shape[1]}, lam={a.lam})")


if __name__ == "__main__":
    main()
