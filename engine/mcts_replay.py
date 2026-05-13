# -*- coding: utf-8 -*-
"""
MCTS リプレイ + 思考ツリー記録 (Phase B.7)
==========================================

1 試合を MCTSAI vs GreedyAI で実行し、 各ターンの MCTS 思考ツリーを保存。
UI で AlphaGo 風のツリービジュアライズに使う。

公開 API:
- play_mcts_game(deck_mcts, deck_opp, seed, n_simulations) -> McctsGameRecord
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from typing import Optional

from .ai import GreedyAI, MCTSAI, play_one_action, serialize_mcts_tree
from .deck import DeckList
from .effects import CardEffectBundle
from .game import play_until_main
from .harness import setup_game


@dataclass
class McctsTurnRecord:
    """1 アクション選択時の MCTS 思考スナップショット。"""

    turn: int                      # ゲームターン
    player_idx: int                # 0 (= MCTS 側) / 1 (= 相手側)
    action_index: int              # 試合全体での通し番号
    chosen_action_label: str       # 人間可読
    root_tree: dict                # serialize_mcts_tree の出力


@dataclass
class McctsGameRecord:
    """1 試合の MCTS 思考記録。"""

    deck_mcts: str
    deck_opp: str
    seed: int
    n_simulations: int
    winner: Optional[int]          # 0 = MCTS、 1 = opp、 None = 引分
    total_turns: int
    total_actions: int
    mcts_turns: list[McctsTurnRecord] = field(default_factory=list)


_MAX_ACTIONS_PER_GAME = 400


def play_mcts_game(
    deck_mcts: DeckList,
    deck_opp: DeckList,
    *,
    effects_overlay: Optional[dict[str, CardEffectBundle]] = None,
    seed: int = 42,
    n_simulations: int = 30,
    mcts_player_idx: int = 0,
    max_tree_depth: int = 2,
    record_only_mcts_player: bool = True,
) -> McctsGameRecord:
    """1 試合を MCTSAI (= mcts_player_idx 側) vs GreedyAI (= 相手側) で実行。

    各 MCTS choose_action 後に root_tree を serialize して記録。

    Args:
        deck_mcts: MCTSAI 側のデッキ
        deck_opp: GreedyAI 側のデッキ
        effects_overlay: load_effect_overlay の戻り値 (任意)
        seed: 乱数 seed
        n_simulations: MCTS の 1 アクションあたり rollout 数
        mcts_player_idx: 0 か 1 (MCTSAI を player_0 とするか player_1 とするか)
        max_tree_depth: ツリー記録の深度
        record_only_mcts_player: True なら MCTSAI 側のターンだけ記録

    Returns:
        McctsGameRecord (= 試合結果 + ターンごとの MCTS ツリー)
    """
    # MCTS が先攻 (mcts_player_idx=0) なら deck_mcts を先に渡す。
    # setup_game は (deck1, deck2) で player_0 / player_1 に割当て。
    if mcts_player_idx == 0:
        d_first, d_second = deck_mcts, deck_opp
    else:
        d_first, d_second = deck_opp, deck_mcts

    state = setup_game(d_first, d_second, effects_overlay=effects_overlay)
    play_until_main(state)  # REFRESH/DRAW/DON フェーズを進める (= 最初の MAIN まで)
    rng = random.Random(seed)

    mcts_ai = MCTSAI(
        rng=random.Random(rng.randint(0, 2**31)),
        n_simulations=n_simulations,
        expose_root_tree=True,
    )
    greedy_ai = GreedyAI(rng=random.Random(rng.randint(0, 2**31)))

    if mcts_player_idx == 0:
        ais = [mcts_ai, greedy_ai]
    else:
        ais = [greedy_ai, mcts_ai]

    record = McctsGameRecord(
        deck_mcts=deck_mcts.name,
        deck_opp=deck_opp.name,
        seed=seed,
        n_simulations=n_simulations,
        winner=None,
        total_turns=0,
        total_actions=0,
    )

    actions_count = 0
    while not state.game_over and actions_count < _MAX_ACTIONS_PER_GAME:
        me = state.turn_player_idx
        opp = 1 - me
        # MCTS 側のターンなら expose、 相手は GreedyAI なので記録不要
        is_mcts_turn = (me == mcts_player_idx)
        # MCTS の前 state を保持 (= action_label 用)
        state_snapshot = copy.deepcopy(state) if is_mcts_turn else None

        try:
            play_one_action(state, ais[me], ais[opp])
        except Exception:
            state.declare_winner(opp, "engine error")
            break

        actions_count += 1
        # MCTS choose_action 後に last_root が set されているはず
        if is_mcts_turn and (not record_only_mcts_player or me == mcts_player_idx):
            if mcts_ai.last_root is not None:
                tree = serialize_mcts_tree(
                    mcts_ai.last_root,
                    mcts_ai.last_chosen_action,
                    state_snapshot,
                    max_depth=max_tree_depth,
                )
                record.mcts_turns.append(McctsTurnRecord(
                    turn=state_snapshot.turn_number if state_snapshot else state.turn_number,
                    player_idx=me,
                    action_index=actions_count,
                    chosen_action_label=tree.get("children", [{}])[0].get("action_label", "(?)") if tree.get("children") else "(no children)",
                    root_tree=tree,
                ))
                # next call の last_root をリセット (= 残骸の混入回避)
                mcts_ai.last_root = None
                mcts_ai.last_chosen_action = None

    record.winner = state.winner
    record.total_turns = state.turn_number
    record.total_actions = actions_count
    return record
