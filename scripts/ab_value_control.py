# -*- coding: utf-8 -*-
"""population value が control デッキを de-bias するか (2026-07-28、 Stage 1 の第二 gate)。

hero=control デッキ、 opp=field。 同一 seed で hero が (A) population value / (B) agnostic value を
使って対戦し hero 勝率を比較(opp は常に agnostic 固定 = hero の value 変化のみ isolate)。
population value で control 勝率が上がれば「ミラー regime の aggro 偏りを population で de-bias」の証拠。

  AVC_HERO=cardrush_1342 AVC_N=120 AVC_WORKERS=12 .venv/bin/python scripts/ab_value_control.py
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
HERO = os.environ.get("AVC_HERO", "cardrush_1342")
POP_VALUE = os.environ.get("AVC_POP", "db/_selfplay/value_population.pkl")
BASE_VALUE = os.environ.get("AVC_BASE", "db/value_gbm_agnostic.pkl")
POOL = ["cardrush_1385", "cardrush_1392", "cardrush_1399", "cardrush_1439", "cardrush_1453",
        "cardrush_1454", "cardrush_1455", "tcgportal_bonney", "tcgportal_hancock",
        "tcgportal_op11_luffy", "tcgportal_op13_luffy"]
_DL = {}


def _dl(slug):
    if slug not in _DL:
        _DL[slug] = make_deck_from_dict(json.loads((ROOT / "decks" / f"{slug}.json").read_text()), _REPO)
    return _DL[slug]


def _play(seed, opp, hero_value):
    fp = seed % 2
    state = setup_game(_dl(HERO), _dl(opp), rng=random.Random(seed), first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    h_idx = 0 if fp == 0 else 1
    o_idx = 1 - h_idx
    ais = [None, None]
    ais[h_idx] = ExploitBeamAI(rng=random.Random(seed * 5 + 1), beam_width=16, max_depth=10,
                               deck_analysis={"deck_slug": HERO}, gbm_path=hero_value)
    ais[o_idx] = ExploitBeamAI(rng=random.Random(seed * 7 + 3), beam_width=16, max_depth=10,
                               deck_analysis={"deck_slug": opp}, gbm_path=BASE_VALUE)
    n = 0
    while not state.game_over and state.turn_number < 42 and n < 700:
        cur = state.turn_player_idx
        try:
            play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    if not state.game_over:
        return None
    return "W" if getattr(state, "winner", -1) == h_idx else "L"


def _one(seed):
    opp = random.Random(seed).choice(POOL)
    return (_play(seed, opp, POP_VALUE), _play(seed, opp, BASE_VALUE))  # (pop, agnostic)


def main():
    n = int(os.environ.get("AVC_N", "120"))
    workers = int(os.environ.get("AVC_WORKERS", "12"))
    seeds = list(range(70000, 70000 + n))
    t0 = time.time()
    print(f"[ab_value_control] hero={HERO}(control) vs field  N={n}", flush=True)
    print(f"  pop={POP_VALUE}  base={BASE_VALUE}", flush=True)
    with mp.Pool(workers) as p:
        res = p.map(_one, seeds)
    pw = sum(1 for a, b in res if a == "W"); pl = sum(1 for a, b in res if a == "L")
    bw = sum(1 for a, b in res if b == "W"); bl = sum(1 for a, b in res if b == "L")
    wr_p = pw / max(1, pw + pl) * 100
    wr_b = bw / max(1, bw + bl) * 100
    print(f"[ab_value_control] population value hero勝率 {wr_p:.1f}% ({pw}-{pl})  |  "
          f"agnostic hero勝率 {wr_b:.1f}% ({bw}-{bl})  |  Δ={wr_p-wr_b:+.1f}pt  ({time.time()-t0:.0f}s)",
          flush=True)


if __name__ == "__main__":
    main()
