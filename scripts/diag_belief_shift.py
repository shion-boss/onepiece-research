# -*- coding: utf-8 -*-
"""ceiling(feature-reveal)の決定分解 (2026-07-12、 ohtsuki「must-react vs gameplan の判断」)。

hero=feature-reveal RolloutRerankAI で対戦させ、 各 MAIN 決定で「真の相手手札特徴を知ると
base(配備value)の手が変わるか」をログ。 = +11.25 天井が **どの決定に集中しているか** を可視化。
shift 率が低く特定 action/場面に集中 → 「相手手札で行動を変える決定」は局在(ohtsuki 仮説)。

  DBG_N=20 DBG_CAND=4 DBG_RO=5 DBG_WORKERS=14 .venv/bin/python scripts/diag_belief_shift.py
"""
import sys, os, random, json
import multiprocessing as mp
from collections import Counter, defaultdict
from pathlib import Path
sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI
from engine.rollout_rerank_ai import RolloutRerankAI
from engine.hand_feature_predictor import FEATURES

ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OV = load_effect_overlay(ROOT / "db" / "card_effects.json")
HERO = os.environ.get("DBG_HERO", "cardrush_1342")
OPP = os.environ.get("DBG_OPP", "cardrush_1454")
CAND = int(os.environ.get("DBG_CAND", "4"))
RO = int(os.environ.get("DBG_RO", "5"))
TURN_CAP = 40


def _deck(s):
    return make_deck_from_dict(json.loads((ROOT / "decks" / f"{s}.json").read_text(encoding="utf-8")), _REPO)


def _beam(slug, seed):
    return ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10, deck_analysis={"deck_slug": slug})


def _one(seed):
    hero = RolloutRerankAI(rng=random.Random(seed * 3 + 1), beam_width=16, max_depth=10,
                           deck_analysis={"deck_slug": HERO}, ro_cand=CAND, ro_n=RO,
                           ro_opp_slug=OPP, ro_determinize=True, ro_feature_reveal=True,
                           ro_log_shifts=True)
    if seed % 2 == 0:
        st = setup_game(_deck(HERO), _deck(OPP), rng=random.Random(seed), first_player=0, effects_overlay=_OV)
        ais = [hero, _beam(OPP, seed * 5 + 2)]
    else:
        st = setup_game(_deck(OPP), _deck(HERO), rng=random.Random(seed), first_player=0, effects_overlay=_OV)
        ais = [_beam(OPP, seed * 5 + 2), hero]
    play_until_main(st)
    n = 0
    while not st.game_over and st.turn_number < TURN_CAP and n < 1500:
        cur = st.turn_player_idx
        try:
            play_one_action(st, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    return hero.shift_log


def main():
    n = int(os.environ.get("DBG_N", "20"))
    workers = int(os.environ.get("DBG_WORKERS", "14"))
    seeds = list(range(5000, 5000 + n))
    with mp.Pool(workers) as p:
        logs = p.map(_one, seeds)
    dec = [d for g in logs for d in g]
    N = len(dec)
    shifts = [d for d in dec if d["shifted"]]
    print(f"hero=feature-reveal {HERO} vs {OPP}  games={n}  MAIN決定={N}")
    print(f"belief が base の手を変えた率 (shift) = {len(shifts)}/{N} = {100*len(shifts)/max(1,N):.1f}%")
    print()
    # shift を base_kind→chosen_kind でクロス集計
    print("=== shift した決定の内訳 (base_kind → chosen_kind) ===")
    trans = Counter((d["base_kind"], d["chosen_kind"]) for d in shifts)
    for (bk, ck), c in trans.most_common(12):
        print(f"  {bk:12s} -> {ck:12s} : {c}")
    print()
    # shift 決定での真特徴の分布 (どの特徴の有無が行動を変えたか)
    print("=== shift 決定 vs 非shift 決定での 真の相手手札特徴 出現率 ===")
    def rate(rows, f):
        return 100 * sum(r["true"][f] for r in rows) / max(1, len(rows))
    non = [d for d in dec if not d["shifted"]]
    print(f"  {'feature':12s} {'shift時':>8s} {'非shift時':>9s}")
    for f in FEATURES:
        print(f"  {f:12s} {rate(shifts,f):7.0f}% {rate(non,f):8.0f}%")
    print()
    # turn 帯別 shift 率
    print("=== turn 帯別 shift 率 ===")
    by_turn = defaultdict(lambda: [0, 0])
    for d in dec:
        b = "early(<=4)" if d["turn"] <= 4 else ("mid(5-8)" if d["turn"] <= 8 else "late(>=9)")
        by_turn[b][0] += 1 if d["shifted"] else 0
        by_turn[b][1] += 1
    for b in ("early(<=4)", "mid(5-8)", "late(>=9)"):
        s, t = by_turn[b]
        print(f"  {b:12s}: {s}/{t} = {100*s/max(1,t):.0f}%")


if __name__ == "__main__":
    main()
