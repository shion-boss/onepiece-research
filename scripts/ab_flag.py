# -*- coding: utf-8 -*-
"""配備 ExploitBeam の boolean フラグを 1 つ切り替えてミラー A/B 計測する汎用ツール。

A = 配備 ExploitBeam の `AB_FLAG` 属性を `AB_VALUE` (既定 False) に set したもの (= under test)。
B = 配備 ExploitBeam (= 既定挙動)。 両者とも deck の deployed GBM を auto-load。

⚠ first-player 優位の交絡を避けるため a_idx (= A がどちら側か) と fp (= 先攻) を
   独立に振る (seed%2 と (seed//2)%2)。 N≥80 推奨 (= campaign の配備ミラー A/B と同水準)。

  AB_SLUG=tcgportal_op13_luffy AB_FLAG=_offense_force_attack AB_N=80 AB_WORKERS=8 \
      .venv/bin/python scripts/ab_flag.py
"""
import sys, os, random, time
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

SLUG = os.environ["AB_SLUG"]
FLAG = os.environ["AB_FLAG"]
VALUE = os.environ.get("AB_VALUE", "False") == "True"


def _load():
    import json
    return make_deck_from_dict(
        json.loads((REPO_ROOT / "decks" / f"{SLUG}.json").read_text(encoding="utf-8")),
        _REPO,
    )


def _beam(seed, *, flagged: bool):
    ai = ExploitBeamAI(
        rng=random.Random(seed), beam_width=16, max_depth=10,
        deck_analysis={"deck_slug": SLUG},
    )
    if flagged:
        setattr(ai, FLAG, VALUE)
    return ai


def _one(seed):
    a_idx = seed % 2            # A (under test) がどちら側か
    fp = (seed // 2) % 2        # 先攻 (a_idx と独立)
    state = setup_game(_load(), _load(), rng=random.Random(seed),
                       first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    ais = [None, None]
    ais[a_idx] = _beam(seed * 5 + 1, flagged=True)
    ais[1 - a_idx] = _beam(seed * 7 + 3, flagged=False)
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
    if w == a_idx:
        return "A"
    if w == (1 - a_idx):
        return "B"
    return None


def main():
    n = int(os.environ.get("AB_N", "80"))
    workers = int(os.environ.get("AB_WORKERS", "8"))
    seeds = list(range(1000, 1000 + n))
    t0 = time.time()
    with mp.Pool(workers) as p:
        res = p.map(_one, seeds)
    a = res.count("A"); b = res.count("B"); d = len(res) - a - b
    wr = a / max(1, a + b) * 100
    print(f"{SLUG}  {FLAG}={VALUE}  A(test) {a} - {b} B(deployed)  "
          f"draw/incomplete {d}  A_wr={wr:.0f}%  ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
