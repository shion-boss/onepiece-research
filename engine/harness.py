# -*- coding: utf-8 -*-
"""
AI vs AI 対戦ハーネス
====================

* deck1 / deck2 を N 回対戦させ、勝率と各種統計を返す
* 先攻後攻を均等に振り分け
* 暴走対策に max_actions_per_game を設ける
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field
from typing import Any, Optional

from pathlib import Path

from .deck import DeckList
from .effects import load_effect_overlay
from .game import GameState, setup_game, play_until_main, Phase
from .ai import GreedyAI, RandomAI, play_one_action


@dataclass
class GameResult:
    winner: int                  # 0 / 1 / -1(時間切れ)
    first_player: int
    turns: int
    actions: int
    p0_life_left: int
    p1_life_left: int
    p0_field: int
    p1_field: int
    log: list[str] = field(default_factory=list)   # keep_logs=True で埋まる


@dataclass
class MatchupReport:
    deck1_name: str
    deck2_name: str
    n_games: int
    deck1_wins: int = 0
    deck2_wins: int = 0
    draws: int = 0
    deck1_first_wins: int = 0    # deck1 が先攻で勝った数
    deck1_second_wins: int = 0   # deck1 が後攻で勝った数
    avg_turns: float = 0.0
    median_turns: float = 0.0
    avg_life_left_winner: float = 0.0
    games: list[GameResult] = field(default_factory=list)

    @property
    def deck1_winrate(self) -> float:
        played = self.deck1_wins + self.deck2_wins + self.draws
        return self.deck1_wins / played if played else 0.0

    def summary(self) -> str:
        lines = [
            f"=== Matchup Report ===",
            f"  {self.deck1_name}  vs  {self.deck2_name}",
            f"  対戦数: {self.n_games}",
            f"  {self.deck1_name} 勝率: {self.deck1_winrate:.1%} "
            f"({self.deck1_wins}/{self.n_games})",
            f"  先攻時勝率: {self.deck1_first_wins}/{self.n_games // 2}, "
            f"後攻時勝率: {self.deck1_second_wins}/{self.n_games // 2}",
            f"  draws (時間切れ): {self.draws}",
            f"  平均ターン: {self.avg_turns:.1f}, 中央値: {self.median_turns:.1f}",
            f"  勝者の平均残ライフ: {self.avg_life_left_winner:.2f}",
        ]
        return "\n".join(lines)


_DEFAULT_OVERLAY_PATH = (
    Path(__file__).resolve().parent.parent / "db" / "card_effects.json"
)


def run_matchup(
    deck1: DeckList,
    deck2: DeckList,
    n_games: int = 100,
    seed: int = 0,
    ai_factory_1=GreedyAI,
    ai_factory_2=GreedyAI,
    max_actions_per_game: int = 1500,
    verbose: bool = False,
    effects_overlay: Optional[dict] = None,
    keep_logs: bool = False,
) -> MatchupReport:
    """deck1 vs deck2 を n_games 回対戦させる。先攻後攻は均等。

    effects_overlay を None で渡すと db/card_effects.json を自動ロード。
    keep_logs=True で各 GameResult.log に state.log のコピーを保存 (メモリ消費注意)。
    """

    if effects_overlay is None:
        effects_overlay = load_effect_overlay(_DEFAULT_OVERLAY_PATH)

    report = MatchupReport(
        deck1_name=deck1.name, deck2_name=deck2.name, n_games=n_games
    )

    rng_master = random.Random(seed)

    for g in range(n_games):
        # 先攻後攻を交互に
        first_player = g % 2  # 0 -> deck1 先攻, 1 -> deck2 先攻
        rng = random.Random(rng_master.randrange(2**31))

        if first_player == 0:
            d_first, d_second = deck1, deck2
        else:
            d_first, d_second = deck2, deck1

        state = setup_game(
            d_first, d_second, rng=rng, first_player=0,
            effects_overlay=effects_overlay,
        )
        play_until_main(state)
        ai_first = ai_factory_1(rng) if first_player == 0 else ai_factory_2(rng)
        ai_second = ai_factory_2(rng) if first_player == 0 else ai_factory_1(rng)
        ais = [ai_first, ai_second]

        actions = 0
        while not state.game_over and actions < max_actions_per_game:
            me = state.turn_player_idx
            opp = 1 - me
            try:
                play_one_action(state, ais[me], ais[opp])
            except Exception as e:
                if verbose:
                    print(f"  [game {g}] error: {e}")
                state.declare_winner(opp, f"engine error: {e}")
                break
            actions += 1

        # state.winner は state.players のインデックス(0=先攻)
        # それを deck1/deck2 のどちらが勝ったかに変換
        if state.winner is None:
            report.draws += 1
            winner_for_deck = -1
        else:
            # state.players[0] は first_player 側のデッキ
            if (state.winner == 0 and first_player == 0) or (state.winner == 1 and first_player == 1):
                report.deck1_wins += 1
                winner_for_deck = 0
                if first_player == 0:
                    report.deck1_first_wins += 1
                else:
                    report.deck1_second_wins += 1
            else:
                report.deck2_wins += 1
                winner_for_deck = 1

        result = GameResult(
            winner=winner_for_deck,
            first_player=first_player,
            turns=state.turn_number,
            actions=actions,
            p0_life_left=len(state.players[0].life),
            p1_life_left=len(state.players[1].life),
            p0_field=len(state.players[0].characters),
            p1_field=len(state.players[1].characters),
            log=list(state.log) if keep_logs else [],
        )
        report.games.append(result)

        if verbose and (g + 1) % max(1, n_games // 10) == 0:
            print(f"  [{g+1}/{n_games}] {report.deck1_name} {report.deck1_wins}-{report.deck2_wins} {report.deck2_name}")

    if report.games:
        turns = [g.turns for g in report.games]
        report.avg_turns = statistics.mean(turns)
        report.median_turns = statistics.median(turns)
        winners_life = []
        for g in report.games:
            if g.winner == 0:
                winners_life.append(g.p0_life_left if g.first_player == 0 else g.p1_life_left)
            elif g.winner == 1:
                winners_life.append(g.p1_life_left if g.first_player == 0 else g.p0_life_left)
        if winners_life:
            report.avg_life_left_winner = statistics.mean(winners_life)

    return report
