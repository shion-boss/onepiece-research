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

# 2026-05-29: matrix 計算 で AUDIT default ON (= 学習 + 検証 統合)
import os
os.environ.setdefault("ONEPIECE_AUDIT_INVARIANTS", "1")

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
LOG_PATH = ROOT / "db" / "matrix_run_log.ndjson"
DEFAULT_AI_VERSION = "GoalDirectedAI_default"


def _compute_cell_worker(task):
    """multiprocessing.Pool worker: 1 cell の run_matchup を 計算。

    task: (slug_a, slug_b, deck_a_path_str, deck_b_path_str, n_games, seed, ai_mode)
    return: dict with slug_a, slug_b, winrate, wins, losses, draws, avg_turns, games_info
    """
    slug_a, slug_b, deck_a_path, deck_b_path, n_games, seed, ai_mode = task
    # 各 worker で 個別 load (= 並列 fork なら CoW で 大体共有、 spawn なら 個別 cost)
    from engine.deck import CardRepository, DeckList
    from engine.harness import run_matchup
    from pathlib import Path as _Path
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    deck_a = DeckList.from_json(_Path(deck_a_path), repo)
    deck_b = DeckList.from_json(_Path(deck_b_path), repo)

    rep_kwargs = dict(n_games=n_games, seed=seed)
    if ai_mode == "greedy":
        from engine.ai import GreedyAI

        def _aif(rng, deck_analysis=None):
            return GreedyAI(rng=rng)

        rep_kwargs["ai_factory_1"] = _aif
        rep_kwargs["ai_factory_2"] = _aif
    elif ai_mode == "planning":
        from engine.ai import PlanningAI

        def _aif(rng, deck_analysis=None):
            return PlanningAI(rng=rng, deck_analysis=deck_analysis)

        rep_kwargs["ai_factory_1"] = _aif
        rep_kwargs["ai_factory_2"] = _aif
    # ai_mode == "default" は harness が GoalDirectedAI を 自動 構築

    rep = run_matchup(deck_a, deck_b, **rep_kwargs)
    games_info = []
    for gi, g in enumerate(getattr(rep, "games", []) or []):
        games_info.append({
            "game_index": gi,
            "winner": g.winner,
            "turns": g.turns,
            "p0_life_left": g.p0_life_left,
            "p1_life_left": g.p1_life_left,
            "p0_field": g.p0_field,
            "p1_field": g.p1_field,
        })
    return {
        "slug_a": slug_a,
        "slug_b": slug_b,
        "winrate": round(rep.deck1_winrate, 4),
        "wins": rep.deck1_wins,
        "losses": rep.deck2_wins,
        "draws": rep.draws,
        "avg_turns": round(rep.avg_turns, 2),
        "games_info": games_info,
    }


