# -*- coding: utf-8 -*-
"""
Cross matchup matrix: 自分側 PlanningAI vs 相手側 GreedyAI (= 公正な Planning 検証)。

既存 db/matchup_matrix.json (= 両側 Greedy) と同じ (deck_a, deck_b) ペアごとに、
自分側 = PlanningAI、 相手側 = GreedyAI で対戦させ、 baseline からの delta を取る。

delta > 0: 「同じデッキを Planning に乗せ替えると Greedy 同士の時より強くなる」
delta < 0: 「Planning に乗せ替えると弱くなる」

実行例:
    .venv/bin/python scripts/compute_matchup_matrix_cross.py --n-games 5
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

from engine.ai import GreedyAI, PlanningAI  # noqa: E402
from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.harness import run_matchup  # noqa: E402

OUT = ROOT / "db" / "matchup_matrix_cross.json"
BASELINE = ROOT / "db" / "matchup_matrix.json"


def planning_factory(beam=4, depth=6):
    def _f(rng=None, deck_analysis=None):
        return PlanningAI(rng=rng, deck_analysis=deck_analysis, beam_width=beam, max_depth=depth)
    return _f


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-games", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--beam", type=int, default=4)
    ap.add_argument("--depth", type=int, default=6)
    ap.add_argument("--decks-glob", default="cardrush_*.json")
    args = ap.parse_args()

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    deck_paths = sorted((ROOT / "decks").glob(args.decks_glob))
    deck_paths += sorted((ROOT / "decks").glob("tcgportal_*.json"))
    deck_paths = [p for p in deck_paths if ".analysis" not in p.name]
    decks: list[tuple[str, str, DeckList]] = []
    for p in deck_paths:
        try:
            d = DeckList.from_json(p, repo)
        except Exception as e:
            print(f"  [WARN] {p.stem}: {e}", flush=True)
            continue
        decks.append((p.stem, d.name, d))
    print(f"対象 {len(decks)} デッキ × {len(decks)} = {len(decks) ** 2} セル", flush=True)
    print(f"自分側 = PlanningAI(beam={args.beam}, depth={args.depth}), 相手側 = GreedyAI", flush=True)
    print(f"設定: n_games={args.n_games}, seed={args.seed}", flush=True)
    print(flush=True)

    factory_plan = planning_factory(beam=args.beam, depth=args.depth)
    factory_greedy = GreedyAI

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
                ai_factory_1=factory_plan, ai_factory_2=factory_greedy,
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
        print(f"  {slug_a:<25} {name_a:<20} done {done}/{total}  elapsed {elapsed:.0f}s  ETA {eta:.0f}s", flush=True)
        cells.append({
            "deck_a": slug_a,
            "deck_a_name": name_a,
            "row": row,
        })

    out = {
        "computed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_games": args.n_games,
        "seed": args.seed,
        "ai_self": "PlanningAI",
        "ai_opp": "GreedyAI",
        "beam": args.beam,
        "depth": args.depth,
        "decks": [{"slug": s, "name": n} for s, n, _ in decks],
        "matrix": cells,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    elapsed = time.time() - t0
    print(flush=True)
    print(f"完了: {OUT}  ({elapsed:.1f}s, {OUT.stat().st_size // 1024} KB)", flush=True)

    # baseline (Greedy vs Greedy) と比較: 各セルごと delta = cross - baseline
    if BASELINE.exists():
        print(flush=True)
        print("=== Greedy vs Greedy baseline との比較 ===", flush=True)
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        # baseline matrix を (deck_a, deck_b) -> winrate に展開
        b_map: dict[tuple[str, str], float] = {}
        for cell in baseline.get("matrix", []):
            for r in cell["row"]:
                if r.get("winrate") is not None:
                    b_map[(cell["deck_a"], r["deck_b"])] = r["winrate"]

        # 全セル delta + 行平均 delta
        name_map = {d["slug"]: d["name"] for d in out["decks"]}
        deck_deltas: dict[str, list[float]] = {s: [] for s in name_map}
        all_deltas = []
        per_cell_deltas: list[tuple[str, str, float, float, float]] = []
        for cell in out["matrix"]:
            a = cell["deck_a"]
            for r in cell["row"]:
                b = r["deck_b"]
                if r.get("winrate") is None:
                    continue
                base = b_map.get((a, b))
                if base is None:
                    continue
                cross = r["winrate"]
                delta = cross - base
                deck_deltas[a].append(delta)
                all_deltas.append(delta)
                per_cell_deltas.append((a, b, base, cross, delta))

        # 行平均 delta (= デッキを Planning 化した時の平均変動)
        print(f"{'deck':<22} {'baseline':>10} {'Planning':>10} {'Δ avg':>9}", flush=True)
        print("-" * 56, flush=True)
        for slug, deltas in deck_deltas.items():
            if not deltas:
                continue
            base_avg = sum(b_map.get((slug, b), 0) for b in name_map if (slug, b) in b_map) / max(1, sum(1 for b in name_map if (slug, b) in b_map))
            cross_avg = sum(r["winrate"] for cell in out["matrix"] if cell["deck_a"] == slug for r in cell["row"] if r.get("winrate") is not None) / max(1, sum(1 for cell in out["matrix"] if cell["deck_a"] == slug for r in cell["row"] if r.get("winrate") is not None))
            avg_delta = sum(deltas) / len(deltas) * 100
            mark = ""
            if avg_delta > 5:
                mark = "  ✓"
            elif avg_delta < -5:
                mark = "  ✗"
            print(f"{name_map[slug]:<20} {base_avg*100:>9.1f}% {cross_avg*100:>9.1f}% {avg_delta:>+7.1f}pt{mark}", flush=True)

        if all_deltas:
            print(flush=True)
            mean = sum(all_deltas) / len(all_deltas) * 100
            wins = sum(1 for d in all_deltas if d > 0)
            losses = sum(1 for d in all_deltas if d < 0)
            print(f"全 {len(all_deltas)} セル平均 Δ: {mean:+.1f}pt (+{wins} / -{losses})", flush=True)

        # 大きい変動セル top 5
        print(flush=True)
        print("=== 大きい変動セル top 5 (= Planning 化の効果が顕著なペア) ===", flush=True)
        per_cell_deltas.sort(key=lambda x: -abs(x[4]))
        for a, b, base, cross, delta in per_cell_deltas[:5]:
            arrow = "↑" if delta > 0 else "↓"
            print(f"  {name_map[a]:<14} vs {name_map[b]:<14} {base*100:>5.0f}% → {cross*100:>5.0f}% ({delta*100:+.0f}pt) {arrow}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
