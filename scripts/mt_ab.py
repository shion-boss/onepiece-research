# -*- coding: utf-8 -*-
"""多ターン探索(post-opp N-turn lookahead)の clean な hero-only A/B (2026-07-13)。

Arm A: hero = ExploitBeam(multi-turn config)  vs opp = ExploitBeam base
Arm B: hero = ExploitBeam base                 vs opp = ExploitBeam base
同一 seed・seat 均等・paired。Δ = A_wr - B_wr = 多ターン探索の寄与(base 比)。

knob は per-AI(exploit_beam_ai.py で bracket 済)なので opp に漏れない = clean。
  MT_TURNS=2 MT_OPP_VALUE=1 MT_SELF_VALUE=0 MT_ASYM=0 MT_N=40 MT_HERO=cardrush_1342 \
  MT_OPP=cardrush_1454 MT_WORKERS=14 .venv/bin/python scripts/mt_ab.py
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
_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OV = load_effect_overlay(ROOT / "db" / "card_effects.json")
HERO = os.environ.get("MT_HERO", "cardrush_1342")
OPP = os.environ.get("MT_OPP", "cardrush_1454")
N = int(os.environ.get("MT_N", "40"))
WORKERS = int(os.environ.get("MT_WORKERS", "14"))
SEED_BASE = int(os.environ.get("MT_SEED_BASE", "3000"))
TURNS = int(os.environ.get("MT_TURNS", "2"))
OPP_VALUE = os.environ.get("MT_OPP_VALUE", "0") == "1"
SELF_VALUE = os.environ.get("MT_SELF_VALUE", "0") == "1"
ASYM = os.environ.get("MT_ASYM", "0") == "1"
TURN_CAP = 40

_MT_KW = dict(postopp_turns=TURNS, postopp_opp_value=OPP_VALUE,
              postopp_self_value=SELF_VALUE, asym_multiturn=ASYM)


def _deck(s):
    return make_deck_from_dict(json.loads((ROOT / "decks" / f"{s}.json").read_text(encoding="utf-8")), _REPO)


def _base(slug, seed):
    return ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10, deck_analysis={"deck_slug": slug})


def _mt(slug, seed):
    return ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10,
                         deck_analysis={"deck_slug": slug}, **_MT_KW)


def _play(seed, hero_mt):
    hero_p0 = (seed % 2 == 0)
    hero_ai = (_mt if hero_mt else _base)
    if hero_p0:
        st = setup_game(_deck(HERO), _deck(OPP), rng=random.Random(seed), first_player=0, effects_overlay=_OV)
        ais = [hero_ai(HERO, seed * 3 + 1), _base(OPP, seed * 5 + 2)]; hidx = 0
    else:
        st = setup_game(_deck(OPP), _deck(HERO), rng=random.Random(seed), first_player=0, effects_overlay=_OV)
        ais = [_base(OPP, seed * 5 + 2), hero_ai(HERO, seed * 3 + 1)]; hidx = 1
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
        return None
    w = getattr(st, "winner", -1)
    return "W" if w == hidx else ("L" if w == (1 - hidx) else None)


def _one_a(seed):
    return _play(seed, True)


def _one_b(seed):
    return _play(seed, False)


def main():
    seeds = list(range(SEED_BASE, SEED_BASE + N))
    t0 = time.time()
    cfg = f"turns={TURNS} opp_value={int(OPP_VALUE)} self_value={int(SELF_VALUE)} asym={int(ASYM)}"
    print(f"multi-turn A/B: {HERO} vs {OPP}  N={N}  [{cfg}]", flush=True)
    with mp.Pool(WORKERS) as p:
        ra = p.map(_one_a, seeds)
    with mp.Pool(WORKERS) as p:
        rb = p.map(_one_b, seeds)
    wa, la = ra.count("W"), ra.count("L")
    wb, lb = rb.count("W"), rb.count("L")
    wra = wa / max(1, wa + la) * 100
    wrb = wb / max(1, wb + lb) * 100
    print(f"A multi-turn : {wa}-{la}  wr={wra:.1f}%")
    print(f"B base       : {wb}-{lb}  wr={wrb:.1f}%")
    print(f"Δ(A-B) = {wra-wrb:+.1f}pt   ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