def _append_log(entry: dict) -> None:
    """matrix 走行中の per-cell / per-game 記録を NDJSON で追記。
    UI (/meta/progress) が tail で読む。 書き込み失敗は無視 (= matrix 本体を止めない)。"""
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


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
    ap.add_argument(
        "--ai-mode", default="default",
        choices=["default", "greedy", "planning"],
        help=(
            "AI factory mode: "
            "default = GoalDirectedAI (= 最新 default、 高品質 だが ~60s/game)、 "
            "greedy = GreedyAI (= 高速、 1-2s/game、 マトリックス 計算 用)、 "
            "planning = PlanningAI (= 中間、 ~10s/game)"
        ),
    )
    ap.add_argument(
        "--workers", type=int, default=1,
        help=(
            "並列度。 1 = sequential (= 既存挙動)、 2+ = multiprocessing で N cell 同時計算。 "
            "推奨: GoalDirectedAI で 4-8 (= memory 2 GiB/worker、 16 GiB RAM 環境 で 8 が 安全)。"
        ),
    )
    args = ap.parse_args()

    # --ai-mode に 応じた factory を 構築。 default 以外 は run_matchup に 渡す。
    ai_factory = None
    if args.ai_mode == "greedy":
        from engine.ai import GreedyAI
        def ai_factory(rng, deck_analysis=None):
            return GreedyAI(rng=rng)
        if args.ai_version == DEFAULT_AI_VERSION:
            args.ai_version = "GreedyAI_matrix_fast"
    elif args.ai_mode == "planning":
        from engine.ai import PlanningAI
        def ai_factory(rng, deck_analysis=None):
            return PlanningAI(rng=rng, deck_analysis=deck_analysis)
        if args.ai_version == DEFAULT_AI_VERSION:
            args.ai_version = "PlanningAI_matrix_mid"

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
    # 走行開始マーカー (= UI が新しい run の開始を検知)
    _append_log({
        "ts": now_utc_iso(),
        "event": "run_start",
        "ai_version": ai_version,
        "n_games": args.n_games,
        "n_decks": len(decks),
        "total_cells": total,
        "seed": args.seed,
        "incremental": bool(args.incremental),
    })
    # 2026-05-27: cell 単位 incremental save (= 行単位 だと GoalDirectedAI で 1 行 ~1-2h、
    # その間 kill すると 全 cell 損失)。 PARTIAL_SAVE_EVERY cell ごと に 「現 row が
    # partial でも 含めて」 全体 dump、 任意 タイミング kill でも 損失 5 cell 以内。
    PARTIAL_SAVE_EVERY = 5

    def _write_partial_snapshot(current_row_cells, current_slug_a, current_name_a):
        """途中 row を 含めて 全体 dump。 partial_row=True flag で 半分作った row を 識別可。"""
        matrix_snapshot = list(cells)
        if current_row_cells:
            matrix_snapshot.append({
                "deck_a": current_slug_a,
                "deck_a_name": current_name_a,
                "row": list(current_row_cells),
                "partial_row": len(current_row_cells) < len(decks),
            })
        partial = {
            "schema_version": MATRIX_SCHEMA_VERSION,
            "computed_at": now_utc_iso(),
            "n_games": args.n_games,
            "seed": args.seed,
            "ai_version": ai_version,
            "partial": True,
            "decks": [{"slug": s, "name": n} for s, n, _ in decks],
            "matrix": matrix_snapshot,
        }
        OUT.write_text(json.dumps(partial, ensure_ascii=False, indent=2), encoding="utf-8")

    # === 並列 path (= --workers > 1) ===
    if args.workers > 1:
        from multiprocessing import Pool

        # cells_to_compute 構築 (= mirror / reuse 除外)
        tasks = []
        mirror_cells_by_a: dict[str, list] = {}
        reused_cells_by_a: dict[str, list] = {}
        for slug_a, name_a, _ in decks:
            hash_a = deck_hashes.get(slug_a, "")
            existing_row = existing_row_by_slug.get(slug_a, {}).get("row", [])
            existing_cell_by_b = {c.get("deck_b"): c for c in existing_row}
            mirror_cells_by_a[slug_a] = []
            reused_cells_by_a[slug_a] = []
            for slug_b, _name_b, _ in decks:
                if slug_a == slug_b:
                    mirror_cells_by_a[slug_a].append({
                        "deck_b": slug_b,
                        "winrate": None,
                        "wins": 0, "losses": 0, "draws": 0,
                        "avg_turns": 0.0,
                        "deck_a_recipe_hash": hash_a,
                        "deck_b_recipe_hash": hash_a,
                        "ai_version": ai_version,
                        "computed_at": now_utc_iso(),
                        "stale": False,
                    })
                    continue
                hash_b = deck_hashes.get(slug_b, "")
                if args.incremental:
                    ec = existing_cell_by_b.get(slug_b)
                    if ec and not is_cell_stale(ec, hash_a, hash_b, ai_version):
                        rc = dict(ec)
                        rc["deck_a_recipe_hash"] = hash_a
                        rc["deck_b_recipe_hash"] = hash_b
                        rc["ai_version"] = ai_version
                        rc["stale"] = False
                        reused_cells_by_a[slug_a].append(rc)
                        reused += 1
                        continue
                tasks.append((
                    slug_a, slug_b,
                    str(ROOT / "decks" / f"{slug_a}.json"),
                    str(ROOT / "decks" / f"{slug_b}.json"),
                    args.n_games, args.seed, args.ai_mode,
                ))

        print(f"並列計算: {len(tasks)} cells × {args.workers} workers (= reuse {reused})", flush=True)
        results: dict = {}  # (slug_a, slug_b) -> cell dict
        deck_name_by_slug = {s: n for s, n, _ in decks}

        def _build_partial_matrix():
            """results + mirror + reuse から 全 row 構成 を rebuild (= partial save 用)。"""
            matrix_snapshot = []
            for slug_a, name_a, _ in decks:
                row_cells = []
                for slug_b, _, _ in decks:
                    if slug_a == slug_b:
                        row_cells.append(mirror_cells_by_a[slug_a][0])
                        continue
                    cell = results.get((slug_a, slug_b))
                    if cell is None:
                        # まだ 計算 してない、 もしくは reuse 候補
                        for rc in reused_cells_by_a[slug_a]:
                            if rc.get("deck_b") == slug_b:
                                cell = rc
                                break
                    if cell is not None:
                        row_cells.append(cell)
                # row_cells が 半分作りでも 全体 dump (= UI partial 対応)
                expected = len(decks)
                matrix_snapshot.append({
                    "deck_a": slug_a,
                    "deck_a_name": name_a,
                    "row": row_cells,
                    "partial_row": len(row_cells) < expected,
                })
            return matrix_snapshot

        def _write_partial_parallel():
            partial = {
                "schema_version": MATRIX_SCHEMA_VERSION,
                "computed_at": now_utc_iso(),
                "n_games": args.n_games,
                "seed": args.seed,
                "ai_version": ai_version,
                "partial": True,
                "decks": [{"slug": s, "name": n} for s, n, _ in decks],
                "matrix": _build_partial_matrix(),
            }
            OUT.write_text(json.dumps(partial, ensure_ascii=False, indent=2), encoding="utf-8")

        t_par = time.time()
        with Pool(args.workers) as pool:
            for r in pool.imap_unordered(_compute_cell_worker, tasks, chunksize=1):
                slug_a = r["slug_a"]
                slug_b = r["slug_b"]
                hash_a = deck_hashes.get(slug_a, "")
                hash_b = deck_hashes.get(slug_b, "")
                cell = make_cell_v2(
                    deck_b_slug=slug_b,
                    winrate=r["winrate"],
                    wins=r["wins"],
                    losses=r["losses"],
                    draws=r["draws"],
                    avg_turns=r["avg_turns"],
                    deck_a_hash=hash_a,
                    deck_b_hash=hash_b,
                    ai_version=ai_version,
                    stale=False,
                )
                results[(slug_a, slug_b)] = cell
                for g in r["games_info"]:
                    _append_log({
                        "ts": now_utc_iso(), "event": "game",
                        "deck_a": slug_a, "deck_a_name": deck_name_by_slug[slug_a],
                        "deck_b": slug_b, "deck_b_name": deck_name_by_slug[slug_b],
                        **g,
                    })
                _append_log({
                    "ts": now_utc_iso(), "event": "cell_done",
                    "deck_a": slug_a, "deck_b": slug_b,
                    "cell_winrate": r["winrate"],
                    "cell_wins": r["wins"], "cell_losses": r["losses"],
                    "cell_draws": r["draws"], "avg_turns": r["avg_turns"],
                })
                recomputed += 1
                done_now = len(results)
                el = time.time() - t_par
                rate = done_now / el if el > 0 else 0
                eta = (len(tasks) - done_now) / rate if rate > 0 else 0
                print(
                    f"  done {done_now}/{len(tasks)}  {slug_a:<22} vs {slug_b:<22} "
                    f"wr={r['winrate']:.3f}  elapsed {el:.0f}s  ETA {eta:.0f}s",
                    flush=True,
                )
                if done_now % 5 == 0:
                    _write_partial_parallel()

        # final
        cells = _build_partial_matrix()
        out = {
            "schema_version": MATRIX_SCHEMA_VERSION,
            "computed_at": now_utc_iso(),
            "n_games": args.n_games,
            "seed": args.seed,
            "ai_version": ai_version,
            "decks": [{"slug": s, "name": n} for s, n, _ in decks],
            "matrix": cells,
        }
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        elapsed = time.time() - t0
        print(f"\n並列計算 完了: {recomputed} cells recomputed, {reused} reused, elapsed {elapsed:.0f}s", flush=True)
        _append_log({
            "ts": now_utc_iso(), "event": "run_done",
            "cells_done": done + recomputed, "elapsed_sec": round(elapsed, 1),
            "reused": reused, "recomputed": recomputed,
        })
        return 0

    # === Sequential path (= --workers == 1、 既存挙動 維持) ===
    for slug_a, name_a, deck_a in decks:
        hash_a = deck_hashes.get(slug_a, "")
        existing_row = existing_row_by_slug.get(slug_a, {}).get("row", [])
        existing_cell_by_b: dict[str, dict] = {
            c.get("deck_b"): c for c in existing_row
        }

        row = []
        cells_in_row = 0  # この row で 計算済 cell 数 (= partial save トリガー用)
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

            _append_log({
                "ts": now_utc_iso(),
                "event": "cell_start",
                "deck_a": slug_a, "deck_a_name": name_a,
                "deck_b": slug_b, "deck_b_name": name_b,
            })
            rep_kwargs = dict(n_games=args.n_games, seed=args.seed)
            if ai_factory is not None:
                rep_kwargs["ai_factory_1"] = ai_factory
                rep_kwargs["ai_factory_2"] = ai_factory
            rep = run_matchup(deck_a, deck_b, **rep_kwargs)
            # per-game の簡易 summary を NDJSON に出す (= UI の log tail で観戦)
            for gi, g in enumerate(getattr(rep, "games", []) or []):
                _append_log({
                    "ts": now_utc_iso(),
                    "event": "game",
                    "deck_a": slug_a, "deck_a_name": name_a,
                    "deck_b": slug_b, "deck_b_name": name_b,
                    "game_index": gi,
                    "winner": g.winner,
                    "turns": g.turns,
                    "p0_life_left": g.p0_life_left,
                    "p1_life_left": g.p1_life_left,
                    "p0_field": g.p0_field,
                    "p1_field": g.p1_field,
                })
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
            _append_log({
                "ts": now_utc_iso(),
                "event": "cell_done",
                "deck_a": slug_a, "deck_a_name": name_a,
                "deck_b": slug_b, "deck_b_name": name_b,
                "cell_winrate": round(rep.deck1_winrate, 4),
                "cell_wins": rep.deck1_wins,
                "cell_losses": rep.deck2_wins,
                "cell_draws": rep.draws,
                "avg_turns": round(rep.avg_turns, 2),
            })
            cells_in_row += 1
            # cell 単位 partial save (= PARTIAL_SAVE_EVERY 個ごと、 もしくは row 末尾)
            if cells_in_row % PARTIAL_SAVE_EVERY == 0:
                _write_partial_snapshot(row, slug_a, name_a)
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
        _append_log({
            "ts": now_utc_iso(),
            "event": "row_done",
            "deck_a": slug_a, "deck_a_name": name_a,
            "rows_done": len(cells),
            "rows_total": len(decks),
            "cells_done": done,
            "cells_total": total,
            "elapsed_sec": round(elapsed, 1),
            "eta_sec": round(eta, 1),
        })

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
    _append_log({
        "ts": now_utc_iso(),
        "event": "run_done",
        "elapsed_sec": round(elapsed, 1),
        "reused": reused,
        "recomputed": recomputed,
    })
    print()
    print(f"完了: {OUT}  ({elapsed:.1f}s, {OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
