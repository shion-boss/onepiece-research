"""v19 (= v18 + 盤面詳細 20) の de-risk 測定 — 2026-07-23。

再収集なし: 保存済み snapshot から 盤面詳細 (効果の大きさ / 除去の到達 interaction / 個体解像度)
を復元して v18(64) に append → v19(84)。 同一の **game 単位 split** で AUC を比較する
(= 同一 game の行が train/test に跨るとリークするため)。

  .venv/bin/python scripts/eiv1_measure_v19.py [--sample 120000]
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
from engine.eiv1_features import board_detail_feats_from_snapshot, eiv1_train_vector  # noqa: E402

CORPUS = ROOT / "db" / "eiv1" / "corpus.jsonl"
CAP = {"max_iter": 400, "max_leaf_nodes": 31, "max_depth": None,
       "learning_rate": 0.05, "l2_regularization": 1.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=120000, help="corpus 末尾から使う行数")
    a = ap.parse_args()

    lines = []
    with open(CORPUS, encoding="utf-8") as f:
        for line in f:
            lines.append(line)
            if len(lines) > a.sample:
                lines.pop(0)
    print(f"corpus 末尾 {len(lines):,} 行で測定", flush=True)

    X18, X19, y, groups, turns = [], [], [], [], []
    prev_key, run_id = None, 0
    for line in lines:
        try:
            d = json.loads(line)
            base = eiv1_train_vector(d)
            extra = board_detail_feats_from_snapshot(d.get("state")) if d.get("state") else [0.0] * 20
            X18.append(base)
            X19.append(base + extra)
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
            turns.append(int((d.get("state") or {}).get("turn_number") or 0))
        except Exception:
            continue
    X18 = np.array(X18, dtype=np.float32)
    X19 = np.array(X19, dtype=np.float32)
    y = np.array(y, dtype=np.int32)
    groups = np.array(groups)
    turns = np.array(turns)
    n = len(y)
    uniq = np.unique(groups)
    print(f"n={n:,} games={len(uniq):,} dim: v18={X18.shape[1]} v19={X19.shape[1]} "
          f"win率={y.mean():.3f}", flush=True)

    # 非ゼロ率 = 新列が実際に情報を持っているか (全 0 なら測る前に設計ミス)
    extra = X19[:, X18.shape[1]:]
    nz = (np.abs(extra) > 1e-9).mean(axis=0)
    print("新 20 列の非ゼロ率: " + " ".join(f"{v:.2f}" for v in nz), flush=True)

    perm = np.random.RandomState(0).permutation(len(uniq))
    test_ids = set(uniq[perm[int(len(uniq) * 0.8):]].tolist())
    is_te = np.fromiter((g in test_ids for g in groups), dtype=bool, count=n)
    tr, te = np.flatnonzero(~is_te), np.flatnonzero(is_te)
    print(f"game 単位 split: train={len(tr):,} test={len(te):,}", flush=True)

    out = {}
    for tag, X in (("v18", X18), ("v19", X19)):
        m = HistGradientBoostingClassifier(random_state=0, **CAP)
        m.fit(X[tr], y[tr])
        p = m.predict_proba(X[te])[:, 1]
        auc = float(roc_auc_score(y[te], p))
        out[tag] = (auc, p)
        print(f"  {tag}: AUC={auc:.4f}", flush=True)

    d_auc = out["v19"][0] - out["v18"][0]
    print(f"\nv19 - v18 = {d_auc:+.4f}", flush=True)
    print("turn 別 AUC (中盤で効くか):", flush=True)
    for lo, hi in ((1, 4), (5, 7), (8, 10), (11, 99)):
        sel = (turns[te] >= lo) & (turns[te] <= hi)
        if sel.sum() < 500 or len(set(y[te][sel].tolist())) < 2:
            continue
        a18 = roc_auc_score(y[te][sel], out["v18"][1][sel])
        a19 = roc_auc_score(y[te][sel], out["v19"][1][sel])
        print(f"  turn {lo:>2}-{hi:<2} n={int(sel.sum()):>6,}  v18={a18:.4f} v19={a19:.4f} "
              f"Δ={a19 - a18:+.4f}", flush=True)


if __name__ == "__main__":
    main()
