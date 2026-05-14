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
from engine.matrix_schema import (  # noqa: E402
    MATRIX_SCHEMA_VERSION,
    collect_deck_hashes,
    compute_recipe_hash_from_file,
    find_stale_cells,
    is_cell_stale,
    make_cell_v2,
    now_utc_iso,
)

OUT = ROOT / "db" / "matchup_matrix.json"
DEFAULT_AI_VERSION = "PlanningAI_R71_phase7"


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
    ap.add_argument("--incremental", action="store_true",
                    help="既存 matrix を読み、 stale cell のみ再計算 (Phase 7F-4)")
    ap.add_argument("--ai-version", default=DEFAULT_AI_VERSION,
                    help="cell に記録する AI version 識別子")
    args = ap.parse_args()

    if args.row_diff:
        before_path = Path(args.row_diff[0])
        after_path = Path(args.row_diff[1])
        return _compare_matrices(before_path, after_path)

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    deck_paths = sorted((ROOT / "decks").glob(args.decks_glob))
    if args.decks_glob in ("*.json", "cardrush_*.json"):
        # メタデッキ対象 (cardrush + tcgportal、 analysis.json と explore_/research_ は除外)
        deck_paths = sorted((ROOT / "decks").glob("cardrush_*.json"))
        deck_paths += sorted((ROOT / "decks").glob("tcgportal_*.json"))
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
    print(f"設定: n_games={args.n_games}, seed={args.seed}")
    print()

    # Phase 7F-4: 各 deck の recipe hash を計算 (= cell に記録)
    deck_hashes: dict[str, str] = {}
    for p in deck_paths:
        h = compute_recipe_hash_from_file(p)
        if h:
            deck_hashes[p.stem] = h
    ai_version = args.ai_version

    # incremental モード: 既存 matrix を読み込み、 stale cell のみ再計算
    existing_matrix: dict = {}
    if args.incremental and OUT.exists():
        try:
            existing_matrix = json.loads(OUT.read_text(encoding="utf-8"))
            stale_cells = find_stale_cells(existing_matrix, deck_hashes, ai_version)
            print(f"  incremental モード: {len(stale_cells)} stale cells を再計算")
            print()
        except Exception:
            print("  既存 matrix が読めない、 full re-run に fallback")
            existing_matrix = {}

    # 既存 row index map (= incremental の reuse 用)
    existing_row_by_slug: dict[str, dict] = {
        r.get("deck_a"): r for r in existing_matrix.get("matrix", [])
    } if existing_matrix else {}

    t0 = time.time()
    cells = []
    total = len(decks) ** 2
    done = 0
    reused = 0
    recomputed = 0
    for slug_a, name_a, deck_a in decks:
        hash_a = deck_hashes.get(slug_a, "")
        existing_row = existing_row_by_slug.get(slug_a, {}).get("row", [])
        existing_cell_by_b: dict[str, dict] = {
            c.get("deck_b"): c for c in existing_row
        }

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
                    "deck_a_recipe_hash": hash_a,
                    "deck_b_recipe_hash": hash_a,
                    "ai_version": ai_version,
                    "computed_at": now_utc_iso(),
                    "stale": False,
                })
                continue

            hash_b = deck_hashes.get(slug_b, "")
            # incremental: 既存 cell が stale じゃなければ reuse
            if args.incremental:
                existing_cell = existing_cell_by_b.get(slug_b)
                if existing_cell and not is_cell_stale(existing_cell, hash_a, hash_b, ai_version):
                    # reuse: hash + ai_version を最新化して保持
                    reused_cell = dict(existing_cell)
                    reused_cell["deck_a_recipe_hash"] = hash_a
                    reused_cell["deck_b_recipe_hash"] = hash_b
                    reused_cell["ai_version"] = ai_version
                    reused_cell["stale"] = False
                    row.append(reused_cell)
                    reused += 1
                    continue

            rep = run_matchup(deck_a, deck_b, n_games=args.n_games, seed=args.seed)
            cell = make_cell_v2(
                deck_b_slug=slug_b,
                winrate=round(rep.deck1_winrate, 4),
                wins=rep.deck1_wins,
                losses=rep.deck2_wins,
                draws=rep.draws,
                avg_turns=round(rep.avg_turns, 2),
                deck_a_hash=hash_a,
                deck_b_hash=hash_b,
                ai_version=ai_version,
                stale=False,
            )
            row.append(cell)
            recomputed += 1
        elapsed = time.time() - t0
        rate = done / elapsed if elapsed > 0 else 0
        eta = (total - done) / rate if rate > 0 else 0
        print(f"  {slug_a:<25} {name_a:<20} done {done}/{total}  elapsed {elapsed:.0f}s  ETA {eta:.0f}s", flush=True)
        cells.append({
            "deck_a": slug_a,
            "deck_a_name": name_a,
            "row": row,
        })
        # 行ごとに incremental save (= 長時間バッチで途中クラッシュ時の損失を防止)
        partial = {
            "schema_version": MATRIX_SCHEMA_VERSION,
            "computed_at": now_utc_iso(),
            "n_games": args.n_games,
            "seed": args.seed,
            "ai_version": ai_version,
            "partial": done < total,
            "decks": [{"slug": s, "name": n} for s, n, _ in decks],
            "matrix": cells,
        }
        OUT.write_text(json.dumps(partial, ensure_ascii=False, indent=2), encoding="utf-8")

    out = {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "computed_at": now_utc_iso(),
        "n_games": args.n_games,
        "seed": args.seed,
        "ai_version": ai_version,
        "decks": [
            {"slug": s, "name": n}
            for s, n, _ in decks
        ],
        "matrix": cells,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.incremental:
        print(f"  incremental: {reused} cells reused, {recomputed} cells recomputed")
    elapsed = time.time() - t0
    print()
    print(f"完了: {OUT}  ({elapsed:.1f}s, {OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
