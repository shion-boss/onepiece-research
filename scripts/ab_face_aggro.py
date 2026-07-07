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


TURN_CAP = int(os.environ.get("AB_TURN_CAP", "40"))  # 公式 floor_rule 40 ターン(超過=both_lose=引分)


def _play(seed, face_on):
    # ⭐ P0/P1 を seed で均等化(run_matchup と同じ = engine の going-first/P0 優位 bias を除去)。
    # 偶数 seed: Enel=P0、 奇数 seed: Enel=P1(デッキ順入替)。 hero の手番だけ face-aggro。
    hero_p0 = (seed % 2 == 0)
    if hero_p0:
        st = setup_game(_deck(HERO), _deck(OPP), rng=random.Random(seed), first_player=0, effects_overlay=_OVERLAY)
        ais = [_mk(HERO, seed * 3 + 1), _mk(OPP, seed * 5 + 2)]; hero_idx = 0
    else:
        st = setup_game(_deck(OPP), _deck(HERO), rng=random.Random(seed), first_player=0, effects_overlay=_OVERLAY)
        ais = [_mk(OPP, seed * 5 + 2), _mk(HERO, seed * 3 + 1)]; hero_idx = 1
    play_until_main(st)
    n = 0
    while not st.game_over and st.turn_number < TURN_CAP and n < 1500:
        cur = st.turn_player_idx
        if cur == hero_idx and face_on:   # hero の手番だけ face-aggro を有効化
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
        return "draw"
    w = getattr(st, "winner", -1)
    return 1 if w == hero_idx else (0 if w == (1 - hero_idx) else "draw")


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
    on_d = sum(1 for r in res if r[0] == "draw")
    off_w = sum(1 for r in res if r[1] == 1)
    off_d = sum(1 for r in res if r[1] == "draw")
    # 公式ルール: 勝率 = hero_wins / N_total(引分は非勝ち)
    print(f"エネル vs カルガラ  face_aggro W={W}  N={n}  TURN_CAP={TURN_CAP}  ({time.time()-t0:.0f}s)")
    print(f"  face_aggro ON : hero勝ち {on_w}/{n} = {100*on_w/n:.0f}%  (引分 {on_d})")
    print(f"  face_aggro OFF: hero勝ち {off_w}/{n} = {100*off_w/n:.0f}%  (引分 {off_d})")
    print(f"  Δ(hero勝率) = {100*on_w/n - 100*off_w/n:+.0f}pt")


if __name__ == "__main__":
    main()
