# -*- coding: utf-8 -*-
"""ε-explored 経験コーパスから action-quality Q(s,a)=P(win|state,action) を学習(枝刈り用)。

ohtsuki 案: 「良い手を選ぶ」でなく「悪い手を経験から刈る」。 探索(ε-greedy)で悪手を含んだ
corpus から Q(s,a) を学び、 beam で明確に劣る候補だけ prune → 選ぶでなく切る(Pareto-safer)。

入力: db/_analyst/experience/exp_*.jsonl (--record-feat --epsilon で収集、 各 main 決定に v6 feat)。
特徴 = v6 state feat(38) + action encode(下記 ACTION_ENC_DIM)。 label = y(その手番 player の勝敗)。
出力: db/q_prune_model.pkl (sklearn GBM) + メタ。

  .venv/bin/python scripts/build_q_prune.py
"""
import glob, json, pickle, sys
import numpy as np

ACTION_TYPES = ["AttackLeader", "AttackCharacter", "PlayCharacter", "PlayEvent",
                "PlayStage", "ActivateMain", "AttachDonToLeader", "AttachDonToCharacter",
                "EndPhase"]
_AIDX = {t: i for i, t in enumerate(ACTION_TYPES)}
ACTION_ENC_DIM = len(ACTION_TYPES) + 3  # one-hot + [atk_power/1e4, target_is_leader, attached_don/4]


def encode_action_fields(action_type, atk_power=0, target_is_leader=0, attached_don=0):
    """action type + 主要 param を固定長ベクトルに。 train(log)/inference(live) 共通。"""
    v = [0.0] * len(ACTION_TYPES)
    if action_type in _AIDX:
        v[_AIDX[action_type]] = 1.0
    v += [float(atk_power) / 10000.0, float(target_is_leader), float(attached_don) / 4.0]
    return v


def _enc_from_log(r):
    return encode_action_fields(
        r.get("action", ""),
        atk_power=r.get("atk_power", 0) or 0,
        target_is_leader=1 if r.get("target_kind") == "leader" else 0,
        attached_don=r.get("atk_attached_don", 0) or 0,
    )


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="db/_analyst/experience")
    ap.add_argument("--out", default="db/q_prune_model.pkl")
    a = ap.parse_args()
    files = sorted(glob.glob(f"{a.dir}/exp_*.jsonl"))
    X, y = [], []
    n_expl = 0
    for f in files:
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            if r.get("kind") is not None:
                continue  # main 決定のみ
            feat = r.get("feat")
            if not feat or "y" not in r:
                continue
            X.append(list(feat) + _enc_from_log(r))
            y.append(int(r["y"]))
    X = np.array(X, dtype=float); y = np.array(y)
    print(f"corpus: {len(files)} files, samples={len(X)}, dim={X.shape[1] if len(X) else 0}, win率={y.mean()*100:.1f}%")
    if len(X) < 2000 or len(set(y)) < 2:
        print("データ不足 or 単一クラス。 corpus を増やす。"); sys.exit(1)
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import roc_auc_score
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=1)
    m = GradientBoostingClassifier(n_estimators=200, max_depth=3, learning_rate=0.05, subsample=0.8)
    m.fit(Xtr, ytr)
    auc = roc_auc_score(yte, m.predict_proba(Xte)[:, 1])
    print(f"held-out AUC = {auc:.3f}  (>0.55 で action の良し悪しを識別できている)")
    pickle.dump({"model": m, "state_dim": len(X[0]) - ACTION_ENC_DIM, "action_dim": ACTION_ENC_DIM,
                 "action_types": ACTION_TYPES}, open(a.out, "wb"))
    print(f"保存: {a.out}")


if __name__ == "__main__":
    main()
