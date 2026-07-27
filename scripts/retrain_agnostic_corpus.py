# -*- coding: utf-8 -*-
"""agnostic value(21dim)を EIV1 全 corpus(beam 分布・多様マッチ)で再学習する = ① coverage/distribution。

動機 ([[project_search_route_pivot]] の①): 現 db/value_gbm_agnostic.pkl は **greedy self-play 産**
(2026-07-02)。 配備は beam。 corpus.jsonl は beam 分布 + 233 deck × 233 opp の極めて多様なマッチ
(49,416 pair、 上位20が 0.2%)。 stored f[:21] は v2 特徴(21dim)と一致確認済 → **state 再構成不要で
高速再学習**。 small-data beam-in-loop(iter5)は 42.2% で負けたが、 それは games=40 の過少学習の疑い。
833k 全 corpus(2万倍)で「beam 分布 + max coverage」の agnostic を作り、 現 agnostic と arena gate。

  train: .venv/bin/python scripts/retrain_agnostic_corpus.py [--max-rows N]
  gate : .venv/bin/python scripts/eiv1_arena.py --arm db/_selfplay/agnostic_corpus833k.pkl \
             --refs agnostic --pairs 80 --workers 12
"""
from __future__ import annotations
import argparse
import json
import pickle
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402

CORPUS = ROOT / "db" / "eiv1" / "corpus.jsonl"
OUT = ROOT / "db" / "_selfplay" / "agnostic_corpus833k.pkl"
DIM = 21   # v2 = agnostic 次元 (drop-in)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-rows", type=int, default=0, help="0=全件")
    a = ap.parse_args()
    t0 = time.time()
    X, y, groups = [], [], []
    prev_key, run_id, skipped = None, 0, 0
    for i, line in enumerate(open(CORPUS, encoding="utf-8")):
        if a.max_rows and i >= a.max_rows:
            break
        try:
            d = json.loads(line)
            f = d.get("f")
            if not f or len(f) < DIM:
                skipped += 1
                continue
            X.append(f[:DIM])
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
        except Exception:
            skipped += 1
            continue
        if (i + 1) % 200000 == 0:
            print(f"  read {i+1:,} rows ({time.time()-t0:.0f}s)", flush=True)
    X = np.asarray(X, dtype=np.float32)
    y = np.asarray(y, dtype=np.int32)
    groups = np.asarray(groups)
    n = len(y)
    print(f"loaded {n:,} rows (skipped {skipped:,}), dim={X.shape[1]}, win率={y.mean()*100:.1f}% "
          f"({time.time()-t0:.0f}s)", flush=True)

    cap = dict(max_iter=1000, max_leaf_nodes=63, learning_rate=0.05,
               l2_regularization=1.0, random_state=0, early_stopping=True,
               validation_fraction=0.1, n_iter_no_change=20)

    # held-out AUC = game 単位 20% split (leak 無し)
    uniq = np.unique(groups)
    rng = np.random.RandomState(0)
    perm = rng.permutation(len(uniq))
    test_ids = set(uniq[perm[int(len(uniq) * 0.8):]].tolist())
    is_te = np.fromiter((g in test_ids for g in groups), dtype=bool, count=n)
    tr, te = np.flatnonzero(~is_te), np.flatnonzero(is_te)
    m = HistGradientBoostingClassifier(**cap)
    m.fit(X[tr], y[tr])
    auc = roc_auc_score(y[te], m.predict_proba(X[te])[:, 1])
    print(f"  held-out AUC (game 単位 20% split, {len(uniq):,} games) = {auc:.4f} "
          f"(⚠ 強さは arena で判定)", flush=True)

    # 本番 = 全件で再学習して保存
    model = HistGradientBoostingClassifier(**cap)
    model.fit(X, y)
    OUT.parent.mkdir(exist_ok=True)
    with open(OUT, "wb") as f:
        pickle.dump(model, f)
    print(f"saved {OUT} ({time.time()-t0:.0f}s)", flush=True)
    print("次: arena gate = .venv/bin/python scripts/eiv1_arena.py "
          f"--arm {OUT.relative_to(ROOT)} --refs agnostic --pairs 80 --workers 12", flush=True)


if __name__ == "__main__":
    main()
