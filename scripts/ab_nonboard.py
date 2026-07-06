# -*- coding: utf-8 -*-
"""多軸 combiner value(side A)vs 生 GBM value(side B)のミラー A/B。

side A の手番だけ ONEPIECE_NONBOARD_BONUS を立てて beam を combiner value で走らせ、 side B は
配備の生 value。 combiner が「人間に近い / より強い」手を選べているかの直接検証。

⚠ first-player 優位を避けるため a_idx(A がどちら側か)と fp(先攻)を独立に振る。 N≥80 推奨。

  AB_SLUG=cardrush_1454 AB_BONUS=db/_selfplay/eval_combiner29.pkl AB_N=80 AB_WORKERS=8 \
      .venv/bin/python scripts/ab_combiner.py
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
BONUS = os.environ["AB_BONUS"]  # nonboard bonus lambda


def _load():
    import json
    return make_deck_from_dict(
        json.loads((REPO_ROOT / "decks" / f"{SLUG}.json").read_text(encoding="utf-8")),
        _REPO,
    )


def _beam(seed):
    return ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10,
                         deck_analysis={"deck_slug": SLUG})


def _one(seed):
    a_idx = seed % 2            # A (combiner) がどちら側か
    fp = (seed // 2) % 2        # 先攻 (a_idx と独立)
    state = setup_game(_load(), _load(), rng=random.Random(seed),
                       first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    ais = [None, None]
    ais[a_idx] = _beam(seed * 5 + 1)
    ais[1 - a_idx] = _beam(seed * 7 + 3)
    n = 0
    while not state.game_over and state.turn_number < 50 and n < 1500:
        cur = state.turn_player_idx
        # A の手番のみ combiner value を有効化
        if cur == a_idx:
            os.environ["ONEPIECE_NONBOARD_BONUS"] = BONUS
        else:
            os.environ.pop("ONEPIECE_NONBOARD_BONUS", None)
        try:
            play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    os.environ.pop("ONEPIECE_NONBOARD_BONUS", None)
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
    print(f"{SLUG}  bonus λ={BONUS}  A(bonus) {a} - {b} B(raw value)  "
          f"draw/incomplete {d}  A_wr={wr:.0f}%  ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
