# -*- coding: utf-8 -*-
"""v5(matchup条件付き) と v2(agnostic) が *同一局面で異なる手* を選ぶ頻度を測る診断。

deploy A/B が null だった時の機構解明用:
  - 一致率が高い (~95%+) → v5 は手を変えず value の *水準* だけ変えた = matchup tag は
    手選択にとって冗長 (= post-opp 盤面が既に相手を encode、 構造的 null)。
  - 一致率が低いのに deploy null → 「手は変わるが良くならない」(= 条件付けが noisy)。

deck を v2-AI で打たせて trajectory を作り、 各 deck 決定局面で v5-AI に同一 clone から
choose_action させて選択手を比較する。 beam は moderate(速度、 相対比較なので可)。

  .venv/bin/python scripts/matchup_value_move_divergence.py --deck tcgportal_bonney \
      --opps tcgportal_calgara,cardrush_1385,cardrush_1342 --prefix mcab_bonney_ --games 12
"""
import argparse
import sys
import random
import multiprocessing as mp
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import json
from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main, apply_action
from engine.ai import play_one_action
from engine.plan_search import fast_clone
from engine.exploit_beam_ai import ExploitBeamAI

_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")


def _ana(s):
    p = ROOT / "decks" / f"{s}.analysis.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _canon(act):
    """action を比較可能な canonical key に。 type + 主要 attr (target/card ids)。"""
    if act is None:
        return ("None",)
    t = type(act).__name__
    keys = []
    for attr in ("card_id", "target_id", "attacker_id", "defender_id", "target", "index", "amount"):
        v = getattr(act, attr, None)
        if v is not None and not callable(v):
            keys.append((attr, str(v)))
    return (t, tuple(keys))


def _mk(slug, gbm, seed):
    ai = ExploitBeamAI(rng=random.Random(seed), deck_analysis={**_ana(slug), "deck_slug": slug},
                       gbm_path=gbm, beam_width=8, max_depth=6)
    return ai


def run_one(task):
    deck, opp, prefix, seed = task
    v2 = str(ROOT / "db" / "_selfplay" / f"{prefix}v2.pkl")
    v5 = str(ROOT / "db" / "_selfplay" / f"{prefix}v5.pkl")
    deck_first = seed % 2 == 0
    if deck_first:
        st = setup_game(DeckList.from_json(ROOT / "decks" / f"{deck}.json", _REPO),
                        DeckList.from_json(ROOT / "decks" / f"{opp}.json", _REPO),
                        rng=random.Random(seed), first_player=0, effects_overlay=_OVERLAY,
                        deck1_analysis=_ana(deck), deck2_analysis=_ana(opp))
        ei = 0
    else:
        st = setup_game(DeckList.from_json(ROOT / "decks" / f"{opp}.json", _REPO),
                        DeckList.from_json(ROOT / "decks" / f"{deck}.json", _REPO),
                        rng=random.Random(seed), first_player=0, effects_overlay=_OVERLAY,
                        deck1_analysis=_ana(opp), deck2_analysis=_ana(deck))
        ei = 1
    play_until_main(st)
    # behavior policy = v2 AI for the deck; opp = deployed
    deck_ai = _mk(deck, v2, seed)
    opp_ai = _mk(opp, None, seed + 7)
    ais = [None, None]; ais[ei] = deck_ai; ais[1 - ei] = opp_ai
    for i, x in enumerate(ais):
        if hasattr(x, "set_ai_opp"):
            x.set_ai_opp(ais[1 - i])
    same = diff = 0
    n = 0
    while not st.game_over and n < 400:
        me = st.turn_player_idx
        if me == ei:
            # query v5 on a clone from same state, compare to v2's pick
            try:
                clone = fast_clone(st)
                v5_ai = _mk(deck, v5, seed)
                if hasattr(v5_ai, "set_ai_opp"):
                    v5_ai.set_ai_opp(_mk(opp, None, seed + 7))
                a5 = v5_ai.choose_action(clone)
                a2 = deck_ai.choose_action(st)
                if _canon(a2) == _canon(a5):
                    same += 1
                else:
                    diff += 1
                # apply v2's pick to continue the v2 trajectory
                apply_action(st, a2)
            except Exception:
                try:
                    play_one_action(st, ais[me], ais[1 - me])
                except Exception:
                    break
        else:
            try:
                play_one_action(st, ais[me], ais[1 - me])
            except Exception:
                break
        n += 1
    return (same, diff)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="tcgportal_bonney")
    ap.add_argument("--opps", default="tcgportal_calgara,cardrush_1385,cardrush_1342,cardrush_1454,cardrush_1456")
    ap.add_argument("--prefix", default=None)
    ap.add_argument("--games", type=int, default=20)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--seed", type=int, default=4242)
    a = ap.parse_args()
    prefix = a.prefix if a.prefix else f"mcab_{a.deck}_"
    opps = [s.strip() for s in a.opps.split(",")]
    tasks = [(a.deck, opps[g % len(opps)], prefix, a.seed + g) for g in range(a.games)]
    with mp.Pool(min(a.workers, len(tasks))) as p:
        res = p.map(run_one, tasks, chunksize=1)
    same = sum(r[0] for r in res); diff = sum(r[1] for r in res)
    tot = same + diff
    print(f"=== {a.deck}: v5 vs v2 手選択の一致 (decision states={tot}, games={a.games}) ===")
    print(f"  一致={same} ({same/max(1,tot)*100:.1f}%)  相違={diff} ({diff/max(1,tot)*100:.1f}%)")
    if tot:
        if diff / tot < 0.05:
            print("  → ほぼ一致 = v5 は手を変えず value 水準だけ変えた = matchup tag は手選択に冗長 (構造的 null)")
        elif diff / tot < 0.20:
            print("  → 一部相違 = 限定的に手を変える (deploy が null なら『変わるが良くならない』)")
        else:
            print("  → 多く相違 = 手は大きく変わる (deploy が null なら条件付けが noisy/誤方向)")


if __name__ == "__main__":
    main()
