# -*- coding: utf-8 -*-
"""打倒カルガラ: post-opp sim の仮想敵を強化すると control デッキの vs calgara 勝率は上がるか?

ohtsuki 仮説: 探索の仮想敵が greedy なのに実相手は ExploitBeam = ミスマッチが control 敗北の機序。
→ sim 仮想敵を planning / exploitbeam に上げて A/B (challenger 側のみ。 calgara は配備固定)。
上がる → ミスマッチが原因 = self-play/強 opp model に投資する green light。 上がらない → さらに深い。

  .venv/bin/python scripts/validate_strong_sim.py --decks cardrush_1385,cardrush_1392 \
      --sims greedy,planning,exploitbeam --n 20 --seed 42
"""
import argparse
import os
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
    challenger, target, sim, n, seed = task
    # sim 仮想敵は challenger の探索内でのみ効かせたい。 ただし plan_search は env を読むので
    # process 全体に effく。 calgara も同 env を使うが、 calgara は勝っている側 = sim 強化で
    # さらに強くなるだけ (challenger に不利方向) なので、 challenger が改善するなら頑健な信号。
    saved = os.environ.get("ONEPIECE_POSTOPP_AI")
    os.environ["ONEPIECE_POSTOPP_AI"] = sim

    def aif_c(rng, deck_analysis=None):
        return ExploitBeamAI(rng=rng, deck_analysis={**(deck_analysis or {}), "deck_slug": challenger})

    def aif_t(rng, deck_analysis=None):
        return ExploitBeamAI(rng=rng, deck_analysis={**(deck_analysis or {}), "deck_slug": target})

    try:
        rep = run_matchup(
            _decklist(challenger), _decklist(target),
            n_games=n, seed=seed, ai_factory_1=aif_c, ai_factory_2=aif_t,
            deck1_analysis=_ana(challenger), deck2_analysis=_ana(target),
            effects_overlay=_OVERLAY,
        )
    finally:
        if saved is None:
            os.environ.pop("ONEPIECE_POSTOPP_AI", None)
        else:
            os.environ["ONEPIECE_POSTOPP_AI"] = saved
    return (challenger, sim, rep.deck1_wins, rep.deck2_wins, rep.draws)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decks", default="cardrush_1385,cardrush_1392")
    ap.add_argument("--target", default="tcgportal_calgara")
    ap.add_argument("--sims", default="greedy,planning,exploitbeam")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    decks = [d.strip() for d in a.decks.split(",") if d.strip()]
    sims = [s.strip() for s in a.sims.split(",") if s.strip()]
    tasks = [(d, a.target, s, a.n, a.seed) for d in decks for s in sims]
    print(f"strong-sim validate: {decks} vs {a.target} | N={a.n} seed={a.seed} | sims={sims}")
    t0 = time.time()
    with mp.Pool(min(a.workers, len(tasks))) as p:
        res = p.map(_run, tasks, chunksize=1)
    by = {(c, s): (w, l, d) for c, s, w, l, d in res}
    print(f"=== challenger winrate vs {a.target} (N={a.n}) === ({time.time()-t0:.0f}s)")
    hdr = "".join(f"{s:>14}" for s in sims)
    print(f"  {'deck':<16}{hdr}")
    for d in decks:
        cells = []
        for s in sims:
            w, l, dd = by.get((d, s), (0, 0, 0))
            cells.append(f"{w}-{l} {w/max(1,w+l+dd)*100:.0f}%")
        print(f"  {d:<16}" + "".join(f"{c:>14}" for c in cells))


if __name__ == "__main__":
    main()
