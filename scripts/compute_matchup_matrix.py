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


def _compare_matrices(before_path: Path, after_path: Path) -> int:
    """2 つの matchup_matrix.json を比較して、 デッキ別の勝率変化を表示。

    10%pt 以上の退行が見つかったら警告終了 (exit 2)。
    """
    if not before_path.exists():
        print(f"ERROR: {before_path} not found")
        return 1
    if not after_path.exists():
        print(f"ERROR: {after_path} not found")
        return 1
    before = json.loads(before_path.read_text(encoding="utf-8"))
    after = json.loads(after_path.read_text(encoding="utf-8"))

    def deck_avg_winrate(matrix_doc: dict) -> dict[str, float]:
        out: dict[str, float] = {}
        for cell in matrix_doc.get("matrix", []):
            slug_a = cell["deck_a"]
            wr_list = [
                r["winrate"]
                for r in cell["row"]
                if r.get("winrate") is not None
            ]
            if wr_list:
                out[slug_a] = sum(wr_list) / len(wr_list)
        return out

    b_wr = deck_avg_winrate(before)
    a_wr = deck_avg_winrate(after)
    all_slugs = sorted(set(b_wr) | set(a_wr))
    print(f"{'deck':<25}  {'before':>8}  {'after':>8}  {'delta':>8}")
    print("-" * 60)
    regression_found = False
    for slug in all_slugs:
        b = b_wr.get(slug)
        a = a_wr.get(slug)
        if b is None or a is None:
            print(f"{slug:<25}  {'N/A':>8}  {'N/A':>8}")
            continue
        delta = a - b
        flag = ""
        if delta <= -0.10:
            flag = "  ⚠ regression"
            regression_found = True
        elif delta >= 0.10:
            flag = "  ✓ improved"
        print(f"{slug:<25}  {b:>7.2%}  {a:>7.2%}  {delta:>+7.2%}{flag}")
    if regression_found:
        print("\n10%pt 以上の退行を検出。 結果を採用する場合は人間レビュー必須。")
        return 2
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-games", type=int, default=30, help="各セルの試合数")
    ap.add_argument("--seed", type=int, default=42, help="乱数 seed")
    ap.add_argument("--decks-glob", default="*.json", help="対象 deck ファイル glob")
    ap.add_argument("--row-diff", nargs=2, metavar=("BEFORE", "AFTER"),
                    help="2 つの matrix json を比較してデッキ別勝率差分を表示")
    args = ap.parse_args()

    if args.row_diff:
        before_path = Path(args.row_diff[0])
        after_path = Path(args.row_diff[1])
        return _compare_matrices(before_path, after_path)

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
