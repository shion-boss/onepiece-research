# -*- coding: utf-8 -*-
"""Resumable + configurable matrix runner (= compute_matchup_matrix.py の派生)。

compute_matchup_matrix.py からの違い:
- AI factory を CLI で切り替え (= NN on/off × beam/depth/adaptive)
- output path を任意指定可能 (= 並列実行で別 file に出せる)
- **per-cell** checkpoint (= 既存 script は per-row、 こちらは cell 単位で resume 可能)
- 既存 output を読んで未完了 cell のみ実行 (= incremental デフォルト ON)
- NN は ONEPIECE_NN_DISABLE 環境変数で制御 (= subprocess 起動側で設定)

実行例 (= 2 軸並列):
    # NN無効 + 軽量 PlanningAI (= 新 baseline)
    ONEPIECE_NN_DISABLE=1 .venv/bin/python scripts/run_matrix_resumable.py \\
        --output db/matchup_matrix.step7_nn_disabled.json \\
        --ai-version step7_nn_disabled_light \\
        --beam 2 --depth 3 --no-adaptive \\
        --n-games 20 --seed 42

    # NN有効 + 軽量 PlanningAI (= NN 効果測定)
    .venv/bin/python scripts/run_matrix_resumable.py \\
        --output db/matchup_matrix.step7_nn_enabled.json \\
        --ai-version step7_nn_enabled_light \\
        --beam 2 --depth 3 --no-adaptive \\
        --n-games 20 --seed 42
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
from engine.ai import PlanningAI, GreedyAI  # noqa: E402
from engine.matrix_schema import (  # noqa: E402
    MATRIX_SCHEMA_VERSION,
    compute_recipe_hash_from_file,
    make_cell_v2,
    now_utc_iso,
)


def _ai_factory(args) -> callable:
    """CLI 引数から AI factory を構築。"""
    if args.ai == "greedy":
        return GreedyAI
    if args.ai == "planning":
        beam = args.beam
        depth = args.depth
        adaptive = args.adaptive
        return lambda *a, **kw: PlanningAI(
            *a, beam_width=beam, max_depth=depth, adaptive=adaptive, **kw
        )
    raise ValueError(f"unknown --ai: {args.ai}")


def _load_existing(output_path: Path) -> dict:
    """既存 output を読んで return。 存在しなければ空 dict。"""
    if not output_path.exists():
        return {}
    try:
        return json.loads(output_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  [WARN] 既存 output {output_path} の読み込み失敗: {e}", flush=True)
        return {}


def _completed_cells_index(existing: dict) -> dict[tuple[str, str], dict]:
    """既存 matrix から (deck_a, deck_b) → cell の index を作る。"""
    idx: dict[tuple[str, str], dict] = {}
    for row in existing.get("matrix", []):
        slug_a = row.get("deck_a")
        for cell in row.get("row", []):
            slug_b = cell.get("deck_b")
            if slug_a and slug_b:
                idx[(slug_a, slug_b)] = cell
    return idx


def _save_checkpoint(out_path: Path, doc: dict, cells_done: int, total: int) -> None:
    """atomic に出力 file を書き換える (= tmp に書いて rename)。"""
    doc["partial"] = cells_done < total
    doc["cells_done"] = cells_done
    doc["cells_total"] = total
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out_path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True, help="matrix JSON 出力先")
    ap.add_argument("--ai-version", required=True, help="cell に記録する AI version 識別子")
    ap.add_argument("--ai", default="planning", choices=["planning", "greedy"], help="AI 種別")
    ap.add_argument("--beam", type=int, default=2, help="PlanningAI beam_width")
    ap.add_argument("--depth", type=int, default=3, help="PlanningAI max_depth")
    ap.add_argument("--adaptive", dest="adaptive", action="store_true", default=False,
                    help="PlanningAI adaptive=True (= 旧挙動、 遅い)")
    ap.add_argument("--no-adaptive", dest="adaptive", action="store_false",
                    help="PlanningAI adaptive=False (= 固定 beam/depth)")
    ap.add_argument("--n-games", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--decks-glob", default="cardrush_*.json")
    ap.add_argument("--include-tcgportal", action="store_true", default=True)
    ap.add_argument("--force", action="store_true", help="既存 cell も再計算")
    args = ap.parse_args()

    nn_status = "DISABLED" if os.environ.get("ONEPIECE_NN_DISABLE") else "ENABLED"
    print(f"=== run_matrix_resumable ===", flush=True)
    print(f"  output: {args.output}", flush=True)
    print(f"  ai: {args.ai} beam={args.beam} depth={args.depth} adaptive={args.adaptive}", flush=True)
    print(f"  n_games={args.n_games} seed={args.seed} NN={nn_status}", flush=True)
    print(f"  ai_version={args.ai_version}", flush=True)
    print(f"  force={args.force}", flush=True)

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    deck_paths = sorted((ROOT / "decks").glob("cardrush_*.json"))
    if args.include_tcgportal:
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

    n = len(decks)
    total = n * n
    print(f"  decks={n}, total cells={total}", flush=True)

    # recipe hash
    deck_hashes: dict[str, str] = {}
    for p in deck_paths:
        h = compute_recipe_hash_from_file(p)
        if h:
            deck_hashes[p.stem] = h

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    existing = _load_existing(out_path)
    completed = _completed_cells_index(existing) if not args.force else {}
    if completed:
        print(f"  既存 cells を {len(completed)} 件検出 → resume", flush=True)

    factory = _ai_factory(args)

    # matrix doc 初期化 (= 既存 row を保持、 不足分のみ追加)
    matrix_by_slug: dict[str, dict] = {
        r.get("deck_a"): r for r in existing.get("matrix", [])
    }

    t0 = time.time()
    cells_done_total = sum(len(r.get("row", [])) for r in existing.get("matrix", []))
    cells_done_initial = cells_done_total
    new_cells_run = 0

    for slug_a, name_a, deck_a in decks:
        hash_a = deck_hashes.get(slug_a, "")
        row_data = matrix_by_slug.get(slug_a)
        if row_data is None:
            row_data = {"deck_a": slug_a, "deck_a_name": name_a, "row": []}
            matrix_by_slug[slug_a] = row_data
        existing_by_b: dict[str, dict] = {c.get("deck_b"): c for c in row_data["row"]}

        for slug_b, name_b, deck_b in decks:
            # 既存 cell があれば skip (= force 除く)
            key = (slug_a, slug_b)
            if not args.force and key in completed:
                continue

            # self vs self → null cell
            if slug_a == slug_b:
                if slug_b not in existing_by_b:
                    cell = {
                        "deck_b": slug_b,
                        "winrate": None,
                        "wins": 0, "losses": 0, "draws": 0,
                        "avg_turns": 0.0,
                        "deck_a_recipe_hash": hash_a,
                        "deck_b_recipe_hash": hash_a,
                        "ai_version": args.ai_version,
                        "computed_at": now_utc_iso(),
                        "stale": False,
                    }
                    row_data["row"].append(cell)
                    existing_by_b[slug_b] = cell
                    cells_done_total += 1
                continue

            hash_b = deck_hashes.get(slug_b, "")
            t_cell = time.time()
            rep = run_matchup(
                deck_a, deck_b,
                n_games=args.n_games, seed=args.seed,
                ai_factory_1=factory, ai_factory_2=factory,
            )
            cell = make_cell_v2(
                deck_b_slug=slug_b,
                winrate=round(rep.deck1_winrate, 4),
                wins=rep.deck1_wins,
                losses=rep.deck2_wins,
                draws=rep.draws,
                avg_turns=round(rep.avg_turns, 2),
                deck_a_hash=hash_a,
                deck_b_hash=hash_b,
                ai_version=args.ai_version,
                stale=False,
            )
            # 既存 cell があれば置換、 なければ append
            if slug_b in existing_by_b:
                # 順序保ったまま置換
                for i, c in enumerate(row_data["row"]):
                    if c.get("deck_b") == slug_b:
                        row_data["row"][i] = cell
                        break
            else:
                row_data["row"].append(cell)
                existing_by_b[slug_b] = cell

            cells_done_total += 1
            new_cells_run += 1
            cell_elapsed = time.time() - t_cell
            elapsed = time.time() - t0
            new_remaining = (total - cells_done_total)
            rate = new_cells_run / elapsed if elapsed > 0 else 0
            eta = new_remaining / rate if rate > 0 else 0
            print(
                f"  cell {cells_done_total}/{total} | "
                f"{slug_a} vs {slug_b} | wr={rep.deck1_winrate:.2f} | "
                f"{cell_elapsed:.1f}s | elapsed {elapsed:.0f}s | ETA {eta:.0f}s",
                flush=True,
            )

            # === per-cell checkpoint ===
            doc = {
                "schema_version": MATRIX_SCHEMA_VERSION,
                "computed_at": now_utc_iso(),
                "n_games": args.n_games,
                "seed": args.seed,
                "ai_version": args.ai_version,
                "ai_config": {
                    "ai": args.ai,
                    "beam": args.beam,
                    "depth": args.depth,
                    "adaptive": args.adaptive,
                    "nn": nn_status,
                },
                "decks": [{"slug": s, "name": nm} for s, nm, _ in decks],
                "matrix": list(matrix_by_slug.values()),
            }
            _save_checkpoint(out_path, doc, cells_done_total, total)

    elapsed = time.time() - t0
    print(f"\n完了: {out_path}  ({elapsed:.1f}s, new {new_cells_run} cells run, resumed {cells_done_initial} cells)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
