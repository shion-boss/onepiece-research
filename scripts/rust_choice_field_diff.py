#!/usr/bin/env python
"""選択列挙 ON の MISMATCH を **canonical field 単位** で diff して原因を pinpoint する。

⭐ なぜ要るか: `rust_choice_diag.py` は 「選択列がどう違うか」 で分類するが、
   **選択列が同形なのに digest だけ違う** 型 (= buff / 一時フラグ / 順序の乖離) は
   そこで止まってしまう。 粗い fingerprint (hand / deck / trash / life) でも見えない差が
   あるので、 Rust の canonical blob を丸ごと受け取って Python と field 単位で突き合わせる。

   2026-08-22 の 「発動コストの選択」 解消では、 これで
     - `.players[0].leader.turn_buff` (= 選択待ち中に発火した【相手のアタック時】)
     - `.last_chara_ko_victim_card` (= 中断中に畳んではいけない transient)
   が 1 行で判り、 推測ベースの調査が終わった。

  .venv/bin/python scripts/rust_choice_field_diff.py --games 16
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import optcg_engine as eng  # noqa: E402

from engine.core import reset_iid  # noqa: E402
from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.effects import load_effect_overlay  # noqa: E402
from engine.game import apply_action, legal_actions, play_until_main, setup_game  # noqa: E402
from engine.state_snapshot import (  # noqa: E402
    canonical_state,
    diff_canonical,
    full_dump,
    state_digest,
)
from scripts.rust_parity_check import _enc  # noqa: E402

POLICY_K = 1


def run(games: int, seed: int, max_steps: int, show: int) -> int:
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    eng.load_overlay(str(ROOT / "db" / "card_effects.json"))
    decks = [p for p in sorted((ROOT / "decks").glob("cardrush_*.json"))
             if ".analysis." not in p.name and ".target_v" not in p.name][:6]
    fields: Counter = Counter()
    n_mm = 0
    for gi in range(games):
        a, b = decks[gi % len(decks)], decks[(gi + 1) % len(decks)]
        reset_iid()
        st = setup_game(DeckList.from_json(str(a), repo), DeckList.from_json(str(b), repo),
                        rng=random.Random(seed + gi), first_player=gi % 2,
                        effects_overlay=overlay)
        play_until_main(st)
        st.choice_enumeration = True
        for _ in range(max_steps):
            if st.game_over:
                break
            acts = legal_actions(st)
            if not acts:
                break
            act = acts[min(1, len(acts) - 1)]
            enc = _enc(st, act)
            if enc.get("t") == "?":
                try:
                    apply_action(st, act)
                except Exception:  # noqa: BLE001
                    break
                continue
            js = json.dumps(full_dump(st))
            try:
                rs = json.loads(eng.apply_action_choice_policy_trace(
                    js, json.dumps(enc), POLICY_K))
            except Exception:  # noqa: BLE001
                rs = {"err": "bail"}
            try:
                apply_action(st, act)
                guard = 0
                while st.pending_choice is not None and guard < 40:
                    guard += 1
                    opts = legal_actions(st)
                    if not opts:
                        st.pending_choice = None
                        break
                    apply_action(st, opts[POLICY_K % len(opts)])
            except Exception:  # noqa: BLE001
                break
            if "err" in rs or rs.get("digest") == state_digest(st):
                continue
            n_mm += 1
            diffs = diff_canonical(canonical_state(st), rs["blob"])
            if n_mm <= show:
                kinds = [t["kind"] for t in (rs.get("trace") or [])]
                print(f"--- MISMATCH #{n_mm} g{gi} {enc.get('t')} choices={kinds}")
                for d in diffs[:8]:
                    print("   ", str(d)[:300])
            for d in diffs[:8]:
                fields[str(d).split(",")[0].strip("(' ")] += 1
    print(f"\n=== MISMATCH {n_mm} 件 / field 別 (= (field, python, rust)) ===")
    for k, v in fields.most_common(20):
        print(f"  {v:3d}  {k}")
    return n_mm


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=16)
    ap.add_argument("--seed", type=int, default=500)
    ap.add_argument("--max-steps", type=int, default=300)
    ap.add_argument("--show", type=int, default=10)
    args = ap.parse_args()
    run(args.games, args.seed, args.max_steps, args.show)


if __name__ == "__main__":
    main()
