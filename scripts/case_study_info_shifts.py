# -*- coding: utf-8 -*-
"""full-info(相手手札公開)が base の手を変える決定を具体 dump して読む (2026-07-13、 ohtsuki
「相手の手札の情報は何の判断に影響を与えているか」)。 集計でなく実例を読んで機構を理解する。

  CS_N=10 CS_CAND=5 CS_RO=8 CS_WORKERS=12 .venv/bin/python scripts/case_study_info_shifts.py
"""
import sys, os, random, json
import multiprocessing as mp
from pathlib import Path
sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI
from engine.rollout_rerank_ai import RolloutRerankAI

ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OV = load_effect_overlay(ROOT / "db" / "card_effects.json")
HERO = os.environ.get("CS_HERO", "cardrush_1342")
OPP = os.environ.get("CS_OPP", "cardrush_1454")
CAND = int(os.environ.get("CS_CAND", "5"))
RO = int(os.environ.get("CS_RO", "8"))


def _deck(s):
    return make_deck_from_dict(json.loads((ROOT / "decks" / f"{s}.json").read_text(encoding="utf-8")), _REPO)


def _beam(slug, seed):
    return ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10, deck_analysis={"deck_slug": slug})


def _one(seed):
    hero = RolloutRerankAI(rng=random.Random(seed * 3 + 1), beam_width=16, max_depth=10,
                           deck_analysis={"deck_slug": HERO}, ro_cand=CAND, ro_n=RO,
                           ro_opp_slug=OPP, ro_determinize=True, ro_reveal_p=1.0,  # full-info(覗く)
                           ro_log_shifts=True)
    if seed % 2 == 0:
        st = setup_game(_deck(HERO), _deck(OPP), rng=random.Random(seed), first_player=0, effects_overlay=_OV)
        ais = [hero, _beam(OPP, seed * 5 + 2)]
    else:
        st = setup_game(_deck(OPP), _deck(HERO), rng=random.Random(seed), first_player=0, effects_overlay=_OV)
        ais = [_beam(OPP, seed * 5 + 2), hero]
    play_until_main(st)
    n = 0
    while not st.game_over and st.turn_number < 40 and n < 1500:
        cur = st.turn_player_idx
        try:
            play_one_action(st, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    return [d for d in hero.shift_log if d["shifted"]]


def main():
    n = int(os.environ.get("CS_N", "10"))
    workers = int(os.environ.get("CS_WORKERS", "12"))
    with mp.Pool(workers) as p:
        res = p.map(_one, range(6000, 6000 + n))
    shifts = [d for g in res for d in g]
    print(f"=== full-info が base の手を変えた決定 {len(shifts)} 件 ({HERO} vs {OPP}, {n}game, CAND{CAND} RO{RO}) ===\n")
    # base→chosen の型遷移で分類して代表例を出す
    from collections import defaultdict
    groups = defaultdict(list)
    for d in shifts:
        groups[(d["base_kind"], d["chosen_kind"])].append(d)
    for key in sorted(groups, key=lambda k: -len(groups[k])):
        bk, ck = key
        ds = groups[key]
        print(f"\n########## {bk} → {ck}  ({len(ds)}件) ##########")
        for d in ds[:4]:  # 各型 最大4例
            print(f"  T{d['turn']} life自{d['me_life']}/敵{d['opp_life']} DON{d['me_don']}")
            print(f"    base : {d['base_move']}")
            print(f"    →info: {d['chosen_move']}")
            print(f"    自盤面: {d['me_board']}")
            print(f"    敵盤面: {d['opp_board']}")
            print(f"    敵真手札: {d['opp_TRUE_hand']}")
            print(f"    真特徴: {[f for f,v in d['true'].items() if v]}")
            print()


if __name__ == "__main__":
    main()
