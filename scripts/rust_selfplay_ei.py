"""Rust ネイティブ self-play による Expert Iteration ループ (データフライホイール) — 2026-07-31。

Rust engine を作った本来の目的 = self-play 学習ループを単一 PC で回す。 その最小実装:

  ① 生成: 現在の value でネイティブ self-play (eng.self_play collect_traj) → (特徴, 勝敗ラベル)
  ② 学習: logistic regression で value 重み (16 次元) を学習 → db/rust_value_weights.json
  ③ 評価: 新 value greedy vs 旧 value greedy を head-to-head (eng.eval_ab、 先後均等) で勝率測定
  ④ 反復: 勝率 > gate なら新 value を採用して ①へ

value は features() の線形結合 (logistic) = Rust の eval_with に weights を渡すだけで完結
(GBM/NN より弱いが Rust 移植が自明でループが閉じる = capability 優先。 強い value は次段)。

  .venv/bin/python scripts/rust_selfplay_ei.py --rounds 4 --games 200 --eval-games 120
  .venv/bin/python scripts/rust_selfplay_ei.py --resume   # 既存 weights から再開
  .venv/bin/python scripts/rust_selfplay_ei.py --preflight   # RL 開始前に engine 速度 + heuristic self-play 分散を観察

⚠ v1 の限界 (self-play 品質): 方策=greedy (beam でなく、 生成速度優先) / 防御未実装 (アタック貫通) /
  value=線形。 = 「フライホイールが閉じて value が greedy を強くする」を実証する最小系。

観察: 各 round で成長 (A/B 勝率) / 学習 (AUC・loss・較正・重み) / self-play 分散 (デッキ・ゲーム長・
  ターン別勝率・先攻有利・matchup・特徴分布) を db/rust_selfplay/manifest.json に永続化。
  ダッシュボードは scripts/rust_selfplay_dashboard.py (http://localhost:8770)。
"""
from __future__ import annotations
import argparse
import json
import math
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import optcg_engine as eng  # noqa: E402

# ⛔ 選択列挙モード (ONEPIECE_CHOICE_SEARCH) では Rust を使わない。
#   Rust は pending_choice / continuation 未実装なので Python と別のゲームになる。
from engine.rust_shadow import assert_rust_safe_for_choice_search  # noqa: E402
assert_rust_safe_for_choice_search("rust_selfplay_ei.py")

import scripts.rust_parity_check as P  # noqa: E402
from engine.state_snapshot import _ser_full  # noqa: E402

WEIGHTS_PATH = ROOT / "db" / "rust_value_weights.json"
OUT_DIR = ROOT / "db" / "rust_selfplay"
MANIFEST_PATH = OUT_DIR / "manifest.json"
N_FEATURES = 16

# features() (rust_engine/src/selfplay.rs) の 16 次元名。 学習した重みを人間可読に表示する為。
FEATURE_NAMES = [
    "ライフ差", "自ライフ", "相手ライフ", "手札差", "自手札", "相手手札",
    "盤面パワー差", "盤面数差", "自盤面数", "相手盤面数", "使用可能ドン",
    "ターン進行", "リーダーパワー差", "自レスト率", "相手レスト率", "bias",
]
TURN_FEATURE_IDX = 11   # features[11] = turn_number / 20.0

# 生成/評価に使うデッキ pool (メタ 16 の一部。 多様性のため異なるアーキタイプ)。
DECK_POOL = [
    "cardrush_1385", "cardrush_1478", "cardrush_1342", "cardrush_1491",
    "pros02_zoro_g", "tcgportal_op13_luffy",
]

_deck_cache: dict[str, str] = {}
_leader_cache: dict[str, tuple[str, str]] = {}   # slug -> (leader_id, leader_name)


def deck_value(slug: str) -> str:
    """Rust に渡す deck Value (マリガン判定材料込み、 rust_parity_check.deck_value に集約)。"""
    if slug not in _leader_cache:
        d = P._dl(slug)
        _leader_cache[slug] = (d.leader.card_id, getattr(d.leader, "name", d.leader.card_id))
    return P.deck_value(slug)


def leader_of(slug: str) -> tuple[str, str]:
    deck_value(slug)   # populate cache
    return _leader_cache[slug]


def rng_state(seed: int) -> str:
    return json.dumps(list(random.Random(seed).getstate()[1]))


