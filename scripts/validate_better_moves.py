# -*- coding: utf-8 -*-
"""find_better_moves の flag を rollout 実勝率で検証 (= 2026-06-18、 board_eval artefact 切り分け)。

find_better_moves は board_eval(post-opp) で「打った手 A より良い手 B」 を flag するが、 board_eval は
盤面除去/DON を過大評価しがち ([[feedback_don_quality_over_quantity]] / [[feedback_evaluation_axis]])。
そこで各 flag で **A 適用後 / B 適用後 から最後まで greedy 対戦を N 回 playout** し、 解析側の実勝率を比較:
  - winrate(B) > winrate(A) → **本物** (= 探索の穴 = engine の問題個所)
  - winrate(B) <= winrate(A) → **board_eval artefact** (= 問題は eval 側)

continuation = GreedyAI 固定 (= A/B 公平、 高速)。 弱め continuation ゆえ B の優位を過小評価しうる点は注意。

usage: PYTHONPATH=. .venv/bin/python scripts/validate_better_moves.py \
    --deck-a cardrush_1478 --deck-b tcgportal_calgara --n-games 3 --threshold 300 --rollouts 24 --topk 6
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.game import EndPhase, Phase, advance_phase, setup_game, play_until_main
from engine.ai import GreedyAI, play_one_action
from engine.exploit_beam_ai import ExploitBeamAI
from engine.turn_plan_enumerator import fast_clone, _apply_with_defense
from scripts.find_better_moves import analyze_decision, _render_line


def _apply_line(st, actions, opp_ai, me_idx):
    for a in actions:
        if isinstance(a, EndPhase):
            continue
        try:
            _apply_with_defense(st, a, opp_ai)
        except Exception:
            break
        if st.game_over:
            break
    guard = 0
    while not st.game_over and st.turn_player_idx == me_idx and guard < 25:
        advance_phase(st)
        guard += 1


def rollout_winrate(snapshot, actions, me_idx, n, base_seed):
    """line 適用後、 最後まで greedy 対戦を n 回。 解析側 me_idx の勝率を返す。"""
    wins = 0
    draws = 0
    start_turn = snapshot.turn_number
    for i in range(n):
        rng = random.Random(base_seed * 1009 + i)
        st = fast_clone(snapshot)
        st.rng = random.Random(base_seed * 7919 + i)
        opp = GreedyAI(rng=rng)
        _apply_line(st, actions, opp, me_idx)
        ais = {0: GreedyAI(rng=rng), 1: GreedyAI(rng=rng)}
        guard = 0
        while not st.game_over and guard < 800:
            guard += 1
            if st.turn_number > start_turn + 40:  # 時間切れ proxy (floor rule)
                break
            tp = st.turn_player_idx
            if st.phase == Phase.MAIN:
                try:
                    play_one_action(st, ais[tp], ais[1 - tp])
                except Exception:
                    break
            else:
                advance_phase(st)
        w = getattr(st, "winner", -1)
        if st.game_over and w == me_idx:
            wins += 1
        elif not st.game_over or w == -1:
            draws += 1
    return wins / n, draws / n


def collect_flags(deck_a, deck_b, *, n_games, threshold, topk, node_cap, max_depth,
                  seed, min_turn, max_turn):
    repo = CardRepository.from_json("db/cards.json")
    overlay = load_effect_overlay("db/card_effects.json")
    da = DeckList.from_json(f"decks/{deck_a}.json", repo)
    db = DeckList.from_json(f"decks/{deck_b}.json", repo)
    flags = []
    for g in range(n_games):
        rng = random.Random(seed + g)
        fp = g % 2
        st = setup_game(da, db, rng=rng, first_player=fp, effects_overlay=overlay,
                        do_mulligan_and_finalize=True)
        play_until_main(st)
        slug_by_idx = {0: deck_a, 1: deck_b} if fp == 0 else {0: deck_b, 1: deck_a}
        ais = {0: ExploitBeamAI(rng=rng, deck_analysis={"deck_slug": slug_by_idx[0]}),
               1: ExploitBeamAI(rng=rng, deck_analysis={"deck_slug": slug_by_idx[1]})}
        opp_ai = GreedyAI(rng=rng)
        self_ai = GreedyAI(rng=rng)
        guard = 0
        analyzed_turn = -1
        while not st.game_over and guard < 4000:
            guard += 1
            me = st.turn_player_idx
            if (st.phase == Phase.MAIN and st.turn_number != analyzed_turn
                    and min_turn <= st.turn_number <= max_turn):
                analyzed_turn = st.turn_number
                snapshot = fast_clone(st)
                played = []
                tno = st.turn_number
                while not st.game_over and st.turn_player_idx == me and st.turn_number == tno:
                    if st.phase == Phase.MAIN:
                        act = play_one_action(st, ais[me], ais[1 - me])
                        if act is not None and not isinstance(act, EndPhase):
                            played.append(act)
                    else:
                        advance_phase(st)
                played_v, best_line, best_v = analyze_decision(
                    snapshot, played, me, topk=topk, opp_ai=opp_ai, self_ai=self_ai,
                    node_cap=node_cap, max_depth=max_depth)
                if best_line is not None and (best_v - played_v) > threshold:
                    flags.append({
                        "game": g, "turn": tno, "me": me,
                        "snapshot": snapshot, "played": list(played),
                        "better": list(best_line),
                        "played_v": played_v, "best_v": best_v,
                        "eval_delta": best_v - played_v,
                        "slug": slug_by_idx[me]})
            else:
                if st.phase == Phase.MAIN:
                    play_one_action(st, ais[me], ais[1 - me])
                else:
                    advance_phase(st)
    flags.sort(key=lambda f: f["eval_delta"], reverse=True)
    return flags


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck-a", default="cardrush_1478")
    ap.add_argument("--deck-b", default="tcgportal_calgara")
    ap.add_argument("--n-games", type=int, default=3)
    ap.add_argument("--threshold", type=float, default=300.0)
    ap.add_argument("--topk", type=int, default=10)
    ap.add_argument("--node-cap", type=int, default=6000)
    ap.add_argument("--max-depth", type=int, default=14)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--min-turn", type=int, default=3)
    ap.add_argument("--max-turn", type=int, default=14)
    ap.add_argument("--rollouts", type=int, default=24)
    ap.add_argument("--validate-topk", type=int, default=6)
    args = ap.parse_args()

    print("flags 収集中 (ExploitBeam matchup)...")
    flags = collect_flags(args.deck_a, args.deck_b, n_games=args.n_games,
                          threshold=args.threshold, topk=args.topk, node_cap=args.node_cap,
                          max_depth=args.max_depth, seed=args.seed,
                          min_turn=args.min_turn, max_turn=args.max_turn)
    print(f"flag 数: {len(flags)} | rollout 検証する上位: {min(args.validate_topk, len(flags))} "
          f"(各 {args.rollouts} playout/line)\n")

    real, artefact = 0, 0
    for k, f in enumerate(flags[:args.validate_topk]):
        me = f["me"]
        wa, da = rollout_winrate(f["snapshot"], f["played"], me, args.rollouts, base_seed=1000 + k)
        wb, db_ = rollout_winrate(f["snapshot"], f["better"], me, args.rollouts, base_seed=1000 + k)
        verdict = "本物(B>A)" if wb > wa + 0.04 else ("artefact(B<=A)" if wb < wa - 0.04 else "差なし")
        if wb > wa + 0.04:
            real += 1
        elif wb < wa - 0.04:
            artefact += 1
        side = "青黄ナミ" if "1478" in f["slug"] else ("カルガラ" if "calgara" in f["slug"] else f["slug"])
        print(f"[g{f['game']} T{f['turn']} P{me} {side}] eval_Δ=+{f['eval_delta']:.0f} → rollout勝率 "
              f"A={wa:.2f} vs B={wb:.2f}  →  {verdict}")
        print(f"    打った手 : {_render_line(f['played'], f['snapshot'], me)}")
        print(f"    より良い : {_render_line(f['better'], f['snapshot'], me)}")
    print(f"\n=== 判定: 本物(探索の穴)={real} / artefact(eval過大)={artefact} / 差なし="
          f"{min(args.validate_topk, len(flags)) - real - artefact} ===")


if __name__ == "__main__":
    main()
