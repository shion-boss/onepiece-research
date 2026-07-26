"""sig(card) の clean isolation de-risk — 2026-07-27。

v21 vs v20 は v20 が board_detail を持つため sig が冗長(confound)。 ここでは board_detail を
sig で**置換**して head-to-head:
  arm A = v22 = v18(64) + sig(24)          = 88
  arm B = v19 = v18(64) + board_detail(20) = 84
= 「sig vs 既存 board rep、 どちらが良い board 表現か」を confound なしで isolate。 arena で判定。

  train: .venv/bin/python scripts/eiv1_sig_isolate.py --tail-mb 150
  arena: .venv/bin/python scripts/eiv1_arena.py --arm db/eiv1/value_sig_v22.pkl \
             --refs db/eiv1/value_sig_v19.pkl --pairs 60 --workers 8
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
OUT_V22 = EIV1 / "value_sig_v22.pkl"   # arm A: v18 + sig
OUT_V19 = EIV1 / "value_sig_v19.pkl"   # arm B: v18 + board_detail


def _read_tail(tail_mb: int) -> list:
    fsize = os.path.getsize(CORPUS)
    tb = min(fsize, tail_mb * 1024 * 1024)
    with open(CORPUS, "rb") as f:
        f.seek(fsize - tb)
        raw = f.read().split(b"\n")
    if tb < fsize and raw:
        raw = raw[1:]
    out = []
    for ln in raw:
        ln = ln.strip()
        if ln:
            try:
                out.append(json.loads(ln))
            except Exception:
                pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tail-mb", type=int, default=150)
    a = ap.parse_args()
    t0 = time.time()
    rows = _read_tail(a.tail_mb)
    print(f"corpus tail: {len(rows):,} 局面 ({time.time()-t0:.0f}s)", flush=True)

    X22, X19, Y = [], [], []   # v22 = v18+sig(88) / v19 = v18+board_detail(84)
    for d in rows:
        snap = d.get("state")
        if not snap:
            continue
        try:
            v20 = eiv1_train_vector(d)
            if len(v20) != 94:
                continue
            v18 = v20[:64]
            sig = sig_board_feats_from_snapshot(snap)
            X22.append(v18 + sig)      # 88
            X19.append(v20[:84])       # 84 (= v18 + board_detail)
            Y.append(int(d.get("y", 0)))
        except Exception:
            continue
    X22 = np.asarray(X22, dtype=np.float32)
    X19 = np.asarray(X19, dtype=np.float32)
    Y = np.asarray(Y, dtype=np.int32)
    n = len(Y)
    print(f"学習: {n:,} 局面 | armA v22={X22.shape[1]}(v18+sig) / armB v19={X19.shape[1]}(v18+board_detail) "
          f"({time.time()-t0:.0f}s)", flush=True)

    cap = dict(max_iter=min(1000, max(100, n // 400)), max_leaf_nodes=63,
               learning_rate=0.05, l2_regularization=1.0, random_state=0)
    rng = np.random.RandomState(0)
    perm = rng.permutation(n)
    tr, te = perm[:int(n * 0.85)], perm[int(n * 0.85):]

    def _fit(X, tag, out):
        m = HistGradientBoostingClassifier(**cap)
        m.fit(X[tr], Y[tr])
        auc = roc_auc_score(Y[te], m.predict_proba(X[te])[:, 1])
        print(f"  {tag}: held-out AUC={auc:.4f}", flush=True)
        mf = HistGradientBoostingClassifier(**cap)
        mf.fit(X, Y)
        with open(out, "wb") as f:
            pickle.dump(mf, f)
        return auc

    _fit(X22, "armA v22 (v18+sig)", OUT_V22)
    _fit(X19, "armB v19 (v18+board_detail)", OUT_V19)
    print(f"saved {OUT_V22.name} / {OUT_V19.name}", flush=True)
    print("次: arena で sig vs board_detail を confound なしで判定:", flush=True)
    print(f"  .venv/bin/python scripts/eiv1_arena.py --arm {OUT_V22.relative_to(ROOT)} "
          f"--refs {OUT_V19.relative_to(ROOT)} --pairs 60 --workers 8", flush=True)


if __name__ == "__main__":
    main()
