# -*- coding: utf-8 -*-
"""防御 policy の A/B(2026-07-08、 claude idea)。 攻撃手選択は天井 + value_defense 既にON でも
エネルが Calgara に 24% 負け → 未探索の**防御判断**を検証。

hero=エネルの choose_defense を 2 policy で比較:
- deployed: 配備(value_defense=true)
- minimal : 極力受ける(block/counter しない、 ただし「受けると負け=ライフ0」の時だけ最小限防御)
もし minimal が deployed より勝つ → エネルは**過剰防御**(カウンター資源を守りに浪費、 攻めに回すべき)。

P0/P1 均等化(harness bias 修正済)。  AB_N=160 AB_WORKERS=8 .venv/bin/python scripts/ab_defense_policy.py
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
HERO = "cardrush_1454"
OPP = "tcgportal_calgara"
TURN_CAP = int(os.environ.get("AB_TURN_CAP", "40"))


LIFE_THR = int(os.environ.get("AB_LIFE_THR", "2"))  # ライフ > これ ならリーダー攻撃は受ける(chip許容)


class MinimalDefenseAI(ExploitBeamAI):
    """refined 保守防御: リーダー攻撃は**ライフに余裕がある間(> LIFE_THR)は受ける**(chip 許容で
    カウンター資源を温存)。 ライフ低下時 (<= LIFE_THR) は配備防御に委ねる。 キャラ攻撃(盤面 KO 脅威)は
    常に配備防御に委ねる(価値あるキャラは守る)。 = 人間的な「早いチップは受け、 効く時に守る」。"""
    def choose_defense(self, state, attacker, target, is_leader_attack, defender):
        try:
            if not is_leader_attack:
                return super().choose_defense(state, attacker, target, is_leader_attack, defender)  # キャラ守る
            if len(getattr(defender, "life", [])) <= LIFE_THR:
                return super().choose_defense(state, attacker, target, is_leader_attack, defender)  # 低ライフは守る
        except Exception:
            pass
        return (None, ())   # ライフ余裕あるリーダー攻撃 = 受ける(資源温存)


def _deck(s):
    import json
    return make_deck_from_dict(json.loads((ROOT / "decks" / f"{s}.json").read_text(encoding="utf-8")), _REPO)


def _mk(slug, seed, minimal_def=False):
    cls = MinimalDefenseAI if (minimal_def and slug == HERO) else ExploitBeamAI
    return cls(rng=random.Random(seed), beam_width=16, max_depth=10, deck_analysis={"deck_slug": slug})


def _play(seed, minimal_def):
    hero_p0 = (seed % 2 == 0)
    if hero_p0:
        st = setup_game(_deck(HERO), _deck(OPP), rng=random.Random(seed), first_player=0, effects_overlay=_OVERLAY)
        ais = [_mk(HERO, seed * 3 + 1, minimal_def), _mk(OPP, seed * 5 + 2)]; hero_idx = 0
    else:
        st = setup_game(_deck(OPP), _deck(HERO), rng=random.Random(seed), first_player=0, effects_overlay=_OVERLAY)
        ais = [_mk(OPP, seed * 5 + 2), _mk(HERO, seed * 3 + 1, minimal_def)]; hero_idx = 1
    play_until_main(st)
    n = 0
    while not st.game_over and st.turn_number < TURN_CAP and n < 1500:
        cur = st.turn_player_idx
        try:
            play_one_action(st, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    if not st.game_over:
        return "draw"
    w = getattr(st, "winner", -1)
    return 1 if w == hero_idx else (0 if w == (1 - hero_idx) else "draw")


def _one(seed):
    return (_play(seed, True), _play(seed, False))


def main():
    n = int(os.environ.get("AB_N", "160"))
    workers = int(os.environ.get("AB_WORKERS", "8"))
    seeds = list(range(1000, 1000 + n))
    t0 = time.time()
    with mp.Pool(workers) as p:
        res = p.map(_one, seeds)
    a_w = sum(1 for r in res if r[0] == 1); b_w = sum(1 for r in res if r[1] == 1)
    print(f"エネル vs カルガラ  防御 policy A/B  N={n}  ({time.time()-t0:.0f}s)")
    print(f"  A: minimal-defense(受ける): {a_w}/{n} = {100*a_w/n:.0f}%")
    print(f"  B: deployed(value_defense): {b_w}/{n} = {100*b_w/n:.0f}%")
    print(f"  Δ = {100*a_w/n - 100*b_w/n:+.0f}pt  (+なら過剰防御=受ける方が良い)")


if __name__ == "__main__":
    main()
