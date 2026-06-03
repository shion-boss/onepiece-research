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


def _winit(slug: str, main_records: list, def_records: list, temp: float,
           shrink_k: float, node_cap: int, cell_axes: tuple) -> None:
    _W["slug"] = slug
    _W["table"] = PlanBonusTable.from_records(main_records, temp=temp, shrink_k=shrink_k)
    _W["def_table"] = PlanBonusTable.from_records(def_records, temp=temp, shrink_k=shrink_k)
    _W["node_cap"] = node_cap
    _W["cell_axes"] = tuple(cell_axes)


def _wgame(task: tuple) -> dict:
    """task = (seed, plan_eps, def_eps, rec_main, rec_def)。 PlanLibraryAI vs GreedyAI を 1 戦。"""
    seed, plan_eps, def_eps, rec_main, rec_def = task
    ai_test = PlanLibraryAI(
        random.Random(seed * 5 + 1), bonus_table=_W["table"], def_table=_W["def_table"],
        node_cap=_W["node_cap"], plan_eps=plan_eps, def_eps=def_eps,
        record_choices=rec_main, record_def_choices=rec_def, cell_axes=_W["cell_axes"],
    )
    ai_opp = GreedyAI(random.Random(seed * 5 + 2))
    res = play_game(_load(_W["slug"]), _load(_W["slug"]), ai_test, ai_opp, seed)
    if res["error"]:
        return {"won": None, "choices": [], "def_choices": [], "error": res["error"]}
    winner = res["winner"]
    won = None if winner < 0 else (winner == res["test_idx"])
    ti = res["test_idx"]
    choices = (list((getattr(res["state"], "_plan_choices", {}) or {}).get(ti, []))
               if rec_main else [])
    def_choices = (list((getattr(res["state"], "_defense_choices", {}) or {}).get(ti, []))
                   if rec_def else [])
    return {"won": won, "choices": choices, "def_choices": def_choices, "error": None}


def _run_parallel(slug, table, def_table, seeds, plan_eps, def_eps, rec_main, rec_def,
                  node_cap, cell_axes, workers) -> list:
    tasks = [(s, plan_eps, def_eps, rec_main, rec_def) for s in seeds]
    main_records = table.to_records()
    def_records = def_table.to_records()
    ia = (slug, main_records, def_records, table.temp, table.shrink_k, node_cap, cell_axes)
    if workers <= 1:
        _winit(*ia)
        return [_wgame(t) for t in tasks]
    with mp.Pool(workers, initializer=_winit, initargs=ia) as pool:
        return list(pool.imap_unordered(_wgame, tasks, chunksize=1))


def collect_round(slug, table, def_table, n_games, plan_eps, def_eps, rec_main, rec_def,
                  node_cap, cell_axes, workers, base_seed):
    seeds = [base_seed + g for g in range(n_games)]
    out = _run_parallel(slug, table, def_table, seeds, plan_eps, def_eps, rec_main, rec_def,
                        node_cap, cell_axes, workers)
    errs = draws = upd_main = upd_def = 0
    for r in out:
        if r["error"]:
            errs += 1
            continue
        if r["won"] is None:
            draws += 1
            continue
        for (cell, mk) in r["choices"]:
            table.update(cell, mk, r["won"])
            upd_main += 1
        for (cell, mk) in r["def_choices"]:
            def_table.update(cell, mk, r["won"])
            upd_def += 1
    return {"errors": errs, "draws": draws, "upd_main": upd_main, "upd_def": upd_def}


