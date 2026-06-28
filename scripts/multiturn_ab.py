# -*- coding: utf-8 -*-
"""multi-turn lookahead A/B: deck の postopp_turns(=相手N ターン先まで rollout)を変えて勝率測定。

control-vs-aggro の構造ギャップ([[project_leader_aware_matchup_ai]] A)検証: dofla が深い lookahead
で「今受けて次以降に除去で勝つ grind」を計画できれば、 vs aggro が上がるはず。 deck 側のみ
postopp_turns を変え、 opp は配備(turns=1)。 両 seat。

  .venv/bin/python scripts/multiturn_ab.py --deck cardrush_1342 \
      --opps tcgportal_bonney,tcgportal_calgara --turns 1,2,3 --n 40
"""
import argparse, sys, time, multiprocessing as mp
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


def _ana(s):
    p = ROOT / "decks" / f"{s}.analysis.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _mk(slug, turns, bw, bd):
    def aif(rng, deck_analysis=None):
        return ExploitBeamAI(rng=rng, deck_analysis={**(deck_analysis or {}), "deck_slug": slug},
                             beam_width=bw, max_depth=bd, postopp_turns=turns)
    return aif


def _run(task):
    turns, deck, opp, n, seed, bw, bd = task
    # seat1: deck=deck1 (turns=N), opp=deck2 (turns=1 配備忠実)
    r1 = run_matchup(
        DeckList.from_json(ROOT / "decks" / f"{deck}.json", _REPO),
        DeckList.from_json(ROOT / "decks" / f"{opp}.json", _REPO),
        n_games=n, seed=seed, ai_factory_1=_mk(deck, turns, bw, bd), ai_factory_2=_mk(opp, 1, bw, bd),
        deck1_analysis=_ana(deck), deck2_analysis=_ana(opp), effects_overlay=_OVERLAY)
    r2 = run_matchup(
        DeckList.from_json(ROOT / "decks" / f"{opp}.json", _REPO),
        DeckList.from_json(ROOT / "decks" / f"{deck}.json", _REPO),
        n_games=n, seed=seed + 1, ai_factory_1=_mk(opp, 1, bw, bd), ai_factory_2=_mk(deck, turns, bw, bd),
        deck1_analysis=_ana(opp), deck2_analysis=_ana(deck), effects_overlay=_OVERLAY)
    dw = r1.deck1_wins + r2.deck2_wins
    ow = r1.deck2_wins + r2.deck1_wins
    dr = r1.draws + r2.draws
    return (turns, opp, dw, ow, dr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="cardrush_1342")
    ap.add_argument("--opps", default="tcgportal_bonney,tcgportal_calgara")
    ap.add_argument("--turns", default="1,2,3")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=2025)
    ap.add_argument("--beam-width", type=int, default=16)
    ap.add_argument("--max-depth", type=int, default=10)
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    opps = [s.strip() for s in a.opps.split(",")]
    turns = [int(x) for x in a.turns.split(",")]
    tasks = [(t, a.deck, opp, a.n, a.seed, a.beam_width, a.max_depth) for opp in opps for t in turns]
    print(f"multi-turn A/B: {a.deck}(postopp_turns 別) vs {opps} | N={a.n}/seat x2 | tasks={len(tasks)}", flush=True)
    t0 = time.time()
    with mp.Pool(min(a.workers, len(tasks))) as p:
        res = p.map(_run, tasks, chunksize=1)
    by = {}
    for t, opp, dw, ow, dr in res:
        by[(t, opp)] = (dw, ow, dr)
    print(f"\n=== {a.deck} vs aggro 勝率 (postopp_turns 深さ別、 両seat N={a.n}x2) === ({time.time()-t0:.0f}s)")
    hdr = f"{'opp':22}" + "".join(f"{'T'+str(t):>7}" for t in turns)
    print(hdr)
    tot = {t: [0, 0, 0] for t in turns}
    for opp in opps:
        cells = []
        for t in turns:
            dw, ow, dr = by[(t, opp)]
            tot[t][0] += dw; tot[t][1] += ow; tot[t][2] += dr
            cells.append(dw / max(1, dw + ow + dr) * 100)
        print(f"{opp:22}" + "".join(f"{c:7.1f}" for c in cells))
    print(f"{'OVERALL':22}" + "".join(f"{tot[t][0]/max(1,sum(tot[t]))*100:7.1f}" for t in turns))
    base = tot[turns[0]][0] / max(1, sum(tot[turns[0]]))
    for t in turns[1:]:
        d = tot[t][0] / max(1, sum(tot[t])) - base
        print(f"  T{t} vs T{turns[0]}: Δ={d*100:+.1f}pt")


if __name__ == "__main__":
    main()
