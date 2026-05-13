# -*- coding: utf-8 -*-
"""
PlanningAI vs PlanningAI の matchup matrix を計算 (R70+ / Step 4)。

既存 db/matchup_matrix.json (= Greedy vs Greedy) を保持しつつ、 新規
db/matchup_matrix_planning.json に書き出す。 計算後、 既存 matrix との
デッキ別勝率差分を表示。

実行例:
    .venv/bin/python scripts/compute_matchup_matrix_planning.py --n-games 10
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.ai import PlanningAI  # noqa: E402
from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.harness import run_matchup  # noqa: E402

OUT = ROOT / "db" / "matchup_matrix_planning.json"
BASELINE = ROOT / "db" / "matchup_matrix.json"


def planning_factory(beam=4, depth=8):
    def _f(rng=None, deck_analysis=None):
        return PlanningAI(rng=rng, deck_analysis=deck_analysis, beam_width=beam, max_depth=depth)
    return _f


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-games", type=int, default=10, help="各セルの試合数")
    ap.add_argument("--seed", type=int, default=42, help="乱数 seed")
    ap.add_argument("--beam", type=int, default=4, help="PlanningAI beam_width")
    ap.add_argument("--depth", type=int, default=8, help="PlanningAI max_depth")
    ap.add_argument("--decks-glob", default="cardrush_*.json", help="対象 deck ファイル glob (analysis 除外)")
    args = ap.parse_args()

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    deck_paths = sorted((ROOT / "decks").glob(args.decks_glob))
    deck_paths += sorted((ROOT / "decks").glob("tcgportal_*.json"))
    # .analysis.json を除外
    deck_paths = [p for p in deck_paths if ".analysis" not in p.name]
    decks: list[tuple[str, str, DeckList]] = []
    for p in deck_paths:
        try:
            d = DeckList.from_json(p, repo)
        except Exception as e:
            print(f"  [WARN] {p.stem}: {e}")
            continue
        decks.append((p.stem, d.name, d))
    print(f"対象 {len(decks)} デッキ × {len(decks)} = {len(decks) ** 2} セル")
    print(f"設定: n_games={args.n_games}, seed={args.seed}, beam={args.beam}, depth={args.depth}")
    print()

    factory = planning_factory(beam=args.beam, depth=args.depth)
    t0 = time.time()
    cells = []
    total = len(decks) ** 2
    done = 0
    for slug_a, name_a, deck_a in decks:
        row = []
        for slug_b, name_b, deck_b in decks:
            done += 1
            if slug_a == slug_b:
                row.append({
                    "deck_b": slug_b,
                    "winrate": None,
                    "wins": 0,
                    "losses": 0,
                    "draws": 0,
                    "avg_turns": 0.0,
                })
                continue
            rep = run_matchup(
                deck_a, deck_b, n_games=args.n_games, seed=args.seed,
                ai_factory_1=factory, ai_factory_2=factory,
            )
            row.append({
                "deck_b": slug_b,
                "winrate": round(rep.deck1_winrate, 4),
                "wins": rep.deck1_wins,
                "losses": rep.deck2_wins,
                "draws": rep.draws,
                "avg_turns": round(rep.avg_turns, 2),
            })
        elapsed = time.time() - t0
        rate = done / elapsed if elapsed > 0 else 0
        eta = (total - done) / rate if rate > 0 else 0
        print(f"  {slug_a:<25} {name_a:<20} done {done}/{total}  elapsed {elapsed:.0f}s  ETA {eta:.0f}s")
        cells.append({
            "deck_a": slug_a,
            "deck_a_name": name_a,
            "row": row,
        })

    out = {
        "computed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_games": args.n_games,
        "seed": args.seed,
        "ai": "PlanningAI",
        "beam": args.beam,
        "depth": args.depth,
        "decks": [
            {"slug": s, "name": n}
            for s, n, _ in decks
        ],
        "matrix": cells,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    elapsed = time.time() - t0
    print()
    print(f"完了: {OUT}  ({elapsed:.1f}s, {OUT.stat().st_size // 1024} KB)")

    # baseline (Greedy) との比較表示
    if BASELINE.exists():
        print()
        print("=== Greedy baseline (db/matchup_matrix.json) との勝率比較 ===")
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))

        def deck_avg(matrix_doc: dict) -> dict[str, float]:
            o: dict[str, float] = {}
            for cell in matrix_doc.get("matrix", []):
                wr_list = [r["winrate"] for r in cell["row"] if r.get("winrate") is not None]
                if wr_list:
                    o[cell["deck_a"]] = sum(wr_list) / len(wr_list)
            return o

        b_wr = deck_avg(baseline)
        a_wr = deck_avg(out)
        slugs = sorted(set(b_wr) | set(a_wr))
        name_map = {d["slug"]: d["name"] for d in out["decks"]}
        print(f"{'deck':<24} {'Greedy':>8} {'Planning':>10} {'Δ':>8}")
        print("-" * 56)
        for s in slugs:
            b = b_wr.get(s)
            a = a_wr.get(s)
            name = name_map.get(s, s)
            if b is None or a is None:
                continue
            print(f"{name:<22} {b:>7.1%} {a:>9.1%} {(a - b)*100:>+7.1f}pt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
