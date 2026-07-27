# -*- coding: utf-8 -*-
"""HandDrainAI(相手手札だけ削る)vs 配備 ExploitBeam の挙動・勝率を測る (2026-07-27)。

観察点:
  1. HandDrain は本当に相手手札を(ExploitBeam より)低く抑えるか = 「削る」目的の達成度。
  2. 手札を削るだけで勝てるか = 勝率(手札削りは手段であって勝利条件か の検証)。

  HD_SLUG=cardrush_1454 HD_N=30 HD_WORKERS=10 .venv/bin/python scripts/ab_hand_drain.py
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
from engine.hand_drain_ai import HandDrainAI

REPO_ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(REPO_ROOT / "db" / "card_effects.json")
SLUG = os.environ.get("HD_SLUG", "cardrush_1454")


def _load():
    return make_deck_from_dict(
        json.loads((REPO_ROOT / "decks" / f"{SLUG}.json").read_text(encoding="utf-8")), _REPO)


def _one(seed):
    a_idx = seed % 2            # HandDrain がどちら側か
    fp = (seed // 2) % 2
    state = setup_game(_load(), _load(), rng=random.Random(seed),
                       first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    ais = [None, None]
    ais[a_idx] = HandDrainAI(rng=random.Random(seed * 5 + 1), beam_width=8, max_depth=8,
                             deck_analysis={"deck_slug": SLUG})
    ais[1 - a_idx] = ExploitBeamAI(rng=random.Random(seed * 7 + 3), beam_width=16, max_depth=10,
                                   deck_analysis={"deck_slug": SLUG})
    opp_hand_after_hd = []   # HandDrain のターン直後の相手手札
    n = 0
    while not state.game_over and state.turn_number < 50 and n < 1500:
        cur = state.turn_player_idx
        try:
            play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
        if cur == a_idx and (state.turn_player_idx != a_idx or state.game_over):
            opp_hand_after_hd.append(len(state.players[1 - a_idx].hand))
    if not state.game_over:
        return None
    w = getattr(state, "winner", -1)
    res = "HD" if w == a_idx else ("EB" if w == (1 - a_idx) else None)
    mean_opp_hand = sum(opp_hand_after_hd) / max(1, len(opp_hand_after_hd))
    return (res, mean_opp_hand)


def main():
    n = int(os.environ.get("HD_N", "30"))
    workers = int(os.environ.get("HD_WORKERS", "10"))
    seeds = list(range(5000, 5000 + n))
    t0 = time.time()
    print(f"[ab_hand_drain] {SLUG}  HandDrain vs ExploitBeam  N={n}", flush=True)
    with mp.Pool(workers) as p:
        res = [r for r in p.map(_one, seeds) if r]
    hd = sum(1 for r, _ in res if r == "HD")
    eb = sum(1 for r, _ in res if r == "EB")
    mean_opp_hand = sum(h for _, h in res) / max(1, len(res))
    wr = hd / max(1, hd + eb) * 100
    print(f"[ab_hand_drain] {SLUG}  HandDrain {hd} - {eb} ExploitBeam  "
          f"HD勝率={wr:.1f}%  HDターン後の相手平均手札={mean_opp_hand:.2f}枚  "
          f"({len(res)} games, {time.time()-t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