def eval_ab(slug, table, def_table, n_games, node_cap, cell_axes, workers, base_seed):
    seeds = [base_seed + g for g in range(n_games)]
    out = _run_parallel(slug, table, def_table, seeds, 0.0, 0.0, False, False,
                        node_cap, cell_axes, workers)
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
    ap.add_argument("--def-eps", type=float, default=0.3, help="防御プランレベル探索 (= 収集時)")
    ap.add_argument("--learn", choices=["main", "defense", "both"], default="defense",
                    help="どの table を学習するか (= main は greedy-anchor 固定で defense のみ学習 等)")
    ap.add_argument("--init-table", type=Path, default=None,
                    help="起点 main table (= corpus warm-start)")
    ap.add_argument("--init-def-table", type=Path, default=None, help="起点 defense table")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "db" / "plan_tables" / "poc.json")
    ap.add_argument("--out-def", type=Path, default=None)
    args = ap.parse_args()

    slug = args.deck
    cell_axes = _CELL_AXES_COARSE
    out_def = args.out_def or args.out.with_name(args.out.stem + "_def.json")
    rec_main = args.learn in ("main", "both")
    rec_def = args.learn in ("defense", "both")
    plan_eps = args.plan_eps if rec_main else 0.0
    def_eps = args.def_eps if rec_def else 0.0
    print(f"=== PlanLibrary value iteration: {slug} (learn={args.learn}) ===", flush=True)
    print(f"rounds={args.rounds} games/r={args.games} eval={args.eval_games} "
          f"workers={args.workers} plan_eps={plan_eps} def_eps={def_eps} "
          f"node_cap={args.node_cap}", flush=True)

    def _load_tbl(p):
        if p and Path(p).exists():
            t = PlanBonusTable.load(p)
            t.temp, t.shrink_k = args.temp, args.shrink_k
            return t
        return PlanBonusTable(temp=args.temp, shrink_k=args.shrink_k)

    table = _load_tbl(args.init_table)
    def_table = _load_tbl(args.init_def_table)
    print(f"[init] main table={len(table)} def table={len(def_table)}", flush=True)

    EVAL_SEED = 900000  # 全ラウンド固定 (= 同一盤面集合で比較、 ohtsuki 指摘)
    t0 = time.perf_counter()
    base = eval_ab(slug, table, def_table, args.eval_games, args.node_cap, cell_axes,
                   args.workers, EVAL_SEED)
    print(f"\n[R0 baseline] vs Greedy: winrate={base['winrate']:.1%} "
          f"W{base['wins']}-L{base['losses']} D{base['draws']} err{base['errors']} "
          f"({time.perf_counter()-t0:.0f}s)", flush=True)
    history = [{"round": 0, "main": len(table), "def": len(def_table), **base}]

    for r in range(1, args.rounds + 1):
        tc0 = time.perf_counter()
        cinfo = collect_round(slug, table, def_table, args.games, plan_eps, def_eps,
                              rec_main, rec_def, args.node_cap, cell_axes, args.workers,
                              base_seed=r * 100000)
        tc = time.perf_counter() - tc0
        te0 = time.perf_counter()
        ev = eval_ab(slug, table, def_table, args.eval_games, args.node_cap, cell_axes,
                     args.workers, EVAL_SEED)
        te = time.perf_counter() - te0
        print(f"[R{r}] collect {args.games}g ({tc:.0f}s err{cinfo['errors']} "
              f"upd_main{cinfo['upd_main']} upd_def{cinfo['upd_def']}) | "
              f"main={len(table)} def={len(def_table)} | "
              f"A/B winrate={ev['winrate']:.1%} W{ev['wins']}-L{ev['losses']} "
              f"D{ev['draws']} err{ev['errors']} ({te:.0f}s)", flush=True)
        history.append({"round": r, "main": len(table), "def": len(def_table), **ev})
        args.out.parent.mkdir(parents=True, exist_ok=True)
        table.save(args.out)
        def_table.save(out_def)
        (args.out.parent / f"{slug}_history.json").write_text(
            json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== サマリ (round → A/B winrate vs Greedy、 eval seed 固定) ===", flush=True)
    for h in history:
        print(f"  R{h['round']:>2}: winrate={h['winrate']:.1%}  main={h['main']:>5} "
              f"def={h['def']:>4}  (W{h['wins']}-L{h['losses']} err{h['errors']})", flush=True)
    tot_err = sum(h["errors"] for h in history)
    print(f"\n{'⚠ engine error 計 %d 件' % tot_err if tot_err else '✅ engine error 0'}",
          flush=True)
    print(f"tables saved → {args.out} / {out_def}", flush=True)


if __name__ == "__main__":
    main()
