"""EIV1 value 学習: 永続 corpus 全件 → 容量をデータと共に伸ばして (progressive) 学習 → value.pkl。

= EIV1 の①表現(v14 grounded)③容量 progressive⑥継続学習(全 corpus 再学習) の"学習"側。
出力 db/eiv1/value.pkl は 29dim(v14) なので gbm_score が自動判別 → 次の collect で hero が使う (フライホイール)。

  .venv/bin/python scripts/eiv1_train.py
"""
from __future__ import annotations
import json
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

EIV1_DIR = ROOT / "db" / "eiv1"
CORPUS = EIV1_DIR / "corpus.jsonl"
VALUE = EIV1_DIR / "value.pkl"
MANIFEST = EIV1_DIR / "manifest.json"


def _progressive_capacity(n: int) -> dict:
    """容量をデータ量に合わせる (小データは絞り過学習回避、 増えたら広げる=天井なしの核③)。"""
    max_iter = int(min(1000, max(60, n // 30)))     # 木の本数 = データと共に増やす
    max_leaf = int(min(63, max(8, 8 + n // 3000)))  # 葉数 = 緩やかに広げる
    return {"max_iter": max_iter, "max_leaf_nodes": max_leaf, "max_depth": None,
            "learning_rate": 0.05, "l2_regularization": 1.0}


def _load_manifest() -> dict:
    if MANIFEST.exists():
        try:
            return json.loads(MANIFEST.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def main():
    if not CORPUS.exists():
        print("!! corpus 無し。 先に eiv1_collect.py を回す")
        return
    manifest = _load_manifest()
    prev_n = int(manifest.get("corpus_n") or 0)   # 前回学習時の corpus 行数 = 今回増分の起点
    from engine.eiv1_features import eiv1_train_vector  # f(v15) + matchup(state) = v16(60)
    X, y = [], []
    for line in open(CORPUS, encoding="utf-8"):
        try:
            d = json.loads(line)
            X.append(eiv1_train_vector(d))   # 保存済み state から v16(相手リーダー)を再計算して append
            y.append(int(d["y"]))
        except Exception:
            continue
    X = np.array(X, dtype=np.float32)
    y = np.array(y, dtype=np.int32)
    n = len(y)
    if n < 100 or len(set(y.tolist())) < 2:
        print(f"!! サンプル不足 or 単一クラス (n={n}, win率={y.mean() if n else 0:.2f}) → 学習 skip")
        return
    cap = _progressive_capacity(n)
    # win率は累積 (= 全 corpus のクラスバランス) だと 1 round 分 (~1%) では動かず固まって見えるので、
    # 「今回の増分だけ」 を主表示にする (corpus は append-only なので末尾 = 今回分)。
    inc = y[prev_n:] if 0 < prev_n <= n else y
    inc_win = float(inc.mean()) if len(inc) else None
    inc_txt = f"win率(今回 {len(inc)}件)={inc_win:.3f}" if inc_win is not None else "win率(今回)=増分なし"
    print(f"EIV1 train: n={n} samples, dim={X.shape[1]}, {inc_txt}, "
          f"win率(累積)={y.mean():.3f}, capacity={cap}", flush=True)

    # held-out AUC (ゲーム境界情報が corpus に無いので単純 20% split の目安値)
    rng = np.random.RandomState(0)
    idx = rng.permutation(n)
    cut = int(n * 0.8)
    tr, te = idx[:cut], idx[cut:]
    auc = None
    if len(set(y[te].tolist())) == 2:
        m = HistGradientBoostingClassifier(random_state=0, **cap)
        m.fit(X[tr], y[tr])
        auc = float(roc_auc_score(y[te], m.predict_proba(X[te])[:, 1]))
        print(f"  held-out AUC (20% split, 目安) = {auc:.4f}", flush=True)

    # 本番 = 全件で再学習して保存 (継続学習)
    model = HistGradientBoostingClassifier(random_state=0, **cap)
    model.fit(X, y)
    with open(VALUE, "wb") as f:
        pickle.dump(model, f)
    iters = manifest.get("train_iters", 0) + 1
    hist = manifest.get("history", [])
    hist.append({"iter": iters, "n": n, "auc": auc, "cap": cap,
                 "win_inc": inc_win, "n_inc": len(inc), "win_cum": float(y.mean())})
    manifest.update({"train_iters": iters, "corpus_n": n, "dim": int(X.shape[1]),
                     "value_path": "db/eiv1/value.pkl", "history": hist[-50:]})
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  saved {VALUE} (iter {iters}, n={n}) + manifest 更新", flush=True)


if __name__ == "__main__":
    main()
