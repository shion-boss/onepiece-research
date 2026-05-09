# -*- coding: utf-8 -*-
"""
全 N デッキ × N デッキの勝率マトリックスを事前計算して
db/matchup_matrix.json に保存する。

API ( /api/meta/matrix ) はこのファイルを読むだけで O(1)。

実行:
    .venv/bin/python scripts/compute_matchup_matrix.py
    .venv/bin/python scripts/compute_matchup_matrix.py --n-games 50 --seed 42
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

from engine.deck import CardRepository, DeckList   # noqa: E402
from engine.harness import run_matchup             # noqa: E402

OUT = ROOT / "db" / "matchup_matrix.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-games", type=int, default=30, help="各セルの試合数")
    ap.add_argument("--seed", type=int, default=42, help="乱数 seed")
    ap.add_argument("--decks-glob", default="*.json", help="対象 deck ファイル glob")
    args = ap.parse_args()

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    deck_paths = sorted((ROOT / "decks").glob(args.decks_glob))
    decks: list[tuple[str, str, DeckList]] = []
    for p in deck_paths:
        try:
            d = DeckList.from_json(p, repo)
        except Exception as e:
            print(f"  [WARN] {p.stem}: {e}")
            continue
        decks.append((p.stem, d.name, d))
    print(f"対象 {len(decks)} デッキ × {len(decks)} = {len(decks) ** 2} セル")
    print(f"設定: n_games={args.n_games}, seed={args.seed}")
    print()

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
            rep = run_matchup(deck_a, deck_b, n_games=args.n_games, seed=args.seed)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
