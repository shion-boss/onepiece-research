# -*- coding: utf-8 -*-
"""エネル vs カルガラ の負けが「デッキ相性」か「操縦(over-pilot)」かを切り分ける診断(2026-07-08)。

両者の操縦 AI 強度を EB(配備 ExploitBeam)/ greedy(GreedyAI)で振って matchup を測る。 P0/P1 均等化。
- EB vs EB      = 配備(既知 ~24%)
- EB vs greedy  = カルガラを弱く。 エネル勝率↑↑ なら カルガラの勝ちは強操縦由来
- greedy vs greedy = デッキ相性そのもの(操縦を両者最弱で揃える)
- greedy vs EB  = エネルを弱く

  AB_N=120 AB_WORKERS=8 .venv/bin/python scripts/diag_pilot_strength.py
"""
import sys, os, random, time
import multiprocessing as mp
from pathlib import Path
sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main
from engine.ai import play_one_action, GreedyAI
from engine.exploit_beam_ai import ExploitBeamAI

ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")
HERO = "cardrush_1454"   # エネル
OPP = "tcgportal_calgara"
TURN_CAP = int(os.environ.get("AB_TURN_CAP", "40"))


def _deck(s):
    import json
    return make_deck_from_dict(json.loads((ROOT / "decks" / f"{s}.json").read_text(encoding="utf-8")), _REPO)


def _mk(slug, seed, strong):
    if strong:
        return ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10, deck_analysis={"deck_slug": slug})
    return GreedyAI(rng=random.Random(seed))


def _play(seed, hero_strong, opp_strong):
    hero_p0 = (seed % 2 == 0)
    if hero_p0:
        st = setup_game(_deck(HERO), _deck(OPP), rng=random.Random(seed), first_player=0, effects_overlay=_OVERLAY)
        ais = [_mk(HERO, seed * 3 + 1, hero_strong), _mk(OPP, seed * 5 + 2, opp_strong)]; hero_idx = 0
    else:
        st = setup_game(_deck(OPP), _deck(HERO), rng=random.Random(seed), first_player=0, effects_overlay=_OVERLAY)
        ais = [_mk(OPP, seed * 5 + 2, opp_strong), _mk(HERO, seed * 3 + 1, hero_strong)]; hero_idx = 1
    play_until_main(st)
    n = 0
    while not st.game_over and st.turn_number < TURN_CAP and n < 1500:
        cur = st.turn_player_idx
        try:
            play_one_action(st, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    if not st.game_over:
        return "draw"
    w = getattr(st, "winner", -1)
    return 1 if w == hero_idx else (0 if w == (1 - hero_idx) else "draw")


def _one(seed):
    return {
        "EBvEB": _play(seed, True, True),
        "EBvGr": _play(seed, True, False),
        "GrvGr": _play(seed, False, False),
        "GrvEB": _play(seed, False, True),
    }


def main():
    n = int(os.environ.get("AB_N", "120"))
    workers = int(os.environ.get("AB_WORKERS", "8"))
    seeds = list(range(1000, 1000 + n))
    t0 = time.time()
    with mp.Pool(workers) as p:
        res = p.map(_one, seeds)
    print(f"エネル vs カルガラ 操縦強度診断  N={n}  ({time.time()-t0:.0f}s)")
    for key, label in [("EBvEB", "エネル強 vs カルガラ強(配備)"),
                       ("EBvGr", "エネル強 vs カルガラ弱(greedy)"),
                       ("GrvGr", "エネル弱 vs カルガラ弱(デッキ相性)"),
                       ("GrvEB", "エネル弱 vs カルガラ強")]:
        w = sum(1 for r in res if r[key] == 1)
        print(f"  {label:34}: エネル {w}/{n} = {100*w/n:.0f}%")


if __name__ == "__main__":
    main()
