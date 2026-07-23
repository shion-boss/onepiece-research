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
SNAP_DIR = EIV1_DIR / "snapshots"
SNAPSHOT_EVERY = 10   # N iter ごとに value.pkl を凍結保存 (自己改善曲線の基準)


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
    X, y, groups = [], [], []
    # group = game_id。 1 game が 5〜6 行を吐くので sample 単位で split すると同一 game が
    # train/test に跨り AUC がリークで上振れする。 旧行 ("g" 無し) は (y,hero,opp) の連続 run で
    # game 境界を復元 (corpus は append-only かつ game の行は連続なので一致する)。
    prev_key, run_id = None, 0
    for line in open(CORPUS, encoding="utf-8"):
        try:
            d = json.loads(line)
            vec = eiv1_train_vector(d)   # 保存済み state から v16(相手リーダー)を再計算して append
            gid = d.get("g")
            if gid is None:
                key = (d.get("y"), d.get("hero"), d.get("opp"))
                if key != prev_key:
                    run_id += 1
                    prev_key = key
                gid = f"_run{run_id}"
            else:
                prev_key = None
            X.append(vec)
            y.append(int(d["y"]))
            groups.append(gid)
        except Exception:
            continue
    X = np.array(X, dtype=np.float32)
    y = np.array(y, dtype=np.int32)
    groups = np.array(groups)
    n = len(y)
    if n < 100 or len(set(y.tolist())) < 2:
        print(f"!! サンプル不足 or 単一クラス (n={n}, win率={y.mean() if n else 0:.2f}) → 学習 skip")
        return
    cap = _progressive_capacity(n)
    # ⚠ win率は出さない: 自己対戦では構造的に ~0.5 になるだけで強さを測れない
    # (強さの推移は ε=0 arena vs EBV2 agnostic が物差し)。 増分だけ件数で示す。
    inc = n - prev_n if 0 < prev_n <= n else n
    print(f"EIV1 train: n={n} samples (今回 +{inc}), dim={X.shape[1]}, capacity={cap}", flush=True)

    # held-out AUC = game 単位 20% split (= 同一 game の行は必ず片側にまとめる → リーク無し)
    uniq = np.unique(groups)
    rng = np.random.RandomState(0)
    perm = rng.permutation(len(uniq))
    test_ids = set(uniq[perm[int(len(uniq) * 0.8):]].tolist())
    is_te = np.fromiter((g in test_ids for g in groups), dtype=bool, count=n)
    tr, te = np.flatnonzero(~is_te), np.flatnonzero(is_te)
    auc = None
    if len(te) and len(set(y[te].tolist())) == 2:
        m = HistGradientBoostingClassifier(random_state=0, **cap)
        m.fit(X[tr], y[tr])
        auc = float(roc_auc_score(y[te], m.predict_proba(X[te])[:, 1]))
        print(f"  held-out AUC (game 単位 20% split, {len(uniq):,} games) = {auc:.4f}", flush=True)

    # 本番 = 全件で再学習して保存 (継続学習)
    model = HistGradientBoostingClassifier(random_state=0, **cap)
    model.fit(X, y)
    with open(VALUE, "wb") as f:
        pickle.dump(model, f)
    # 動的 spec を model と対で保存 (= 推論側は <model>.spec.json を読むので取り違えない)。
    # spec が空でも書く (= 「この model は v20 素のまま」を明示)。
    try:
        from engine.feature_spec import active_spec, save_spec, spec_path_for_model
        save_spec(spec_path_for_model(VALUE), active_spec(),
                  {"iter": manifest.get("train_iters", 0) + 1, "n": n, "dim": int(X.shape[1])})
    except Exception:
        pass
    iters = manifest.get("train_iters", 0) + 1
    hist = manifest.get("history", [])
    hist.append({"iter": iters, "n": n, "n_inc": int(inc), "auc": auc, "cap": cap,
                 "auc_split": "game", "n_games": int(len(uniq))})   # iter119 以降 = リーク無し AUC
    manifest.update({"train_iters": iters, "corpus_n": n, "dim": int(X.shape[1]),
                     "value_path": "db/eiv1/value.pkl", "history": hist[-50:]})
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  saved {VALUE} (iter {iters}, n={n}) + manifest 更新", flush=True)

    # 10 iter ごとに value を凍結保存 (= 過去の自分と戦わせる自己改善曲線の基準、 eiv1_arena.py が使う)。
    # 上書きだけだと「過去より強くなったか」を後から測れないので残す (5.5MB/個 ≒ 1 個/日)。
    if iters % SNAPSHOT_EVERY == 0:
        SNAP_DIR.mkdir(parents=True, exist_ok=True)
        snap = SNAP_DIR / f"value_iter{iters}.pkl"
        with open(snap, "wb") as f:
            pickle.dump(model, f)
        try:   # snapshot も spec と対で残す (= 後で arena の基準として正しく復元できる)
            from engine.feature_spec import active_spec, save_spec, spec_path_for_model
            save_spec(spec_path_for_model(snap), active_spec(), {"iter": iters, "n": n})
        except Exception:
            pass
        print(f"  snapshot: {snap.name}", flush=True)


if __name__ == "__main__":
    main()
