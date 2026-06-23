# -*- coding: utf-8 -*-
"""control デッキ vs calgara の **value source** screening (打倒カルガラ campaign)。

仮説 ([[reference_calgara_counter_strategy]] / [[project_value_defense_per_deck_config]]):
control デッキ (クロコ 1385 / イム 1392) の per-deck GBM は AI 自身の下手な control
self-play で学習されており「下手を強化する循環」 に陥っている。 value source を
board_eval / 汎化 (agnostic v4) GBM に差し替えると piloting が改善する可能性。

各 challenger を target (= calgara) に N 戦、 challenger 側の value source を 3 arm で振る:
  - perdeck : per-deck GBM (= 現配備、 baseline)
  - board   : board_eval (= GBM 無効、 hand-tuned linear)
  - agnostic: 汎化 v4 GBM (= 多デッキ + archetype 特徴)
target (calgara) 側は常に配備構成 (= per-deck GBM + 配備 config) で固定。

  .venv/bin/python scripts/screen_control_value_source.py \
      --decks cardrush_1385,cardrush_1392 --target tcgportal_calgara --n 30 --seed 42
"""
import argparse
import os
import sys
import time
import multiprocessing as mp
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.harness import run_matchup
from engine.exploit_beam_ai import ExploitBeamAI

_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")
_AGNOSTIC = str(ROOT / "db" / "value_gbm_agnostic.pkl")


def _decklist(slug):
    return DeckList.from_json(ROOT / "decks" / f"{slug}.json", _REPO)


def _ana(slug):
    import json
    p = ROOT / "decks" / f"{slug}.analysis.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _run(task):
    challenger, target, arm, n, seed = task

    def aif_c(rng, deck_analysis=None):
        ai = ExploitBeamAI(rng=rng, deck_analysis={**(deck_analysis or {}), "deck_slug": challenger})
        if arm == "board":
            ai._gbm_path = ""          # falsy → choose_action が env を立てず board_eval
        elif arm == "agnostic":
            ai._gbm_path = _AGNOSTIC   # 汎化 v4 を強制 (recovery gate を bypass)
        # "perdeck": 既定のまま (= per-deck pkl 解決)
        return ai

    def aif_t(rng, deck_analysis=None):
        return ExploitBeamAI(rng=rng, deck_analysis={**(deck_analysis or {}), "deck_slug": target})

    rep = run_matchup(
        _decklist(challenger), _decklist(target),
        n_games=n, seed=seed, ai_factory_1=aif_c, ai_factory_2=aif_t,
        deck1_analysis=_ana(challenger), deck2_analysis=_ana(target),
        effects_overlay=_OVERLAY,
    )
    return (challenger, arm, rep.deck1_wins, rep.deck2_wins, rep.draws)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decks", default="cardrush_1385,cardrush_1392")
    ap.add_argument("--target", default="tcgportal_calgara")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()

    decks = [d.strip() for d in a.decks.split(",") if d.strip()]
    arms = ["perdeck", "board", "agnostic"]
    tasks = [(d, a.target, arm, a.n, a.seed) for d in decks for arm in arms]
    print(f"screen value source: decks={decks} vs {a.target} | N={a.n} seed={a.seed} "
          f"| arms={arms}")
    t0 = time.time()
    with mp.Pool(min(a.workers, len(tasks))) as p:
        res = p.map(_run, tasks, chunksize=1)
    by = {(c, arm): (w, l, d) for c, arm, w, l, d in res}
    print(f"=== challenger winrate vs {a.target} (N={a.n}) ===  ({time.time()-t0:.0f}s)")
    print(f"  {'deck':<18}{'perdeck':>12}{'board':>12}{'agnostic':>12}")
    for d in decks:
        cells = []
        for arm in arms:
            w, l, dd = by.get((d, arm), (0, 0, 0))
            wr = w / max(1, w + l + dd) * 100
            cells.append(f"{w}-{l} {wr:.0f}%")
        print(f"  {d:<18}{cells[0]:>12}{cells[1]:>12}{cells[2]:>12}")


if __name__ == "__main__":
    main()
