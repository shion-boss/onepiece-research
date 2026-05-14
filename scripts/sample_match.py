# -*- coding: utf-8 -*-
"""
サンプル試合 viewer (= matrix 走行中でも別プロセスで観戦可能)
==============================================================

matrix プロセスは試合 log を保存しない (= cost 削減)。
このスクリプトで 1 試合だけ verbose log で確認できる。

実行例:
    .venv/bin/python scripts/sample_match.py
    .venv/bin/python scripts/sample_match.py --deck-a cardrush_1454 --deck-b cardrush_1453
    .venv/bin/python scripts/sample_match.py --seed 100 --turn-summary
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.effects import load_effect_overlay  # noqa: E402
from engine.harness import run_matchup  # noqa: E402


def _format_turn_summary(log_lines: list[str]) -> list[str]:
    """log を turn 別に要約。"""
    by_turn: dict[str, list[str]] = defaultdict(list)
    for line in log_lines:
        if line.startswith("T") and ":" in line:
            turn_part = line.split(":", 1)[0]
            by_turn[turn_part].append(line)
    out = []
    for tkey in sorted(by_turn.keys(), key=lambda x: (int(x.split()[0][1:]), x.split()[1])):
        lines = by_turn[tkey]
        # 重要イベントだけ抽出 (= atk / play / event / 起動メイン / KO / hit / GAME OVER)
        important = [
            l for l in lines
            if any(k in l for k in [
                "atk:", "play:", "event:", "起動メイン", "KO:", "hit:",
                "GAME OVER", "blocked", "blocker", "counter +",
                "attach don to leader", "start:"
            ])
        ]
        out.extend(important)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deck-a", default="cardrush_1454", help="P0 デッキ slug (= 紫エネル 既定)")
    ap.add_argument("--deck-b", default="cardrush_1453", help="P1 デッキ slug (= 緑ミホーク 既定)")
    ap.add_argument("--seed", type=int, default=42, help="乱数 seed (= 42 既定で再現性)")
    ap.add_argument("--turn-summary", action="store_true",
                    help="ターン別の重要イベントだけ抽出表示 (= verbose log の代わり)")
    ap.add_argument("--max-lines", type=int, default=300, help="表示上限行数")
    args = ap.parse_args()

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    try:
        d1 = DeckList.from_json(ROOT / "decks" / f"{args.deck_a}.json", repo)
        d2 = DeckList.from_json(ROOT / "decks" / f"{args.deck_b}.json", repo)
    except FileNotFoundError as e:
        print(f"deck not found: {e}")
        return 1

    print(f"=== サンプル試合: {d1.name} vs {d2.name} ===")
    print(f"  seed={args.seed}, AI=PlanningAI (= matrix と同 default)")
    print()

    rep = run_matchup(
        d1, d2,
        n_games=1,
        seed=args.seed,
        effects_overlay=overlay,
        keep_logs=True,
        enforce_rules=False,
    )
    g = rep.games[0]

    if g.winner == 0:
        result = f"P0 ({d1.name}) 勝"
    elif g.winner == 1:
        result = f"P1 ({d2.name}) 勝"
    else:
        result = "draw / timeout"

    print(f"--- 結果 ---")
    print(f"  {result}")
    print(f"  turns: {g.turns}, total actions: {g.actions}")
    print(f"  残ライフ: P0={g.p0_life_left} / P1={g.p1_life_left}")
    print(f"  残場キャラ: P0={g.p0_field} / P1={g.p1_field}")
    print()

    log = _format_turn_summary(g.log) if args.turn_summary else g.log
    print(f"--- {'重要イベント' if args.turn_summary else 'ログ全文'} ({len(log)} 行) ---")
    for line in log[:args.max_lines]:
        print(line)
    if len(log) > args.max_lines:
        print(f"... (合計 {len(log)} 行、 --max-lines で拡張可)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
