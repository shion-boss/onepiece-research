# -*- coding: utf-8 -*-
"""LLMPlayerAI のスモークテスト。

確認すること:
  1) LLM に渡す prompt が カード名・効果込みで生成される (= Ollama 不要)
  2) Ollama 未起動でも choose_action が Greedy に degrade して Action を返す
  3) run_matchup で LLMPlayerAI vs GreedyAI が 1 試合完走する

Ollama を起動して env ONEPIECE_LLM_MODEL を指定すれば 実 LLM で動く。
  OLLAMA_HOST=http://localhost:11434 ONEPIECE_LLM_MODEL=qwen2.5:7b-instruct \
    .venv/bin/python scripts/llm_play_smoke.py
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.deck import CardRepository
from engine.deckbuilder import auto_build_deck
from engine.game import legal_actions, play_until_main, setup_game
from engine.harness import run_matchup
from engine.ai import GreedyAI
from engine.llm_player_ai import LLMPlayerAI


def main() -> None:
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    deck1 = auto_build_deck("OP01-001", repo, rng=random.Random(1), name="赤ゾロ")
    deck2 = auto_build_deck("OP02-001", repo, rng=random.Random(2), name="白ひげ")

    # --- 1) prompt の実物を 1 つ表示 (Ollama 不要) -----------------------
    print("=" * 72)
    print("[1] 生成 prompt のサンプル (= LLM が見る盤面 + 番号付き合法手)")
    print("=" * 72)
    rng = random.Random(7)
    state = setup_game(deck1, deck2, rng=rng, first_player=0)
    play_until_main(state)
    actions = legal_actions(state)
    # 合法手が複数ある手番までは setup 直後で十分 (= main 到達済)
    llm = LLMPlayerAI(rng=random.Random(7))
    print(llm._render_action_prompt(state, actions))

    # --- 2) Ollama 無しでの fallback (= Greedy degrade) ------------------
    print("\n" + "=" * 72)
    print("[2] choose_action を 1 回 (Ollama 未起動なら Greedy に degrade)")
    print("=" * 72)
    act = llm.choose_action(state)
    print(f"  選ばれた Action: {type(act).__name__}")
    print(f"  llm_calls={llm.llm_calls}  llm_fallbacks={llm.llm_fallbacks}")
    if llm.llm_fallbacks:
        print("  -> Ollama 未起動を検知し Greedy に degrade しました (= 期待通り)")
    else:
        print("  -> LLM が応答しました (= Ollama 起動中)")

    # --- 3) 1 試合完走 (LLMPlayerAI = player1, Greedy = player2) ---------
    print("\n" + "=" * 72)
    print("[3] run_matchup で 1 試合完走チェック")
    print("=" * 72)

    def llm_factory(rng, deck_analysis=None):
        return LLMPlayerAI(rng=rng, deck_analysis=deck_analysis)

    def greedy_factory(rng, deck_analysis=None):
        return GreedyAI(rng=rng, deck_analysis=deck_analysis)

    report = run_matchup(
        deck1,
        deck2,
        n_games=1,
        seed=7,
        ai_factory_1=llm_factory,
        ai_factory_2=greedy_factory,
    )
    print(f"  完走: {report.n_games} 試合")
    print(f"  deck1(LLM) 勝率: {report.deck1_winrate:.0%}  "
          f"平均ターン: {report.avg_turns:.1f}")
    print("\nOK: 配線は健全。 Ollama を起動すれば実 LLM で打ちます。")


if __name__ == "__main__":
    main()