def _pair(seed: int) -> tuple[str, str]:
    """seed → (deck_a, deck_b)。 生成/評価で同じ組を再現する。"""
    a = DECK_POOL[seed % len(DECK_POOL)]
    b = DECK_POOL[(seed // len(DECK_POOL) + 1) % len(DECK_POOL)]
    if a == b:
        b = DECK_POOL[(seed + 1) % len(DECK_POOL)]
    return a, b


def generate(weights: list[float] | None, n_games: int, seed0: int) -> dict:
    """現在の value で n_games 生成し、 特徴/ラベル + 観察用メタ (per-game) を返す。

    返り値 dict:
      X, y          : np.ndarray  (特徴 [rows,16], ラベル [rows])
      game_ids      : np.ndarray  (各 row が属する game index、 holdout split 用)
      games         : list[dict]  (per-game: deck_a/b, leader, winner, turns, first_player)
      gen_sec       : float
    """
    wj = json.dumps(weights) if weights is not None else None
    X, Y, game_ids = [], [], []
    games: list[dict] = []
    t0 = time.time()
    for g in range(n_games):
        seed = seed0 + g
        a, b = _pair(seed)
        first = seed % 2
        r = json.loads(eng.self_play(deck_value(a), deck_value(b), rng_state(seed),
                                     first, "greedy", wj, 8, 12, 40, True))
        la_id, la_nm = leader_of(a)
        lb_id, lb_nm = leader_of(b)
        games.append({
            "deck_a": a, "deck_b": b,
            "leader_a": la_id, "leader_a_name": la_nm,
            "leader_b": lb_id, "leader_b_name": lb_nm,
            "winner": r.get("winner"), "turns": r.get("turns"),
            "first_player": first, "game_over": r.get("game_over"),
        })
        for row in r.get("trajectory", []):
            X.append(row["f"])
            Y.append(row["y"])
            game_ids.append(g)
    return {
        "X": np.asarray(X, dtype=np.float64),
        "y": np.asarray(Y, dtype=np.float64),
        "game_ids": np.asarray(game_ids, dtype=np.int64),
        "games": games,
        "gen_sec": time.time() - t0,
    }


def train_logistic(X: np.ndarray, y: np.ndarray, l2: float = 1e-3, iters: int = 400, lr: float = 0.5) -> list[float]:
    """features (bias 込み 16 次元) → P(勝ち) の logistic regression。 numpy full-batch GD。"""
    n, d = X.shape
    w = np.zeros(d)
    for _ in range(iters):
        z = X @ w
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
        grad = X.T @ (p - y) / n + l2 * w
        w -= lr * grad
    return w.tolist()


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def _auc(y: np.ndarray, p: np.ndarray) -> float:
    """ROC-AUC (Mann-Whitney U、 tie 対応)。 sklearn 不使用で軽量。"""
    pos = p[y >= 0.5]
    neg = p[y < 0.5]
    if len(pos) == 0 or len(neg) == 0:
        return 0.5
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p), dtype=np.float64)
    ranks[order] = np.arange(1, len(p) + 1)
    # tie は平均ランクに (mergesort 安定なので簡易 tie 補正)
    sp = p[order]
    i = 0
    while i < len(sp):
        j = i
        while j + 1 < len(sp) and sp[j + 1] == sp[i]:
            j += 1
        if j > i:
            ranks[order[i:j + 1]] = (i + 1 + j + 1) / 2.0
        i = j + 1
    r_pos = ranks[y >= 0.5].sum()
    n_pos, n_neg = len(pos), len(neg)
    return float((r_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def value_diagnostics(gen: dict, weights: list[float]) -> dict:
    """新 weights を holdout (末尾 20% の game) で評価: AUC・logloss・較正・弁別。"""
    X, y, gid = gen["X"], gen["y"], gen["game_ids"]
    if len(y) < 200:
        return {}
    n_games = int(gid.max()) + 1 if len(gid) else 0
    cut = int(n_games * 0.8)
    tr = gid < cut
    ho = gid >= cut
    w = np.asarray(weights, dtype=np.float64)
    out: dict = {}
    # train
    if tr.sum() > 50:
        p = _sigmoid(X[tr] @ w)
        out["train_auc"] = round(_auc(y[tr], p), 4)
        eps = 1e-7
        out["train_logloss"] = round(float(-np.mean(y[tr] * np.log(p + eps) + (1 - y[tr]) * np.log(1 - p + eps))), 4)
    # holdout (リーク無し = 本物の予測精度)
    if ho.sum() > 50:
        ph = _sigmoid(X[ho] @ w)
        yh = y[ho]
        out["holdout_auc"] = round(_auc(yh, ph), 4)
        out["holdout_n"] = int(ho.sum())
        out["brier"] = round(float(np.mean((ph - yh) ** 2)), 4)
        # 較正 (reliability、 10 bin)
        ece = 0.0
        bins = []
        for i in range(10):
            lo, hi = i / 10.0, (i + 1) / 10.0
            m = (ph >= lo) & (ph < hi) if i < 9 else (ph >= lo) & (ph <= hi)
            k = int(m.sum())
            if k:
                conf, acc = float(ph[m].mean()), float(yh[m].mean())
                ece += (k / len(ph)) * abs(conf - acc)
                bins.append({"pred": round(conf, 3), "actual": round(acc, 3), "n": k})
            else:
                bins.append({"pred": round((lo + hi) / 2, 3), "actual": None, "n": 0})
        out["calibration"] = {"bins": bins, "ece": round(float(ece), 4)}
        # 予測値ヒスト (勝/負 別) = 弁別力
        out["hist_win"] = [int(x) for x in np.histogram(ph[yh >= 0.5], bins=10, range=(0, 1))[0]]
        out["hist_loss"] = [int(x) for x in np.histogram(ph[yh < 0.5], bins=10, range=(0, 1))[0]]
    return out


def selfplay_stats(gen: dict) -> dict:
    """生成した self-play の分散/偏り: デッキ分散・ゲーム長・ターン別勝率・先攻有利・matchup・特徴分布。"""
    X, y, games = gen["X"], gen["y"], gen["games"]
    st: dict = {"n_games": len(games), "n_rows": int(len(y))}
    decided = [g for g in games if g.get("winner") is not None]
    st["draw_rate"] = round(1 - len(decided) / len(games), 3) if games else 0.0
    # 先攻有利 (first player の勝率) — 席バイアスの監視
    fp_wins = sum(1 for g in decided if g["winner"] == g["first_player"])
    st["first_player_winrate"] = round(fp_wins / len(decided), 3) if decided else 0.5
    # ゲーム長
    turns = [g["turns"] for g in decided if g.get("turns")]
    if turns:
        st["mean_turns"] = round(sum(turns) / len(turns), 1)
        st["median_turns"] = int(sorted(turns)[len(turns) // 2])
        gl = Counter()
        for t in turns:
            gl[min(20, (t + 1) // 2 * 2)] += 1
        st["game_len_hist"] = [{"turn": k, "n": v} for k, v in sorted(gl.items())]
    # デッキ分散 (参加ゲーム数 + 勝率) — self-play で各デッキが均等に登場しているか
    dg: dict = defaultdict(lambda: [0, 0])   # slug -> [games, wins]
    for g in games:
        for side, dk in (("a", g["deck_a"]), ("b", g["deck_b"])):
            dg[dk][0] += 1
        if g.get("winner") is not None:
            wdk = g["deck_a"] if g["winner"] == 0 else g["deck_b"]
            dg[wdk][1] += 1
    deck_rows = [{"deck": k, "n": v[0], "win": round(v[1] / v[0], 3) if v[0] else 0.0}
                 for k, v in dg.items()]
    deck_rows.sort(key=lambda r: -r["n"])
    st["deck_dist"] = deck_rows
    if deck_rows:
        ns = [r["n"] for r in deck_rows]
        st["deck_min"], st["deck_max"], st["deck_types"] = min(ns), max(ns), len(deck_rows)
    # matchup (自リーダー行 × 相手リーダー列、 hero 視点勝率)
    mm: dict = defaultdict(lambda: [0, 0])
    lname: dict = {}
    for g in decided:
        la, lb = g["leader_a"], g["leader_b"]
        lname[la] = g["leader_a_name"]; lname[lb] = g["leader_b_name"]
        mm[(la, lb)][0] += 1; mm[(la, lb)][1] += 1 if g["winner"] == 0 else 0
        mm[(lb, la)][0] += 1; mm[(lb, la)][1] += 1 if g["winner"] == 1 else 0
    leaders = sorted({l for pair in mm for l in pair})
    def _lbl(lid):
        nm = lname.get(lid, lid)
        return f"{nm[:6]} {str(lid).split('-')[0]}"
    cells = []
    for h in leaders:
        row = []
        for o in leaders:
            nw = mm.get((h, o))
            if not nw or nw[0] < 5:
                row.append({"win": None, "n": nw[0] if nw else 0})
            else:
                row.append({"win": round(nw[1] / nw[0], 3), "n": nw[0]})
        cells.append(row)
    st["matchup"] = {"labels": [_lbl(l) for l in leaders], "cells": cells}
    # ターン別 hero 勝率 (feature[11]*20 から bucket)
    if len(y):
        tvals = np.rint(X[:, TURN_FEATURE_IDX] * 20).astype(int)
        tb: dict = defaultdict(lambda: [0, 0])
        for t, yi in zip(tvals, y):
            b = "1-4" if t <= 4 else ("5-7" if t <= 7 else ("8-10" if t <= 10 else "11+"))
            tb[b][0] += 1; tb[b][1] += yi
        order = {"1-4": 0, "5-7": 1, "8-10": 2, "11+": 3}
        st["turn_winrate"] = [{"bucket": b, "n": v[0], "win": round(v[1] / v[0], 3)}
                              for b, v in sorted(tb.items(), key=lambda kv: order.get(kv[0], 9))]
        # 特徴分布 (mean/std) — self-play 局面が各特徴でどう散っているか
        st["feature_mean"] = [round(float(x), 4) for x in X.mean(axis=0)]
        st["feature_std"] = [round(float(x), 4) for x in X.std(axis=0)]
    return st


def eval_ab(w_new: list[float] | None, w_old: list[float] | None, n_games: int, seed0: int,
            mode: str = "beam") -> dict:
    """value(w_new) vs value(w_old) を head-to-head。 先後を均等化して w_new の勝率+SE を返す。
    ⚠ mode=beam 推奨: 学習 value は greedy-1-ply では spurious 特徴を exploit されて負ける
    (empty-hand=win 等)、 探索 (beam) の葉評価に使うと heuristic を上回る (memory: value は search に載せる)。"""
    wn = json.dumps(w_new) if w_new is not None else None
    wo = json.dumps(w_old) if w_old is not None else None
    wins = 0
    played = 0
    draws = 0
    for g in range(n_games):
        seed = seed0 + g
        a, b = _pair(seed)
        new_is_p0 = g % 2 == 0
        w0j, w1j = (wn, wo) if new_is_p0 else (wo, wn)
        r = json.loads(eng.eval_ab(deck_value(a), deck_value(b), rng_state(seed),
                                   seed % 2, mode, w0j, w1j, 8, 10, 40))
        win = r.get("winner")
        if win is None:
            played += 1
            draws += 1
            continue
        new_won = (win == 0) == new_is_p0
        wins += 1 if new_won else 0
        played += 1
    wr = wins / played if played else 0.0
    se = math.sqrt(wr * (1 - wr) / played) if played else 0.0
    return {"win": round(wr, 4), "se": round(se, 4), "n": n_games, "draws": draws, "mode": mode}


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        try:
            return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"config": {}, "rounds": [], "preflight": None}


def _write_manifest(man: dict) -> None:
    """atomic write (tmp + rename)。 ダッシュボードが 15s 毎に読むので途中書き JSON を見せない。"""
    import os
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    man["updated"] = _now()
    tmp = MANIFEST_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, MANIFEST_PATH)


def _config(args) -> dict:
    return {
        "decks": DECK_POOL,
        "deck_leaders": {s: {"id": leader_of(s)[0], "name": leader_of(s)[1]} for s in DECK_POOL},
        "features": FEATURE_NAMES,
        "games_per_round": getattr(args, "games", None),
        "eval_games": getattr(args, "eval_games", None),
        "gate": getattr(args, "gate", None),
        "gen_mode": "greedy",
        "eval_mode": "beam",
        "beam": [8, 10],
        "n_features": N_FEATURES,
        "note": "Rust ネイティブ self-play EI (logistic value, 16dim)。 生成=greedy / A/B=beam。 v1=防御未実装",
    }


def preflight(n_games: int) -> None:
    """RL 開始前の観察: engine 速度 + heuristic (weights=None) self-play の分散を測って manifest に記録。"""
    eng.load_overlay(str(ROOT / "db" / "card_effects.json"))
    print(f"preflight: heuristic self-play {n_games} 試合を生成し分散/速度を計測 ...", flush=True)
    gen = generate(None, n_games, seed0=777)
    sp = selfplay_stats(gen)
    sps = round(len(gen["y"]) / gen["gen_sec"], 1) if gen["gen_sec"] else 0.0
    gps = round(n_games / gen["gen_sec"], 1) if gen["gen_sec"] else 0.0
    man = _load_manifest()
    man["config"] = _config(argparse.Namespace(games=None, eval_games=None, gate=0.53))
    man["preflight"] = {
        "policy": "heuristic (weights=None)", "n_games": n_games,
        "gen_sec": round(gen["gen_sec"], 2), "samples_per_sec": sps, "games_per_sec": gps,
        "selfplay": sp, "ts": _now(),
    }
    _write_manifest(man)
    print(f"  生成 {gen['gen_sec']:.1f}s = {gps:.0f} games/s / {sps:.0f} samples/s、 "
          f"draw={sp.get('draw_rate')} 先攻勝率={sp.get('first_player_winrate')} "
          f"中央ターン={sp.get('median_turns')}", flush=True)
    print(f"  → {MANIFEST_PATH} に記録。 dashboard: http://localhost:8770", flush=True)


def main():
    ap = argparse.ArgumentParser(description="Rust self-play Expert Iteration ループ")
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--games", type=int, default=200, help="1 round の生成ゲーム数")
    ap.add_argument("--eval-games", type=int, default=120, help="A/B 評価ゲーム数")
    ap.add_argument("--gate", type=float, default=0.53, help="採用する勝率下限 (対 前 value)")
    ap.add_argument("--resume", action="store_true", help="既存 weights から再開")
    ap.add_argument("--preflight", action="store_true",
                    help="RL 開始前に engine 速度 + heuristic self-play 分散を計測して終了")
    ap.add_argument("--preflight-games", type=int, default=120)
    args = ap.parse_args()

    if args.preflight:
        preflight(args.preflight_games)
        return

    eng.load_overlay(str(ROOT / "db" / "card_effects.json"))

    weights: list[float] | None = None
    man = _load_manifest()
    if args.resume and WEIGHTS_PATH.exists():
        weights = json.loads(WEIGHTS_PATH.read_text())["weights"]
        print(f"resume: 既存 value (次元 {len(weights)}) から開始")
    else:
        man["rounds"] = []   # 新規ランは round 履歴をリセット (resume 時は追記)

    man["config"] = _config(args)
    _write_manifest(man)

    base_round = man["rounds"][-1]["round"] + 1 if (args.resume and man["rounds"]) else 0

    for rnd_i in range(args.rounds):
        rnd = base_round + rnd_i
        # ① 生成 (現在の value で self-play)
        gen = generate(weights, args.games, seed0=1000 * (rnd + 1))
        gen_dt = gen["gen_sec"]
        # ② 学習
        w_new = train_logistic(gen["X"], gen["y"])
        # ③ 評価 (新 value vs 旧 value、 beam 葉評価)
        ab = eval_ab(w_new, weights, args.eval_games, seed0=50_000 + 1000 * rnd)
        wr = ab["win"]
        adopt = wr >= args.gate
        tag = "採用" if adopt else "棄却"
        # 観察: 学習診断 + self-play 分散
        diag = value_diagnostics(gen, w_new)
        sp = selfplay_stats(gen)
        sps = round(len(gen["y"]) / gen_dt, 1) if gen_dt else 0.0
        print(f"round {rnd}: gen {args.games}g/{len(gen['y'])}rows {gen_dt:.1f}s "
              f"({sps:.0f} samp/s) | A/B 新vs旧 = {wr*100:.1f}%±{ab['se']*100:.1f} "
              f"(N={args.eval_games}) | holdout AUC={diag.get('holdout_auc','—')} → {tag}", flush=True)
        # manifest に round を追記
        man = _load_manifest()
        man["config"] = _config(args)
        man["rounds"].append({
            "round": rnd, "n_games": args.games, "n_rows": int(len(gen["y"])),
            "gen_sec": round(gen_dt, 2), "samples_per_sec": sps,
            "ab_win": wr, "ab_se": ab["se"], "ab_n": ab["n"], "ab_draws": ab["draws"],
            "gate": args.gate, "adopt": adopt,
            "train_auc": diag.get("train_auc"), "holdout_auc": diag.get("holdout_auc"),
            "train_logloss": diag.get("train_logloss"), "brier": diag.get("brier"),
            "holdout_n": diag.get("holdout_n"),
            "calibration": diag.get("calibration"),
            "hist_win": diag.get("hist_win"), "hist_loss": diag.get("hist_loss"),
            "weights": w_new, "selfplay": sp, "ts": _now(),
        })
        _write_manifest(man)
        if adopt:
            weights = w_new
            WEIGHTS_PATH.write_text(json.dumps({
                "weights": weights, "n_features": N_FEATURES, "round": rnd,
                "note": "Rust self-play EI logistic value (features 線形, bias 込み 16dim)",
            }, ensure_ascii=False, indent=1), encoding="utf-8")

    if weights is not None:
        print(f"\n最終 value → {WEIGHTS_PATH}")
        print(f"観察: http://localhost:8770  (manifest = {MANIFEST_PATH})")
        print("Rust で使う: eng.self_play(..., weights_json=json.dumps(weights), ...)")


if __name__ == "__main__":
    main()
