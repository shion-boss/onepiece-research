# -*- coding: utf-8 -*-
"""合成デッキ (色ごとに全カードを50枚ずつ巡回網羅) に構造オラクルを当てて、 どのデッキにも
入らない ~3,850 カードの runtime path バグ (crash/保存則/DON/構造) を探す (= 2026-06-05、
カバレッジ最大化)。 make_deck_from_dict は validation せず構築するので任意カードで deck 化可能。"""
import sys, json, random
sys.path.insert(0, ".")
sys.path.insert(0, "scripts")
import hunt_aggressive_combined as A
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.human_session import HumanSession
from engine.ai import RandomAI
from collections import Counter, defaultdict

repo = CardRepository.from_json("db/cards.json")
overlay = load_effect_overlay("db/card_effects.json")
cards = json.load(open("db/cards.json"))
cardlist = cards if isinstance(cards, list) else cards.get("cards", [])

# 色ごとに leader と 非leader を分類 (= multi-color は各色に登録)
leaders = defaultdict(list)
chars = defaultdict(list)
for c in cardlist:
    col = str(c.get("color", ""))
    cols = col.split("/") if "/" in col else [col]
    for cc in cols:
        if not cc:
            continue
        (leaders if c.get("category") == "LEADER" else chars)[cc].append(c["card_id"])

# 各色: 非leaderカードを50枚ずつ chunk して合成デッキ群を作る (= 全カード網羅)
synth_decks = []  # (name, DeckList)
for col, cl in chars.items():
    if col not in leaders or not leaders[col]:
        continue
    leader = leaders[col][0]
    for ci in range(0, len(cl), 50):
        chunk = cl[ci:ci + 50]
        if len(chunk) < 50:
            chunk = chunk + cl[:50 - len(chunk)]  # 端数は先頭で埋めて50枚に
        dd = {"leader": leader, "main": [{"card_id": cid, "count": 1} for cid in chunk],
              "name": f"synth_{col}_{ci//50}"}
        try:
            synth_decks.append((dd["name"], make_deck_from_dict(dd, repo)))
        except Exception:
            pass
print(f"合成デッキ: {len(synth_decks)} (色ごと×全カード網羅)", flush=True)


def play(dl_a, dl_b, seed, hf):
    s = HumanSession(deck_a=dl_a, deck_b=dl_b,
                     ai_factory=lambda rng, d=None: RandomAI(rng=rng),
                     seed=seed, effects_overlay=overlay, human_first=hf)
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
            if same > 120:
                return ("STUCK", steps, None)
        else:
            same = 0; last = sig
        if pk == "action":
            if base_cards is None:
                base_cards = A._per_player_card_counts(s.state)
                base_don = [A._don_ledger(p) for p in s.state.players]
            v = A.check_all(s.state, base_cards, base_don)
            if v:
                return ("ORACLE", steps, f"t{s.state.turn_number} :: {v}")
        try:
            if pk == "action":
                acts = s.legal_actions_for_human()
                if not acts:
                    return ("NO_ACT", steps, None)
                s.apply_human_action(A.pick_action(acts, rng)["idx"])
            elif pk == "choice":
                s.apply_human_choice(A.modal_pick(pl, rng))
            elif pk == "defense":
                A.do_defense(s, pl, rng)
            else:
                break
        except Exception as e:  # noqa: BLE001
            import traceback
            return ("PY_EXC", steps, f"{type(e).__name__}: {str(e)[:70]} | {traceback.format_exc().splitlines()[-2][:75]}")
    if base_cards is not None:
        v = A.check_all(s.state, base_cards, base_don)
        if v:
            return ("ORACLE", steps, f"(final) {v}")
    for ln in s.state.log:
        if "engine error" in ln:
            return ("ENGINE_ERROR", steps, ln.split("engine error:")[-1].strip()[:90])
    return ("OK", steps, None)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    res = Counter(); bugs = []; total = 0
    for i, (na, da) in enumerate(synth_decks):
        for j in range(n):
            nb, db = synth_decks[(i + 1 + j) % len(synth_decks)]
            seed = 60000 + i * 13 + j
            st, steps, info = play(da, db, seed, j % 2 == 0)
            res[st] += 1; total += 1
            if st != "OK":
                bugs.append((na, nb, seed, st, info))
        if i % 10 == 0:
            print(f"  ... {i}/{len(synth_decks)} | total {total} bugs {len(bugs)}", flush=True)
    print(f"\n=== 合成デッキ構造 hunt {total} 試合 ({len(synth_decks)} decks) ===")
    for k, c in res.most_common():
        print(f"  {k}: {c}")
    if bugs:
        print(f"\n!!! 問題 {len(bugs)} 件 (先頭40):")
        for na, nb, sd, st, info in bugs[:40]:
            print(f"  ★[{st}] {na} vs {nb} #{sd}: {info}")
    sys.exit(1 if bugs else 0)


if __name__ == "__main__":
    main()
