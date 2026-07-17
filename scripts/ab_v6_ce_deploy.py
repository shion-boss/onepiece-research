# -*- coding: utf-8 -*-
"""v6 counter-event GBM の配備ゲート A/B (= 配備忠実 16/10、 多様な相手、 両seat、 paired)。

HERO(deck) を、 arm_ce (= 再学習した counter-event v6 GBM + counter_event_def=True) と
arm_base (= 現配備 GBM、 flag OFF) の2構成で、 各 OPP に対し 両seat・同seed で戦わせ、
HERO 勝率を per-opp + 集計で比較する。 ce > base かつ 大きな per-opp 退行が無ければ配備可。

  HERO=cardrush_1454 CE_GBM=db/_selfplay/beamloop_cardrush_1454_iter7.pkl \
    BASE_GBM=db/value_gbm_cardrush_1454.pkl \
    OPPS=tcgportal_calgara,tcgportal_bonney,cardrush_1385,cardrush_1453,cardrush_1342 \
    N=24 WORKERS=12 BW=16 BD=10 .venv/bin/python scripts/ab_v6_ce_deploy.py
"""
import sys, os, random, time, json
import multiprocessing as mp
from pathlib import Path
sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI

ROOT = Path(os.getcwd())
REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")
HERO = os.environ["HERO"]
CE_GBM = os.environ["CE_GBM"]
BASE_GBM = os.environ["BASE_GBM"]
OPPS = [s.strip() for s in os.environ["OPPS"].split(",")]
BW = int(os.environ.get("BW", "16"))
BD = int(os.environ.get("BD", "10"))


def _load(slug):
    return make_deck_from_dict(json.loads((ROOT/"decks"/f"{slug}.json").read_text(encoding="utf-8")), REPO)


def _hero_ai(seed, *, ce):
    return ExploitBeamAI(rng=random.Random(seed), beam_width=BW, max_depth=BD,
                         deck_analysis={"deck_slug": HERO},
                         gbm_path=(CE_GBM if ce else BASE_GBM), counter_event_def=ce)


def _opp_ai(opp, seed):
    return ExploitBeamAI(rng=random.Random(seed), beam_width=BW, max_depth=BD,
                         deck_analysis={"deck_slug": opp})


def _play(opp, hero_idx, seed, *, ce):
    decks = [None, None]
    decks[hero_idx] = _load(HERO); decks[1-hero_idx] = _load(opp)
    st = setup_game(decks[0], decks[1], rng=random.Random(seed),
                    first_player=hero_idx, effects_overlay=OVERLAY)
    play_until_main(st)
    ais = [None, None]
    ais[hero_idx] = _hero_ai(seed*5+1, ce=ce)
    ais[1-hero_idx] = _opp_ai(opp, seed*7+3)
    n = 0
    while not st.game_over and st.turn_number < 50 and n < 1500:
        cur = st.turn_player_idx
        try:
            play_one_action(st, ais[cur], ais[1-cur])
        except Exception:
            break
        n += 1
    if not st.game_over:
        return None
    return getattr(st, "winner", -1) == hero_idx


def _task(args):
    opp, hero_idx, seed = args
    return (opp, _play(opp, hero_idx, seed, ce=True), _play(opp, hero_idx, seed, ce=False))


def main():
    n = int(os.environ.get("N", "24")); workers = int(os.environ.get("WORKERS", "12"))
    tasks = []
    for opp in OPPS:
        for hero_idx in (0, 1):          # 両seat
            for i in range(n):
                tasks.append((opp, hero_idx, 6000 + hash((opp, hero_idx, i)) % 100000))
    t0 = time.time()
    with mp.Pool(workers) as p:
        res = p.map(_task, tasks)
    from collections import defaultdict
    ce_w = defaultdict(int); ce_t = defaultdict(int); bs_w = defaultdict(int); bs_t = defaultdict(int)
    for opp, ce, bs in res:
        if ce is not None: ce_w[opp] += int(ce); ce_t[opp] += 1
        if bs is not None: bs_w[opp] += int(bs); bs_t[opp] += 1
    print(f"=== deploy gate: {HERO} (beam {BW}/{BD}, 両seat, N={n}/seat) ({time.time()-t0:.0f}s) ===")
    tce = tbs = twce = twbs = 0
    for opp in OPPS:
        cw = ce_w[opp]/max(1,ce_t[opp])*100; bw = bs_w[opp]/max(1,bs_t[opp])*100
        print(f"  vs {opp:20} ce={cw:5.1f}%  base={bw:5.1f}%  Δ={cw-bw:+5.1f}pt")
        twce += ce_w[opp]; tce += ce_t[opp]; twbs += bs_w[opp]; tbs += bs_t[opp]
    CW = twce/max(1,tce)*100; BW_ = twbs/max(1,tbs)*100
    print(f"  --- 集計: ce={CW:.1f}%  base={BW_:.1f}%  Δ={CW-BW_:+.1f}pt "
          f"→ {'DEPLOY 可 (ce>base)' if CW>BW_ else 'NO-GO (ce<=base)'}")


if __name__ == "__main__":
    main()
