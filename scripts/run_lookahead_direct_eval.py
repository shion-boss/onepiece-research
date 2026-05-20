# -*- coding: utf-8 -*-
"""2026-05-18: 1-turn NN AI vs 3-turn NN AI の 直接対決 mirror eval。

各 AI に **異なる NN を bind** して 同じ デッキで mirror 対戦。
AI instance bind の WeightNN (= _WeightNNBindMixin) を 使用、 1 プロセス内で
2 つの NN を 同時 active 化可能。

実行例:
    .venv/bin/python scripts/run_lookahead_direct_eval.py \\
        --one-nn db/weight_nn_oneturn.pt \\
        --three-nn db/weight_nn_threeturn.pt \\
        --output db/ai_search/oneturn_vs_threeturn_n10.json \\
        --n-games 10

出力: 各デッキで 1-turn AI が何勝、 3-turn AI が何勝。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.harness import run_matchup  # noqa: E402
from engine.ai_experimental import WeightNNPlanningAI, WeightNNThreeTurnAI  # noqa: E402


def _save(out_path: Path, doc: dict) -> None:
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out_path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--one-nn", required=True, help="1-turn AI 用 NN path (= db/weight_nn_oneturn.pt)")
    ap.add_argument("--three-nn", required=True, help="3-turn AI 用 NN path (= db/weight_nn_threeturn.pt)")
    ap.add_argument("--output", required=True)
    ap.add_argument("--n-games", type=int, default=10)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    one_path = ROOT / args.one_nn
    three_path = ROOT / args.three_nn
    assert one_path.exists(), f"1-turn NN 不在: {one_path}"
    assert three_path.exists(), f"3-turn NN 不在: {three_path}"

    print(f"=== 直接対決 mirror eval: 1-turn NN vs 3-turn NN ===", flush=True)
    print(f"  1-turn NN: {one_path}", flush=True)
    print(f"  3-turn NN: {three_path}", flush=True)
    print(f"  n_games per deck: {args.n_games}", flush=True)

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    deck_paths = sorted((ROOT / "decks").glob("cardrush_*.json"))
    deck_paths += sorted((ROOT / "decks").glob("tcgportal_*.json"))
    deck_paths = [p for p in deck_paths if ".analysis" not in p.name]

    decks = []
    for p in deck_paths:
        try:
            d = DeckList.from_json(p, repo)
            decks.append((p.stem, d.name, d))
        except Exception as e:
            print(f"  [WARN] {p.stem}: {e}", flush=True)

    print(f"  decks: {len(decks)}", flush=True)

    # 1-turn AI factory (= bind 1-turn NN)
    def one_factory(*a, **kw):
        kw.setdefault("adaptive", False)
        kw.setdefault("beam_width", 2)
        kw.setdefault("max_depth", 3)
        return WeightNNPlanningAI(*a, nn_path=str(one_path), **kw)

    # 3-turn AI factory (= bind 3-turn NN)
    def three_factory(*a, **kw):
        kw.setdefault("adaptive", False)
        kw.setdefault("beam_width", 2)
        kw.setdefault("max_depth", 12)
        kw["max_turns"] = 3
        return WeightNNThreeTurnAI(*a, nn_path=str(three_path), **kw)

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
        # P0 = 1-turn AI, P1 = 3-turn AI
        rep = run_matchup(
            deck, deck, n_games=args.n_games, seed=args.seed,
            ai_factory_1=one_factory, ai_factory_2=three_factory,
        )
        result = {
            "deck": slug,
            "deck_name": name,
            "oneturn_wins": rep.deck1_wins,
            "threeturn_wins": rep.deck2_wins,
            "draws": rep.draws,
            "elapsed": time.time() - t_deck,
        }
        results.append(result)

        # 即時 save (= 中断耐性)
        _save(out_path, {
            "comparison": "1-turn NN vs 3-turn NN",
            "one_nn": str(one_path),
            "three_nn": str(three_path),
            "n_games": args.n_games,
            "results": results,
        })
        total = result["oneturn_wins"] + result["threeturn_wins"] + result["draws"]
        one_pct = 100 * result["oneturn_wins"] / total if total else 0
        print(
            f"  [{len(results)}/{len(decks)}] {slug:30s} "
            f"1-turn={result['oneturn_wins']:2d} 3-turn={result['threeturn_wins']:2d} draw={result['draws']:2d} "
            f"({one_pct:.0f}% 1-turn) {result['elapsed']:.0f}s",
            flush=True,
        )

    elapsed = time.time() - t0
    print(f"\n=== DONE 直接対決. {elapsed:.0f}s ===", flush=True)

    # summary
    total_one = sum(r["oneturn_wins"] for r in results)
    total_three = sum(r["threeturn_wins"] for r in results)
    total_draw = sum(r["draws"] for r in results)
    total = total_one + total_three + total_draw
    if total > 0:
        print(f"  1-turn AI: {total_one} wins ({100*total_one/total:.1f}%)", flush=True)
        print(f"  3-turn AI: {total_three} wins ({100*total_three/total:.1f}%)", flush=True)
        print(f"  draws:     {total_draw} ({100*total_draw/total:.1f}%)", flush=True)
        if total_three > total_one:
            print(f"  → 3-turn AI が +{100*(total_three-total_one)/total:.1f}pt 強い", flush=True)
        elif total_one > total_three:
            print(f"  → 1-turn AI が +{100*(total_one-total_three)/total:.1f}pt 強い", flush=True)
        else:
            print(f"  → 引き分け", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
