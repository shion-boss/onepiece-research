# -*- coding: utf-8 -*-
"""counter-event を my_counter に算入して再学習した GBM の A/B (clean isolation)。

A(test) = counter-event-aware GBM (COUNTER_EVENT_DEF=1 で学習) + counter_event_def=True。
B       = 同条件で counter-event 無しに学習した baseline GBM。
両者 同 features(v2 21dim)・同 collection・同 deck。 違いは counter-event を my_counter に
入れて学習したか否かだけ = counter-event value の純効果を測る。 mirror + a_idx/fp 均等化。

  AB_SLUG=cardrush_1454 CE_GBM=db/value_gbm_cardrush_1454_ce.pkl \
    BASE_GBM=db/value_gbm_cardrush_1454_base.pkl N=160 WORKERS=12 \
    .venv/bin/python scripts/ab_ce_retrain.py
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
SLUG = os.environ["AB_SLUG"]
CE_GBM = os.environ["CE_GBM"]
BASE_GBM = os.environ["BASE_GBM"]


def _load():
    return make_deck_from_dict(json.loads((ROOT/"decks"/f"{SLUG}.json").read_text(encoding="utf-8")), REPO)


def _ai(seed, *, ce):
    return ExploitBeamAI(
        rng=random.Random(seed), beam_width=16, max_depth=10,
        deck_analysis={"deck_slug": SLUG},
        gbm_path=(CE_GBM if ce else BASE_GBM),
        counter_event_def=ce,
    )


def _one(seed):
    a_idx = seed % 2
    fp = (seed // 2) % 2
    st = setup_game(_load(), _load(), rng=random.Random(seed), first_player=fp, effects_overlay=OVERLAY)
    play_until_main(st)
    ais = [None, None]
    ais[a_idx] = _ai(seed*5+1, ce=True)       # A = counter-event-aware
    ais[1-a_idx] = _ai(seed*7+3, ce=False)    # B = baseline
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
    w = getattr(st, "winner", -1)
    return "A" if w == a_idx else ("B" if w == 1-a_idx else None)


def main():
    n = int(os.environ.get("N", "160")); workers = int(os.environ.get("WORKERS", "12"))
    t0 = time.time()
    with mp.Pool(workers) as p:
        res = p.map(_one, list(range(5000, 5000+n)))
    a = res.count("A"); b = res.count("B")
    print(f"{SLUG}  A(counter-event GBM) {a} - {b} B(baseline GBM)  "
          f"A_wr={a/max(1,a+b)*100:.1f}%  ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
