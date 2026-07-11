# -*- coding: utf-8 -*-
"""配備形 RolloutRerankAI(determinize=公平)の A/B。

Arm A: hero = RolloutRerankAI(相手隠匿手札を determinize=覗かない) vs opp = ExploitBeam
Arm B: hero = ExploitBeam(配備) vs opp = ExploitBeam
同 seed・seat 均等。Δ = A_winrate - B_winrate = **配備可能な公平版の gain**。

full-info の ab_rollout_policy(+43pt)と違い、これは相手手札を determinize するので human-play で
そのまま公平に使える版。gain がどれだけ残るかを測る。

  RR_HERO=cardrush_1342 RR_OPP=cardrush_1454 RR_N=20 RR_CAND=4 RR_RO=3 RR_WORKERS=12 \
      .venv/bin/python scripts/ab_rollout_rerank.py
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
from engine.rollout_rerank_ai import RolloutRerankAI

ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OV = load_effect_overlay(ROOT / "db" / "card_effects.json")
HERO = os.environ.get("RR_HERO", "cardrush_1342")
OPP = os.environ.get("RR_OPP", "cardrush_1454")
N = int(os.environ.get("RR_N", "20"))
CAND = int(os.environ.get("RR_CAND", "4"))
RO = int(os.environ.get("RR_RO", "3"))
WORKERS = int(os.environ.get("RR_WORKERS", "12"))
REVEAL_P = float(os.environ.get("RR_REVEAL_P", "0.0"))  # 手札予測 accuracy 代理 (0=一様, 1=full-info)
HAND_PREDICT = os.environ.get("RR_HAND_PREDICT", "0") == "1"  # 学習した手札予測器で weighted-sample
TURN_CAP = 40


def _deck(s):
    return make_deck_from_dict(json.loads((ROOT / "decks" / f"{s}.json").read_text(encoding="utf-8")), _REPO)


def _beam(slug, seed):
    return ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10, deck_analysis={"deck_slug": slug})


def _hero(slug, seed, rerank):
    if not rerank:
        return _beam(slug, seed)
    return RolloutRerankAI(rng=random.Random(seed), beam_width=16, max_depth=10,
                           deck_analysis={"deck_slug": slug}, ro_cand=CAND, ro_n=RO,
                           ro_opp_slug=OPP, ro_determinize=True, ro_reveal_p=REVEAL_P,
                           ro_hand_predict=HAND_PREDICT)


def _play(seed, rerank):
    hero_p0 = (seed % 2 == 0)
    if hero_p0:
        st = setup_game(_deck(HERO), _deck(OPP), rng=random.Random(seed), first_player=0, effects_overlay=_OV)
        ais = [_hero(HERO, seed * 3 + 1, rerank), _beam(OPP, seed * 5 + 2)]; hidx = 0
    else:
        st = setup_game(_deck(OPP), _deck(HERO), rng=random.Random(seed), first_player=0, effects_overlay=_OV)
        ais = [_beam(OPP, seed * 5 + 2), _hero(HERO, seed * 3 + 1, rerank)]; hidx = 1
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
    seeds = list(range(3000, 3000 + N))
    t0 = time.time()
    print(f"RolloutRerank(determinize) A/B: {HERO} vs {OPP}  N={N} CAND={CAND} RO={RO}", flush=True)
    with mp.Pool(WORKERS) as p:
        ra = p.map(_one_a, seeds)
    with mp.Pool(WORKERS) as p:
        rb = p.map(_one_b, seeds)
    wa, la = ra.count("W"), ra.count("L")
    wb, lb = rb.count("W"), rb.count("L")
    wra = wa / max(1, wa + la) * 100
    wrb = wb / max(1, wb + lb) * 100
    print(f"A rerank(公平): {wa}-{la}  wr={wra:.1f}%")
    print(f"B 配備        : {wb}-{lb}  wr={wrb:.1f}%")
    print(f"Δ(A-B) = {wra-wrb:+.1f}pt   ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
