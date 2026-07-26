"""sig(card) 盤面合成特徴 (v21) の de-risk — 2026-07-27。

同一 corpus・同一 y で v20(94)と v21(94+sig24)の value を学習し、 arena で head-to-head。
= sig 盤面合成の効果だけを isolate (data-matched)。 AUC でなく arena が判定 (今季の鉄則)。

  train: .venv/bin/python scripts/eiv1_sig_derisk.py --tail-mb 200
  arena: .venv/bin/python scripts/eiv1_arena.py --arm db/eiv1/value_sig_v21.pkl \
             --refs db/eiv1/value_sig_v20base.pkl --pairs 60 --workers 10
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
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402

from engine.eiv1_features import eiv1_train_vector, sig_board_feats_from_snapshot  # noqa: E402

EIV1 = ROOT / "db" / "eiv1"
CORPUS = EIV1 / "corpus.jsonl"
OUT_V21 = EIV1 / "value_sig_v21.pkl"
OUT_V20 = EIV1 / "value_sig_v20base.pkl"


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
        if ln:
            try:
                rows.append(json.loads(ln))
            except Exception:
                pass
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tail-mb", type=int, default=200)
    a = ap.parse_args()
    t0 = time.time()
    rows = _read_tail(a.tail_mb)
    print(f"corpus tail: {len(rows):,} 局面 ({time.time()-t0:.0f}s)", flush=True)

    X20, X21, Y = [], [], []
    for d in rows:
        snap = d.get("state")
        if not snap:
            continue
        try:
            v20 = eiv1_train_vector(d)
            if len(v20) != 94:            # feature_spec 混在等は除外 (v20 純正のみ)
                continue
            sig = sig_board_feats_from_snapshot(snap)
            X20.append(v20)
            X21.append(v20 + sig)
            Y.append(int(d.get("y", 0)))
        except Exception:
            continue
    X20 = np.asarray(X20, dtype=np.float32)
    X21 = np.asarray(X21, dtype=np.float32)
    Y = np.asarray(Y, dtype=np.int32)
    n = len(Y)
    sig_nz = float((X21[:, 94:] != 0).any(axis=1).mean()) if n else 0.0
    print(f"学習データ: {n:,} 局面 | v20={X20.shape[1]}dim v21={X21.shape[1]}dim | "
          f"sig 非ゼロ局面 {sig_nz*100:.0f}% ({time.time()-t0:.0f}s)", flush=True)

    cap = dict(max_iter=min(1000, max(100, n // 400)), max_leaf_nodes=63,
               learning_rate=0.05, l2_regularization=1.0, random_state=0)
    rng = np.random.RandomState(0)
    perm = rng.permutation(n)
    tr, te = perm[:int(n * 0.85)], perm[int(n * 0.85):]

    def _fit_auc(X, tag):
        m = HistGradientBoostingClassifier(**cap)
        m.fit(X[tr], Y[tr])
        auc = roc_auc_score(Y[te], m.predict_proba(X[te])[:, 1])
        print(f"  {tag}: held-out AUC={auc:.4f} (⚠ 強さの指標でない=arena で判定)", flush=True)
        mf = HistGradientBoostingClassifier(**cap)
        mf.fit(X, Y)
        return mf

    m20 = _fit_auc(X20, "v20 baseline")
    m21 = _fit_auc(X21, "v21 (+sig)")
    with open(OUT_V20, "wb") as f:
        pickle.dump(m20, f)
    with open(OUT_V21, "wb") as f:
        pickle.dump(m21, f)
    print(f"saved {OUT_V20.name} / {OUT_V21.name}", flush=True)
    print("次: arena head-to-head で sig の効果を判定:", flush=True)
    print(f"  .venv/bin/python scripts/eiv1_arena.py --arm {OUT_V21.relative_to(ROOT)} "
          f"--refs {OUT_V20.relative_to(ROOT)} --pairs 60 --workers 10", flush=True)


if __name__ == "__main__":
    main()
