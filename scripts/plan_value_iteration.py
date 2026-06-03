#!/usr/bin/env python3
"""層6: PlanLibraryAI の value iteration + A/B (= [[project_superhuman_ai_distillation]])。

PoC (1 デッキ): batch value iteration を **並列** で回す。
  各 round:
    collect: PlanLibraryAI(table snapshot, plan-ε探索) vs GreedyAI を N 並列対戦
             → (cell, multiset_sig, won) を集めて table を一括更新 (= 到達 plan の実勝率)。
    eval:    PlanLibraryAI(table, eps=0) vs GreedyAI を M 並列対戦 → winrate。
  「全列挙 → bonus 最適化 → 真の最善手」 が GreedyAI を上回るかを検証。

collect 相手 = GreedyAI (= mirror でなく): (a) 列挙 AI 1 つで半速、 (b) A/B 目標 (vs Greedy)
を直接最適化 (= best-response)。 train/eval は seed を分けて leakage 回避。

検証鉄則 [[feedback_verify_game_completion_reason]]: play_one_action を try/except、
engine error を握り潰さず error_games として明示カウント。
[[feedback_checkpoint_resume]]: round 毎に table + history を save。

使い方:
  .venv/bin/python -u scripts/plan_value_iteration.py --deck cardrush_1342 \
      --rounds 6 --games 240 --eval-games 160 --workers 12 --plan-eps 0.2
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import random
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main
from engine.ai import GreedyAI, play_one_action
from engine.plan_library import PlanBonusTable, _CELL_AXES_COARSE
from engine.plan_library_ai import PlanLibraryAI

_REPO = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(REPO_ROOT / "db" / "card_effects.json")


def _load(slug: str):
    return make_deck_from_dict(
        json.loads((REPO_ROOT / "decks" / f"{slug}.json").read_text(encoding="utf-8")), _REPO
    )


def play_game(deck_test, deck_opp, ai_test, ai_opp, seed: int,
              max_turns: int = 50, max_actions: int = 2000) -> dict:
    """1 game を手動ループで完走。 ai_test を player index に割り当て。

    Returns: {winner, test_idx, error, turns, state}。
    """
    fp = seed % 2
    state = setup_game(deck_test, deck_opp, rng=random.Random(seed),
                       first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    test_idx = 0 if fp == 0 else 1
    ais = [None, None]
    ais[test_idx] = ai_test
    ais[1 - test_idx] = ai_opp

    error = None
    n_actions = 0
    while not state.game_over and n_actions < max_actions and state.turn_number <= max_turns:
        me = state.turn_player_idx
        try:
            play_one_action(state, ais[me], ais[1 - me])
        except Exception as e:
            error = repr(e)
            break
        n_actions += 1

    winner = getattr(state, "winner", -1) if state.game_over else -1
    return {"winner": winner, "test_idx": test_idx, "error": error,
            "turns": state.turn_number, "state": state}


# ===========================================================================
# 並列 worker (= table snapshot を read-only で使い、 結果だけ返す)
# ===========================================================================

_W: dict = {}


def _winit(slug: str, records: list, temp: float, shrink_k: float,
           node_cap: int, cell_axes: tuple) -> None:
    _W["slug"] = slug
    _W["table"] = PlanBonusTable.from_records(records, temp=temp, shrink_k=shrink_k)
    _W["node_cap"] = node_cap
    _W["cell_axes"] = tuple(cell_axes)


def _wgame(task: tuple) -> dict:
    """task = (seed, plan_eps, record). PlanLibraryAI vs GreedyAI を 1 戦。

    Returns: {seed, won (bool|None), choices (list[(cell,mk)]), error}。
    """
    seed, plan_eps, record = task
    table = _W["table"]
    slug = _W["slug"]
    ai_test = PlanLibraryAI(
        random.Random(seed * 5 + 1), bonus_table=table, node_cap=_W["node_cap"],
        plan_eps=plan_eps, record_choices=record, cell_axes=_W["cell_axes"],
    )
    ai_opp = GreedyAI(random.Random(seed * 5 + 2))
    res = play_game(_load(slug), _load(slug), ai_test, ai_opp, seed)
    if res["error"]:
        return {"seed": seed, "won": None, "choices": [], "error": res["error"]}
    winner = res["winner"]
    if winner < 0:
        won = None  # draw
    else:
        won = (winner == res["test_idx"])
    choices = []
    if record:
        ch = getattr(res["state"], "_plan_choices", {}) or {}
        choices = list(ch.get(res["test_idx"], []))
    return {"seed": seed, "won": won, "choices": choices, "error": None}


def _run_parallel(slug: str, table: PlanBonusTable, seeds: list, plan_eps: float,
                  record: bool, node_cap: int, cell_axes: tuple, workers: int) -> list:
    tasks = [(s, plan_eps, record) for s in seeds]
    records = table.to_records()
    if workers <= 1:
        _winit(slug, records, table.temp, table.shrink_k, node_cap, cell_axes)
        return [_wgame(t) for t in tasks]
    with mp.Pool(workers, initializer=_winit,
                 initargs=(slug, records, table.temp, table.shrink_k, node_cap, cell_axes)) as pool:
        return list(pool.imap_unordered(_wgame, tasks, chunksize=1))


def collect_round(slug, table, n_games, plan_eps, node_cap, cell_axes, workers, base_seed):
    seeds = [base_seed + g for g in range(n_games)]
    out = _run_parallel(slug, table, seeds, plan_eps, True, node_cap, cell_axes, workers)
    errs = draws = updates = 0
    for r in out:
        if r["error"]:
            errs += 1
            continue
        if r["won"] is None:
            draws += 1
            continue
        for (cell, mk) in r["choices"]:
            table.update(cell, mk, r["won"])
            updates += 1
    return {"errors": errs, "draws": draws, "updates": updates}


def eval_ab(slug, table, n_games, node_cap, cell_axes, workers, base_seed):
    seeds = [base_seed + g for g in range(n_games)]
    out = _run_parallel(slug, table, seeds, 0.0, False, node_cap, cell_axes, workers)
    wins = losses = draws = errs = 0
    for r in out:
        if r["error"]:
            errs += 1
        elif r["won"] is None:
            draws += 1
        elif r["won"]:
            wins += 1
        else:
            losses += 1
    total = wins + losses
    return {"wins": wins, "losses": losses, "draws": draws, "errors": errs,
            "winrate": (wins / total) if total else 0.0}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="cardrush_1342")
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--games", type=int, default=240)
    ap.add_argument("--eval-games", type=int, default=160)
    ap.add_argument("--plan-eps", type=float, default=0.2)
    ap.add_argument("--node-cap", type=int, default=800)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--temp", type=float, default=2000.0)
    ap.add_argument("--shrink-k", type=float, default=6.0)
    ap.add_argument("--init-table", type=Path, default=None,
                    help="起点 table (= corpus warm-start)。 --rounds 0 で eval のみ")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "db" / "plan_tables" / "poc.json")
    args = ap.parse_args()

    slug = args.deck
    cell_axes = _CELL_AXES_COARSE
    print(f"=== PlanLibrary value iteration PoC: {slug} ===", flush=True)
    print(f"rounds={args.rounds} games/r={args.games} eval={args.eval_games} "
          f"workers={args.workers} plan_eps={args.plan_eps} node_cap={args.node_cap} "
          f"cell_axes={cell_axes}", flush=True)

    if args.init_table and args.init_table.exists():
        table = PlanBonusTable.load(args.init_table)
        table.temp = args.temp
        table.shrink_k = args.shrink_k
        print(f"[init] loaded warm-start table: {len(table)} plans from {args.init_table}",
              flush=True)
    else:
        table = PlanBonusTable(temp=args.temp, shrink_k=args.shrink_k)

    t0 = time.perf_counter()
    base = eval_ab(slug, table, args.eval_games, args.node_cap, cell_axes, args.workers, 900000)
    _r0lbl = f"warm-start table={len(table)}" if len(table) else "board_eval のみ"
    print(f"\n[R0 / {_r0lbl}] vs Greedy: winrate={base['winrate']:.1%} "
          f"W{base['wins']}-L{base['losses']} D{base['draws']} err{base['errors']} "
          f"({time.perf_counter()-t0:.0f}s)", flush=True)
    history = [{"round": 0, "table_size": 0, **base}]

    for r in range(1, args.rounds + 1):
        tc0 = time.perf_counter()
        cinfo = collect_round(slug, table, args.games, args.plan_eps, args.node_cap,
                              cell_axes, args.workers, base_seed=r * 100000)
        tc = time.perf_counter() - tc0
        te0 = time.perf_counter()
        ev = eval_ab(slug, table, args.eval_games, args.node_cap, cell_axes,
                     args.workers, base_seed=900000 + r * 1000)
        te = time.perf_counter() - te0
        print(f"[R{r}] collect {args.games}g ({tc:.0f}s err{cinfo['errors']} "
              f"draw{cinfo['draws']} upd{cinfo['updates']}) | table={len(table)} | "
              f"A/B winrate={ev['winrate']:.1%} W{ev['wins']}-L{ev['losses']} "
              f"D{ev['draws']} err{ev['errors']} ({te:.0f}s)", flush=True)
        history.append({"round": r, "table_size": len(table), **ev})
        args.out.parent.mkdir(parents=True, exist_ok=True)
        table.save(args.out)
        (args.out.parent / f"{slug}_history.json").write_text(
            json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== サマリ (round → A/B winrate vs Greedy) ===", flush=True)
    for h in history:
        print(f"  R{h['round']:>2}: winrate={h['winrate']:.1%}  table={h['table_size']:>6}  "
              f"(W{h['wins']}-L{h['losses']} D{h['draws']} err{h['errors']})", flush=True)
    tot_err = sum(h["errors"] for h in history)
    if tot_err:
        print(f"\n⚠ engine error 計 {tot_err} 件 = 要調査 ([[feedback_verify_game_completion_reason]])",
              flush=True)
    else:
        print("\n✅ engine error 0 (= 全 game クリーン完走)", flush=True)
    print(f"table saved → {args.out}", flush=True)


if __name__ == "__main__":
    main()
