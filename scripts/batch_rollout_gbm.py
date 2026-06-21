# -*- coding: utf-8 -*-
"""全デッキ rollout-GBM 展開バッチ (= 2026-06-18、 検証ハーネス→value 学習の横展開)。

各デッキで:
  1. rollout-label GBM を学習 (= train_value_gbm.py --rollout-label N、 test パスへ)
  2. A/B: rollout-GBM(X) vs 現行value(Y = 既存GBM があればそれ、 無ければ board_eval) を mirror 対決
  3. 勝率 >= --promote-threshold かつ --promote 指定時のみ 本番パス db/value_gbm_<slug>.pkl へ昇格

**規律**: メタは既に単一outcome GBM を持つので、 rollout がそれを上回った時だけ上書き (= 回帰防止)。
非GBMデッキは baseline=board_eval なのでほぼ確実に勝つ (= 青黄ナミ 79% 実証)。

checkpoint: scoreboard JSON に逐次保存し、 再実行で完了デッキを skip (= [[feedback_checkpoint_resume]])。

usage:
  # dry-run (学習+A/Bのみ、 昇格しない):
  PYTHONPATH=. .venv/bin/python scripts/batch_rollout_gbm.py --decks non-gbm --games 220 --ab-games 20
  # 勝ったら昇格:
  PYTHONPATH=. .venv/bin/python scripts/batch_rollout_gbm.py --decks meta --promote --promote-threshold 0.55
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts.ab_value_gbm import run as ab_run
from scripts.ab_value_gbm import run_parallel as ab_run_par


def _all_deck_slugs() -> list[str]:
    out = []
    for p in sorted((REPO / "decks").glob("*.json")):
        s = p.stem
        if any(x in s for x in ("analysis", "target_v1", "locked")):
            continue
        out.append(s)
    return out


def _has_gbm(slug: str) -> bool:
    return (REPO / "db" / f"value_gbm_{slug}.pkl").exists()


def _select(spec: str) -> list[str]:
    if spec == "all":
        return _all_deck_slugs()
    if spec == "non-gbm":
        return [s for s in _all_deck_slugs() if not _has_gbm(s)]
    if spec == "meta":
        return json.loads((REPO / "db" / "meta_decks.json").read_text())["meta_deck_slugs"]
    # カンマ区切り明示リスト
    return [s.strip() for s in spec.split(",") if s.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decks", default="non-gbm",
                    help="all | non-gbm | meta | <slug,slug,...>")
    ap.add_argument("--games", type=int, default=220, help="学習ゲーム数")
    ap.add_argument("--rollout-label", type=int, default=12)
    ap.add_argument("--rollout-ai", default="greedy",
                    choices=["greedy", "light", "beam", "exploitbeam"],
                    help="rollout policy (= ラベル教師。 beam は勝ちデッキの上積み用)")
    ap.add_argument("--test-suffix", default="rollout",
                    help="test pkl 名 db/value_gbm_<slug>_<suffix>.pkl (= beam上積みは beamroll)")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--ab-games", type=int, default=20)
    ap.add_argument("--ab-workers", type=int, default=12,
                    help="A/B mirror の並列度 (= ExploitBeam は ~10s/game なので high-N は並列必須)")
    ap.add_argument("--promote", action="store_true", help="勝率閾値超で本番GBMへ昇格")
    ap.add_argument("--promote-threshold", type=float, default=0.55)
    ap.add_argument("--scoreboard", type=Path,
                    default=REPO / "db" / "rollout_gbm_scoreboard.json")
    args = ap.parse_args()

    slugs = _select(args.decks)
    board: dict = {}
    if args.scoreboard.exists():
        board = json.loads(args.scoreboard.read_text())
    print(f"対象 {len(slugs)} デッキ | 既完了 {len([s for s in slugs if s in board])} | "
          f"promote={args.promote}(>={args.promote_threshold})\n", flush=True)

    for i, slug in enumerate(slugs):
        if slug in board:
            print(f"[{i+1}/{len(slugs)}] {slug}: skip (済 winrate={board[slug].get('winrate')})", flush=True)
            continue
        t0 = time.time()
        test_pkl = REPO / "db" / f"value_gbm_{slug}_{args.test_suffix}.pkl"
        baseline = str(REPO / "db" / f"value_gbm_{slug}.pkl") if _has_gbm(slug) else "none"
        base_kind = "既存GBM" if baseline != "none" else "board_eval"
        # 1) train
        r = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "train_value_gbm.py"),
             "--deck", slug, "--games", str(args.games),
             "--rollout-label", str(args.rollout_label),
             "--rollout-ai", args.rollout_ai,
             "--workers", str(args.workers), "--out", str(test_pkl)],
            capture_output=True, text=True, cwd=str(REPO))
        if r.returncode != 0 or not test_pkl.exists():
            print(f"[{i+1}/{len(slugs)}] {slug}: 学習失敗 skip\n{r.stdout[-300:]}{r.stderr[-300:]}", flush=True)
            board[slug] = {"error": "train_failed"}
            args.scoreboard.write_text(json.dumps(board, ensure_ascii=False, indent=1))
            continue
        # 2) A/B vs baseline (high-N は並列で)
        try:
            if args.ab_workers > 1:
                wr = ab_run_par(slug, str(test_pkl), baseline, args.ab_games,
                                seed=100, workers=args.ab_workers)
            else:
                wr = ab_run(slug, str(test_pkl), baseline, args.ab_games, seed=100)
        except Exception as e:
            print(f"[{i+1}/{len(slugs)}] {slug}: A/B失敗 {e}", flush=True)
            board[slug] = {"error": f"ab_failed:{e}"}
            args.scoreboard.write_text(json.dumps(board, ensure_ascii=False, indent=1))
            continue
        promoted = False
        if args.promote and wr >= args.promote_threshold:
            shutil.copyfile(test_pkl, REPO / "db" / f"value_gbm_{slug}.pkl")
            promoted = True
        board[slug] = {"winrate": round(wr, 3), "baseline": base_kind,
                       "promoted": promoted, "sec": round(time.time() - t0)}
        args.scoreboard.write_text(json.dumps(board, ensure_ascii=False, indent=1))
        tag = "昇格" if promoted else ("勝(未昇格)" if wr >= args.promote_threshold else "見送り")
        print(f"[{i+1}/{len(slugs)}] {slug}: vs {base_kind} → X勝率 {wr:.1%}  [{tag}]  "
              f"({board[slug]['sec']}s)", flush=True)

    # サマリ
    done = {s: board[s] for s in slugs if s in board and "winrate" in board[s]}
    wins = [s for s, v in done.items() if v["winrate"] >= args.promote_threshold]
    print(f"\n=== 完了 {len(done)} | 閾値超(>={args.promote_threshold}) {len(wins)} | "
          f"昇格 {len([s for s,v in done.items() if v.get('promoted')])} ===")
    for s in sorted(done, key=lambda x: done[x]["winrate"], reverse=True):
        v = done[s]
        print(f"  {s:28} vs {v['baseline']:9} {v['winrate']:.1%} "
              f"{'昇格' if v.get('promoted') else ''}")


if __name__ == "__main__":
    main()
