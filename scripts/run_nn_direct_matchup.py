# -*- coding: utf-8 -*-
"""NN有効 PlanningAI vs NN無効 PlanningAI の直接対戦 matrix。

各デッキで NN-on AI vs NN-off AI を 100 戦して、 NN自身の強さを直接測定。
mirror matrix (= run_matrix_resumable.py の A/B) はゼロサムなので NN 自身の
良し悪し判定には使えない。 本 script で 「NN を入れたら AI が強くなるか」 を
プレイヤーレベルで評価する。

実行例:
    .venv/bin/python scripts/run_nn_direct_matchup.py \\
        --output db/nn_direct_matchup.json \\
        --n-games 100 --seed 42

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
from engine.ai import PlanningAI  # noqa: E402
from engine.nn_eval import nn_disabled  # noqa: E402


class PlanningAI_NoNN(PlanningAI):
    """choose_action / choose_defense 中 NN を bypass する PlanningAI 派生。

    nn_disabled context manager で _NN_FORCE_DISABLED=True にして 線形 fallback。
    自分の手番中の eval 全て (= plan_search の leaf compute_score) が NN を使わない。
    """

    name = "PlanningNoNN"

    def choose_action(self, state):
        with nn_disabled():
            return super().choose_action(state)

    def choose_defense(self, state, attacker, target, is_leader_attack, defender):
        with nn_disabled():
            return super().choose_defense(state, attacker, target, is_leader_attack, defender)


def _planning_factory(beam: int, depth: int, adaptive: bool):
    return lambda *a, **kw: PlanningAI(
        *a, beam_width=beam, max_depth=depth, adaptive=adaptive, **kw
    )


def _planning_no_nn_factory(beam: int, depth: int, adaptive: bool):
    return lambda *a, **kw: PlanningAI_NoNN(
        *a, beam_width=beam, max_depth=depth, adaptive=adaptive, **kw
    )


def _save_checkpoint(out_path: Path, doc: dict) -> None:
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out_path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--n-games", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--beam", type=int, default=2)
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--adaptive", dest="adaptive", action="store_true", default=False)
    ap.add_argument("--no-adaptive", dest="adaptive", action="store_false")
    ap.add_argument("--force", action="store_true", help="既存 deck も再計算")
    args = ap.parse_args()

    # NN 強制無効化されてないか確認
    if os.environ.get("ONEPIECE_NN_DISABLE"):
        print("[ERROR] ONEPIECE_NN_DISABLE=1 が設定されている。 NN 有効 AI 側が無効化されてしまう。", flush=True)
        return 1

    # NN model 存在チェック
    from engine.nn_eval import get_model
    m = get_model()
    if m is None:
        print("[ERROR] NN model が load できない (= db/nn_eval.pt 不在)", flush=True)
        return 1
    print(f"NN model: {type(m).__name__}", flush=True)

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    deck_paths = sorted((ROOT / "decks").glob("cardrush_*.json"))
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

    print(f"  decks={len(decks)}, n_games per deck={args.n_games}", flush=True)
    print(f"  AI: PlanningAI(beam={args.beam},depth={args.depth},adaptive={args.adaptive})", flush=True)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 既存 result を読んで resume
    existing: dict = {}
    if out_path.exists() and not args.force:
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
            existing_decks = {r["deck"] for r in existing.get("results", [])}
            print(f"  既存 {len(existing_decks)} デッキを resume", flush=True)
        except Exception as e:
            print(f"  [WARN] 既存 file 読込失敗 ({e})、 full re-run", flush=True)
            existing = {}

    results: list[dict] = list(existing.get("results", []))
    done_decks: set[str] = {r["deck"] for r in results}

    nn_factory = _planning_factory(args.beam, args.depth, args.adaptive)
    no_nn_factory = _planning_no_nn_factory(args.beam, args.depth, args.adaptive)

    t0 = time.time()
    for slug, name, deck in decks:
        if not args.force and slug in done_decks:
            continue

        t_deck = time.time()
        # AI 1 = NN有効, AI 2 = NN無効
        # 先攻後攻は run_matchup が均等にする
        rep = run_matchup(
            deck, deck,
            n_games=args.n_games, seed=args.seed,
            ai_factory_1=nn_factory, ai_factory_2=no_nn_factory,
        )
        # NN-on 側 = deck1 側、 winrate は NN-on の勝率
        nn_winrate = rep.deck1_winrate
        result = {
            "deck": slug,
            "deck_name": name,
            "nn_wins": rep.deck1_wins,
            "no_nn_wins": rep.deck2_wins,
            "draws": rep.draws,
            "nn_winrate": round(nn_winrate, 4),
            "avg_turns": round(rep.avg_turns, 2),
            "n_games": args.n_games,
        }
        results.append(result)
        done_decks.add(slug)

        deck_elapsed = time.time() - t_deck
        elapsed = time.time() - t0
        new_remaining = (len(decks) - len(done_decks))
        rate = len([r for r in results if r["deck"] not in (existing.get("results", []) and {r2["deck"] for r2 in existing["results"]} or set())]) / elapsed if elapsed > 0 else 0
        eta = new_remaining * deck_elapsed if rate else 0

        marker = "✓" if nn_winrate > 0.5 else ("✗" if nn_winrate < 0.5 else "=")
        print(
            f"  [{len(done_decks)}/{len(decks)}] {slug:<28} | "
            f"NN {rep.deck1_wins}-{rep.deck2_wins}-{rep.draws} ({nn_winrate*100:.1f}%) {marker} | "
            f"{deck_elapsed:.0f}s | ETA {eta:.0f}s",
            flush=True,
        )

        # checkpoint per deck
        doc = {
            "computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "n_games_per_deck": args.n_games,
            "seed": args.seed,
            "ai_config": {
                "ai": "planning",
                "beam": args.beam,
                "depth": args.depth,
                "adaptive": args.adaptive,
            },
            "partial": len(done_decks) < len(decks),
            "decks_done": len(done_decks),
            "decks_total": len(decks),
            "results": results,
        }
        _save_checkpoint(out_path, doc)

    elapsed = time.time() - t0
    n_done = len(results)
    if n_done > 0:
        avg_winrate = sum(r["nn_winrate"] for r in results) / n_done
        wins = sum(1 for r in results if r["nn_winrate"] > 0.5)
        losses = sum(1 for r in results if r["nn_winrate"] < 0.5)
        print(flush=True)
        print(f"完了: {out_path} ({elapsed:.1f}s)", flush=True)
        print(f"  平均 NN winrate: {avg_winrate*100:.1f}% across {n_done} decks", flush=True)
        print(f"  NN > 50%: {wins} decks, NN < 50%: {losses} decks", flush=True)
        print(f"  → NN が AI として強い: {'YES' if avg_winrate > 0.5 else 'NO'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
