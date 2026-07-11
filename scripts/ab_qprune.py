# -*- coding: utf-8 -*-
"""経験ベース枝刈り(q_prune)の cross-matchup A/B。

hero(deck A)が q_prune margin を使う vs 同 hero が使わない、を **同じ相手 deck B・
同 seed・seat-balanced** で比較 → 枝刈りが配備 AI を強くするか(no-harm か)を検証。

各 matchup: hero-prune vs opp を N game、hero-noprune vs opp を N game(同 seed)。
Δ = prune 勝率 - noprune 勝率。>0 なら枝刈りが有益。

  QP_MARGIN=0.04 QP_N=60 QP_WORKERS=10 .venv/bin/python scripts/ab_qprune.py
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
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")

MARGIN = float(os.environ.get("QP_MARGIN", "0.04"))
N = int(os.environ.get("QP_N", "60"))
WORKERS = int(os.environ.get("QP_WORKERS", "10"))

# hero=deck a が q_prune、opp=deck b は素の配備。多相手で robust に。
PAIRS = [
    ("cardrush_1342", "tcgportal_calgara"),
    ("cardrush_1454", "tcgportal_bonney"),
    ("cardrush_1385", "cardrush_1456"),
    ("cardrush_1453", "tcgportal_hancock"),
]


def _load(slug):
    return make_deck_from_dict(
        json.loads((ROOT / "decks" / f"{slug}.json").read_text(encoding="utf-8")), _REPO)


def _hero(slug, seed, margin):
    ai = ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10,
                       deck_analysis={"deck_slug": slug})
    ai._qprune_margin = margin  # None=素、>0=枝刈り
    return ai


def _one(args):
    hero_slug, opp_slug, seed, margin = args
    hero_seat = seed % 2               # hero がどちら側か
    fp = (seed // 2) % 2               # 先攻(hero_seat と独立)
    d_first = _load(hero_slug) if hero_seat == 0 else _load(opp_slug)
    d_second = _load(opp_slug) if hero_seat == 0 else _load(hero_slug)
    state = setup_game(d_first, d_second, rng=random.Random(seed),
                       first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    ais = [None, None]
    ais[hero_seat] = _hero(hero_slug, seed * 5 + 1, margin)
    ais[1 - hero_seat] = _hero(opp_slug, seed * 7 + 3, None)  # opp は素
    n = 0
    while not state.game_over and state.turn_number < 50 and n < 1500:
        cur = state.turn_player_idx
        try:
            play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    if not state.game_over:
        return None
    w = getattr(state, "winner", -1)
    return "W" if w == hero_seat else ("L" if w == (1 - hero_seat) else None)


def _run(pairs, margin, seeds):
    tasks = [(h, o, s, margin) for (h, o) in pairs for s in seeds]
    with mp.Pool(WORKERS) as p:
        res = p.map(_one, tasks)
    w = res.count("W"); l = res.count("L")
    return w, l, len(res) - w - l


def main():
    seeds = list(range(2000, 2000 + N))
    t0 = time.time()
    print(f"q_prune margin={MARGIN}  N={N}/matchup × {len(PAIRS)} matchup  (hero=各pair左)")
    wp, lp, dp = _run(PAIRS, MARGIN, seeds)     # prune ON
    wn, ln, dn = _run(PAIRS, None, seeds)       # prune OFF (baseline)
    wr_p = wp / max(1, wp + lp) * 100
    wr_n = wn / max(1, wn + ln) * 100
    print(f"prune ON : {wp}-{lp}  (draw/incomp {dp})  hero_wr={wr_p:.1f}%")
    print(f"prune OFF: {wn}-{ln}  (draw/incomp {dn})  hero_wr={wr_n:.1f}%")
    print(f"Δ(ON-OFF) = {wr_p - wr_n:+.1f}pt   ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
