#!/usr/bin/env python3
"""multi-interactive do-list カード (1 do-list に複数 human-interactive primitive) を
人間 context で各 when を発火し、 chained pending_choice が全て順に解決し効果が完遂するか検証。
continuation fix (シャルリア宮) の全 43 カード横展開確認。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.deck import CardRepository
from engine.effects import (load_effect_overlay, trigger_on_play, trigger_main_event,
                            resolve_pending_choice, trigger_on_attack)
from engine.core import GameState, Player, InPlay, Phase
import random

repo = CardRepository.from_json("db/cards.json")
ov = load_effect_overlay("db/card_effects.json")
cards = {c.card_id if hasattr(c, "card_id") else c["card_id"]: c
         for c in json.load(open("db/cards.json"))}
raw = {c["card_id"]: c for c in json.load(open("db/cards.json"))}

INTERACT = {"search_top_n", "search", "search_from_trash", "play_from_hand", "play_from_trash",
            "play_from_hand_or_trash", "play_event_from_hand", "trash_self_hand_random",
            "summon_from_deck", "ko", "rest", "return_to_hand", "return_to_deck_bottom",
            "optional_cost_then", "reveal_top_play", "life_to_hand", "hand_to_self_life"}
import re
def base(c): return re.sub(r"_(p|r)\d+$", "", c)

# 複数 interactive primitive を持つ base + when
targets = {}
for cid, b in ov.items() if isinstance(ov, dict) else []:
    pass
overlay = json.load(open("db/card_effects.json"))
for cid, b in overlay.items():
    if not isinstance(b, list) or base(cid) != cid:
        continue
    for e in b:
        do = e.get("do", []) or []
        ic = [list(p.keys())[0] for p in do if isinstance(p, dict) and p and list(p.keys())[0] in INTERACT]
        if len(ic) >= 2:
            targets.setdefault(cid, []).append(e.get("when"))


def make_state(card_id):
    p1 = Player(name="P0", leader=InPlay.of(repo.get("OP13-079"), sickness=False))
    p2 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    # 多様な deck/hand/trash (= filter を満たす候補を確保)
    pool = ["OP01-013", "OP01-016", "OP02-013", "OP05-117", "OP13-086"]
    p1.deck = [repo.get(x) for x in pool] * 6
    p1.hand = [repo.get("OP01-013"), repo.get("OP01-016"), repo.get("OP02-013")]
    p1.trash = [repo.get("OP01-013"), repo.get("OP02-013")] * 3
    p1.don_active = 8
    st = GameState(players=[p1, p2], phase=Phase.MAIN, rng=random.Random(1), effects_overlay=ov)
    st.human_player_idx = 0
    st.turn_number = 3
    st.turn_player_idx = 0
    return st, p1, p2


problems = []
checked = 0
for cid, whens in sorted(targets.items()):
    for when in set(whens):
        if when not in ("on_play", "main"):
            continue  # on_play/main の発火が安定 (activate_main は cost path 別)
        checked += 1
        st, me, opp = make_state(cid)
        cd = repo.get(cid)
        try:
            if when == "on_play":
                ip = InPlay.of(cd, sickness=True)
                me.characters.append(ip)
                trigger_on_play(st, me, opp, ip, ov)
            else:  # main (event)
                trigger_main_event(st, me, opp, cd, ov)
            # 全 pending_choice を順に解決 (stuck/loss 検出)
            steps = 0
            kinds = []
            while st.pending_choice is not None and steps < 30:
                steps += 1
                pl = st.pending_choice
                k = pl.get("kind")
                kinds.append(k)
                lim = int(pl.get("limit", 1) or 1)
                if k in ("self_hand_discard_pick", "counter_discard_pick"):
                    cs = pl.get("candidates", [])
                    picks = list(range(min(lim, len(cs))))
                elif k == "search_top_n":
                    cs = pl.get("cards", [])
                    m = [c["idx"] for c in cs if c.get("matches_filter")]
                    picks = m[:lim] if m else []
                else:
                    cs = pl.get("candidates") or pl.get("cards") or []
                    picks = [0] if cs else []
                resolve_pending_choice(st, picks)
            if st.pending_choice is not None:
                problems.append((cid, when, "STUCK", kinds))
        except Exception as ex:
            import traceback
            problems.append((cid, when, "CRASH:" + str(ex)[:60], traceback.format_exc().splitlines()[-1]))

print(f"checked {checked} (card,when) of {len(targets)} multi-interactive cards")
if problems:
    print(f"!!! 問題 {len(problems)}:")
    for p in problems:
        print("  ", p)
else:
    print("✓ 全 multi-interactive カードで chain 完遂 (stuck/crash なし)")
