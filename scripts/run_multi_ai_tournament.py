# -*- coding: utf-8 -*-
"""複数 AI を mirror 対戦で全 vs 全 tournament、 最強 AI を発見。

2026-05-18: 朝の自走で 多数の AI variant が完成、 統合比較で「最強」 を確定。

候補:
  baseline       NoNN PlanningAI (= 線形 eval) ← 基準
  adaptive       per-deck NN preference (= 朝の確定 best、 +2pt vs baseline)
  weight_nn      WeightNNPlanningAI (= Plan F supervised)
  weight_nn_2t   WeightNNTwoTurnAI (= 2 ターン + 重み NN)
  alphazero      AlphaZeroValueAI (= 2 ターン + Plan D AZ value、 学習後 only)
  mega           MegaPlanningAI (= 全 NN 統合)
  mcts_az        AlphaZeroMCTSAI (= MCTS + Plan D AZ value、 学習後 only)

実行:
  .venv/bin/python scripts/run_multi_ai_tournament.py \\
    --candidates baseline,adaptive,weight_nn_2t,mega \\
    --n-games 10 --output db/multi_ai_tournament.json
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.harness import run_matchup  # noqa: E402
from engine.ai import DeepPlanningAI  # noqa: E402
from engine.ai_experimental import _NoNNPlanningBase  # noqa: E402


def _ai_factory(name: str):
    """name → AI factory 関数。"""
    if name == "baseline":
        return lambda *a, **kw: _NoNNPlanningBase(*a, beam_width=2, max_depth=3, adaptive=False, **kw)
    if name == "adaptive":
        # DeepPlanningAI 既存実装 (= adaptive 機構 自動)
        return lambda *a, **kw: DeepPlanningAI(*a, beam_width=2, max_depth=3, adaptive=False, **kw)
    # ai_experimental から動的 import
    mod = importlib.import_module("engine.ai_experimental")
    cls_name = {
        "weight_nn": "WeightNNPlanningAI",
        "weight_nn_2t": "WeightNNTwoTurnAI",
        "alphazero": "AlphaZeroValueAI",
        "mega": "MegaPlanningAI",
        "mcts_az": "AlphaZeroMCTSAI",
        "twoturn": "TwoTurnPlanningAI",
        "lethal": "LethalRusherAI",
    }.get(name)
    if not cls_name:
        raise ValueError(f"unknown AI name: {name}")
    cls = getattr(mod, cls_name)
    return lambda *a, **kw: cls(*a, **kw)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", required=True,
                    help="カンマ区切り AI 名 (= baseline,adaptive,weight_nn_2t 等)")
    ap.add_argument("--n-games", type=int, default=10)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--output", default="db/multi_ai_tournament.json")
    args = ap.parse_args()

    candidates = [s.strip() for s in args.candidates.split(",") if s.strip()]
    print(f"=== Multi-AI Tournament ===")
    print(f"  candidates: {candidates}")
    print(f"  n_games per deck per pair: {args.n_games}")

    factories = {name: _ai_factory(name) for name in candidates}

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    deck_paths = sorted((ROOT / "decks").glob("cardrush_*.json"))
    deck_paths += sorted((ROOT / "decks").glob("tcgportal_*.json"))
    deck_paths = [p for p in deck_paths if ".analysis" not in p.name]
    decks = []
    for p in deck_paths:
        try:
            decks.append((p.stem, DeckList.from_json(p, repo)))
        except Exception:
            pass
    print(f"  decks: {len(decks)}")

    # 全 ペア 対戦 (= 自分 vs 自分 除く)
    results = {}  # (a, b) → list of {deck, a_winrate}
    t0 = time.time()
    for i, name_a in enumerate(candidates):
        for j, name_b in enumerate(candidates):
            if i >= j:
                continue  # i < j のみ計算、 j < i は 1 - winrate で導出
            pair_key = f"{name_a}_vs_{name_b}"
            print(f"\n--- {pair_key} ---")
            pair_results = []
            for slug, deck in decks:
                t_deck = time.time()
                rep = run_matchup(
                    deck, deck,
                    n_games=args.n_games, seed=args.seed,
                    ai_factory_1=factories[name_a],
                    ai_factory_2=factories[name_b],
                )
                wr = rep.deck1_winrate
                elapsed = time.time() - t_deck
                pair_results.append({
                    "deck": slug,
                    "a_wins": rep.deck1_wins,
                    "b_wins": rep.deck2_wins,
                    "draws": rep.draws,
                    "a_winrate": round(wr, 4),
                })
                marker = "✓" if wr > 0.55 else ("✗" if wr < 0.45 else "=")
                print(f"  {slug:<28} a_wr={wr*100:>4.0f}% {marker} ({elapsed:.0f}s)")
            avg_wr = sum(r["a_winrate"] for r in pair_results) / len(pair_results)
            print(f"  avg a_wr: {avg_wr*100:.1f}%")
            results[pair_key] = {
                "ai_a": name_a, "ai_b": name_b,
                "n_games": args.n_games,
                "decks": pair_results,
                "avg_a_winrate": round(avg_wr, 4),
            }

    # 各 AI の 全体平均勝率 (= vs 他 全 AI、 自分以外)
    ai_avg = {name: [] for name in candidates}
    for key, r in results.items():
        a = r["ai_a"]; b = r["ai_b"]; wr = r["avg_a_winrate"]
        ai_avg[a].append(wr)
        ai_avg[b].append(1 - wr)  # 逆方向

    print(f"\n=== Final Ranking ===")
    print(f"  {'AI':<20}{'avg wr':>10}{'n pairs':>10}")
    ranking = []
    for name, wrs in ai_avg.items():
        if wrs:
            avg = sum(wrs) / len(wrs)
            ranking.append((name, avg))
            print(f"  {name:<20}{avg*100:>9.1f}%{len(wrs):>10}")
    ranking.sort(key=lambda x: -x[1])

    doc = {
        "computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_games": args.n_games,
        "seed": args.seed,
        "candidates": candidates,
        "pair_results": results,
        "ranking": [{"ai": n, "avg_winrate": round(w, 4)} for n, w in ranking],
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== DONE in {time.time()-t0:.0f}s. saved: {args.output} ===")
    print(f"  最強 AI: {ranking[0][0]} ({ranking[0][1]*100:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
