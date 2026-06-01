#!/usr/bin/env python3
"""人間vsAI UX fuzzer: 人間が実際にカードをプレイ + 全 modal を解決する形で多数 game を走らせ、
crash / stuck (同 pending が進まない) / 例外 を検出。 multi-interactive カード + 各 pending_choice
kind を exercise して human-play UX バグを炙り出す。"""
import json
import os
import random
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api.main import _build_human_session, HumanSessionSpec

DECKS = ["cardrush_1342", "cardrush_1385", "cardrush_1392", "cardrush_1399",
         "cardrush_1439", "cardrush_1453", "cardrush_1454", "cardrush_1455",
         "cardrush_1456", "tcgportal_bonney", "tcgportal_calgara", "tcgportal_coby",
         "tcgportal_corazon", "tcgportal_hancock", "tcgportal_op11_luffy", "tcgportal_op13_luffy"]

N_GAMES = int(sys.argv[1]) if len(sys.argv) > 1 else 40


def pick_for(payload, rng):
    kind = payload.get("kind")
    lim = int(payload.get("limit", 1) or 1)
    if kind in ("mulligan_confirm", "mulligan_redrawn"):
        return [0]
    if kind in ("self_hand_discard_pick", "counter_discard_pick", "activate_main_discard_pick"):
        cands = payload.get("candidates", [])
        return list(range(min(lim, len(cands))))
    if kind == "search_top_n":
        cs = payload.get("cards", [])
        matching = [c["idx"] for c in cs if c.get("matches_filter")]
        return matching[:lim] if matching else ([cs[0]["idx"]] if cs and rng.random() < 0.5 else [])
    if kind in ("search_top_n_bottom_reorder", "scry_life_reorder", "scry_deck_reorder"):
        return []  # ID順 fallback
    if kind in ("optional_cost_confirm", "on_attack_optional", "on_opp_attack_optional",
                "end_of_turn_optional", "replace_ko_optional", "reveal_top_play_confirm",
                "life_taken_choice", "view_life_top_choose_position", "option_pick",
                "field_full_select_trash"):
        return [rng.choice([0, 1])] if kind in ("optional_cost_confirm", "replace_ko_optional",
                                                "reveal_top_play_confirm") else [0]
    cands = payload.get("candidates") or payload.get("cards") or []
    if cands:
        return [0] if rng.random() < 0.7 else []
    return []


def play_one(a, b, seed, human_first, rng):
    spec = HumanSessionSpec(deck_a_slug=a, deck_b_slug=b, seed=seed, human_first=human_first)
    s = _build_human_session(spec)
    steps = 0
    last_sig = None
    same_count = 0
    choice_kinds = set()
    while not s.state.game_over and steps < 1200:
        steps += 1
        pk = s.pending_kind
        # stuck 検出: 同一 (pending_kind, payload kind, turn) が連続
        sig = (pk, (s.pending_payload or {}).get("kind"), s.state.turn_number)
        if sig == last_sig:
            same_count += 1
            if same_count > 60:
                return ("STUCK", steps, sig, choice_kinds)
        else:
            same_count = 0
            last_sig = sig
        if pk == "choice":
            ck = (s.pending_payload or {}).get("kind")
            choice_kinds.add(ck)
            s.apply_human_choice(pick_for(s.pending_payload or {}, rng))
        elif pk == "action":
            acts = s.legal_actions_for_human()
            if not acts:
                return ("NO_ACTIONS", steps, None, choice_kinds)
            # 序盤は play/attach/attack を多めに、 たまに EndPhase
            non_end = [x for x in acts if x.get("kind") != "EndPhase"]
            if non_end and rng.random() < 0.8:
                a_pick = rng.choice(non_end)
            else:
                a_pick = next((x for x in acts if x.get("kind") == "EndPhase"), acts[0])
            s.apply_human_action(a_pick["idx"])
        elif pk == "defense":
            # 70% no-block、 たまに blocker
            s.apply_human_defense(None, [])
        else:
            break
    return ("OK" if s.state.game_over else "TIMEOUT", steps, None, choice_kinds)


def main():
    rng = random.Random(7)
    crashes = []
    all_kinds = set()
    results = {"OK": 0, "TIMEOUT": 0, "STUCK": 0, "NO_ACTIONS": 0, "CRASH": 0}
    for g in range(N_GAMES):
        a, b = rng.sample(DECKS, 2)
        seed = rng.randint(1, 10**6)
        hf = rng.random() < 0.5
        try:
            status, steps, sig, cks = play_one(a, b, seed, hf, rng)
            results[status] = results.get(status, 0) + 1
            all_kinds |= cks
            if status in ("STUCK", "NO_ACTIONS", "TIMEOUT"):
                crashes.append((status, a, b, seed, hf, steps, sig))
            print(f"  game {g+1}/{N_GAMES} {status} {a} vs {b} steps={steps}", flush=True)
        except Exception as e:
            results["CRASH"] += 1
            crashes.append(("CRASH", a, b, seed, hf, str(e), traceback.format_exc()))
            print(f"  game {g+1}/{N_GAMES} CRASH {a} vs {b} seed={seed} hf={hf}: {e}", flush=True)
            print(traceback.format_exc(), flush=True)
    print(f"=== fuzz {N_GAMES} games ===")
    print("results:", results)
    print("exercised choice kinds:", sorted(k for k in all_kinds if k))
    if crashes:
        print(f"\n!!! 問題 {len(crashes)} 件:")
        for c in crashes[:15]:
            print("  ", c[:6])
            if c[0] == "CRASH":
                print("    ", c[6].splitlines()[-1] if len(c) > 6 else "")
    else:
        print("\n✓ crash/stuck なし")


if __name__ == "__main__":
    main()
