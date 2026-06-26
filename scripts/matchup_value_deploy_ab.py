# -*- coding: utf-8 -*-
"""matchup-conditioned value (v5) vs agnostic value (v2) の deploy A/B (per-opp 集計)。

matchup_value_ab.py が column-slice で作った db/_selfplay/{prefix}{v2,v5}.pkl を、
配備忠実 (16/10 + value_defense は deck config 通り) で 多様な opp 集合に対し両 seat 実測。
v2 = agnostic baseline (= matchup feature 無し)、 v5 = matchup-条件付き。 両 arm は data/scale
完全同一で feature の有無だけが差 → 差分 = matchup-conditioning の純粋効果。

per-opp と overall で v2/v5 勝率を出す。 v5 が overall で v2 を上回れば仮説 validated
(= ohtsuki『評価関数を相手攻略情報で可変に』が piloting を改善)。 配備 gating は N>=60/opp 級
([[feedback_ab_statistical_power]])。

  .venv/bin/python scripts/matchup_value_deploy_ab.py --deck cardrush_1342 \
      --opps tcgportal_calgara,tcgportal_bonney,cardrush_1385,cardrush_1453,cardrush_1454 \
      --prefix mcab_1342_ --n 40 --beam-width 16 --max-depth 10 --workers 12
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


def _ana(s):
    p = ROOT / "decks" / f"{s}.analysis.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _mk_factory(slug, gbm, bw, bd):
    def aif(rng, deck_analysis=None):
        return ExploitBeamAI(rng=rng, deck_analysis={**(deck_analysis or {}), "deck_slug": slug},
                             gbm_path=gbm, beam_width=bw, max_depth=bd)
    return aif


def _run(task):
    """(arm, opp) を両 seat 実測。 arm の pkl を deck の leaf value に差す。 opp は配備。"""
    arm, gbm, deck, opp, n, seed, bw, bd = task
    rep1 = run_matchup(
        DeckList.from_json(ROOT / "decks" / f"{deck}.json", _REPO),
        DeckList.from_json(ROOT / "decks" / f"{opp}.json", _REPO),
        n_games=n, seed=seed, ai_factory_1=_mk_factory(deck, gbm, bw, bd),
        ai_factory_2=_mk_factory(opp, None, bw, bd),
        deck1_analysis=_ana(deck), deck2_analysis=_ana(opp), effects_overlay=_OVERLAY,
    )
    rep2 = run_matchup(
        DeckList.from_json(ROOT / "decks" / f"{opp}.json", _REPO),
        DeckList.from_json(ROOT / "decks" / f"{deck}.json", _REPO),
        n_games=n, seed=seed + 1, ai_factory_1=_mk_factory(opp, None, bw, bd),
        ai_factory_2=_mk_factory(deck, gbm, bw, bd),
        deck1_analysis=_ana(opp), deck2_analysis=_ana(deck), effects_overlay=_OVERLAY,
    )
    dw = rep1.deck1_wins + rep2.deck2_wins
    ow = rep1.deck2_wins + rep2.deck1_wins
    dr = rep1.draws + rep2.draws
    return (arm, opp, dw, ow, dr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="cardrush_1342")
    ap.add_argument("--opps", default="tcgportal_calgara,tcgportal_bonney,cardrush_1385,cardrush_1453,cardrush_1454")
    ap.add_argument("--prefix", default=None, help="既定 mcab_<deck>_")
    ap.add_argument("--arms", default="v2,v5",
                    help="comma。 default=配備GBM auto-load / v2,v5=column-slice 産 pkl")
    ap.add_argument("--n", type=int, default=40, help="seat あたり (両 seat で 2x)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--beam-width", type=int, default=16, help="16=配備忠実/8=高速screen")
    ap.add_argument("--max-depth", type=int, default=10)
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    prefix = a.prefix if a.prefix else f"mcab_{a.deck}_"
    opps = [s.strip() for s in a.opps.split(",")]
    arm_names = [x.strip() for x in a.arms.split(",")]
    arms = {}  # arm -> gbm path or None (default = 配備GBM auto-load)
    for arm in arm_names:
        if arm == "default":
            arms[arm] = None
            continue
        p = str(ROOT / "db" / "_selfplay" / f"{prefix}{arm}.pkl")
        if not Path(p).exists():
            print(f"!! missing {p} (run matchup_value_ab.py first)"); return
        arms[arm] = p
    tasks = [(arm, gbm, a.deck, opp, a.n, a.seed, a.beam_width, a.max_depth)
             for opp in opps for arm, gbm in arms.items()]
    print(f"deploy A/B: {a.deck}(beam {a.beam_width}/{a.max_depth}, arms={arm_names}) vs {opps} | "
          f"N={a.n}/seat x2 | tasks={len(tasks)}", flush=True)
    t0 = time.time()
    with mp.Pool(min(a.workers, len(tasks))) as p:
        res = p.map(_run, tasks, chunksize=1)
    # 集計
    by = {}  # (arm,opp) -> (dw,ow,dr)
    for arm, opp, dw, ow, dr in res:
        by[(arm, opp)] = (dw, ow, dr)
    print(f"\n=== {a.deck}: matchup-conditioned value A/B === ({time.time()-t0:.0f}s)")
    hdr = f"{'opp':22}" + "".join(f"{arm+'%':>8}" for arm in arm_names)
    print(hdr)
    tot = {arm: [0, 0, 0] for arm in arm_names}
    for opp in opps:
        cells = []
        for arm in arm_names:
            dw, ow, dr = by[(arm, opp)]
            tot[arm][0] += dw; tot[arm][1] += ow; tot[arm][2] += dr
            cells.append(dw / max(1, dw + ow + dr) * 100)
        print(f"{opp:22}" + "".join(f"{c:8.1f}" for c in cells))
    wr = {}
    for arm in arm_names:
        dw, ow, dr = tot[arm]
        wr[arm] = dw / max(1, dw + ow + dr) * 100
    print(f"{'OVERALL':22}" + "".join(f"{wr[arm]:8.1f}" for arm in arm_names))
    n_per = a.n * 2 * len(opps)
    # 主比較: v5 vs (v2 があれば v2、 無ければ default)
    base = "v2" if "v2" in arm_names else ("default" if "default" in arm_names else arm_names[0])
    if "v5" in arm_names and base != "v5":
        delta = wr["v5"] - wr[base]
        verdict = (f"v5 > {base} = matchup-conditioning 有効"
                   if delta > 2 else
                   f"v5 ≈ {base} = 効果なし ([[feedback_ab_statistical_power]])"
                   if abs(delta) <= 2 else
                   f"v5 < {base} = 有害 (過学習/noise)")
        print(f"\n  overall v5-{base} Δ={delta:+.1f}pt (N={n_per}/arm) → {verdict}")


if __name__ == "__main__":
    main()
