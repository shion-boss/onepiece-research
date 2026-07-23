"""v16 (= v15 + 相手リーダー matchup 特徴) の効果を既存 corpus で de-risk 測定 — 2026-07-24。

再収集なし: 保存済み state から相手リーダー tag(13) + interaction(4) を復元して f(v15,43) に append
→ v16(60)。 v15 と v16 を同一 split で学習し turn 別 AUC を比較 (= 相手リーダー識別で予測が上がるか)。

  .venv/bin/python scripts/eiv1_measure_v16.py [--sample 120000]
"""
from __future__ import annotations
import argparse
import json
import sys
import types
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from engine import gbm_value as G

CORPUS = ROOT / "db" / "eiv1" / "corpus.jsonl"


def _fake_state(snap):
    def mk(p):
        leader = types.SimpleNamespace(card=types.SimpleNamespace(card_id=p["leader"]["card_id"]))
        return types.SimpleNamespace(leader=leader, life=[0] * p["life_count"],
                                     hand=[0] * p["hand_count"], don_active=p.get("don_active", 0))
    return types.SimpleNamespace(players=[mk(p) for p in snap["players"]])


def matchup_feats(snap):
    """保存済み snapshot から 相手リーダー tag(13) + interaction(4) = 17 を復元。"""
    fs = _fake_state(snap)
    hi = snap["hero_idx"]
    return G._opp_matchup_tag_vector(fs, hi) + G._opp_matchup_interaction_vector(fs, hi)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=120000)
    a = ap.parse_args()
    F15, EX, Y, TURN = [], [], [], []
    with open(CORPUS) as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except Exception:
                continue
            F15.append(d["f"])
            EX.append(matchup_feats(d["state"]))
            Y.append(int(d["y"]))
            TURN.append(int(d["state"]["turn_number"]))
            if len(Y) >= a.sample:
                break
    F15 = np.array(F15, dtype=np.float32)
    EX = np.array(EX, dtype=np.float32)
    F16 = np.concatenate([F15, EX], axis=1)
    Y = np.array(Y, dtype=np.int32)
    TURN = np.array(TURN)
    n = len(Y)
    print(f"サンプル {n} | v15 dim {F15.shape[1]} | v16 dim {F16.shape[1]} | 勝率 {Y.mean():.3f}")

    rng = np.random.RandomState(0)
    idx = rng.permutation(n)
    cut = int(n * 0.8)
    tr, te = idx[:cut], idx[cut:]
    cap = dict(max_iter=300, max_leaf_nodes=31, learning_rate=0.06, l2_regularization=1.0, random_state=0)

    def fit_auc(X):
        m = HistGradientBoostingClassifier(**cap)
        m.fit(X[tr], Y[tr])
        p = m.predict_proba(X[te])[:, 1]
        return m, p

    _, p15 = fit_auc(F15)
    _, p16 = fit_auc(F16)
    yte = Y[te]; tte = TURN[te]
    print(f"\n=== 全体 held-out AUC ===")
    print(f"  v15 (相手リーダー無し): {roc_auc_score(yte, p15):.4f}")
    print(f"  v16 (相手リーダー有り): {roc_auc_score(yte, p16):.4f}   Δ={roc_auc_score(yte,p16)-roc_auc_score(yte,p15):+.4f}")

    print(f"\n=== ターン別 held-out AUC (v15 → v16) ===")
    print(f"{'ターン':>5} {'件数':>6} {'v15':>7} {'v16':>7} {'Δ':>7}")
    for t in range(1, 13):
        mask = tte == t
        yy = yte[mask]
        if mask.sum() < 100 or len(set(yy.tolist())) < 2:
            continue
        a15 = roc_auc_score(yy, p15[mask])
        a16 = roc_auc_score(yy, p16[mask])
        print(f"{t:>5} {mask.sum():>6} {a15:>7.3f} {a16:>7.3f} {a16-a15:>+7.3f}")


if __name__ == "__main__":
    main()
