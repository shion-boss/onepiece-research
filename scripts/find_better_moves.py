# -*- coding: utf-8 -*-
"""反実仮想レビュー: self-play の各決定点で「打った手より効果的な手」を検出する
(= 2026-06-18、 ohtsuki さん「ログを見て"こっちの手が効果的では?"に Claude が気付けるように」)。

オラクル = beam+GBM value (= ExploitBeam と同方針):
  1. 決定点 (= 自ターン開始 MAIN) を snapshot。
  2. `enumerate_turn_plans` で候補ターンプランを列挙 (= 到達盤面 dedup、 cap つき)。
  3. 各候補を **post-opp value** で評価 (= 自プラン適用 → 相手 greedy ターンを sim →
     `compute_score`、 ONEPIECE_GBM_VALUE_PATH set 時は学習 GBM)。 これが「効果的さ」の物差し。
  4. 実際に打った手 (= 解析対象 AI のそのターンの行動列) を同じ value で評価。
  5. 最良候補 − 打った手 > threshold なら **flag** (= より効果的な手があった)。

出力 = Δ 降順の flag リスト (= 局面 / 打った手 / より良い手 / value 差)。 Claude がこれを読んで
「本当に効果的か + その戦略的理由」 を最終判断する素材にする。

注意: 検出力は **オラクル(候補列挙+value)の強さが上限**。 解析対象 AI がオラクルと同等以上だと
flag は出にくい。 弱め AI (greedy 等) の log を強オラクルで見ると改善点が多く出る。

usage:
  PYTHONPATH=. .venv/bin/python scripts/find_better_moves.py \
      --deck-a cardrush_1478 --deck-b cardrush_1342 --ai greedy --n-games 3 --threshold 1500
  # 学習 GBM を value に使う:
  ONEPIECE_GBM_VALUE_PATH=db/value_gbm_cardrush_1478.pkl PYTHONPATH=. .venv/bin/python scripts/find_better_moves.py ...
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import random

from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.eval import compute_score
from engine.game import (
    EndPhase, Phase, advance_phase, setup_game, play_until_main,
)
from engine.ai import GreedyAI, play_one_action
from engine.goal_directed_ai import GoalDirectedAI
from engine.exploit_beam_ai import ExploitBeamAI
from engine.plan_search import _simulate_opp_turn
from engine.turn_plan_enumerator import enumerate_turn_plans, fast_clone, _apply_with_defense
from engine.turn_action_enumerator import offense_token


# --------------------------------------------------------------------------- #
def _render_line(actions, state, me_idx) -> str:
    if not actions:
        return "パス"
    toks = []
    for a in actions:
        if isinstance(a, EndPhase):
            continue
        t = offense_token(a, state, me_idx)
        if t[0] == "play":
            toks.append(f"{t[1]}出す")
        elif t[0] == "attack":
            toks.append(f"攻撃[{t[1]}]")
        elif t[0].startswith("don"):
            toks.append(f"{t[0]}{t[1] if len(t) > 1 else ''}")
        else:
            toks.append(str(t))
    return " → ".join(toks) if toks else "パス"


def value_postopp(snapshot, line_actions, me_idx, opp_ai, self_ai) -> float:
    """line を適用 → 相手ターン sim → compute_score(自次ターン開始, me 視点)。
    = ExploitBeam の post-opp value (GBM は env で自動)。"""
    st = fast_clone(snapshot)
    for a in line_actions:
        if isinstance(a, EndPhase):
            continue
        try:
            _apply_with_defense(st, a, opp_ai)
        except Exception:
            break
        if st.game_over:
            break
    # 自ターンを終える → 相手ターンへ
    guard = 0
    while not st.game_over and st.turn_player_idx == me_idx and guard < 25:
        advance_phase(st)
        guard += 1
    if not st.game_over and st.turn_player_idx != me_idx:
        _simulate_opp_turn(st, 1 - me_idx, opp_ai, self_ai)
    try:
        return float(compute_score(st, me_idx))
    except Exception:
        return 0.0


@dataclass
class Flag:
    game: int
    turn: int
    me_idx: int
    played: str
    played_v: float
    better: str
    better_v: float
    delta: float


def analyze_decision(snapshot, played_actions, me_idx, *, topk, opp_ai, self_ai,
                     node_cap, max_depth):
    """この決定点で played より良い候補があれば (played_v, best_line_str, best_v) を返す。"""
    played_v = value_postopp(snapshot, played_actions, me_idx, opp_ai, self_ai)
    plans, _stats = enumerate_turn_plans(snapshot, me_idx, node_cap=node_cap, max_depth=max_depth)
    # 候補は eval_score(pre-opp) 上位 topk を post-opp で精査 (= beam+post-opp re-rank)
    plans.sort(key=lambda p: p.eval_score, reverse=True)
    best_v = played_v
    best_line = None
    for p in plans[:topk]:
        v = value_postopp(snapshot, list(p.concrete_template), me_idx, opp_ai, self_ai)
        if v > best_v:
            best_v = v
            best_line = p.concrete_template
    return played_v, best_line, best_v


def run(deck_a, deck_b, *, analyze_side, ai_kind, n_games, threshold, topk,
        node_cap, max_depth, seed, min_turn, max_turn):
    repo = CardRepository.from_json("db/cards.json")
    overlay = load_effect_overlay("db/card_effects.json")
    da = DeckList.from_json(f"decks/{deck_a}.json", repo)
    db = DeckList.from_json(f"decks/{deck_b}.json", repo)

    def mk_ai(rng, slug):
        if ai_kind == "greedy":
            return GreedyAI(rng=rng)
        if ai_kind == "goal":
            return GoalDirectedAI(rng=rng)
        # exploitbeam = 配備 AI (= deck slug で GBM 自動ロード、 無ければ board_eval)
        return ExploitBeamAI(rng=rng, deck_analysis={"deck_slug": slug})

    flags: list[Flag] = []
    n_decisions = 0
    for g in range(n_games):
        rng = random.Random(seed + g)
        fp = g % 2
        st = setup_game(da, db, rng=rng, first_player=fp, effects_overlay=overlay,
                        do_mulligan_and_finalize=True)
        play_until_main(st)
        # first_player に応じた slug→index 割当 (= setup_game の並び替えに合わせる)
        slug_by_idx = {0: deck_a, 1: deck_b} if fp == 0 else {0: deck_b, 1: deck_a}
        ais = {0: mk_ai(rng, slug_by_idx[0]), 1: mk_ai(rng, slug_by_idx[1])}
        opp_ai = GreedyAI(rng=rng)
        self_ai = GreedyAI(rng=rng)
        guard = 0
        analyzed_this_turn = -1
        while not st.game_over and guard < 4000:
            guard += 1
            me = st.turn_player_idx
            # 解析対象側 (= analyze_side) の自ターン開始で snapshot → 1 ターン記録 → 解析
            is_target = (analyze_side == "a" and me == 0) or \
                        (analyze_side == "b" and me == 1) or (analyze_side == "both")
            if (is_target and st.phase == Phase.MAIN
                    and st.turn_number != analyzed_this_turn
                    and min_turn <= st.turn_number <= max_turn):
                analyzed_this_turn = st.turn_number
                snapshot = fast_clone(st)
                played: list = []
                tno = st.turn_number
                while not st.game_over and st.turn_player_idx == me and st.turn_number == tno:
                    if st.phase == Phase.MAIN:
                        act = play_one_action(st, ais[me], ais[1 - me])
                        if act is not None and not isinstance(act, EndPhase):
                            played.append(act)
                    else:
                        advance_phase(st)
                n_decisions += 1
                played_v, best_line, best_v = analyze_decision(
                    snapshot, played, me, topk=topk, opp_ai=opp_ai, self_ai=self_ai,
                    node_cap=node_cap, max_depth=max_depth)
                if best_line is not None and (best_v - played_v) > threshold:
                    flags.append(Flag(
                        game=g, turn=tno, me_idx=me,
                        played=_render_line(played, snapshot, me), played_v=played_v,
                        better=_render_line(list(best_line), snapshot, me), better_v=best_v,
                        delta=best_v - played_v))
            else:
                if st.phase == Phase.MAIN:
                    play_one_action(st, ais[me], ais[1 - me])
                else:
                    advance_phase(st)

    flags.sort(key=lambda f: f.delta, reverse=True)
    print(f"=== 反実仮想レビュー: {da.name} vs {db.name} | 解析側={analyze_side} "
          f"AI={ai_kind} | {n_games}戦 ===")
    print(f"解析した決定点: {n_decisions} | より効果的な手が在った局面 (Δ>{threshold}): {len(flags)}\n")
    for f in flags:
        print(f"[g{f.game} T{f.turn} P{f.me_idx}] Δ=+{f.delta:.0f}")
        print(f"  打った手 : {f.played}   (value {f.played_v:+.0f})")
        print(f"  より良い : {f.better}   (value {f.better_v:+.0f})")
    return flags


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck-a", default="cardrush_1478")
    ap.add_argument("--deck-b", default="cardrush_1342")
    ap.add_argument("--analyze", default="a", choices=["a", "b", "both"])
    ap.add_argument("--ai", default="greedy", choices=["greedy", "goal", "exploitbeam"],
                    help="解析対象 (= log を生成する) AI。 exploitbeam = 配備AI")
    ap.add_argument("--n-games", type=int, default=3)
    ap.add_argument("--threshold", type=float, default=1500.0)
    ap.add_argument("--topk", type=int, default=12)
    ap.add_argument("--node-cap", type=int, default=8000)
    ap.add_argument("--max-depth", type=int, default=14)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--min-turn", type=int, default=3)
    ap.add_argument("--max-turn", type=int, default=20)
    args = ap.parse_args()
    run(args.deck_a, args.deck_b, analyze_side=args.analyze, ai_kind=args.ai,
        n_games=args.n_games, threshold=args.threshold, topk=args.topk,
        node_cap=args.node_cap, max_depth=args.max_depth, seed=args.seed,
        min_turn=args.min_turn, max_turn=args.max_turn)


if __name__ == "__main__":
    main()
