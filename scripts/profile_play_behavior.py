# -*- coding: utf-8 -*-
"""deck(value X) vs opp の行動プロファイル(攻撃/守備/盤面/ゲーム長)を value 別に比較。
matchup-conditioning の誤学習診断用: v5onp が calgara に「攻めるべき所を慎重」になってないか等。

  .venv/bin/python scripts/profile_play_behavior.py --deck tcgportal_bonney --opp tcgportal_calgara \
      --values v2onp=db/_selfplay/cmp_bonney_v2onp.pkl,v5onp=db/_selfplay/cmp_bonney_v5onp.pkl --games 30
"""
import argparse
import sys
import random
import multiprocessing as mp
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import json
from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main, AttackLeader, AttackCharacter, AttachDonToLeader
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI

_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")


def _ana(s):
    p = ROOT / "decks" / f"{s}.analysis.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _mk(slug, gbm, seed):
    return ExploitBeamAI(rng=random.Random(seed), deck_analysis={**_ana(slug), "deck_slug": slug},
                         gbm_path=gbm, beam_width=16, max_depth=10)


def run_one(task):
    deck, opp, gbm, seed = task
    df = seed % 2 == 0
    if df:
        st = setup_game(DeckList.from_json(ROOT/"decks"/f"{deck}.json", _REPO),
                        DeckList.from_json(ROOT/"decks"/f"{opp}.json", _REPO),
                        rng=random.Random(seed), first_player=0, effects_overlay=_OVERLAY,
                        deck1_analysis=_ana(deck), deck2_analysis=_ana(opp)); ei = 0
    else:
        st = setup_game(DeckList.from_json(ROOT/"decks"/f"{opp}.json", _REPO),
                        DeckList.from_json(ROOT/"decks"/f"{deck}.json", _REPO),
                        rng=random.Random(seed), first_player=0, effects_overlay=_OVERLAY,
                        deck1_analysis=_ana(opp), deck2_analysis=_ana(deck)); ei = 1
    play_until_main(st)
    ais = [None, None]; ais[ei] = _mk(deck, gbm, seed); ais[1-ei] = _mk(opp, None, seed+7)
    for i, x in enumerate(ais):
        if hasattr(x, "set_ai_opp"): x.set_ai_opp(ais[1-i])
    atk_leader = atk_char = pump = n = 0
    turns = 0
    while not st.game_over and n < 400:
        me = st.turn_player_idx
        try:
            act = play_one_action(st, ais[me], ais[1-me])
        except Exception:
            break
        if me == ei:
            if isinstance(act, AttackLeader): atk_leader += 1
            elif isinstance(act, AttackCharacter): atk_char += 1
            elif isinstance(act, AttachDonToLeader): pump += 1
        n += 1
    turns = int(getattr(st, "turn_number", 0))
    w = getattr(st, "winner", -1)
    win = 1 if w == ei else 0
    return (win, atk_leader, atk_char, pump, turns)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="tcgportal_bonney")
    ap.add_argument("--opp", default="tcgportal_calgara")
    ap.add_argument("--values", default="v2onp=db/_selfplay/cmp_bonney_v2onp.pkl,v5onp=db/_selfplay/cmp_bonney_v5onp.pkl")
    ap.add_argument("--games", type=int, default=30)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--seed", type=int, default=900)
    a = ap.parse_args()
    vals = {}
    for kv in a.values.split(","):
        k, v = kv.split("="); vals[k.strip()] = (str(ROOT / v.strip()) if v.strip() else None)
    print(f"profile: {a.deck} vs {a.opp} | values={list(vals)} | games={a.games}")
    print(f"{'value':8} {'win%':>6} {'atkLdr':>7} {'atkChr':>7} {'pump':>6} {'turns':>6}  (per game)")
    for name, gbm in vals.items():
        tasks = [(a.deck, a.opp, gbm, a.seed + g) for g in range(a.games)]
        with mp.Pool(min(a.workers, len(tasks))) as p:
            res = p.map(run_one, tasks, chunksize=1)
        g = len(res)
        win = sum(r[0] for r in res) / g * 100
        al = sum(r[1] for r in res) / g
        ac = sum(r[2] for r in res) / g
        pm = sum(r[3] for r in res) / g
        tn = sum(r[4] for r in res) / g
        print(f"{name:8} {win:6.1f} {al:7.1f} {ac:7.1f} {pm:6.1f} {tn:6.1f}")


if __name__ == "__main__":
    main()
