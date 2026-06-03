#!/usr/bin/env python3
"""層1 probe: fine-board 数 vs 抽象 signature 数 の collapse 比を実測。

measure_plan_enumeration は到達盤面 (fine) を数えるが、 ohtsuki「プラン」 = 抽象 signature
(= 対象 iid を落とした token 列)。 fine が高turnで数千でも、 抽象に畳めば library 規模は
ずっと小さいはず。 その collapse 比と例を出す。
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import Phase, setup_game, play_until_main
from engine.ai import GreedyAI, play_one_action
from engine.turn_plan_enumerator import enumerate_turn_plans

_REPO = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(REPO_ROOT / "db" / "card_effects.json")


def _load(slug):
    return make_deck_from_dict(
        json.loads((REPO_ROOT / "decks" / f"{slug}.json").read_text(encoding="utf-8")), _REPO
    )


def main():
    slug = sys.argv[1] if len(sys.argv) > 1 else "cardrush_1342"
    probe_turns = {4, 6, 8, 9, 10}
    deck = _load(slug)
    rng = random.Random(7)
    state = setup_game(deck, _load(slug), rng=rng, first_player=0, effects_overlay=_OVERLAY)
    play_until_main(state)
    ais = [GreedyAI(random.Random(11)), GreedyAI(random.Random(12))]
    enum_def = GreedyAI(random.Random(13))

    seen = set()
    n_act = 0
    while not state.game_over and n_act < 600 and probe_turns:
        me = state.turn_player_idx
        key = (state.turn_number, me)
        if state.phase == Phase.MAIN and key not in seen and state.turn_number in probe_turns:
            seen.add(key)
            probe_turns.discard(state.turn_number)
            t0 = time.perf_counter()
            plans, st = enumerate_turn_plans(state, me, defender_ai=enum_def, node_cap=40000)
            dt = time.perf_counter() - t0
            print(f"\n===== T{state.turn_number} actor={me} don={state.players[me].don_active} "
                  f"({dt:.1f}s, {'CAPPED' if st['capped'] else 'complete'}) =====")
            print(f"  distinct plans (multiset) : {st['distinct_plans']:>6}  <- library 規模")
            print(f"  canonical fine boards     : {st['distinct_boards']:>6}  (参考: 束縛変種込み)")
            print(f"  nodes expanded            : {st['nodes_expanded']:>6}")
            # 例: ordered signature を 5 個
            uniq = []
            seen_sig = set()
            for p in plans:
                if p.signature not in seen_sig:
                    seen_sig.add(p.signature)
                    uniq.append(p.signature)
                if len(uniq) >= 5:
                    break
            print("  例 (ordered signatures):")
            for s in uniq:
                print(f"    {list(s)}")
        play_one_action(state, ais[me], ais[1 - me])
        n_act += 1


if __name__ == "__main__":
    main()
