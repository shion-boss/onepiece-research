"""候補 spec を 関門3 (ε=0 arena) にかける — 2026-07-24。

feature 探索 (eiv1_feature_search.py) が関門2 (AUC) まで通した候補列を、 配備条件で学習し、
現行 value と直接対戦させて **強くなったか** を判定する。 今日の実測で「AUC が上がっても強さは
変わらない」が繰り返し起きているため、 採用の最終判断は必ずここで行う。

  .venv/bin/python scripts/eiv1_gate_candidate.py db/eiv1/feature_spec.card_candidate.json \
      --sample 220000 --pairs 40 --workers 6
  # 通れば --accept で db/eiv1/feature_spec.json に採用 (次の train から次元が伸びる)
"""
from __future__ import annotations
import argparse
import json
import os
import pickle
import subprocess
import sys
import time
from pathlib import Path

for _tv in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_tv, "1")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402
from engine import feature_spec as FS  # noqa: E402
from engine.eiv1_features import eiv1_train_vector  # noqa: E402

EIV1_DIR = ROOT / "db" / "eiv1"
CORPUS = EIV1_DIR / "corpus.jsonl"
VALUE = EIV1_DIR / "value.pkl"
CAND = EIV1_DIR / "_candidate_value.pkl"
LOG = EIV1_DIR / "feature_search_log.jsonl"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", help="候補 spec の JSON パス")
    ap.add_argument("--sample", type=int, default=220000, help="候補 value の学習に使う行数")
    ap.add_argument("--pairs", type=int, default=40, help="arena のペア数 (1 ペア=4 game)")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--margin", type=float, default=0.02,
                    help="現 value 相手に (0.5 - margin) 未満なら棄却")
    ap.add_argument("--accept", action="store_true",
                    help="関門3 を通ったら feature_spec.json に採用する")
    a = ap.parse_args()
    t0 = time.time()
    spec = FS.load_spec(a.spec)
    if not spec:
        print(f"!! spec が空: {a.spec}")
        return
    print(f"候補 {len(spec)} 列を関門3 にかける ({a.spec})", flush=True)

    lines: list = []
    with open(CORPUS, encoding="utf-8") as f:
        for line in f:
            lines.append(line)
            if len(lines) > a.sample:
                lines.pop(0)
    X, y = [], []
    for line in lines:
        try:
            d = json.loads(line)
            snap = d.get("state")
            if not snap:
                continue
            X.append(eiv1_train_vector(d) + FS.evaluate(snap, spec))
            y.append(int(d["y"]))
        except Exception:
            continue
    X = np.array(X, dtype=np.float32)
    y = np.array(y, dtype=np.int32)
    print(f"学習: n={len(y):,} dim={X.shape[1]} ({time.time() - t0:.0f}s)", flush=True)
    m = HistGradientBoostingClassifier(random_state=0, max_iter=1000, max_leaf_nodes=63,
                                       max_depth=None, learning_rate=0.05,
                                       l2_regularization=1.0)
    m.fit(X, y)
    with open(CAND, "wb") as f:
        pickle.dump(m, f)
    FS.save_spec(FS.spec_path_for_model(CAND), spec, {"source": a.spec})
    print(f"候補 value 保存 → arena ({time.time() - t0:.0f}s)", flush=True)

    r = subprocess.run(
        [str(ROOT / ".venv" / "bin" / "python"), str(ROOT / "scripts" / "eiv1_arena.py"),
         "--arm", str(CAND), "--refs", str(VALUE), "--pairs", str(a.pairs),
         "--workers", str(a.workers)],
        capture_output=True, text=True)
    print(r.stdout.strip(), flush=True)
    win = None
    for line in reversed((r.stdout or "").splitlines()):
        if "勝率 =" in line:
            try:
                win = float(line.split("勝率 =")[1].split("±")[0].strip())
            except Exception:
                pass
            break
    rec = {"gate": "arena", "spec": a.spec, "n_cols": len(spec), "win": win,
           "n_train": int(len(y)), "secs": round(time.time() - t0, 1)}
    if win is None:
        rec["result"] = "arena_failed"
    elif win < 0.5 - a.margin:
        rec["result"] = "rejected"
        print(f"→ 棄却 (arena 勝率 {win:.3f} < {0.5 - a.margin:.3f})", flush=True)
    else:
        rec["result"] = "passed"
        print(f"→ 関門3 通過 (arena 勝率 {win:.3f})", flush=True)
        if a.accept:
            prev = FS.active_spec()
            FS.save_spec(FS.ACTIVE_SPEC_PATH, prev + spec,
                         {"added": len(spec), "arena_win": win, "source": a.spec})
            print(f"✅ 採用: spec 合計 {len(prev) + len(spec)} 列。 次の train から次元が伸びる",
                  flush=True)
            rec["accepted"] = True
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
