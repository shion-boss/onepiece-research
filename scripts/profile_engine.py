"""engine 速度 profiling: ExploitBeam の 1 game を cProfile で計測し hotspot を特定。

  .venv/bin/python scripts/profile_engine.py --turns 1 --games 1 --opp tcgportal_calgara
  .venv/bin/python scripts/profile_engine.py --turns 2 --games 1 --opp tcgportal_bonney --value

hotspot(cumtime 上位)を見て、 最適化の対象を決める(推測でなく計測)。
"""
from __future__ import annotations
import argparse, cProfile, pstats, io, os, random, time
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def run_games(deck, opp, turns, games, opp_value):
    from engine.deck import CardRepository, make_deck_from_dict
    from engine.effects import load_effect_overlay
    from engine.game import setup_game, play_until_main
    from engine.ai import play_one_action
    from engine.exploit_beam_ai import ExploitBeamAI
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")
    def dk(s):
        return make_deck_from_dict(__import__("json").loads((ROOT / "decks" / f"{s}.json").read_text()), repo)
    dt, do = dk(deck), dk(opp)
    n_moves = 0
    for g in range(games):
        st = setup_game(dt, do, rng=random.Random(g), first_player=g % 2, effects_overlay=ov)
        play_until_main(st)
        a0 = ExploitBeamAI(rng=random.Random(1), deck_analysis={"deck_slug": deck}, postopp_turns=turns)
        a1 = ExploitBeamAI(rng=random.Random(2), deck_analysis={"deck_slug": opp}, postopp_turns=1)
        if opp_value:
            a0._postopp_opp_value = True
        ais = [a0, a1]
        k = 0
        while not st.game_over and st.turn_number < 50 and k < 1500:
            try:
                play_one_action(st, ais[st.turn_player_idx], ais[1 - st.turn_player_idx])
            except Exception as e:
                print("err", e); break
            k += 1; n_moves += 1
    return n_moves


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="cardrush_1454")
    ap.add_argument("--opp", default="tcgportal_calgara")
    ap.add_argument("--turns", type=int, default=1)
    ap.add_argument("--games", type=int, default=1)
    ap.add_argument("--value", action="store_true", help="turns>1 の相手/自分 rollout を value 誘導")
    ap.add_argument("--top", type=int, default=25)
    a = ap.parse_args()
    if a.value:
        os.environ["ONEPIECE_POSTOPP_SELF_VALUE"] = "1"
    pr = cProfile.Profile()
    t0 = time.time()
    pr.enable()
    n_moves = run_games(a.deck, a.opp, a.turns, a.games, a.value)
    pr.disable()
    el = time.time() - t0
    print(f"\n=== {a.games} game(s), turns={a.turns}, value={a.value}: {el:.1f}s, {n_moves} moves, "
          f"{el/max(1,n_moves)*1000:.0f}ms/move ===")
    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats("cumulative")
    ps.print_stats(a.top)
    # tottime 上位も(自身の時間 = 最適化対象)
    ps2 = pstats.Stats(pr, stream=s).sort_stats("tottime")
    s.write("\n===== TOTTIME 上位(自身の時間=最適化対象) =====\n")
    ps2.print_stats(a.top)
    print(s.getvalue())


if __name__ == "__main__":
    main()
