#!/usr/bin/env python
"""**選択列挙 ON の Rust self-play** が実際に学習を回せるかを測る。

⭐ なぜ要るか: 差分ハーネスの MISMATCH=0 は 「黙って間違えない」 の保証であって、
   **bail が多ければ self-play が完走しない** = 学習データが取れない。
   「正しい」 と 「使える」 は別物なので、 完走率とスループットを直接測る。

  .venv/bin/python scripts/rust_choice_selfplay_probe.py --games 40
  .venv/bin/python scripts/rust_choice_selfplay_probe.py --games 40 --mode beam
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import optcg_engine as eng  # noqa: E402

import scripts.rust_parity_check as P  # noqa: E402


def run(games: int, mode: str, seed: int, choice_enum: bool = True) -> None:
    eng.load_overlay(str(ROOT / "db" / "card_effects.json"))
    P._load()
    # ⭐ 診断 ON。 方策は bail した手を **黙って捨てる** ので、 完走率だけ見ると
    #   「Rust が実行できない手を避けているだけ」 を見逃す (= 学習分布の偏り)。
    eng.reset_coverage_stats(True)
    slugs = [p.stem for p in sorted((ROOT / "decks").glob("cardrush_*.json"))
             if ".analysis." not in p.name and ".target_v" not in p.name]
    stat: Counter = Counter()
    bail_reasons: Counter = Counter()
    turns_sum = 0
    t0 = time.time()
    for gi in range(games):
        a = P.deck_value(slugs[gi % len(slugs)])
        b = P.deck_value(slugs[(gi + 1) % len(slugs)])
        rng_state = json.dumps(list(random.Random(seed + gi).getstate()[1]))
        try:
            r = json.loads(eng.self_play(
                a, b, rng_state, gi % 2, mode,
                None, 8, 12, 40, False, 80, choice_enum))
        except Exception as e:  # noqa: BLE001
            stat["bail(試合が中断)"] += 1
            bail_reasons[str(e)[:70]] += 1
            continue
        if r.get("game_over"):
            stat["完走(決着)"] += 1
        else:
            stat["完走(ターン上限)"] += 1
        turns_sum += int(r.get("turns") or 0)
    el = time.time() - t0
    done = stat["完走(決着)"] + stat["完走(ターン上限)"]
    print(f"=== Rust self-play ({games} game / mode={mode} / 選択列挙={'ON' if choice_enum else 'OFF'}) ===")
    for k, v in stat.most_common():
        print(f"  {k}: {v}")
    print(f"  完走率 = {done / games:.1%}   平均ターン = {turns_sum / max(1, done):.1f}")
    print(f"  {el:.1f}s ({1000 * el / games:.0f} ms/game)")
    cov = json.loads(eng.coverage_stats())
    acts = cov.get("actions") or {}
    tot_ok = sum(v.get("ok", 0) for v in acts.values())
    tot_bail = sum(v.get("bail", 0) for v in acts.values())
    if tot_ok + tot_bail:
        print(f"\n  候補 action の bail 率 = {tot_bail}/{tot_ok + tot_bail} "
              f"= {tot_bail / (tot_ok + tot_bail):.2%}  (= 方策が黙って避けた手)")
        rows = sorted(acts.items(), key=lambda kv: -kv[1].get("bail", 0))[:8]
        for k, v in rows:
            if v.get("bail"):
                print(f"    {k}: ok={v.get('ok',0)} bail={v.get('bail',0)}")
    for k, v in (cov.get("bail_reasons") or {}).items() if isinstance(cov.get("bail_reasons"), dict) else []:
        pass
    br = cov.get("bail_reasons")
    if br:
        print("\n  候補 bail の理由 top:")
        items = sorted(br.items(), key=lambda kv: -kv[1])[:10] if isinstance(br, dict) else list(br)[:10]
        for k, v in items:
            print(f"    {v:6d}  {str(k)[:88]}")
    if bail_reasons:
        print("\n  中断の理由 (= 移植の優先順位):")
        for k, v in bail_reasons.most_common(12):
            print(f"    {v:4d}  {k}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=40)
    ap.add_argument("--mode", default="greedy")
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--no-choice", action="store_true", help="選択列挙 OFF の基準線を測る")
    args = ap.parse_args()
    run(args.games, args.mode, args.seed, not args.no_choice)


if __name__ == "__main__":
    main()
