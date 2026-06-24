# -*- coding: utf-8 -*-
"""打倒カルガラ: 「もっと攻める/proactive」 戦略軸を直接テスト (ohtsuki 提案)。

これまでのレバーは判断の質 (value/予測/無駄手)。 これは戦略 (= 何を優先するか) の軸。
challenger 側の _offense_force_attack を ON (= beam より「とりあえず攻撃/boost」 を優先、
旧挙動) に戻し、 序盤から殴らせると vs calgara の race が改善するかを測る。 calgara 固定。

  .venv/bin/python scripts/test_early_aggression.py --decks cardrush_1385,cardrush_1392 --n 50
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


def _decklist(slug):
    return DeckList.from_json(ROOT / "decks" / f"{slug}.json", _REPO)


def _ana(slug):
    p = ROOT / "decks" / f"{slug}.analysis.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _run(task):
    challenger, target, force_atk, n, seed = task

    def aif_c(rng, deck_analysis=None):
        ai = ExploitBeamAI(rng=rng, deck_analysis={**(deck_analysis or {}), "deck_slug": challenger})
        if force_atk:
            ai._offense_force_attack = True
        return ai

    def aif_t(rng, deck_analysis=None):
        return ExploitBeamAI(rng=rng, deck_analysis={**(deck_analysis or {}), "deck_slug": target})

    rep = run_matchup(
        _decklist(challenger), _decklist(target),
        n_games=n, seed=seed, ai_factory_1=aif_c, ai_factory_2=aif_t,
        deck1_analysis=_ana(challenger), deck2_analysis=_ana(target),
        effects_overlay=_OVERLAY,
    )
    return (challenger, force_atk, rep.deck1_wins, rep.deck2_wins, rep.draws)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decks", default="cardrush_1385,cardrush_1392")
    ap.add_argument("--target", default="tcgportal_calgara")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    decks = [d.strip() for d in a.decks.split(",") if d.strip()]
    tasks = [(d, a.target, fa, a.n, a.seed) for d in decks for fa in (False, True)]
    print(f"early-aggression test: {decks} vs {a.target} | N={a.n} seed={a.seed}")
    t0 = time.time()
    with mp.Pool(min(a.workers, len(tasks))) as p:
        res = p.map(_run, tasks, chunksize=1)
    by = {(c, fa): (w, l, d) for c, fa, w, l, d in res}
    print(f"=== challenger winrate vs {a.target} (N={a.n}) === ({time.time()-t0:.0f}s)")
    print(f"  {'deck':<16}{'force_atk=OFF(配備)':>20}{'force_atk=ON(攻め)':>20}")
    for d in decks:
        cells = []
        for fa in (False, True):
            w, l, dd = by.get((d, fa), (0, 0, 0))
            cells.append(f"{w}-{l} {w/max(1,w+l+dd)*100:.0f}%")
        print(f"  {d:<16}{cells[0]:>20}{cells[1]:>20}")


if __name__ == "__main__":
    main()
