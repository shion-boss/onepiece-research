# -*- coding: utf-8 -*-
"""grind-control 脅威除去 bonus の非ミラー paired A/B (2026-07-27、 戦略トレース発見)。

hero=固定 grind-control(既定ドフラ 1342)、 opp=固定(大型盤面を作る相手)。 同一 seed で
A=hero+_threat_removal_w=W と B=hero baseline を各々 opp と対戦させ、 hero 勝率を比較(paired)。
mirror だと control 同士で 5000+ 脅威が稀 → under-test なので、 大型盤面 opp との非ミラーで測る。
⚠ setup_game は先攻を index0 に置くので hero_idx を fp から導く。

  CR_HERO=cardrush_1342 CR_OPP=cardrush_1385 CR_W=0.5 CR_N=150 CR_WORKERS=3 \
      .venv/bin/python scripts/ab_control_removal.py
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
HERO = os.environ.get("CR_HERO", "cardrush_1342")
OPP = os.environ.get("CR_OPP", "cardrush_1385")
W = float(os.environ.get("CR_W", "0.5"))


def _dl(slug):
    return make_deck_from_dict(json.loads((ROOT / "decks" / f"{slug}.json").read_text()), _REPO)


def _play(seed, w):
    fp = seed % 2
    state = setup_game(_dl(HERO), _dl(OPP), rng=random.Random(seed), first_player=fp,
                       effects_overlay=_OVERLAY)
    play_until_main(state)
    hero_idx = 0 if fp == 0 else 1
    opp_idx = 1 - hero_idx
    hero_ai = ExploitBeamAI(rng=random.Random(seed * 5 + 1), beam_width=16, max_depth=10,
                            deck_analysis={"deck_slug": HERO})
    if w != 0.0:
        hero_ai._threat_removal_w = w
    opp_ai = ExploitBeamAI(rng=random.Random(seed * 7 + 3), beam_width=16, max_depth=10,
                           deck_analysis={"deck_slug": OPP})
    ais = [None, None]
    ais[hero_idx] = hero_ai
    ais[opp_idx] = opp_ai
    n = 0
    while not state.game_over and state.turn_number < 55 and n < 1500:
        cur = state.turn_player_idx
        try:
            play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    if not state.game_over:
        return None
    w_id = getattr(state, "winner", -1)
    return "W" if w_id == hero_idx else ("L" if w_id == opp_idx else None)


def _one(seed):
    return (_play(seed, W), _play(seed, 0.0))  # (bonus, baseline)


def main():
    n = int(os.environ.get("CR_N", "150"))
    workers = int(os.environ.get("CR_WORKERS", "3"))
    seeds = list(range(30000, 30000 + n))
    t0 = time.time()
    print(f"[ab_control_removal] hero={HERO} vs opp={OPP}  W={W}  N={n}", flush=True)
    with mp.Pool(workers) as p:
        res = p.map(_one, seeds)
    bw = sum(1 for a, b in res if a == "W"); bl = sum(1 for a, b in res if a == "L")
    kw = sum(1 for a, b in res if b == "W"); kl = sum(1 for a, b in res if b == "L")
    wr_b = bw / max(1, bw + bl) * 100
    wr_k = kw / max(1, kw + kl) * 100
    print(f"[ab_control_removal] bonus(W={W}) hero勝率 {wr_b:.1f}% ({bw}-{bl})  |  "
          f"baseline hero勝率 {wr_k:.1f}% ({kw}-{kl})  |  Δ={wr_b-wr_k:+.1f}pt  ({time.time()-t0:.0f}s)",
          flush=True)


if __name__ == "__main__":
    main()
