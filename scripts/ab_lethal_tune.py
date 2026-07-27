# -*- coding: utf-8 -*-
"""per-attack リーサル + 閾値 delta の較正 sweep vs 配備 (2026-07-27)。

A = ExploitBeam(_lethal_peratk=True, _lethal_thresh_delta=LT_DELTA)。 B = 配備 ExploitBeam。
per-attack は p_lethal を系統的に下げるので、 閾値を delta 下げて aggro の保守化 regression を回復
できるかを sweep。 A > 50% を全 deck (aggro/mid/control) で満たす delta を探す。

  LT_SLUG=cardrush_1456 LT_DELTA=0.15 LT_N=160 LT_WORKERS=12 .venv/bin/python scripts/ab_lethal_tune.py
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

REPO_ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(REPO_ROOT / "db" / "card_effects.json")
SLUG = os.environ.get("LT_SLUG", "cardrush_1456")
DELTA = float(os.environ.get("LT_DELTA", "0.15"))


def _load():
    return make_deck_from_dict(
        json.loads((REPO_ROOT / "decks" / f"{SLUG}.json").read_text(encoding="utf-8")), _REPO)


def _beam(seed, peratk):
    ai = ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10,
                       deck_analysis={"deck_slug": SLUG})
    if peratk:
        ai._lethal_peratk = True
        ai._lethal_thresh_delta = DELTA
    else:
        # B = baseline(旧リーサル計算器 = 総和近似、 delta なし)。 配備 default が per-attack ON に
        # なったので明示的に OFF にする。
        ai._lethal_peratk = False
        ai._lethal_thresh_delta = 0.0
    return ai


def _one(seed):
    a_idx = seed % 2
    fp = (seed // 2) % 2
    state = setup_game(_load(), _load(), rng=random.Random(seed),
                       first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    ais = [None, None]
    ais[a_idx] = _beam(seed * 5 + 1, peratk=True)
    ais[1 - a_idx] = _beam(seed * 7 + 3, peratk=False)
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
    return "A" if w == a_idx else ("B" if w == (1 - a_idx) else None)


def main():
    n = int(os.environ.get("LT_N", "160"))
    workers = int(os.environ.get("LT_WORKERS", "12"))
    seeds = list(range(8000, 8000 + n))
    t0 = time.time()
    print(f"[ab_lethal_tune] {SLUG}  A(per-attack + thresh_delta={DELTA}) vs B(配備)  N={n}", flush=True)
    with mp.Pool(workers) as p:
        res = p.map(_one, seeds)
    a = res.count("A"); b = res.count("B"); d = len(res) - a - b
    wr = a / max(1, a + b) * 100
    print(f"[ab_lethal_tune] {SLUG}  A {a} - {b} B  draw {d}  A_wr={wr:.1f}%  "
          f"({time.time()-t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
