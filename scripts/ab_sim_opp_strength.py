# -*- coding: utf-8 -*-
"""探索の仮想敵の「強さ」を変えて配備 ExploitBeam が強くなるか A/B (= ohtsuki 指摘
「仮想的 greedy は伸びしろない」)。

配備 ExploitBeam は post-opp sim / defense sim で **相手を GreedyAI と仮定** する。 弱い仮想敵で
最適化 → 相手ターン後の盤面を過度に有利に評価 → 読みが甘くなる (= 深読みするほど悪化、
[[project_70pct_vs_greedy]])。 仮想敵を**強く**すれば「相手はちゃんと咎める」前提で読める
(= AlphaZero 原則: 強い相手を想定して最適化)。

  hero-STRONG = ExploitBeam + set_ai_opp(ExploitBeam)   (= 強い仮想敵で読む)
  hero-GREEDY = ExploitBeam + set_ai_opp(GreedyAI)        (= 現配備 default)

⚠ **強い actual 相手** (既定 = plain ExploitBeam) に当てないと差が出ない (= 弱い相手は AI の
   過度な楽観を咎めないので、 現実的な読みの利得が勝敗に出ない)。 同一 seed で paired。

  AB_SLUG=cardrush_1342 AB_N=40 AB_WORKERS=10 AB_SIM=beam AB_OPP=beam \
      .venv/bin/python scripts/ab_sim_opp_strength.py

  AB_SIM (hero の仮想敵、 test 側): beam(既定, ExploitBeam=強) / evalgreedy(greedy+1ply)
  AB_OPP (actual 相手): beam(既定, ExploitBeam) / beamracer(強+顔詰め) / greedy
"""
import sys, os, random, time
import multiprocessing as mp
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main
from engine.ai import play_one_action, GreedyAI, EvalGreedyAI
from engine.exploit_beam_ai import ExploitBeamAI

REPO_ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(REPO_ROOT / "db" / "card_effects.json")

SLUG = os.environ["AB_SLUG"]
SIM = os.environ.get("AB_SIM", "beam")     # hero の仮想敵 (test 側の強さ)
OPP = os.environ.get("AB_OPP", "beam")     # actual 相手


def _load():
    import json
    return make_deck_from_dict(
        json.loads((REPO_ROOT / "decks" / f"{SLUG}.json").read_text(encoding="utf-8")),
        _REPO,
    )


def _hero(seed, *, strong_sim: bool):
    da = {"deck_slug": SLUG}
    ai = ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10, deck_analysis=da)
    if not strong_sim:
        ai.set_ai_opp(GreedyAI(rng=random.Random(seed + 11), deck_analysis=da))  # 現配備 default
    elif SIM == "evalgreedy":
        ai.set_ai_opp(EvalGreedyAI(rng=random.Random(seed + 11), deck_analysis=da))
    else:  # beam = 強い仮想敵 (自己相当)。 sim 側は beam8 で軽量化 (post-opp は 1 手なので十分)
        ai.set_ai_opp(ExploitBeamAI(rng=random.Random(seed + 11), beam_width=8, max_depth=8,
                                    deck_analysis=da))
    return ai


def _opp(seed):
    da = {"deck_slug": SLUG}
    if OPP == "beamracer":
        from engine.ai_experimental import AggressiveBeamRacerAI
        return AggressiveBeamRacerAI(rng=random.Random(seed), beam_width=16, max_depth=10, deck_analysis=da)
    if OPP == "greedy":
        return GreedyAI(rng=random.Random(seed), deck_analysis=da)
    return ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10, deck_analysis=da)


def _play(hero, opp, hero_idx, seed, fp):
    state = setup_game(_load(), _load(), rng=random.Random(seed),
                       first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    ais = [None, None]
    ais[hero_idx] = hero
    ais[1 - hero_idx] = opp
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
    return True if w == hero_idx else (False if w == (1 - hero_idx) else None)


def _one(seed):
    hero_idx = seed % 2
    fp = (seed // 2) % 2
    strong = _play(_hero(seed * 5 + 1, strong_sim=True), _opp(seed * 3 + 2), hero_idx, seed, fp)
    greedy = _play(_hero(seed * 5 + 1, strong_sim=False), _opp(seed * 3 + 2), hero_idx, seed, fp)
    return (strong, greedy)


def main():
    n = int(os.environ.get("AB_N", "40"))
    workers = int(os.environ.get("AB_WORKERS", "10"))
    seeds = list(range(4000, 4000 + n))
    t0 = time.time()
    with mp.Pool(workers) as p:
        res = p.map(_one, seeds)
    s_w = sum(1 for s, g in res if s is True); s_l = sum(1 for s, g in res if s is False)
    g_w = sum(1 for s, g in res if g is True); g_l = sum(1 for s, g in res if g is False)
    s_wr = s_w / max(1, s_w + s_l) * 100
    g_wr = g_w / max(1, g_w + g_l) * 100
    s_only = sum(1 for s, g in res if s is True and g is False)
    g_only = sum(1 for s, g in res if g is True and s is False)
    print(f"{SLUG}  hero=ExploitBeam  vs {OPP}  sim={SIM}  (N={n}, paired)")
    print(f"  strong-sim-opp : {s_w}-{s_l}  wr={s_wr:.0f}%")
    print(f"  greedy-sim-opp : {g_w}-{g_l}  wr={g_wr:.0f}%  (= 現配備)")
    print(f"  paired flips: STRONG-wins/GREEDY-loses={s_only}  GREEDY-wins/STRONG-loses={g_only}")
    print(f"  Δwr(STRONG-GREEDY) = {s_wr - g_wr:+.1f}pt   ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
