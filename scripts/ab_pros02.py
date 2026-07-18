# -*- coding: utf-8 -*-
"""pros_02 signal (ONEPIECE_PROS02_W) の mirror A/B + 行動計測。

A = pros_02 signal ON (_pros02_w=W)、 B = OFF (_pros02_w=0)。 同一デッキのミラー、
deck_analysis は overlay込み (= pros02_signals が beam に届く)。 a_idx/fp を独立に振る。

計測: 勝率 (A vs B) + A側の平均 攻撃回数/game (= 攻撃回数優先 signal が効くと増える想定)。

  AB_SLUG=cardrush_1454 AB_W=8 AB_N=40 AB_WORKERS=8 .venv/bin/python scripts/ab_pros02.py
"""
import sys, os, random, time, json
import multiprocessing as mp
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main, AttackLeader, AttackCharacter
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI
from engine.harness import _try_load_deck_analysis

REPO_ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(REPO_ROOT / "db" / "card_effects.json")
SLUG = os.environ["AB_SLUG"]
W = float(os.environ.get("AB_W", "8"))


class _Slugged:
    def __init__(self, slug): self.slug = slug


def _da():
    return _try_load_deck_analysis(_Slugged(SLUG))  # overlay込み (pros02_signals)


def _load():
    return make_deck_from_dict(
        json.loads((REPO_ROOT / "decks" / f"{SLUG}.json").read_text(encoding="utf-8")), _REPO)


def _beam(seed, w):
    ai = ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10, deck_analysis=_da())
    ai._pros02_w = w
    return ai


def _count_attacks(log_lines, name_hint=None):
    return sum(1 for ln in log_lines if " atk:" in ln)


def _one(seed):
    a_idx = seed % 2
    fp = (seed // 2) % 2
    state = setup_game(_load(), _load(), rng=random.Random(seed),
                       first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    ais = [None, None]
    ais[a_idx] = _beam(seed * 5 + 1, W)      # A = pros02 ON
    ais[1 - a_idx] = _beam(seed * 7 + 3, 0.0)  # B = OFF
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
    # A側の攻撃回数 (log から、 turn_player 別は取れないので総数の半分近似は避け、 A手番の atk のみ数える)
    logs = getattr(state, "log", []) or []
    a_atk = sum(1 for ln in logs if f"P{a_idx}" in ln and " atk:" in ln)
    b_atk = sum(1 for ln in logs if f"P{1-a_idx}" in ln and " atk:" in ln)
    res = "A" if w == a_idx else ("B" if w == (1 - a_idx) else "D")
    return (res, a_atk, b_atk)


def main():
    n = int(os.environ.get("AB_N", "40"))
    workers = int(os.environ.get("AB_WORKERS", "8"))
    seeds = list(range(2000, 2000 + n))
    t0 = time.time()
    with mp.Pool(workers) as p:
        res = [r for r in p.map(_one, seeds) if r]
    a = sum(1 for r in res if r[0] == "A")
    b = sum(1 for r in res if r[0] == "B")
    d = sum(1 for r in res if r[0] == "D")
    aa = [r[1] for r in res]; ba = [r[2] for r in res]
    wr = a / max(1, a + b) * 100
    print(f"{SLUG}  PROS02_W={W}  A(pros02) {a} - {b} B(off)  draw/incomplete {d}  "
          f"A_wr={wr:.0f}%  | 攻撃回数/game A={sum(aa)/max(1,len(aa)):.1f} B={sum(ba)/max(1,len(ba)):.1f}"
          f"  ({time.time()-t0:.0f}s, N={len(res)})")


if __name__ == "__main__":
    main()
