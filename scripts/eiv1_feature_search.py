"""自動 feature 探索 = 「指標が勝手に増え、 効かないものは勝手に捨てられる」仕組み — 2026-07-23。

  生成 → 帰無分布で刈り込み → ブロック AUC → 候補 value 学習 → ε=0 arena gate → 採用/棄却

⭐ 増やすだけならノイズも増える。 本体は **捨てる側** で、 3 段の関門を通ったものだけ採用する:
  関門1 (統計): ランダム列 (帰無分布) より permutation importance が明確に高い列だけ残す。
                300 列試して「効いたものを残す」を素朴にやると必ず偶然を拾うのでここが要。
  関門2 (予測): 残った列を足して game 単位 split の AUC が --min-auc 以上改善するか。
  関門3 (強さ): ε=0 arena で現 value と直接対戦し、 **勝率が落ちていない**こと。
                AUC が上がっても強くならない乖離は実測済なので、 最後は必ず対戦で見る。

採用したら db/eiv1/feature_spec.json を更新 (次の train から次元が伸びる)。 履歴は
db/eiv1/feature_search_log.jsonl に採用/棄却の理由付きで残る。

  .venv/bin/python scripts/eiv1_feature_search.py --sample 120000 --arena-pairs 40
  .venv/bin/python scripts/eiv1_feature_search.py --no-arena     # 関門2 まで (速い)
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
from sklearn.inspection import permutation_importance  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402
from engine import feature_spec as FS  # noqa: E402
from engine.eiv1_features import eiv1_train_vector  # noqa: E402

EIV1_DIR = ROOT / "db" / "eiv1"
CORPUS = EIV1_DIR / "corpus.jsonl"
VALUE = EIV1_DIR / "value.pkl"
CAND = EIV1_DIR / "_candidate_value.pkl"
LOG = EIV1_DIR / "feature_search_log.jsonl"
CAP = {"max_iter": 300, "max_leaf_nodes": 31, "max_depth": None,
       "learning_rate": 0.05, "l2_regularization": 1.0}
N_NOISE = 16   # 帰無分布用のランダム列数


def _log(rec: dict) -> None:
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _load_rows(sample: int) -> list:
    lines = []
    with open(CORPUS, encoding="utf-8") as f:
        for line in f:
            lines.append(line)
            if len(lines) > sample:
                lines.pop(0)
    return lines


def _build(lines: list, cand: list):
    """corpus 行 → (base=現行 spec 込みの学習ベクトル, 候補列, y, group, turn)。"""
    Xb, Xc, y, groups = [], [], [], []
    prev_key, run_id = None, 0
    for line in lines:
        try:
            d = json.loads(line)
            snap = d.get("state")
            if not snap:
                continue
            Xb.append(eiv1_train_vector(d))
            Xc.append(FS.evaluate(snap, cand))
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
            continue
    return (np.array(Xb, dtype=np.float32), np.array(Xc, dtype=np.float32),
            np.array(y, dtype=np.int32), np.array(groups))


def _split(groups: np.ndarray, seed: int = 0):
    uniq = np.unique(groups)
    perm = np.random.RandomState(seed).permutation(len(uniq))
    test_ids = set(uniq[perm[int(len(uniq) * 0.8):]].tolist())
    is_te = np.fromiter((g in test_ids for g in groups), dtype=bool, count=len(groups))
    return np.flatnonzero(~is_te), np.flatnonzero(is_te), len(uniq)


def _auc(X, y, tr, te) -> float:
    m = HistGradientBoostingClassifier(random_state=0, **CAP)
    m.fit(X[tr], y[tr])
    return float(roc_auc_score(y[te], m.predict_proba(X[te])[:, 1]))


def _eval_block(lines: list, spec: list) -> np.ndarray:
    """corpus 行 × spec → 行列 (state を持つ行だけ、 _build と同じ順序)。"""
    out = []
    for line in lines:
        try:
            snap = json.loads(line).get("state")
            if not snap:
                continue
            out.append(FS.evaluate(snap, spec))
        except Exception:
            continue
    return np.array(out, dtype=np.float32)


def _card_search(a, t0, cards=None, tag="card"):
    """カード ID 列の探索。 ⭐ 疎な列を数千本まとめて放り込むと (a) メモリと学習時間が爆発し
    (b) 偶然効いて見える列を必ず拾う。 ブロックに割って **各ブロックごとに帰無分布 (ランダム列)
    と比較** することで、 両方を同時に抑える。"""
    if cards is None:
        zones = tuple(z for z in a.card_zones.split(",") if z)
        freq = FS.card_frequency()
        top_n = len(freq) if a.card_ids < 0 else a.card_ids
        cards = FS.generate_card_candidates(top_n, zones)
        print(f"カード ID 列: {len(freq)} 種中 上位 {top_n} × {len(zones)} zone = "
              f"{len(cards):,} 列 をブロック {a.card_block} ごとに選別", flush=True)
    else:
        print(f"{tag} 列: {len(cards):,} 列 をブロック {a.card_block} ごとに選別", flush=True)

    lines = _load_rows(a.sample)
    Xb, _, y, groups = _build(lines, [])
    n = len(y)
    tr, te, n_games = _split(groups)
    print(f"n={n:,} games={n_games:,} base_dim={Xb.shape[1]} ({time.time() - t0:.0f}s)", flush=True)
    rng = np.random.RandomState(0)
    noise = rng.normal(size=(n, N_NOISE)).astype(np.float32)
    sub = te if len(te) <= 8000 else rng.choice(te, 8000, replace=False)

    kept, kept_imp = [], []
    for bi in range(0, len(cards), a.card_block):
        blk = cards[bi:bi + a.card_block]
        Xk = _eval_block(lines, blk)
        if len(Xk) != n:
            print(f"  block {bi // a.card_block + 1}: 行数不一致 → skip", flush=True)
            continue
        X = np.hstack([Xb, Xk, noise])
        m = HistGradientBoostingClassifier(random_state=0, **CAP)
        m.fit(X[tr], y[tr])
        pi = permutation_importance(m, X[sub], y[sub], n_repeats=2, random_state=0,
                                    scoring="roc_auc", n_jobs=1)
        imp = pi.importances_mean
        b = Xb.shape[1]
        ic, inz = imp[b:b + len(blk)], imp[b + len(blk):]
        thr = float(inz.max())
        hits = [int(i) for i in np.argsort(-ic) if ic[i] > thr]
        for i in hits:
            kept.append(blk[i]); kept_imp.append(float(ic[i]))
        print(f"  block {bi // a.card_block + 1}/{-(-len(cards) // a.card_block)}: "
              f"{len(blk)} 列中 {len(hits)} 列が閾値超え (thr={thr:.5f}) "
              f"({time.time() - t0:.0f}s)", flush=True)
        del X, Xk

    if not kept:
        _log({"result": "no_candidate", "mode": tag})
        print("採用候補なし → 終了", flush=True)
        return
    order = np.argsort(-np.array(kept_imp))[:a.max_keep]
    kept = [kept[int(i)] for i in order]
    print(f"関門1 通過 {len(kept)} 列 (上位):", flush=True)
    for c in kept[:10]:
        print(f"    {FS.col_name(c)}", flush=True)

    Xk = _eval_block(lines, kept)
    auc_base = _auc(Xb, y, tr, te)
    auc_new = _auc(np.hstack([Xb, Xk]), y, tr, te)
    d_auc = auc_new - auc_base
    print(f"関門2: AUC {auc_base:.4f} → {auc_new:.4f} ({d_auc:+.4f}, 要求 {a.min_auc:+.4f}) "
          f"({time.time() - t0:.0f}s)", flush=True)
    if d_auc < a.min_auc:
        _log({"result": "rejected_auc", "mode": tag, "n_kept": len(kept),
              "auc_base": auc_base, "auc_new": auc_new, "d_auc": d_auc})
        print("→ 棄却 (AUC 改善が不足)", flush=True)
        return
    _log({"result": "passed_auc_pending_arena", "mode": tag, "n_kept": len(kept),
          "d_auc": d_auc, "names": [FS.col_name(c) for c in kept]})
    print("関門2 通過 → 関門3 (arena) は別途 --no-arena を外して実行、 "
          "または下記を spec に手動採用", flush=True)
    FS.save_spec(EIV1_DIR / f"feature_spec.{tag}_candidate.json", kept,
                 {"mode": tag, "d_auc": d_auc, "auc_base": auc_base, "auc_new": auc_new})
    print(f"候補 spec を db/eiv1/feature_spec.{tag}_candidate.json に保存 ({len(kept)} 列)",
          flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=120000, help="探索 (関門1-2) に使う corpus 行数")
    ap.add_argument("--full-sample", type=int, default=220000,
                    help="関門3 の候補 value 学習に使う corpus 行数")
    ap.add_argument("--min-auc", type=float, default=0.0010, help="関門2: 要求する AUC 改善")
    ap.add_argument("--max-keep", type=int, default=40, help="1 回の探索で採用する最大列数")
    ap.add_argument("--interactions", type=int, default=8,
                    help="関門1 を通った上位 N 列に文脈スカラーを掛けた列も試す (0=しない)")
    ap.add_argument("--arena-pairs", type=int, default=40, help="関門3 の arena ペア数 (1 ペア=4 game)")
    ap.add_argument("--arena-margin", type=float, default=0.02,
                    help="関門3: 現 value 相手に (0.5 - margin) 未満なら棄却")
    ap.add_argument("--no-arena", action="store_true", help="関門3 を省く (探索のみ)")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--dry-run", action="store_true", help="採用しない (spec を書き換えない)")
    ap.add_argument("--group", default="",
                    help="der / don / agg (comma 可) を探索する。 未指定はカード ID or 集計列")
    ap.add_argument("--card-ids", type=int, default=0,
                    help="カード ID 列を探索する (頻出上位 N 種、 -1 = 全種)。 0 = 集計列を探索")
    ap.add_argument("--card-zones",
                    # opp_seen_hand = 公開サーチ/バウンスで割れた相手の手札。 2026-07-24 に記録が
                    # 入るまで常に空だったので前回の探索では除外していた
                    default="my_board,opp_board,my_hand,my_trash,opp_trash,opp_seen_hand")
    ap.add_argument("--card-block", type=int, default=600,
                    help="カード ID 列はブロックに分けて選別 (メモリと時間の上限を切る)")
    a = ap.parse_args()
    t0 = time.time()

    if a.group:
        gen = {"der": FS.generate_derived_candidates, "don": FS.generate_don_candidates,
               "agg": FS.generate_candidates, "eye": FS.generate_eyes_candidates}
        cols = []
        for g in a.group.split(","):
            if g in gen:
                cols += gen[g]()
        return _card_search(a, t0, cards=cols, tag=a.group.replace(",", "_"))
    if a.card_ids:
        return _card_search(a, t0)
    cand_cols = FS.generate_candidates()
    print(f"候補列を機械生成: {len(cand_cols)} 列 "
          f"({len(FS.ZONES)} zone × {len(FS.CATS)} カテゴリ × 統計)", flush=True)
    lines = _load_rows(a.sample)
    Xb, Xc, y, groups = _build(lines, cand_cols)
    n = len(y)
    tr, te, n_games = _split(groups)
    print(f"n={n:,} games={n_games:,} base_dim={Xb.shape[1]} cand_dim={Xc.shape[1]} "
          f"({time.time() - t0:.0f}s)", flush=True)

    # --- 関門1: 帰無分布 (ランダム列) より importance が高い列だけ残す -------------
    rng = np.random.RandomState(0)
    noise = rng.normal(size=(n, N_NOISE)).astype(np.float32)
    X = np.hstack([Xb, Xc, noise])
    m = HistGradientBoostingClassifier(random_state=0, **CAP)
    m.fit(X[tr], y[tr])
    # test の一部で permutation importance (全件は重い)
    sub = te if len(te) <= 12000 else rng.choice(te, 12000, replace=False)
    pi = permutation_importance(m, X[sub], y[sub], n_repeats=3, random_state=0,
                                scoring="roc_auc", n_jobs=1)
    imp = pi.importances_mean
    b, c = Xb.shape[1], Xc.shape[1]
    imp_cand, imp_noise = imp[b:b + c], imp[b + c:]
    thr = float(imp_noise.max())
    order = np.argsort(-imp_cand)
    keep_idx = [int(i) for i in order if imp_cand[i] > thr][:a.max_keep]
    print(f"関門1: ノイズ列の最大 importance = {thr:.5f} → 超えた候補 "
          f"{int((imp_cand > thr).sum())} 列、 採用上位 {len(keep_idx)} 列 "
          f"({time.time() - t0:.0f}s)", flush=True)
    for i in keep_idx[:10]:
        print(f"    {FS.col_name(cand_cols[i]):<40} imp={imp_cand[i]:.5f}", flush=True)
    if not keep_idx:
        _log({"result": "no_candidate", "thr": thr})
        print("採用候補なし → 終了", flush=True)
        return

    kept = [cand_cols[i] for i in keep_idx]

    # --- 交互作用の第 2 波 (この repo の実績上、 効くのは盤面と相互作用する形) ------
    if a.interactions:
        inter = FS.generate_interactions(kept[:a.interactions])
        Xi = np.array([FS.evaluate(json.loads(line).get("state") or {}, inter)
                       for line in lines if json.loads(line).get("state")], dtype=np.float32)
        if len(Xi) == n:
            X2 = np.hstack([Xb, Xi, noise])
            m2 = HistGradientBoostingClassifier(random_state=0, **CAP)
            m2.fit(X2[tr], y[tr])
            pi2 = permutation_importance(m2, X2[sub], y[sub], n_repeats=3, random_state=0,
                                         scoring="roc_auc", n_jobs=1)
            imp2 = pi2.importances_mean
            ii, nn2 = imp2[Xb.shape[1]:Xb.shape[1] + len(inter)], imp2[Xb.shape[1] + len(inter):]
            thr2 = float(nn2.max())
            add = [inter[int(i)] for i in np.argsort(-ii) if ii[int(i)] > thr2][:a.max_keep // 2]
            print(f"関門1b (交互作用): {len(inter)} 列中 {len(add)} 列が閾値超え", flush=True)
            kept += add

    # --- 関門2: ブロック AUC ---------------------------------------------------
    Xk = np.array([FS.evaluate(json.loads(line).get("state") or {}, kept)
                   for line in lines if json.loads(line).get("state")], dtype=np.float32)
    auc_base = _auc(Xb, y, tr, te)
    auc_new = _auc(np.hstack([Xb, Xk]), y, tr, te)
    d_auc = auc_new - auc_base
    print(f"関門2: AUC {auc_base:.4f} → {auc_new:.4f} ({d_auc:+.4f}, 要求 {a.min_auc:+.4f}) "
          f"({time.time() - t0:.0f}s)", flush=True)
    if d_auc < a.min_auc:
        _log({"result": "rejected_auc", "n_kept": len(kept), "auc_base": auc_base,
              "auc_new": auc_new, "d_auc": d_auc})
        print("→ 棄却 (AUC 改善が不足)", flush=True)
        return

    # --- 関門3: ε=0 arena で現 value と直接対戦 --------------------------------
    if a.no_arena or a.dry_run:
        print("関門3 は省略", flush=True)
    else:
        # 候補 value は大きめの sample で学習 (配備条件に近づける。 全件は corpus 1GB 級で
        # メモリを食うので --full-sample で上限を切る)
        full = _load_rows(a.full_sample)
        Xf_b, _, yf, gf = _build(full, [])
        Xf_k = np.array([FS.evaluate(json.loads(line).get("state") or {}, kept)
                         for line in full if json.loads(line).get("state")], dtype=np.float32)
        cand_model = HistGradientBoostingClassifier(
            random_state=0, max_iter=1000, max_leaf_nodes=63, max_depth=None,
            learning_rate=0.05, l2_regularization=1.0)
        cand_model.fit(np.hstack([Xf_b, Xf_k]), yf)
        with open(CAND, "wb") as f:
            pickle.dump(cand_model, f)
        FS.save_spec(FS.spec_path_for_model(CAND), kept, {"source": "feature_search"})
        print(f"候補 value 学習完了 (n={len(yf):,}, dim={Xf_b.shape[1] + Xf_k.shape[1]}) "
              f"→ arena ({time.time() - t0:.0f}s)", flush=True)
        r = subprocess.run(
            [str(ROOT / ".venv" / "bin" / "python"), str(ROOT / "scripts" / "eiv1_arena.py"),
             "--arm", str(CAND), "--refs", str(VALUE), "--pairs", str(a.arena_pairs),
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
        if win is None:
            _log({"result": "rejected_arena_failed", "n_kept": len(kept), "d_auc": d_auc})
            print("→ 棄却 (arena が測れなかった)", flush=True)
            return
        if win < 0.5 - a.arena_margin:
            _log({"result": "rejected_arena", "n_kept": len(kept), "d_auc": d_auc, "win": win})
            print(f"→ 棄却 (arena 勝率 {win:.3f} < {0.5 - a.arena_margin:.3f})", flush=True)
            return
        print(f"関門3: arena 勝率 {win:.3f} → 通過", flush=True)

    # --- 採用 ------------------------------------------------------------------
    if a.dry_run:
        print("dry-run: spec は更新しない", flush=True)
        return
    prev = FS.active_spec()
    FS.save_spec(FS.ACTIVE_SPEC_PATH, prev + kept,
                 {"added": len(kept), "d_auc": d_auc, "auc_base": auc_base, "auc_new": auc_new,
                  "sample": n, "secs": round(time.time() - t0, 1)})
    _log({"result": "accepted", "n_added": len(kept), "n_total": len(prev) + len(kept),
          "d_auc": d_auc, "names": [FS.col_name(c) for c in kept]})
    print(f"✅ 採用: +{len(kept)} 列 (spec 合計 {len(prev) + len(kept)} 列)。 "
          f"次の train から次元が伸びる", flush=True)


if __name__ == "__main__":
    main()
