# -*- coding: utf-8 -*-
"""広いデッキプール (16-pool + archive 126デッキ、 441 unique cards) に 構造オラクルを当てて
16プール外 227 カードの crash/保存則/DON/構造 バグを探す (= 2026-06-05、 カバレッジ拡大)。"""
import sys, glob, random
sys.path.insert(0, ".")
sys.path.insert(0, "scripts")
import fuzz_human_play as F
import hunt_aggressive_combined as A
from engine.deck import CardRepository, DeckList
from engine.human_session import HumanSession
from engine.ai import RandomAI
from collections import Counter

repo = CardRepository.from_json("db/cards.json")
overlay = F.load_effect_overlay("db/card_effects.json") if hasattr(F, "load_effect_overlay") else __import__("engine.effects", fromlist=["load_effect_overlay"]).load_effect_overlay("db/card_effects.json")

# 全 loadable deck の path map
paths = []
for fn in glob.glob("decks/cardrush_*.json") + glob.glob("decks/tcgportal_*.json") \
        + glob.glob("decks/_archive/cardrush_raw/*.json") + glob.glob("decks/_archive/*.json"):
    paths.append(fn)

decks = []
for p in paths:
    try:
        decks.append((p, DeckList.from_json(p, repo)))
    except Exception:
        pass
print(f"loadable decks: {len(decks)}", flush=True)


def build(dl_a, dl_b, seed, hf):
    return HumanSession(deck_a=dl_a, deck_b=dl_b,
                        ai_factory=lambda rng, d=None: RandomAI(rng=rng),
                        seed=seed, effects_overlay=overlay, human_first=hf)


def play(dl_a, dl_b, seed, hf):
    s = build(dl_a, dl_b, seed, hf)
    rng = random.Random(seed)
    steps = 0
    last = None; same = 0
    base_cards = base_don = None
    while not s.state.game_over and steps < 2500:
        steps += 1
        pk = s.pending_kind; pl = s.pending_payload or {}
        sig = (pk, pl.get("kind"), s.state.turn_number,
               len(s.state.players[0].hand), len(s.state.players[1].hand))
        if sig == last:
            same += 1
            if same > 120: return ("STUCK", steps, None)
        else:
            same = 0; last = sig
        if pk == "action":
            if base_cards is None:
                base_cards = A._per_player_card_counts(s.state)
                base_don = [A._don_ledger(p) for p in s.state.players]
            v = A.check_all(s.state, base_cards, base_don)
            if v: return ("ORACLE", steps, f"t{s.state.turn_number} :: {v}")
        try:
            if pk == "action":
                acts = s.legal_actions_for_human()
                if not acts: return ("NO_ACT", steps, None)
                s.apply_human_action(A.pick_action(acts, rng)["idx"])
            elif pk == "choice":
                s.apply_human_choice(A.modal_pick(pl, rng))
            elif pk == "defense":
                A.do_defense(s, pl, rng)
            else: break
        except Exception as e:  # noqa: BLE001
            import traceback
            return ("PY_EXC", steps, f"{type(e).__name__}: {str(e)[:70]} | {traceback.format_exc().splitlines()[-2][:70]}")
    if base_cards is not None:
        v = A.check_all(s.state, base_cards, base_don)
        if v: return ("ORACLE", steps, f"(final) {v}")
    for ln in s.state.log:
        if "engine error" in ln:
            return ("ENGINE_ERROR", steps, ln.split("engine error:")[-1].strip()[:90])
    return ("OK", steps, None)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    res = Counter(); bugs = []; total = 0
    rng = random.Random(99)
    # 各 deck を self-play + ランダム相手で叩く (= 全 deck のカードを exercise)
    for i, (pa, da) in enumerate(decks):
        for j in range(n):
            pb, db = decks[(i + 1 + j) % len(decks)]
            seed = 50000 + i * 17 + j
            st, steps, info = play(da, db, seed, j % 2 == 0)
            res[st] += 1; total += 1
            if st != "OK":
                bugs.append((pa.split("/")[-1], pb.split("/")[-1], seed, st, info))
        if i % 20 == 0:
            print(f"  ... {i}/{len(decks)} | total {total} bugs {len(bugs)}", flush=True)
    print(f"\n=== 広プール構造 hunt {total} 試合 ({len(decks)} decks) ===")
    for k, c in res.most_common(): print(f"  {k}: {c}")
    if bugs:
        print(f"\n!!! 問題 {len(bugs)} 件 (先頭40):")
        for a, b, sd, st, info in bugs[:40]:
            print(f"  ★[{st}] {a} vs {b} #{sd}: {info}")
    sys.exit(1 if bugs else 0)


if __name__ == "__main__":
    main()
