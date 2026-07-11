# -*- coding: utf-8 -*-
"""Q(s,a) の「action 信号の強さ」を測る診断(枝刈りに teeth があるか)。

枝刈りが効くには「state を固定して action を変えたとき Q が大きく動く」必要がある。
corpus の各 state feat を固定し、9 action-type × 代表 param で Q を評価 → その spread
(max-min) を集計。spread が小さい = label が state 支配 = action で刈れない(credit
assignment 限界)。大きい = 明確に劣る手があり刈れる。

  .venv/bin/python scripts/q_action_signal.py --dir db/_analyst/exp_diverse --model db/q_prune_model.pkl
"""
import argparse, glob, json, pickle
import numpy as np

# build_q_prune と同一の action encode を再現
ACTION_TYPES = ["AttackLeader", "AttackCharacter", "PlayCharacter", "PlayEvent",
                "PlayStage", "ActivateMain", "AttachDonToLeader", "AttachDonToCharacter",
                "EndPhase"]
_AIDX = {t: i for i, t in enumerate(ACTION_TYPES)}


def enc(atype, atk_power=0, target_is_leader=0, attached_don=0):
    v = [0.0] * len(ACTION_TYPES)
    if atype in _AIDX:
        v[_AIDX[atype]] = 1.0
    v += [float(atk_power) / 10000.0, float(target_is_leader), float(attached_don) / 4.0]
    return v


# 各 action-type の「代表的な」param(実戦で出うる値)。attack は power/target を振る。
ACTION_PROBES = [
    ("AttackLeader", 6000, 1, 2),
    ("AttackCharacter", 6000, 0, 2),
    ("PlayCharacter", 0, 0, 0),
    ("PlayEvent", 0, 0, 0),
    ("PlayStage", 0, 0, 0),
    ("ActivateMain", 0, 0, 0),
    ("AttachDonToLeader", 0, 0, 0),
    ("AttachDonToCharacter", 0, 0, 0),
    ("EndPhase", 0, 0, 0),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="db/_analyst/exp_diverse")
    ap.add_argument("--model", default="db/q_prune_model.pkl")
    ap.add_argument("--sample", type=int, default=3000)
    a = ap.parse_args()

    m = pickle.load(open(a.model, "rb"))["model"]
    probe_enc = [enc(*p) for p in ACTION_PROBES]

    feats = []
    for f in sorted(glob.glob(f"{a.dir}/exp_*.jsonl")):
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            if r.get("kind") is not None:
                continue
            ft = r.get("feat")
            if ft:
                feats.append(list(ft))
    if not feats:
        print("feat 無し"); return
    rng = np.random.default_rng(0)
    idx = rng.choice(len(feats), size=min(a.sample, len(feats)), replace=False)

    spreads, top_gap = [], []
    for i in idx:
        ft = feats[i]
        rows = np.array([ft + pe for pe in probe_enc], dtype=float)
        qs = m.predict_proba(rows)[:, 1]
        qs_sorted = np.sort(qs)[::-1]
        spreads.append(float(qs.max() - qs.min()))
        top_gap.append(float(qs_sorted[0] - qs_sorted[1]))  # 最良と次善の差
    spreads = np.array(spreads); top_gap = np.array(top_gap)
    print(f"サンプル state 数: {len(idx)}")
    print(f"action spread (max Q - min Q), state 固定):")
    print(f"  平均 {spreads.mean():.4f} / 中央 {np.median(spreads):.4f} / 90%ile {np.percentile(spreads,90):.4f}")
    print(f"最良と次善の Q 差:")
    print(f"  平均 {top_gap.mean():.4f} / 中央 {np.median(top_gap):.4f}")
    # 解釈: spread が value の board_eval delta スケール(勝率±)で 0.1 未満なら刈る teeth 弱い
    frac_teeth = float((spreads > 0.10).mean())
    print(f"spread>0.10 の state 割合(明確に劣る手がある=刈れる): {frac_teeth*100:.1f}%")


if __name__ == "__main__":
    main()
