# -*- coding: utf-8 -*-
"""多ターン探索が ドフラ を full-info の「build > race」挙動に寄せるか (2026-07-13、 低分散診断)。
base / multi-turn の hero MAIN 決定を action-kind 別に数え、 顔攻撃(race) vs 展開(build)率を比較。
full-info は case study で build-heavy(顔殴り→展開)と判明済 → multi-turn がそれに寄れば方向◎。

  MB_K=8 MB_WORKERS=12 .venv/bin/python scripts/mt_behavior.py
"""
import sys, os, random, json
import multiprocessing as mp
from collections import Counter
from pathlib import Path
sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main, AttackLeader, AttackCharacter, ActivateMain, PlayCharacter, PlayEvent
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI
ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OV = load_effect_overlay(ROOT / "db" / "card_effects.json")
HERO = os.environ.get("MB_HERO", "cardrush_1342")
OPP = os.environ.get("MB_OPP", "cardrush_1454")


def _deck(s):
    return make_deck_from_dict(json.loads((ROOT / "decks" / f"{s}.json").read_text(encoding="utf-8")), _REPO)


def _kind(a):
    if isinstance(a, AttackLeader): return "atk_leader"
    if isinstance(a, AttackCharacter): return "atk_char"
    if isinstance(a, (PlayCharacter, PlayEvent)): return "build/play"
    if isinstance(a, ActivateMain): return "activate"
    return type(a).__name__


class _Rec(ExploitBeamAI):
    def choose_action(self, state):
        a = super().choose_action(state)
        if getattr(state.phase, "name", "") == "MAIN" and state.turn_player_idx == self._me:
            self.kinds[_kind(a)] += 1
        return a


def _play(seed, kw):
    hp = seed % 2 == 0
    hero = _Rec(rng=random.Random(seed * 3 + 1), beam_width=16, max_depth=10, deck_analysis={"deck_slug": HERO}, **kw)
    hero.kinds = Counter()
    opp = ExploitBeamAI(rng=random.Random(seed * 5 + 2), beam_width=16, max_depth=10, deck_analysis={"deck_slug": OPP})
    if hp:
        st = setup_game(_deck(HERO), _deck(OPP), rng=random.Random(seed), first_player=0, effects_overlay=_OV); ais = [hero, opp]; hero._me = 0
    else:
        st = setup_game(_deck(OPP), _deck(HERO), rng=random.Random(seed), first_player=0, effects_overlay=_OV); ais = [opp, hero]; hero._me = 1
    play_until_main(st)
    n = 0
    while not st.game_over and st.turn_number < 40 and n < 1200:
        cur = st.turn_player_idx
        try:
            play_one_action(st, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    return hero.kinds


def _run(kw):
    k = int(os.environ.get("MB_K", "8"))
    workers = int(os.environ.get("MB_WORKERS", "12"))
    with mp.Pool(workers) as p:
        res = p.starmap(_play, [(s, kw) for s in range(7000, 7000 + k)])
    tot = Counter()
    for c in res:
        tot += c
    return tot


def main():
    configs = [
        ("base(turns=1)", {}),
        ("MT t2 opp+self (best so far)", dict(postopp_turns=2, postopp_opp_value=True, postopp_self_value=True)),
        ("MT t2 opp+self+asym (search×value)", dict(postopp_turns=2, postopp_opp_value=True, postopp_self_value=True, asym_multiturn=True)),
        ("MT t3 opp+self+asym", dict(postopp_turns=3, postopp_opp_value=True, postopp_self_value=True, asym_multiturn=True)),
    ]
    print(f"{HERO} vs {OPP}  hero MAIN 決定の action-kind 分布\n")
    for label, kw in configs:
        tot = _run(kw)
        N = sum(tot.values())
        atk_l = tot.get("atk_leader", 0)
        build = tot.get("build/play", 0)
        print(f"{label:24s} 決定{N}: 顔攻撃(race)={100*atk_l/max(1,N):4.0f}%  展開(build)={100*build/max(1,N):4.0f}%  "
              f"| {dict(tot.most_common())}")


if __name__ == "__main__":
    main()
