#!/usr/bin/env python
"""選択列挙 (= 効果中の選択を探索に載せる) の A/B。

⭐ 何を測るか: engine には 「人間なら選べるが AI は固定ヒューリスティックで決めている」
   箇所が 50 箇所あり、 探索 (plan_search) は legal_actions しか分岐源にしていないので
   それらは探索の外にあった (実測 24 game で 1,483 件 ≒ 62 件/game)。
   ResolveChoice アクション + `state.choice_enum_idxs` で **片側だけ** 選択を探索させ、
   勝率差を測る。

⚠ [[feedback_ab_harness_balance_player_index]]: 席 (P0/P1) を固定すると 30-50pt の bias が
   出るので、 **hero を P0/P1 で半分ずつ** 走らせる。
⚠ [[feedback_ab_statistical_power]]: 配備 gate は N>=60-100。

  .venv/bin/python scripts/ab_choice_search.py --deck-a cardrush_1342 --deck-b cardrush_1385 -n 40
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import game as G  # noqa: E402
from engine import harness as H  # noqa: E402
from engine.deck import CardRepository, DeckList  # noqa: E402


def _patch_setup(hero_idx: int | None):
    """setup_game を包んで hero だけ選択列挙にする。 hero_idx=None なら両者 OFF。"""
    orig = G.setup_game

    def _sg(*a, **kw):
        st = orig(*a, **kw)
        if hero_idx is not None:
            st.choice_enumeration = True
            st.choice_enum_idxs = (hero_idx,)
        return st

    G.setup_game = _sg
    H.setup_game = _sg
    return orig


def _restore(orig):
    G.setup_game = orig
    H.setup_game = orig


def run(deck_a: str, deck_b: str, n: int, seed: int) -> None:
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    da = DeckList.from_json(str(ROOT / "decks" / f"{deck_a}.json"), repo)
    db = DeckList.from_json(str(ROOT / "decks" / f"{deck_b}.json"), repo)
    half = max(1, n // 2)

    def _play(hero_seat: int | None, d1, d2, games: int, sd: int):
        orig = _patch_setup(hero_seat)
        try:
            return H.run_matchup(d1, d2, n_games=games, seed=sd)
        finally:
            _restore(orig)

    # hero = 選択探索あり。 席を入れ替えて 2 回走らせる (= P0/P1 bias 消し)
    r0 = _play(0, da, db, half, seed)          # hero = P0 (deck_a 側)
    r1 = _play(1, db, da, half, seed + 1)      # hero = P1 (deck_a 側、 席交換)
    hero_wins = r0.deck1_wins + r1.deck2_wins
    hero_games = r0.n_games + r1.n_games

    b0 = _play(None, da, db, half, seed)
    b1 = _play(None, db, da, half, seed + 1)
    base_wins = b0.deck1_wins + b1.deck2_wins
    base_games = b0.n_games + b1.n_games

    hw = hero_wins / max(hero_games, 1)
    bw = base_wins / max(base_games, 1)
    print(f"=== 選択列挙 A/B  {deck_a} vs {deck_b}  (席入替済) ===")
    print(f"  選択探索 ON  : {hero_wins}/{hero_games} = {hw:.1%}")
    print(f"  選択探索 OFF : {base_wins}/{base_games} = {bw:.1%}  (= 従来のヒューリスティック)")
    print(f"  差分         : {(hw - bw) * 100:+.1f}pt")
    print(f"  ⚠ N={hero_games} 。 配備判断には N>=60-100 が要る "
          f"([[feedback_ab_statistical_power]])")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck-a", default="cardrush_1342")
    ap.add_argument("--deck-b", default="cardrush_1385")
    ap.add_argument("-n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()
    run(args.deck_a, args.deck_b, args.n, args.seed)


if __name__ == "__main__":
    main()
