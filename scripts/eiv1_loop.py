"""EIV1 駆動器 = 「回せばデータが貯まる」器 (2026-07-23)。

1 ラウンド = collect(append corpus) → train(全 corpus 再学習, 容量 progressive)。 これを --rounds 回す。
= EIV1 の⑤フライホイール⑥継続学習を1コマンドに。 毎日これを回せばデータが積まれ value が育つ。

  .venv/bin/python scripts/eiv1_loop.py --rounds 5 --games 40 --workers 12
  # cron/nohup で毎日回せば「コツコツ蓄積」。 iter0 は agnostic で collect → 学習後は EIV1 value で collect。
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "bin" / "python")
MANIFEST = ROOT / "db" / "eiv1" / "manifest.json"


def _corpus_n() -> int:
    c = ROOT / "db" / "eiv1" / "corpus.jsonl"
    return sum(1 for _ in open(c)) if c.exists() else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--games", type=int, default=40, help="1 ラウンドの collect ゲーム数")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--epsilon", type=float, default=0.15)
    ap.add_argument("--heroes", default=None, help="hero プール (comma-list か @file)。 未指定は --hero")
    ap.add_argument("--hero", default="cardrush_1454")
    ap.add_argument("--opps", default="cardrush_1385,tcgportal_calgara,tcgportal_bonney,cardrush_1399")
    ap.add_argument("--beam-width", type=int, default=8)
    ap.add_argument("--max-depth", type=int, default=6)
    ap.add_argument("--arena-every", type=int, default=8,
                    help="N ラウンドごとに ε=0 arena で強さを測る (0=しない)")
    ap.add_argument("--arena-pairs", type=int, default=100, help="arena の ペア数 (1 ペア=4 game)")
    ap.add_argument("--arena-refs", default="agnostic,snapshot:oldest")
    a = ap.parse_args()
    print(f"=== EIV1 loop: rounds={a.rounds} games/round={a.games} | 開始 corpus={_corpus_n()} ===",
          flush=True)
    for r in range(1, a.rounds + 1):
        print(f"\n----- round {r}/{a.rounds} -----", flush=True)
        # collect (append)
        hero_args = ["--heroes", a.heroes] if a.heroes else ["--hero", a.hero]
        subprocess.run([PY, str(ROOT / "scripts" / "eiv1_collect.py"),
                        *hero_args, "--opps", a.opps,
                        "--games", str(a.games), "--workers", str(a.workers),
                        "--epsilon", str(a.epsilon),
                        "--beam-width", str(a.beam_width), "--max-depth", str(a.max_depth)],
                       check=False)
        # train (全 corpus 再学習)
        subprocess.run([PY, str(ROOT / "scripts" / "eiv1_train.py")], check=False)
        # arena (ε=0 で 凍結基準と直接対戦 = 「強くなったか」の実測。 corpus の win率 は
        # ε ハンデ込みなので強さ指標にならない)
        if a.arena_every and r % a.arena_every == 0:
            subprocess.run([PY, str(ROOT / "scripts" / "eiv1_arena.py"),
                            "--pairs", str(a.arena_pairs), "--refs", a.arena_refs,
                            "--workers", str(a.workers),
                            "--beam-width", str(a.beam_width), "--max-depth", str(a.max_depth)],
                           check=False)
    n = _corpus_n()
    hist = []
    if MANIFEST.exists():
        try:
            hist = json.loads(MANIFEST.read_text(encoding="utf-8")).get("history", [])
        except Exception:
            pass
    print(f"\n=== EIV1 loop 完了: corpus={n} samples ===", flush=True)
    if hist:
        print("AUC 推移 (天井なしの証拠 = データ↑で単調に上がるか):", flush=True)
        for h in hist[-8:]:
            print(f"  iter{h['iter']:>3} n={h['n']:>7} AUC={h.get('auc')}", flush=True)
    arena = ROOT / "db" / "eiv1" / "arena.jsonl"
    if arena.exists():
        print("強さ推移 (ε=0 arena、 = 実際に強くなったか):", flush=True)
        for line in list(open(arena, encoding="utf-8"))[-6:]:
            try:
                d = json.loads(line)
            except Exception:
                continue
            print(f"  iter{d['iter']:>4} vs {d['ref']:<18} 勝率={d.get('win'):.3f}"
                  f" ±{d.get('se'):.3f} (N={d.get('n_games')})", flush=True)


if __name__ == "__main__":
    main()
