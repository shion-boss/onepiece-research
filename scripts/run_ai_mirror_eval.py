# -*- coding: utf-8 -*-
"""改良 AI vs baseline NoNN PlanningAI を 全 16 デッキで mirror 対戦。

ユーザ要件 (= 2026-05-17): AI のみ変更可、 戦う条件は揃える、 同デッキ同士の mirror で
強さを判定。 試行錯誤のため小サンプル (= n_games=10) で多数 case 試行。

実行例:
    .venv/bin/python scripts/run_ai_mirror_eval.py \\
        --ai-class engine.ai_experimental.LethalRusherAI \\
        --output db/ai_search/lethal_rusher.json \\
        --n-games 10 --seed 42

per-deck checkpoint + resume 対応。
"""

from __future__ import annotations

import argparse
import importlib
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


class _BaselineNoNNPlanning(PlanningAI):
    """baseline: NoNN PlanningAI (= 線形 eval、 beam=2 depth=3 adaptive=False)。"""
    name = "BaselineNoNN"

    def choose_action(self, state):
        with nn_disabled():
            return super().choose_action(state)

    def choose_defense(self, state, attacker, target, is_leader_attack, defender):
        with nn_disabled():
            return super().choose_defense(state, attacker, target, is_leader_attack, defender)


def _resolve_ai_class(spec: str):
    """'engine.ai_experimental.LethalRusherAI' → class 取得。"""
    mod_path, cls_name = spec.rsplit(".", 1)
    mod = importlib.import_module(mod_path)
    return getattr(mod, cls_name)


def _save(out_path: Path, doc: dict) -> None:
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out_path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ai-class", required=True,
                    help="改良 AI の dotted path (= engine.ai_experimental.LethalRusherAI)")
    ap.add_argument("--ai-kwargs", default="{}",
                    help='改良 AI に渡す kwargs (= JSON、 例: {"lethal_mult":3.0})')
    ap.add_argument("--output", required=True)
    ap.add_argument("--n-games", type=int, default=10,
                    help="各 デッキで mirror 対戦の試合数 (default 10、 確定検証なら 50)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--label", default=None,
                    help="case label (= reporting 用、 default は class 名)")
    ap.add_argument("--baseline-beam", type=int, default=2)
    ap.add_argument("--baseline-depth", type=int, default=3)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    ai_cls = _resolve_ai_class(args.ai_class)
    ai_kwargs = json.loads(args.ai_kwargs)
    label = args.label or args.ai_class.split(".")[-1]

    print(f"=== mirror eval: {label} ===", flush=True)
    print(f"  ai_class: {args.ai_class}", flush=True)
    print(f"  ai_kwargs: {ai_kwargs}", flush=True)
    print(f"  n_games per deck: {args.n_games}", flush=True)
    print(f"  baseline: NoNN PlanningAI(beam={args.baseline_beam},depth={args.baseline_depth})", flush=True)

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

    # baseline factory (= 固定)
    bb = args.baseline_beam
    bd = args.baseline_depth
    baseline_factory = lambda *a, **kw: _BaselineNoNNPlanning(
        *a, beam_width=bb, max_depth=bd, adaptive=False, **kw
    )

    # 改良 AI factory
    def improved_factory(*a, **kw):
        merged = {**kw, **ai_kwargs}
        # adaptive=False / beam=2 / depth=3 を default に (= 改良 AI が override する想定)
        if "adaptive" not in merged:
            merged["adaptive"] = False
        if "beam_width" not in merged:
            merged["beam_width"] = bb
        if "max_depth" not in merged:
            merged["max_depth"] = bd
        return ai_cls(*a, **merged)

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
        rep = run_matchup(
            deck, deck, n_games=args.n_games, seed=args.seed,
            ai_factory_1=improved_factory, ai_factory_2=baseline_factory,
        )
        result = {
            "deck": slug,
            "deck_name": name,
            "improved_wins": rep.deck1_wins,
            "baseline_wins": rep.deck2_wins,
            "draws": rep.draws,
            "improved_winrate": round(rep.deck1_winrate, 4),
            "avg_turns": round(rep.avg_turns, 2),
            "n_games": args.n_games,
        }
        results.append(result)
        done_decks.add(slug)

        elapsed_deck = time.time() - t_deck
        elapsed = time.time() - t0
        n_done = len(done_decks)
        wr = rep.deck1_winrate
        marker = "✓+" if wr > 0.55 else ("✗-" if wr < 0.45 else "=")
        print(
            f"  [{n_done}/{len(decks)}] {slug:<28} | "
            f"imp={rep.deck1_wins}-{rep.deck2_wins}-{rep.draws} ({wr*100:>4.0f}%) {marker} | "
            f"{elapsed_deck:.0f}s | elapsed {elapsed:.0f}s",
            flush=True,
        )

        doc = {
            "label": label,
            "ai_class": args.ai_class,
            "ai_kwargs": ai_kwargs,
            "n_games_per_deck": args.n_games,
            "seed": args.seed,
            "computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "partial": len(done_decks) < len(decks),
            "decks_done": len(done_decks),
            "decks_total": len(decks),
            "results": results,
        }
        _save(out_path, doc)

    if results:
        avg = sum(r["improved_winrate"] for r in results) / len(results)
        wins = sum(1 for r in results if r["improved_winrate"] > 0.55)
        losses = sum(1 for r in results if r["improved_winrate"] < 0.45)
        print(flush=True)
        print(f"=== 結果 ({label}) ===", flush=True)
        print(f"  改良 AI 平均勝率 vs baseline: {avg*100:.1f}% (mirror 期待 50%)", flush=True)
        print(f"  delta vs baseline: {(avg-0.5)*100:+.1f}pt", flush=True)
        print(f"  ✓ 勝ち (>55%): {wins} デッキ / ✗ 負け (<45%): {losses} デッキ", flush=True)
        if avg > 0.55:
            print(f"  → 改良 AI は強い: YES", flush=True)
        elif avg < 0.45:
            print(f"  → 改良 AI は弱い: YES", flush=True)
        else:
            print(f"  → ほぼ同等: YES", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
