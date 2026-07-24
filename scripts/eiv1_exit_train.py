"""EIV1-ExIt policy 学習 = 探索の初手ランキングを群内相対 advantage として蒸留 — 2026-07-24。

各判断 (兄弟初手グループ) で探索が出した score を、 群内で正規化 (GRPO 流:
(score - 群平均)/群std) して「その手の相対優位」を作り、 policy model が feat116 → 相対優位 を
回帰。 絶対 value 単位に依らず**兄弟の相対順位**を学ぶ (研究の共通処方箋 = 較正と弁別の分離)。

出力 db/eiv1/exit_policy.pkl は engine.exit_policy が beam prior に消費 → 次の探索を導く (複利)。
容量は progressive (データと共に伸ばす)。 ランキング再現率 (top-1 一致) を毎回報告。

  .venv/bin/python scripts/eiv1_exit_train.py
"""
from __future__ import annotations
import json
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
from sklearn.ensemble import HistGradientBoostingRegressor  # noqa: E402

EIV1_DIR = ROOT / "db" / "eiv1"
EXIT_CORPUS = EIV1_DIR / "exit_corpus.jsonl"
POLICY = EIV1_DIR / "exit_policy.pkl"
MANIFEST = EIV1_DIR / "exit_manifest.json"


def _capacity(n: int) -> dict:
    return {"max_iter": int(min(800, max(60, n // 40))),
            "max_leaf_nodes": int(min(63, max(8, 8 + n // 4000))),
            "learning_rate": 0.05, "l2_regularization": 1.0, "random_state": 0}


def main():
    if not EXIT_CORPUS.exists():
        print("!! exit_corpus 無し。 先に eiv1_exit_collect.py")
        return
    X, adv, groups = [], [], []
    # ランキング品質評価用に、 判断ごとの (真 score, feature 行 index) も保持
    decisions = []
    gi = 0
    for line in open(EXIT_CORPUS, encoding="utf-8"):
        try:
            d = json.loads(line)
            sibs = d.get("sibs") or []
            if len(sibs) < 2:
                continue
            scores = np.array([s for _, s in sibs], dtype=np.float64)
            mu, sd = scores.mean(), scores.std()
            sd = sd if sd > 1e-9 else 1.0
            idxs = []
            for (fv, sc), a in zip(sibs, (scores - mu) / sd):
                X.append(fv)
                adv.append(float(a))
                groups.append(gi)
                idxs.append(len(X) - 1)
            decisions.append((scores, idxs))
            gi += 1
        except Exception:
            continue
    if len(X) < 100:
        print(f"!! サンプル不足 (兄弟手 {len(X)}) → skip")
        return
    X = np.array(X, dtype=np.float32)
    y = np.array(adv, dtype=np.float32)
    n = len(y)
    cap = _capacity(n)
    print(f"ExIt train: 判断 {gi:,} / 兄弟手 {n:,} / dim {X.shape[1]} / capacity {cap}", flush=True)

    # 判断単位で 20% を held-out (ランキング再現率の評価用)
    rng = np.random.RandomState(0)
    perm = rng.permutation(gi)
    test_g = set(perm[int(gi * 0.8):].tolist())
    tr_rows = [i for i, g in enumerate(groups) if g not in test_g]
    m = HistGradientBoostingRegressor(**cap)
    m.fit(X[tr_rows], y[tr_rows])

    # ランキング再現率: held-out 判断で、 予測 argmax が 真 score argmax と一致する率
    hit = tot = 0
    for g, (scores, idxs) in enumerate(decisions):
        if g not in test_g:
            continue
        pred = m.predict(X[idxs])
        if int(np.argmax(pred)) == int(np.argmax(scores)):
            hit += 1
        tot += 1
    top1 = hit / tot if tot else 0.0
    # baseline: ランダムに 1 手選ぶ再現率 (= 平均 1/兄弟数)
    rand = float(np.mean([1.0 / len(idxs) for g, (_, idxs) in enumerate(decisions)
                          if g in test_g])) if tot else 0.0
    print(f"  held-out top-1 一致率 = {top1:.3f} (ランダム {rand:.3f}) "
          f"= 探索の最善手を policy が {top1:.1%} 再現", flush=True)

    # 本番 = 全データで再学習して保存
    model = HistGradientBoostingRegressor(**cap)
    model.fit(X, y)
    with open(POLICY, "wb") as f:
        pickle.dump(model, f)
    man = {}
    if MANIFEST.exists():
        try:
            man = json.loads(MANIFEST.read_text(encoding="utf-8"))
        except Exception:
            man = {}
    it = man.get("iters", 0) + 1
    hist = man.get("history", [])
    hist.append({"iter": it, "decisions": gi, "sibs": n, "top1": round(top1, 4),
                 "rand": round(rand, 4)})
    man.update({"iters": it, "decisions": gi, "sibs": n, "history": hist[-100:]})
    MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  saved {POLICY} (iter {it})", flush=True)


if __name__ == "__main__":
    main()
