# -*- coding: utf-8 -*-
"""絶対強度測定: NN-on vs baseline + NN-off vs baseline を全 16 デッキで比較。

mirror 対戦 (= run_nn_direct_matchup.py) は「相性」 のみで「絶対強度」 を測れない。
本 script は共通 baseline AI (= GreedyAI / LookaheadAI) との勝率を比較して、
NN を入れることで AI が「真に強くなったか」 を判定する。

実行例:
    .venv/bin/python scripts/run_absolute_strength.py \\
        --output db/absolute_strength_v5.json \\
        --n-games 50 --baseline greedy

per-deck checkpoint + resume 対応。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.harness import run_matchup  # noqa: E402
from engine.ai import PlanningAI, GreedyAI, LookaheadAI, RandomAI  # noqa: E402
from engine.nn_eval import nn_disabled, get_model  # noqa: E402


class PlanningAI_NoNN(PlanningAI):
    name = "PlanningNoNN"
    def choose_action(self, state):
        with nn_disabled():
            return super().choose_action(state)
    def choose_defense(self, state, attacker, target, is_leader_attack, defender):
        with nn_disabled():
            return super().choose_defense(state, attacker, target, is_leader_attack, defender)


def _baseline_factory(name: str):
    if name == "greedy":
        return GreedyAI
    if name == "lookahead":
        return LookaheadAI
    if name == "random":
        return RandomAI
    raise ValueError(f"unknown baseline: {name}")


def _save(out_path: Path, doc: dict) -> None:
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out_path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--n-games", type=int, default=50)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--baseline", default="greedy", choices=["greedy", "lookahead", "random"])
    ap.add_argument("--beam", type=int, default=2)
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if os.environ.get("ONEPIECE_NN_DISABLE"):
        print("[ERROR] ONEPIECE_NN_DISABLE=1 — NN-on side が無効化される", flush=True)
        return 1
    m = get_model()
    if m is None:
        print("[ERROR] NN model 不在", flush=True)
        return 1
    print(f"NN model: {type(m).__name__}", flush=True)
    print(f"baseline: {args.baseline}", flush=True)

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    deck_paths = sorted((ROOT / "decks").glob("cardrush_*.json"))
    deck_paths += sorted((ROOT / "decks").glob("tcgportal_*.json"))
    deck_paths = [p for p in deck_paths if ".analysis" not in p.name]

    decks: list[tuple[str, str, DeckList]] = []
    for p in deck_paths:
        try:
            d = DeckList.from_json(p, repo)
            decks.append((p.stem, d.name, d))
        except Exception as e:
            print(f"  [WARN] {p.stem}: {e}", flush=True)

    print(f"decks={len(decks)}, n_games per deck per side={args.n_games}", flush=True)

    nn_factory = lambda *a, **kw: PlanningAI(
        *a, beam_width=args.beam, max_depth=args.depth, adaptive=False, **kw
    )
    nonn_factory = lambda *a, **kw: PlanningAI_NoNN(
        *a, beam_width=args.beam, max_depth=args.depth, adaptive=False, **kw
    )
    baseline_factory = _baseline_factory(args.baseline)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict = {}
    if out_path.exists() and not args.force:
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    done_decks: set[str] = {r["deck"] for r in existing.get("results", [])}
    results: list[dict] = list(existing.get("results", []))

    t0 = time.time()
    for slug, name, deck in decks:
        if not args.force and slug in done_decks:
            continue

        t_deck = time.time()
        # NN-on vs baseline
        rep_nn = run_matchup(
            deck, deck, n_games=args.n_games, seed=args.seed,
            ai_factory_1=nn_factory, ai_factory_2=baseline_factory,
        )
        # NoNN vs baseline (= 同条件で対比)
        rep_nonn = run_matchup(
            deck, deck, n_games=args.n_games, seed=args.seed,
            ai_factory_1=nonn_factory, ai_factory_2=baseline_factory,
        )

        result = {
            "deck": slug,
            "deck_name": name,
            "nn_vs_baseline": {
                "wins": rep_nn.deck1_wins, "losses": rep_nn.deck2_wins, "draws": rep_nn.draws,
                "winrate": round(rep_nn.deck1_winrate, 4), "avg_turns": round(rep_nn.avg_turns, 2),
            },
            "nonn_vs_baseline": {
                "wins": rep_nonn.deck1_wins, "losses": rep_nonn.deck2_wins, "draws": rep_nonn.draws,
                "winrate": round(rep_nonn.deck1_winrate, 4), "avg_turns": round(rep_nonn.avg_turns, 2),
            },
            "n_games": args.n_games,
            "baseline": args.baseline,
        }
        # delta は NN-on の利得 (+ なら NN 入れた方が強い)
        result["delta"] = round(rep_nn.deck1_winrate - rep_nonn.deck1_winrate, 4)
        results.append(result)
        done_decks.add(slug)

        deck_elapsed = time.time() - t_deck
        elapsed = time.time() - t0
        delta_marker = "✓+" if result["delta"] > 0.05 else ("✗-" if result["delta"] < -0.05 else "=")
        print(
            f"  [{len(done_decks)}/{len(decks)}] {slug:<28} | "
            f"NN={rep_nn.deck1_winrate*100:>4.0f}% NoNN={rep_nonn.deck1_winrate*100:>4.0f}% "
            f"delta={result['delta']*100:>+5.1f}pt {delta_marker} | "
            f"{deck_elapsed:.0f}s | elapsed {elapsed:.0f}s",
            flush=True,
        )

        doc = {
            "computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "n_games_per_deck_per_side": args.n_games,
            "seed": args.seed,
            "baseline": args.baseline,
            "partial": len(done_decks) < len(decks),
            "results": results,
        }
        _save(out_path, doc)

    if results:
        nn_wins = sum(1 for r in results if r["delta"] > 0.05)
        nonn_wins = sum(1 for r in results if r["delta"] < -0.05)
        ties = len(results) - nn_wins - nonn_wins
        nn_avg = sum(r["nn_vs_baseline"]["winrate"] for r in results) / len(results)
        nonn_avg = sum(r["nonn_vs_baseline"]["winrate"] for r in results) / len(results)
        print(flush=True)
        print(f"=== 結果 (vs {args.baseline}AI) ===", flush=True)
        print(f"  NN-on  平均勝率: {nn_avg*100:.1f}% across {len(results)} decks", flush=True)
        print(f"  NoNN   平均勝率: {nonn_avg*100:.1f}% across {len(results)} decks", flush=True)
        print(f"  delta (NN - NoNN): {(nn_avg-nonn_avg)*100:+.2f}pt", flush=True)
        print(f"  NN 勝ち {nn_wins} デッキ / NoNN 勝ち {nonn_wins} デッキ / 同等 {ties}", flush=True)
        print(f"  → NN を入れる方が強い: {'YES' if nn_avg > nonn_avg + 0.02 else 'NO' if nn_avg < nonn_avg - 0.02 else 'ほぼ同等'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
