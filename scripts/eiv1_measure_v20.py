"""v18 → v19 → v20 の ladder de-risk 測定 — 2026-07-23。

v19 = v18 + 盤面詳細 20 (個体解像度が効き、 除去射程列は盤面ではほぼ発火せず)。
v20 = v19 + 除去射程 × 的 の interaction 10 を **効く場所** に置いたもの
      (自分 = 手札の実カード / 相手 = leader prior − 見た札 の belief)。

同一の game 単位 split で 3 本を比較する (= 同一 game の行が train/test に跨るリークを避ける)。

  .venv/bin/python scripts/eiv1_measure_v20.py [--sample 120000]
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

for _tv in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_tv, "1")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402
from engine.eiv1_features import (  # noqa: E402
    board_detail_feats_from_snapshot, eiv1_train_vector, hand_reach_feats_from_snapshot,
)

CORPUS = ROOT / "db" / "eiv1" / "corpus.jsonl"
CAP = {"max_iter": 400, "max_leaf_nodes": 31, "max_depth": None,
       "learning_rate": 0.05, "l2_regularization": 1.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=120000)
    a = ap.parse_args()

    lines = []
    with open(CORPUS, encoding="utf-8") as f:
        for line in f:
            lines.append(line)
            if len(lines) > a.sample:
                lines.pop(0)
    print(f"corpus 末尾 {len(lines):,} 行で測定", flush=True)

    X18, B19, H20, y, groups, turns = [], [], [], [], [], []
    prev_key, run_id = None, 0
    for line in lines:
        try:
            d = json.loads(line)
            snap = d.get("state")
            X18.append(eiv1_train_vector(d))
            B19.append(board_detail_feats_from_snapshot(snap) if snap else [0.0] * 20)
            H20.append(hand_reach_feats_from_snapshot(snap) if snap else [0.0] * 10)
            y.append(int(d["y"]))
            gid = d.get("g")
            if gid is None:
                key = (d.get("y"), d.get("hero"), d.get("opp"))
                if key != prev_key:
                    run_id += 1
                    prev_key = key
                gid = f"_run{run_id}"
            else:
                prev_key = None
            groups.append(gid)
            turns.append(int((snap or {}).get("turn_number") or 0))
        except Exception:
            continue
    X18 = np.array(X18, dtype=np.float32)
    X19 = np.hstack([X18, np.array(B19, dtype=np.float32)])
    X20 = np.hstack([X19, np.array(H20, dtype=np.float32)])
    y = np.array(y, dtype=np.int32)
    groups = np.array(groups)
    turns = np.array(turns)
    n = len(y)
    uniq = np.unique(groups)
    print(f"n={n:,} games={len(uniq):,} dim: {X18.shape[1]}/{X19.shape[1]}/{X20.shape[1]} "
          f"win率={y.mean():.3f}", flush=True)
    nz = (np.abs(np.array(H20, dtype=np.float32)) > 1e-9).mean(axis=0)
    print("v20 新 10 列の非ゼロ率: " + " ".join(f"{v:.2f}" for v in nz), flush=True)

    perm = np.random.RandomState(0).permutation(len(uniq))
    test_ids = set(uniq[perm[int(len(uniq) * 0.8):]].tolist())
    is_te = np.fromiter((g in test_ids for g in groups), dtype=bool, count=n)
    tr, te = np.flatnonzero(~is_te), np.flatnonzero(is_te)
    print(f"game 単位 split: train={len(tr):,} test={len(te):,}", flush=True)

    out = {}
    for tag, X in (("v18", X18), ("v19", X19), ("v20", X20)):
        m = HistGradientBoostingClassifier(random_state=0, **CAP)
        m.fit(X[tr], y[tr])
        p = m.predict_proba(X[te])[:, 1]
        out[tag] = (float(roc_auc_score(y[te], p)), p)
        print(f"  {tag}: AUC={out[tag][0]:.4f}", flush=True)

    print(f"\nv19 - v18 = {out['v19'][0] - out['v18'][0]:+.4f}", flush=True)
    print(f"v20 - v19 = {out['v20'][0] - out['v19'][0]:+.4f}", flush=True)
    print(f"v20 - v18 = {out['v20'][0] - out['v18'][0]:+.4f}", flush=True)
    print("\nturn 別 AUC:", flush=True)
    for lo, hi in ((1, 4), (5, 7), (8, 10), (11, 99)):
        sel = (turns[te] >= lo) & (turns[te] <= hi)
        if sel.sum() < 500 or len(set(y[te][sel].tolist())) < 2:
            continue
        vals = {t: roc_auc_score(y[te][sel], out[t][1][sel]) for t in ("v18", "v19", "v20")}
        print(f"  turn {lo:>2}-{hi:<2} n={int(sel.sum()):>6,}  "
              f"v18={vals['v18']:.4f} v19={vals['v19']:.4f} v20={vals['v20']:.4f} "
              f"(v20-v18 {vals['v20'] - vals['v18']:+.4f})", flush=True)


if __name__ == "__main__":
    main()
