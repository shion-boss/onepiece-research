# -*- coding: utf-8 -*-
"""control-vs-control で value を高N A/B (2026-07-28、 ohtsuki hint「control同士+試行増で新発見」)。

control mirror(both 同一 control deck)で hero が (A) pop value / (B) agnostic value。 opp は agnostic 固定。
control 同士は aggro の懲罰が無いので、 control 状態を見た pop value がここで初めて勝つかもしれない。
a_idx/fp を独立に振り先攻バイアス相殺。

  AC_SLUG=cardrush_1342 AC_POP=db/_selfplay/value_pop_strong.pkl AC_N=300 AC_WORKERS=12 \
      .venv/bin/python scripts/ab_ctrl_value.py
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
SLUG = os.environ.get("AC_SLUG", "cardrush_1342")
POP = os.environ.get("AC_POP", "db/_selfplay/value_pop_strong.pkl")
BASE = os.environ.get("AC_BASE", "db/value_gbm_agnostic.pkl")


def _load():
    return make_deck_from_dict(json.loads((ROOT / "decks" / f"{SLUG}.json").read_text()), _REPO)


def _one(seed):
    a_idx = seed % 2           # A(pop value)がどちら側か
    fp = (seed // 2) % 2       # 先攻(独立)
    state = setup_game(_load(), _load(), rng=random.Random(seed), first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    ais = [None, None]
    ais[a_idx] = ExploitBeamAI(rng=random.Random(seed * 5 + 1), beam_width=8, max_depth=6,
                               deck_analysis={"deck_slug": SLUG}, gbm_path=POP)
    ais[1 - a_idx] = ExploitBeamAI(rng=random.Random(seed * 7 + 3), beam_width=8, max_depth=6,
                                   deck_analysis={"deck_slug": SLUG}, gbm_path=BASE)
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
    w = getattr(state, "winner", -1)
    return "A" if w == a_idx else ("B" if w == (1 - a_idx) else None)


def main():
    n = int(os.environ.get("AC_N", "300"))
    workers = int(os.environ.get("AC_WORKERS", "12"))
    seeds = list(range(90000, 90000 + n))
    t0 = time.time()
    print(f"[ab_ctrl_value] {SLUG} mirror  A(pop value) vs B(agnostic)  N={n}", flush=True)
    with mp.Pool(workers) as p:
        res = p.map(_one, seeds)
    a = res.count("A"); b = res.count("B")
    wr = a / max(1, a + b) * 100
    print(f"[ab_ctrl_value] {SLUG}: pop value 勝率 {wr:.1f}% ({a}-{b})  ({time.time()-t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
