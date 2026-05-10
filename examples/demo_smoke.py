# -*- coding: utf-8 -*-
"""
スモークテスト: ルールエンジンが 1 ゲーム最後まで回ることを確認する
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.deck import CardRepository
from engine.deckbuilder import auto_build_deck
from engine.game import Phase, setup_game, play_until_main, advance_phase
from engine.ai import GreedyAI, play_one_action


def main():
    print("[1] カードリポジトリ読み込み ...")
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    print(f"    -> {len(repo._by_id)} 件")

    rng = random.Random(42)
    print("\n[2] 自動デッキ構築 ...")
    deck1 = auto_build_deck("OP01-001", repo, rng=random.Random(1), name="赤ゾロ")
    deck2 = auto_build_deck("OP02-001", repo, rng=random.Random(2), name="赤白ひげ")
    print(f"    deck1: {deck1.name} = {len(deck1.main)} 枚")
    print(f"    deck2: {deck2.name} = {len(deck2.main)} 枚")
    p1 = deck1.validate()
    p2 = deck2.validate()
    print(f"    deck1 違反: {p1}")
    print(f"    deck2 違反: {p2}")

    print("\n[3] ゲームセットアップ ...")
    state = setup_game(deck1, deck2, rng=rng, first_player=0)
    play_until_main(state)

    ai0, ai1 = GreedyAI(rng), GreedyAI(rng)
    ais = [ai0, ai1]

    print("\n[4] ゲーム実行 ...")
    max_actions = 1000
    actions_count = 0
    while not state.game_over and actions_count < max_actions:
        me = state.turn_player_idx
        opp = 1 - me
        play_one_action(state, ais[me], ais[opp])
        actions_count += 1

    print(f"\n[5] 結果")
    print(f"    勝者: P{state.winner}")
    print(f"    総ターン: {state.turn_number}")
    print(f"    総アクション: {actions_count}")
    print(f"    P0 ライフ残: {len(state.players[0].life)} / 場キャラ: {len(state.players[0].characters)}")
    print(f"    P1 ライフ残: {len(state.players[1].life)} / 場キャラ: {len(state.players[1].characters)}")

    print("\n[6] ログ末尾 30 行")
    for line in state.log[-30:]:
        print(f"  {line}")


if __name__ == "__main__":
    main()
