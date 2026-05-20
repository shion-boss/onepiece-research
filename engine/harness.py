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
from .ai import GreedyAI, PlanningAI, RandomAI, play_one_action


def _default_ai_factory(rng, deck_analysis=None):
    """harness の new default AI (= 2026-05-20): GoalDirectedAI(v1 spec + adaptive=True)。

    過去 default の PlanningAI と 比較 で +6pt 改善 確証済 (= wave 1+2+3+4_r1、 14 deck × 60g)。
    deck_slug は deck_analysis から auto-detect (= goal_directed_ai._resolve_target_spec)。

    lazy import で module load 時 の torch import 回避 (= Vercel function memory 制限対策)。
    """
    from .goal_directed_ai import GoalDirectedAI
    return GoalDirectedAI(rng=rng, deck_analysis=deck_analysis, adaptive=True, spec_version="v1")


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
    snapshots: list[dict] = field(default_factory=list)  # record_snapshots=True で埋まる
    rule_violations: list[str] = field(default_factory=list)  # referee 違反ログ
    action_evals: list[dict] = field(default_factory=list)  # R64+ AI 行動品質評価


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


def _try_load_deck_analysis(deck: DeckList) -> Optional[dict]:
    """deck.slug があれば decks/<slug>.analysis.json をロード。
    2026-05-17: slug を analysis dict に注入 (= AI が nn_per_deck preference を引ける)。"""
    if not getattr(deck, "slug", None):
        return None
    path = Path("decks") / f"{deck.slug}.analysis.json"
    if not path.exists():
        path = Path(__file__).resolve().parent.parent / "decks" / f"{deck.slug}.analysis.json"
    if not path.exists():
        # analysis 不在でも slug だけは渡す (= adaptive NN 判定で使う)
        return {"deck_slug": deck.slug}
    try:
        import json
        d = json.loads(path.read_text(encoding="utf-8"))
        d["deck_slug"] = deck.slug  # 注入
        return d
    except Exception:
        return {"deck_slug": deck.slug}


def _construct_ai(factory, rng, deck_analysis):
    """AI factory が deck_analysis を受け取れるか試す。
    GreedyAI/EvalGreedyAI 等は kwarg 対応、 古い factory は無視。"""
    try:
        return factory(rng, deck_analysis=deck_analysis)
    except TypeError:
        return factory(rng)


