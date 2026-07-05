"""①-1: 多ターン探索を value-guided rollout で A/B(greedy strawman 卒業)。

過去の多ターン(postopp_turns>1)が null だった真因 = 相手/自分の未来ターン sim が greedy strawman。
これを value 誘導(相手=POSTOPP_OPP_VALUE / 自分=POSTOPP_SELF_VALUE=EvalGreedyAI)にして、
「2ラウンド先を まともな相手で覗く」 と iter1(turns=1) を超えるかを測る。 両 seat、 同じ配備 value 使用。

  .venv/bin/python scripts/mt_value_ab.py --deck cardrush_1454 \
      --opps cardrush_1454,tcgportal_calgara,tcgportal_bonney,cardrush_1456 --n 25
"""
from __future__ import annotations
import argparse, os, sys, time
import multiprocessing as mp
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# 自分の未来ターン rollout を value 誘導に(env、 fork で worker に継承)。 turns>1 の時のみ効く。
os.environ["ONEPIECE_POSTOPP_SELF_VALUE"] = "1"
# 多ターン探索の bound(病的爆発対策): 深 N-round rollout を上位 K plan だけに cap。
os.environ.setdefault("ONEPIECE_POSTOPP_TOPK", "4")

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


def _mk(slug, turns, opp_value, bw, bd):
    def aif(rng, deck_analysis=None):
        # turns>1 は rollout を軽く(cap=8)して bound と併せ tractable に
        cap = 8 if turns > 1 else 30
        ai = ExploitBeamAI(rng=rng, deck_analysis={**(deck_analysis or {}), "deck_slug": slug},
                           beam_width=bw, max_depth=bd, postopp_turns=turns, postopp_cap=cap)
        if opp_value:
            ai._postopp_opp_value = True   # 相手ターン sim を value 誘導(strawman 卒業)
        return ai
    return aif


def _run(task):
    """(arm_turns, opp_value, opp) を両 seat。 deck 側が multi-turn、 opp は turns=1 配備。"""
    turns, opp_value, deck, opp, n, seed, bw, bd = task
    r1 = run_matchup(
        DeckList.from_json(ROOT / "decks" / f"{deck}.json", _REPO),
        DeckList.from_json(ROOT / "decks" / f"{opp}.json", _REPO),
        n_games=n, seed=seed, ai_factory_1=_mk(deck, turns, opp_value, bw, bd),
        ai_factory_2=_mk(opp, 1, False, bw, bd),
        deck1_analysis=_ana(deck), deck2_analysis=_ana(opp), effects_overlay=_OVERLAY)
    r2 = run_matchup(
        DeckList.from_json(ROOT / "decks" / f"{opp}.json", _REPO),
        DeckList.from_json(ROOT / "decks" / f"{deck}.json", _REPO),
        n_games=n, seed=seed + 1, ai_factory_1=_mk(opp, 1, False, bw, bd),
        ai_factory_2=_mk(deck, turns, opp_value, bw, bd),
        deck1_analysis=_ana(opp), deck2_analysis=_ana(deck), effects_overlay=_OVERLAY)
    dw = r1.deck1_wins + r2.deck2_wins
    ow = r1.deck2_wins + r2.deck1_wins
    dr = r1.draws + r2.draws
    return (turns, opp, dw, ow, dr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="cardrush_1454")
    ap.add_argument("--opps", default="cardrush_1454,tcgportal_calgara,tcgportal_bonney,cardrush_1456")
    ap.add_argument("--n", type=int, default=25)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--beam-width", type=int, default=16)
    ap.add_argument("--max-depth", type=int, default=10)
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    opps = [s.strip() for s in a.opps.split(",")]
    # arm: (turns, opp_value) = 1=baseline(iter1) / 2v=turns2+value-guided
    arms = [("mt1", 1, False), ("mt2v", 2, True)]
    tasks = [(t, ov, a.deck, opp, a.n, a.seed, a.beam_width, a.max_depth)
             for opp in opps for (_, t, ov) in arms]
    print(f"mt_value A/B: {a.deck} vs {opps} | arms=mt1(baseline)/mt2v(turns2+value-guided) | "
          f"N={a.n}/seat x2 | POSTOPP_SELF_VALUE=1", flush=True)
    t0 = time.time()
    with mp.Pool(min(a.workers, len(tasks))) as p:
        res = p.map(_run, tasks, chunksize=1)
    by = {}
    for turns, opp, dw, ow, dr in res:
        by[(turns, opp)] = (dw, ow, dr)
    print(f"\n=== {a.deck}: multi-turn value-guided A/B === ({time.time()-t0:.0f}s)")
    print(f"{'opp':22}{'mt1%':>8}{'mt2v%':>8}")
    tot = {1: [0, 0, 0], 2: [0, 0, 0]}
    for opp in opps:
        cells = []
        for t in (1, 2):
            dw, ow, dr = by[(t, opp)]
            tot[t][0] += dw; tot[t][1] += ow; tot[t][2] += dr
            cells.append(dw / max(1, dw + ow + dr) * 100)
        print(f"{opp:22}{cells[0]:8.1f}{cells[1]:8.1f}")
    w = {t: tot[t][0] / max(1, sum(tot[t])) * 100 for t in (1, 2)}
    print(f"{'OVERALL':22}{w[1]:8.1f}{w[2]:8.1f}   delta={w[2]-w[1]:+.1f}")


if __name__ == "__main__":
    main()
