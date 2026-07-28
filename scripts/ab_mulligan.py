# -*- coding: utf-8 -*-
"""マリガン sensitivity 診断 (2026-07-28、 leaf-独立の別レバー)。

hero が {heuristic(現行) / keep(常keep) / throw(常mull) / random} の各モードで field と対戦、
hero 勝率を比較。 heuristic が keep/throw/random より明確に高ければ「マリガン計算器はレバー」
(= より良い hand-quality 計算器で伸びる余地)。 差が無ければマリガンは効かない(現行で十分)。
opp は常に heuristic。 hero の mulligan mode のみ isolate(setup analysis._mull_mode)。

  MULL_HERO=cardrush_1454 MULL_N=200 MULL_WORKERS=12 .venv/bin/python scripts/ab_mulligan.py
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
HERO = os.environ.get("MULL_HERO", "cardrush_1454")
POOL = ["cardrush_1385", "cardrush_1392", "cardrush_1399", "cardrush_1439", "cardrush_1453",
        "cardrush_1456", "tcgportal_bonney", "tcgportal_hancock", "tcgportal_op11_luffy",
        "tcgportal_op13_luffy"]
_DL = {}
_ANA = None


def _dl(slug):
    if slug not in _DL:
        _DL[slug] = make_deck_from_dict(json.loads((ROOT / "decks" / f"{slug}.json").read_text()), _REPO)
    return _DL[slug]


def _hero_ana(mode):
    global _ANA
    if _ANA is None:
        try:
            _ANA = json.loads((ROOT / "decks" / f"{HERO}.analysis.json").read_text())
        except Exception:
            _ANA = {}
    a = dict(_ANA)
    if mode != "heuristic":
        a["_mull_mode"] = mode
    return a


def _play(seed, opp, mode):
    fp = seed % 2
    h_ana = _hero_ana(mode)
    # hero=deck1、 opp=deck2。 setup は先攻を index0 に置くので analysis も同順で渡す。
    if fp == 0:
        state = setup_game(_dl(HERO), _dl(opp), rng=random.Random(seed), first_player=0,
                           effects_overlay=_OVERLAY, deck1_analysis=h_ana, deck2_analysis=None)
        h_idx = 0
    else:
        state = setup_game(_dl(opp), _dl(HERO), rng=random.Random(seed), first_player=1,
                           effects_overlay=_OVERLAY, deck1_analysis=None, deck2_analysis=h_ana)
        h_idx = 1
    play_until_main(state)
    o_idx = 1 - h_idx
    ais = [None, None]
    ais[h_idx] = ExploitBeamAI(rng=random.Random(seed * 5 + 1), beam_width=16, max_depth=10,
                               deck_analysis={"deck_slug": HERO})
    ais[o_idx] = ExploitBeamAI(rng=random.Random(seed * 7 + 3), beam_width=16, max_depth=10,
                               deck_analysis={"deck_slug": opp})
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
    return getattr(state, "winner", -1) == h_idx


MODES = ["heuristic", "keep", "throw", "random"]


def _one(args):
    seed, mode = args
    opp = random.Random(seed).choice(POOL)
    r = _play(seed, opp, mode)
    return (mode, r)


def main():
    n = int(os.environ.get("MULL_N", "200"))
    workers = int(os.environ.get("MULL_WORKERS", "12"))
    t0 = time.time()
    tasks = [(90000 + i, m) for m in MODES for i in range(n)]
    print(f"[ab_mulligan] hero={HERO}  各モード N={n}  (opp=heuristic)", flush=True)
    with mp.Pool(workers) as p:
        res = p.map(_one, tasks, chunksize=8)
    agg = {m: [0, 0] for m in MODES}
    for mode, r in res:
        if r is True:
            agg[mode][0] += 1
        elif r is False:
            agg[mode][1] += 1
    print(f"=== マリガン sensitivity (hero={HERO}, {time.time()-t0:.0f}s) ===", flush=True)
    for m in MODES:
        w, l = agg[m]
        wr = w / max(1, w + l) * 100
        print(f"  {m:10} hero勝率 {wr:.1f}% ({w}-{l})", flush=True)


if __name__ == "__main__":
    main()
