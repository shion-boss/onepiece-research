# -*- coding: utf-8 -*-
"""Claude 教師データ(distill corpus)から deck の value を学習。

[[project_claude_teacher_data_collection]]。 claude_play の distill_<slug>.jsonl
(= Claude の良い play の各局面 v6 特徴量 + 勝敗) で GBM value を学習 = self-play の循環
(良い手を打たない→学べない) を、 Claude の expert 分布で破る (= Bonanza 法の Claude 版)。

  .venv/bin/python scripts/distill_claude_value.py --deck cardrush_1454
    [--corpus db/claude_play/distill_cardrush_1454.jsonl] [--mix-selfplay db/_selfplay/xxx.jsonl]

出力: db/_selfplay/<slug>_claude_distilled.pkl (38-dim v6)。
配備は field gate (matchup_value_deploy_ab) で deployed value 超えを確認してから。
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_corpus(path: Path):
    X, y = [], []
    if not path.exists():
        return X, y
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
            f = r.get("feat")
            yy = r.get("y")
            if isinstance(f, list) and len(f) == 38 and yy in (0, 1):
                X.append(f); y.append(int(yy))
        except Exception:
            pass
    return X, y


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="cardrush_1454")
    ap.add_argument("--corpus", default=None, help="既定 db/claude_play/distill_<deck>.jsonl")
    ap.add_argument("--out", default=None, help="既定 db/_selfplay/<deck>_claude_distilled.pkl")
    ap.add_argument("--min-samples", type=int, default=500, help="これ未満なら学習せず警告(データ不足)")
    a = ap.parse_args()
    corpus = Path(a.corpus) if a.corpus else ROOT / "db" / "claude_play" / f"distill_{a.deck}.jsonl"
    X, y = _load_corpus(corpus)
    npos = sum(y)
    print(f"[distill] deck={a.deck} corpus={corpus.name} samples={len(X)} pos={npos}"
          f"({npos/max(1,len(y))*100:.0f}%)", flush=True)
    if len(X) < a.min_samples:
        print(f"[distill] ⚠ データ不足 ({len(X)} < {a.min_samples})。 cloud agent の蓄積を待つ。", flush=True)
        # 参考: 何局分か概算 (1局 ~15-25 決定局面)
        print(f"  ≈ {len(X)//20} 局相当。 min {a.min_samples//20}+ 局(理想 ~100局)推奨。", flush=True)
        return
    if len(set(y)) < 2:
        print("[distill] ⚠ 単一クラス (全勝 or 全敗)。 相手を多様化して再収集。", flush=True)
        return
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import roc_auc_score
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, random_state=1,
                                          stratify=y if 0 < npos < len(y) else None)
    m = GradientBoostingClassifier(n_estimators=200, max_depth=3, learning_rate=0.05,
                                   subsample=0.8, random_state=0).fit(Xtr, ytr)
    auc = roc_auc_score(yte, [p[1] for p in m.predict_proba(Xte)])
    print(f"[distill] held-out AUC = {auc:.4f}  (Claude expert 分布の value)", flush=True)
    # full-fit + save
    import pickle
    mf = GradientBoostingClassifier(n_estimators=200, max_depth=3, learning_rate=0.05,
                                    subsample=0.8, random_state=0).fit(X, y)
    outdir = ROOT / "db" / "_selfplay"; outdir.mkdir(exist_ok=True)
    out = Path(a.out) if a.out else outdir / f"{a.deck}_claude_distilled.pkl"
    pickle.dump(mf, open(out, "wb"))
    print(f"[saved] {out} (38-dim v6, Claude 教師 distilled value)", flush=True)
    print(f"[next] field gate: matchup_value_deploy_ab.py --deck {a.deck} で deployed 超えを確認 → cp で配備", flush=True)


if __name__ == "__main__":
    main()
