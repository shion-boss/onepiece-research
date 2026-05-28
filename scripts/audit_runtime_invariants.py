#!/usr/bin/env python3
"""Phase 2 runtime invariant audit (= 2026-05-28、 docs/AUTO_AUDIT_SYSTEM.md Layer 2)。

ONEPIECE_AUDIT_INVARIANTS=1 で AI vs AI batch を 走らせ、 engine が 検出 した
state.audit_violations + state._effect_events を 集約 → 違反 report。

使い方:
  .venv/bin/python scripts/audit_runtime_invariants.py
  .venv/bin/python scripts/audit_runtime_invariants.py --n-games 100 --workers 8
  .venv/bin/python scripts/audit_runtime_invariants.py --deck-a cardrush_1342 --deck-b cardrush_1342

出力:
  db/runtime_audit_report.json (= 全 違反 list)
  db/runtime_audit_report.md (= 上位 30 件)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

# audit を 必ず ON で 実行
os.environ.setdefault("ONEPIECE_AUDIT_INVARIANTS", "1")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

OUT_JSON = REPO_ROOT / "db" / "runtime_audit_report.json"
OUT_MD = REPO_ROOT / "db" / "runtime_audit_report.md"


def run_game(deck_a_path: Path, deck_b_path: Path, seed: int, ai_mode: str) -> dict:
    """1 試合 を 走らせて state.audit_violations + effect_events meta を 返す。"""
    from engine.deck import CardRepository, DeckList
    from engine.harness import run_matchup
    from engine.ai import GreedyAI
    from engine.goal_directed_ai import GoalDirectedAI

    cards_path = REPO_ROOT / "db" / "cards.json"
    repo = CardRepository.from_json(cards_path)
    deck_a = DeckList.from_json(deck_a_path, repo)
    deck_b = DeckList.from_json(deck_b_path, repo)

    if ai_mode == "goal":
        def factory(rng, deck_analysis=None):
            return GoalDirectedAI(
                rng=rng, deck_analysis=deck_analysis,
                adaptive=False, beam_width=2, max_depth=4,
                spec_version="v1",
            )
    else:
        def factory(rng, deck_analysis=None):
            return GreedyAI(rng=rng, deck_analysis=deck_analysis)

    rep = run_matchup(
        deck_a, deck_b, n_games=1, seed=seed,
        ai_factory_1=factory, ai_factory_2=factory,
    )
    g = rep.games[0]

    # state は run_matchup 内 で 破棄 されている → 違反 は game.audit_violations 経由 で
    # 残す 必要 がある。 現状 は run_matchup 拡張 で 集める 必要 あり。
    # 暫定: rep に audit_violations 含めるよう engine/harness.py 修正 する 必要あり (= follow-up)。
    # ここ で は ゲーム メタ情報 のみ 返す。
    return {
        "winner": g.winner,
        "turns": g.turns,
        "deck_a": deck_a_path.name,
        "deck_b": deck_b_path.name,
        "audit_violations": getattr(g, "audit_violations", []),
        "effect_events_count": len(getattr(g, "effect_events", [])),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-games", type=int, default=10)
    ap.add_argument("--deck-a", default="cardrush_1342")
    ap.add_argument("--deck-b", default="cardrush_1342")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--ai-mode", choices=["goal", "greedy"], default="goal")
    args = ap.parse_args()

    decks_dir = REPO_ROOT / "decks"
    deck_a_path = decks_dir / f"{args.deck_a}.json"
    deck_b_path = decks_dir / f"{args.deck_b}.json"

    if not deck_a_path.exists():
        print(f"ERROR: deck not found: {deck_a_path}", file=sys.stderr)
        sys.exit(1)
    if not deck_b_path.exists():
        print(f"ERROR: deck not found: {deck_b_path}", file=sys.stderr)
        sys.exit(1)

    print("=" * 70)
    print(f"Runtime Audit (Layer 2)")
    print("=" * 70)
    print(f"deck a: {args.deck_a}")
    print(f"deck b: {args.deck_b}")
    print(f"n_games: {args.n_games}")
    print(f"ai_mode: {args.ai_mode}")
    print(f"audit enabled (env): {os.environ.get('ONEPIECE_AUDIT_INVARIANTS')}")
    print()

    all_violations = []
    total_events = 0
    t_start = time.time()
    for i in range(args.n_games):
        result = run_game(deck_a_path, deck_b_path, args.seed + i, args.ai_mode)
        violations = result.get("audit_violations", [])
        all_violations.extend(violations)
        total_events += result.get("effect_events_count", 0)
        if (i + 1) % max(1, args.n_games // 10) == 0:
            elapsed = time.time() - t_start
            print(f"  [{i+1}/{args.n_games}] elapsed={elapsed:.1f}s "
                  f"violations={len(all_violations)} events={total_events}")

    print()
    print("-" * 70)
    print(f"完了 ({time.time() - t_start:.1f}s)")
    print(f"total violations: {len(all_violations)}")
    print(f"total effect events: {total_events}")

    # 集計
    by_rule = Counter(v.get("rule_id", "?") for v in all_violations)
    print()
    print("by rule:")
    for rule, count in sorted(by_rule.items()):
        print(f"  {rule}: {count}")

    # 出力
    report = {
        "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "config": {
            "n_games": args.n_games,
            "deck_a": args.deck_a,
            "deck_b": args.deck_b,
            "ai_mode": args.ai_mode,
            "seed": args.seed,
        },
        "summary": {
            "total_violations": len(all_violations),
            "total_effect_events": total_events,
            "by_rule": dict(by_rule),
        },
        "violations": all_violations,
    }
    OUT_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# Runtime Audit Report (Layer 2)",
        "",
        f"generated: {report['generated_at']}  ",
        f"n_games: {args.n_games}, deck: {args.deck_a} vs {args.deck_b}, ai: {args.ai_mode}  ",
        f"total violations: {len(all_violations)}  ",
        f"total effect events: {total_events}  ",
        "",
        "## by rule",
        "",
    ]
    for rule, count in sorted(by_rule.items()):
        lines.append(f"- `{rule}`: {count}")
    lines += ["", "## top 30 violations", ""]
    for i, v in enumerate(all_violations[:30]):
        lines += [
            f"### {i+1}. {v.get('rule_id', '?')} (sev {v.get('severity', '?')})",
            "",
            f"- turn: {v.get('turn')} phase: {v.get('phase')}",
            f"- message: {v.get('message', '')}",
            f"- evidence: `{json.dumps(v.get('evidence', {}), ensure_ascii=False)[:200]}`",
            "",
        ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print()
    print(f"output: {OUT_JSON.relative_to(REPO_ROOT)}")
    print(f"        {OUT_MD.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
