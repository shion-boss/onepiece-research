# -*- coding: utf-8 -*-
"""打倒カルガラ: self-play で学習した Enel value を *配備 beam* に差し、 *配備カルガラ* に
勝てるかを A/B (= 自己対戦の成果が実戦に effくか)。

baseline (= Enel 配備 board_eval、 vs カルガラ ~35%) と、 各 self-play iter の学習 GBM を
beam の leaf value に差した時の勝率を比較。 学習 value が beam で baseline を超えれば
= self-play 由来の **deployable な打倒カルガラ改善**。

  .venv/bin/python scripts/test_learned_value_deploy.py --arms default,iter5,iter8,iter11 --n 60
"""
import argparse
import sys
import time
import multiprocessing as mp
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import json
from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.harness import run_matchup
from engine.exploit_beam_ai import ExploitBeamAI

_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")
DECK, OPP = "cardrush_1467", "tcgportal_calgara"


def _ana(s):
    p = ROOT / "decks" / f"{s}.analysis.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _arm_path(arm):
    if arm == "default":
        return None
    return str(ROOT / "db" / "_selfplay" / f"enel_{arm}.pkl")


def _run(task):
    arm, n, seed = task
    gbm = _arm_path(arm)

    def aif_c(rng, deck_analysis=None):
        ai = ExploitBeamAI(rng=rng, deck_analysis={**(deck_analysis or {}), "deck_slug": DECK},
                           gbm_path=gbm)  # gbm=None → 既定(board_eval)、 path → 学習 value
        return ai

    def aif_t(rng, deck_analysis=None):
        return ExploitBeamAI(rng=rng, deck_analysis={**(deck_analysis or {}), "deck_slug": OPP})

    rep = run_matchup(
        DeckList.from_json(ROOT / "decks" / f"{DECK}.json", _REPO),
        DeckList.from_json(ROOT / "decks" / f"{OPP}.json", _REPO),
        n_games=n, seed=seed, ai_factory_1=aif_c, ai_factory_2=aif_t,
        deck1_analysis=_ana(DECK), deck2_analysis=_ana(OPP), effects_overlay=_OVERLAY,
    )
    return (arm, rep.deck1_wins, rep.deck2_wins, rep.draws)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="default,iter5,iter8,iter11")
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    arms = [x.strip() for x in a.arms.split(",")]
    tasks = [(arm, a.n, a.seed) for arm in arms]
    print(f"deployable test: {DECK}(beam, 各 value) vs {OPP}(配備) | N={a.n} seed={a.seed}")
    t0 = time.time()
    with mp.Pool(min(a.workers, len(tasks))) as p:
        res = p.map(_run, tasks, chunksize=1)
    by = {arm: (w, l, d) for arm, w, l, d in res}
    print(f"=== Enel(beam+value) vs 配備カルガラ 勝率 (N={a.n}) === ({time.time()-t0:.0f}s)")
    for arm in arms:
        w, l, d = by.get(arm, (0, 0, 0))
        tag = " ← baseline(~35%)" if arm == "default" else ""
        print(f"  {arm:10} {w}-{l}-{d}  {w/max(1,w+l+d)*100:.0f}%{tag}")


if __name__ == "__main__":
    main()