def run_matchup(
    deck1: DeckList,
    deck2: DeckList,
    n_games: int = 100,
    seed: int = 0,
    ai_factory_1=_default_ai_factory,
    ai_factory_2=_default_ai_factory,
    max_actions_per_game: int = 1500,
    verbose: bool = False,
    effects_overlay: Optional[dict] = None,
    keep_logs: bool = False,
    record_snapshots: bool = False,
    only_game_index: Optional[int] = None,
    enforce_rules: bool = True,
    referee_strict: bool = False,
    deck1_analysis: Optional[dict] = None,
    deck2_analysis: Optional[dict] = None,
    record_replays: bool = False,
    replays_db_path: Optional[Path] = None,
) -> MatchupReport:
    """deck1 vs deck2 を n_games 回対戦させる。先攻後攻は均等。

    effects_overlay を None で渡すと db/card_effects.json を自動ロード。
    keep_logs=True で各 GameResult.log に state.log のコピーを保存 (メモリ消費注意)。
    record_snapshots=True で各 GameResult.snapshots に push_log 毎の盤面 dict を保存 (リプレイ用)。
    only_game_index が指定された場合、その index のゲームだけ実行 (他はスキップ、rng は同期)。
    enforce_rules=True (既定) で各アクション前後にルール違反をチェック (RuleReferee)。
    referee_strict=True で違反検出時に対戦を即停止 (= テスト用)。既定の False では
    違反をログに記録するだけで対戦は継続。
    record_replays=True で各試合を db/match_replays.sqlite に永続化 (= 学習データ蓄積)。
    keep_logs/record_snapshots は自動的に True 扱い。 replays_db_path を指定すれば
    別 sqlite ファイルに保存 (= テスト用)。
    """

    if effects_overlay is None:
        effects_overlay = load_effect_overlay(_DEFAULT_OVERLAY_PATH)

    if record_replays:
        # 学習用に詳細データを強制保存
        keep_logs = True
        record_snapshots = True

    # 引数で analysis 未指定なら decks/<slug>.analysis.json から自動ロード
    if deck1_analysis is None:
        deck1_analysis = _try_load_deck_analysis(deck1)
    if deck2_analysis is None:
        deck2_analysis = _try_load_deck_analysis(deck2)

    report = MatchupReport(
        deck1_name=deck1.name, deck2_name=deck2.name, n_games=n_games
    )

    rng_master = random.Random(seed)

    for g in range(n_games):
        # 先攻後攻を交互に
        first_player = g % 2  # 0 -> deck1 先攻, 1 -> deck2 先攻
        rng = random.Random(rng_master.randrange(2**31))

        # only_game_index 指定時は他のゲームはスキップ (rng_master は進めて互換維持)
        if only_game_index is not None and g != only_game_index:
            report.games.append(GameResult(
                winner=-1, first_player=first_player, turns=0, actions=0,
                p0_life_left=0, p1_life_left=0, p0_field=0, p1_field=0,
            ))
            continue

        if first_player == 0:
            d_first, d_second = deck1, deck2
            ana_first, ana_second = deck1_analysis, deck2_analysis
        else:
            d_first, d_second = deck2, deck1
            ana_first, ana_second = deck2_analysis, deck1_analysis

        state = setup_game(
            d_first, d_second, rng=rng, first_player=0,
            effects_overlay=effects_overlay,
            deck1_analysis=ana_first, deck2_analysis=ana_second,
        )
        if record_snapshots:
            state.record_snapshots = True
            # setup 中の "start:" ログ分の snapshot を補完
            if state.log:
                state.snapshots.append(state._build_snapshot(state.log[-1]))
        play_until_main(state)
        # first_player == 0 なら deck1 が先攻 (= AI1, analysis1)、 1 なら逆
        if first_player == 0:
            ai_first = _construct_ai(ai_factory_1, rng, deck1_analysis)
            ai_second = _construct_ai(ai_factory_2, rng, deck2_analysis)
        else:
            ai_first = _construct_ai(ai_factory_2, rng, deck2_analysis)
            ai_second = _construct_ai(ai_factory_1, rng, deck1_analysis)
        ais = [ai_first, ai_second]
        # PlanningAI 等が plan_search 内で choose_defense sim を呼ぶための ai_opp 注入
        for i, ai in enumerate(ais):
            if hasattr(ai, "set_ai_opp"):
                ai.set_ai_opp(ais[1 - i])

        # ルール違反監視 referee (オプション)
        referee = None
        if enforce_rules:
            from .referee import RuleReferee
            referee = RuleReferee(
                strict=referee_strict,
                log_fn=(print if verbose else None),
            )

        actions = 0
        while not state.game_over and actions < max_actions_per_game:
            me = state.turn_player_idx
            opp = 1 - me
            try:
                play_one_action(state, ais[me], ais[opp], referee=referee)
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
            snapshots=list(state.snapshots) if record_snapshots else [],
            rule_violations=(list(referee.violations) if referee else []),
            action_evals=list(state.action_evals),
        )
        report.games.append(result)

        if record_replays:
            from .replay_recorder import save_replay
            try:
                save_replay(
                    deck_a=getattr(deck1, "slug", None) or deck1.name,
                    deck_b=getattr(deck2, "slug", None) or deck2.name,
                    game_idx=g,
                    winner_for_deck_a=winner_for_deck,
                    first_player=first_player,
                    turns=state.turn_number,
                    log=result.log,
                    snapshots=result.snapshots,
                    seed=seed,
                    extra_meta={"actions": actions, "rule_violations": result.rule_violations},
                    db_path=replays_db_path,
                )
            except Exception as e:
                if verbose:
                    print(f"  [game {g}] replay save failed: {e}")

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
        # ルール違反サマリ (verbose のときに出力)
        total_violations = sum(len(g.rule_violations) for g in report.games)
        if verbose and total_violations > 0:
            print(f"  ⚠ ルール違反検出: {total_violations} 件 (全{len(report.games)}試合)")
            for i, g in enumerate(report.games):
                for v in g.rule_violations[:3]:
                    print(f"    game {i}: {v}")

    return report
