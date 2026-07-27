# -*- coding: utf-8 -*-
"""相手手札カウンター値 予測器の精度診断 (2026-07-27、 recipe: 計算機の精度を上げる)。

self-play では相手の実手札が判るので、 予測(expected_counter_total、 一様プール仮定)vs 実際(手札の
counter 値合計)を突合してバイアスを測る。 仮説: 賢い相手は counter を温存 → 手札 counter 密度が高い →
一様仮定は過小評価。

  DIAG_SLUG=cardrush_1454 DIAG_N=80 DIAG_WORKERS=12 .venv/bin/python scripts/diag_counter_predictor.py
"""
import sys, os, random, time, json
import multiprocessing as mp
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI
from engine.hand_estimator import expected_counter_total

REPO_ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(REPO_ROOT / "db" / "card_effects.json")
SLUG = os.environ.get("DIAG_SLUG", "cardrush_1454")


def _load():
    return make_deck_from_dict(
        json.loads((REPO_ROOT / "decks" / f"{SLUG}.json").read_text(encoding="utf-8")), _REPO)


def _ebv2(seed):
    return ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10,
                         deck_analysis={"deck_slug": SLUG})


def _one(seed):
    fp = seed % 2
    state = setup_game(_load(), _load(), rng=random.Random(seed),
                       first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    ais = [_ebv2(seed * 5 + 1), _ebv2(seed * 7 + 3)]
    samples = []   # (hand_size, predicted, actual)
    n = 0
    last_turn = -1
    while not state.game_over and state.turn_number < 50 and n < 1500:
        if state.turn_number != last_turn:
            last_turn = state.turn_number
            for pi in (0, 1):
                opp = state.players[pi]
                hs = len(opp.hand)
                if hs == 0:
                    continue
                try:
                    pred = expected_counter_total(state, pi)
                except Exception:
                    continue
                actual = sum(int(getattr(c, "counter", 0) or 0) for c in opp.hand)
                samples.append((hs, pred, actual))
        cur = state.turn_player_idx
        try:
            play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    return samples


def main():
    n = int(os.environ.get("DIAG_N", "80"))
    workers = int(os.environ.get("DIAG_WORKERS", "12"))
    seeds = list(range(11000, 11000 + n))
    t0 = time.time()
    print(f"[diag_counter_pred] {SLUG}  N={n} games", flush=True)
    with mp.Pool(workers) as p:
        res = [s for game in p.map(_one, seeds) for s in game]
    if not res:
        print("  サンプル 0", flush=True)
        return
    tot = len(res)
    mean_pred = sum(p for _, p, _ in res) / tot
    mean_act = sum(a for _, _, a in res) / tot
    print(f"  {tot:,} サンプル ({time.time()-t0:.0f}s)", flush=True)
    print(f"  予測平均 = {mean_pred:.0f}  /  実際平均 = {mean_act:.0f}  →  "
          f"バイアス = {mean_pred-mean_act:+.0f}  ({'過小評価' if mean_pred<mean_act else '過大評価'})", flush=True)
    # 手札枚数別
    byhs = defaultdict(lambda: [0.0, 0.0, 0])
    for hs, pr, ac in res:
        byhs[hs][0] += pr; byhs[hs][1] += ac; byhs[hs][2] += 1
    print("  手札枚数別 (予測 → 実際):", flush=True)
    for hs in sorted(byhs):
        sp, sa, c = byhs[hs]
        if c < 20:
            continue
        print(f"    {hs}枚: 予測{sp/c:5.0f} → 実際{sa/c:5.0f}  (差{(sp-sa)/c:+5.0f}, n={c})", flush=True)


if __name__ == "__main__":
    main()
