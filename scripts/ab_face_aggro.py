# -*- coding: utf-8 -*-
"""顔攻撃ボーナス(ONEPIECE_FACE_AGGRO)の matchup A/B。 rollout 誤り scan が「配備エネルは顔を
殴らなさすぎ(誤りの74%で最良手=顔攻撃)」と発見 → その fix を検証。

hero=エネル(P0)、 opp=カルガラ(P1、 配備)。 同一 game seed で hero が face-aggro ON / OFF の 2 回を
プレイし、 hero 勝敗を paired 比較。 opp は不変。 = fix が実勝率を上げるかの直接検証。

  AB_W=1.0 AB_N=120 AB_WORKERS=8 .venv/bin/python scripts/ab_face_aggro.py
"""
import sys, os, random, time
import multiprocessing as mp
from pathlib import Path
sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI

ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")
HERO = "cardrush_1454"   # エネル
OPP = "tcgportal_calgara"
W = os.environ.get("AB_W", "1.0")


def _deck(s):
    import json
    return make_deck_from_dict(json.loads((ROOT / "decks" / f"{s}.json").read_text(encoding="utf-8")), _REPO)


def _mk(slug, seed):
    return ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10, deck_analysis={"deck_slug": slug})


def _play(seed, face_on):
    st = setup_game(_deck(HERO), _deck(OPP), rng=random.Random(seed),
                    first_player=seed % 2, effects_overlay=_OVERLAY)
    play_until_main(st)
    ais = [_mk(HERO, seed * 3 + 1), _mk(OPP, seed * 5 + 2)]
    n = 0
    while not st.game_over and st.turn_number < 50 and n < 1500:
        cur = st.turn_player_idx
        if cur == 0 and face_on:   # hero の手番だけ face-aggro を有効化
            os.environ["ONEPIECE_FACE_AGGRO"] = W
        else:
            os.environ.pop("ONEPIECE_FACE_AGGRO", None)
        try:
            play_one_action(st, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    os.environ.pop("ONEPIECE_FACE_AGGRO", None)
    if not st.game_over:
        return None
    w = getattr(st, "winner", -1)
    return 1 if w == 0 else (0 if w == 1 else None)


def _one(seed):
    return (_play(seed, True), _play(seed, False))


def main():
    n = int(os.environ.get("AB_N", "120"))
    workers = int(os.environ.get("AB_WORKERS", "8"))
    seeds = list(range(1000, 1000 + n))
    t0 = time.time()
    with mp.Pool(workers) as p:
        res = p.map(_one, seeds)
    on_w = sum(1 for r in res if r[0] == 1)
    on_n = sum(1 for r in res if r[0] is not None)
    off_w = sum(1 for r in res if r[1] == 1)
    off_n = sum(1 for r in res if r[1] is not None)
    print(f"エネル vs カルガラ  face_aggro W={W}  N={n}  ({time.time()-t0:.0f}s)")
    print(f"  face_aggro ON : hero {on_w}/{on_n} = {100*on_w/max(1,on_n):.0f}%")
    print(f"  face_aggro OFF: hero {off_w}/{off_n} = {100*off_w/max(1,off_n):.0f}%")
    print(f"  Δ = {100*on_w/max(1,on_n) - 100*off_w/max(1,off_n):+.0f}pt")


if __name__ == "__main__":
    main()
