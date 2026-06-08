# -*- coding: utf-8 -*-
"""ローカル LLM (Ollama) を 既存 AI と N 戦させ、 LLM の勝率を測る CLI バッチ。

run_matchup は両側に任意の AI factory を差せるので、 片方を LLMPlayerAI、
もう片方を Greedy / ExploitBeam(SmartOpponent) / GoalDirected にするだけ。

例:
  # 軽量基準線 (= LLM の素の実力)
  .venv/bin/python scripts/ai_vs_llm.py --opponent greedy --deck cardrush_1342 --n-games 10

  # 配備最強 ExploitBeam を相手に (Ollama 起動 + モデル指定)
  OLLAMA_HOST=http://localhost:11434 ONEPIECE_LLM_MODEL=qwen2.5:7b-instruct \
    .venv/bin/python scripts/ai_vs_llm.py --opponent exploitbeam \
      --deck-llm cardrush_1342 --deck-opp cardrush_1385 --n-games 20

Ollama 未起動なら LLM は Greedy に degrade する。 その場合は出力の
「LLM が実際に選んだ手」 が 0/N になり、 実質 Greedy vs 相手 だと分かる。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.deck import CardRepository, make_deck_from_dict
from engine.harness import run_matchup
from engine.ai import GreedyAI
from engine.goal_directed_ai import GoalDirectedAI
from engine.llm_player_ai import LLMPlayerAI


def load_deck(slug: str, repo: CardRepository):
    p = ROOT / "decks" / f"{slug}.json"
    if not p.exists():
        raise SystemExit(f"deck not found: {p}")
    return make_deck_from_dict(json.loads(p.read_text(encoding="utf-8")), repo)


def load_analysis(slug: str):
    p = ROOT / "decks" / f"{slug}.analysis.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def make_opponent_factory(kind: str, slug: str):
    if kind == "greedy":
        return lambda rng, da=None: GreedyAI(rng=rng, deck_analysis=da)
    if kind == "goaldirected":
        return lambda rng, da=None: GoalDirectedAI(rng=rng, deck_analysis=da)
    if kind in ("exploitbeam", "smart"):
        from engine.smart_opponent_ai import SmartOpponentAI

        return lambda rng, da=None: SmartOpponentAI(
            rng=rng, deck_analysis=da, deck_slug=slug
        )
    raise SystemExit(f"unknown opponent: {kind}")


def main() -> None:
    ap = argparse.ArgumentParser(description="LLM vs 既存AI 強さ測定")
    ap.add_argument(
        "--opponent",
        default="greedy",
        choices=["greedy", "goaldirected", "exploitbeam", "smart"],
        help="LLM の相手にする既存 AI",
    )
    ap.add_argument("--deck", default="cardrush_1342", help="両者同一(ミラー)のとき使う slug")
    ap.add_argument("--deck-llm", default=None, help="LLM 側 deck slug (未指定なら --deck)")
    ap.add_argument("--deck-opp", default=None, help="相手 AI 側 deck slug (未指定なら --deck)")
    ap.add_argument("--n-games", type=int, default=10)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--model", default=None, help="ONEPIECE_LLM_MODEL を上書き")
    args = ap.parse_args()

    deck_llm_slug = args.deck_llm or args.deck
    deck_opp_slug = args.deck_opp or args.deck

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    deck_llm = load_deck(deck_llm_slug, repo)
    deck_opp = load_deck(deck_opp_slug, repo)
    ana_llm = load_analysis(deck_llm_slug)
    ana_opp = load_analysis(deck_opp_slug)

    # LLM factory: 生成した instance を集めて llm_calls/fallbacks を後で集計
    llm_instances: list[LLMPlayerAI] = []

    def llm_factory(rng, da=None):
        ai = LLMPlayerAI(rng=rng, deck_analysis=da, model=args.model)
        llm_instances.append(ai)
        return ai

    opp_factory = make_opponent_factory(args.opponent, deck_opp_slug)

    print(
        f"LLM({deck_llm_slug}, model={args.model or 'env/default'}) "
        f"vs {args.opponent}({deck_opp_slug})  x{args.n_games}戦 ..."
    )
    report = run_matchup(
        deck_llm,
        deck_opp,
        n_games=args.n_games,
        seed=args.seed,
        ai_factory_1=llm_factory,
        ai_factory_2=opp_factory,
        deck1_analysis=ana_llm,
        deck2_analysis=ana_opp,
    )

    calls = sum(a.llm_calls for a in llm_instances)
    fbs = sum(a.llm_fallbacks for a in llm_instances)
    chosen = calls - fbs

    print("=" * 64)
    print(
        f"LLM 勝率: {report.deck1_winrate:.1%}   "
        f"(N={report.n_games}, 平均ターン {report.avg_turns:.1f})"
    )
    if calls:
        print(
            f"LLM が実際に選んだ手: {chosen}/{calls} ({chosen / calls:.0%})   "
            f"fallback(Greedy degrade): {fbs}"
        )
        if chosen == 0:
            print(
                "  ⚠ 全手 fallback = Ollama 未起動の可能性。"
                f" これは実質 Greedy vs {args.opponent} の結果です。"
            )
    else:
        print("  (合法手1つの局面ばかりで LLM 呼び出しが発生せず)")


if __name__ == "__main__":
    main()
