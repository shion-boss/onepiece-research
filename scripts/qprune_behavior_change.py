# -*- coding: utf-8 -*-
"""q_prune が hero の「実際に選ぶ手」を変えるか(=方策シフト率)を測る。

同一 state を deepcopy し、margin ON の AI と OFF の AI(同 seed=rng 同一)に choose_action
させ、選んだ action(type+target)が違う割合を集計。0% なら prune は挙動 no-op = 複利ループ
は立ち上がらない。>0% なら方策がシフト = R1 で新構造が出うる。

  QP_MARGIN=0.04 .venv/bin/python scripts/qprune_behavior_change.py
"""
import sys, os, random, copy, json
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main, legal_actions, apply_action
from engine.ai import GreedyAI
from engine.exploit_beam_ai import ExploitBeamAI

ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OV = load_effect_overlay(ROOT / "db" / "card_effects.json")
MARGIN = float(os.environ.get("QP_MARGIN", "0.04"))
PAIRS = [("cardrush_1342", "tcgportal_calgara"), ("cardrush_1454", "tcgportal_bonney")]


def _load(s):
    return make_deck_from_dict(json.loads((ROOT / "decks" / f"{s}.json").read_text(encoding="utf-8")), _REPO)


def _sig(a):
    return (type(a).__name__, getattr(a, "attacker_iid", None), getattr(a, "target_iid", None),
            getattr(a, "card_iid", None), getattr(a, "target_kind", None))


def main():
    total = 0; changed = 0; games = 0
    for hero_slug, opp_slug in PAIRS:
        for g in range(6):
            seed = 5000 + g
            state = setup_game(_load(hero_slug), _load(opp_slug), rng=random.Random(seed),
                               first_player=g % 2, effects_overlay=_OV)
            play_until_main(state)
            hero_seat = 0 if g % 2 == 0 else 1
            opp = GreedyAI(rng=random.Random(seed + 1), deck_analysis={"deck_slug": opp_slug})
            n = 0
            while not state.game_over and state.turn_number < 40 and n < 400:
                cur = state.turn_player_idx
                if cur == hero_seat and state.phase.name == "MAIN":
                    # 同 state を2系統にコピー、prune ON/OFF で選択比較
                    s1 = copy.deepcopy(state); s2 = copy.deepcopy(state)
                    ai_on = ExploitBeamAI(rng=random.Random(777), beam_width=16, max_depth=10,
                                          deck_analysis={"deck_slug": hero_slug})
                    ai_on._qprune_margin = MARGIN
                    ai_off = ExploitBeamAI(rng=random.Random(777), beam_width=16, max_depth=10,
                                           deck_analysis={"deck_slug": hero_slug})
                    ai_off._qprune_margin = None
                    try:
                        a_on = ai_on.choose_action(s1); a_off = ai_off.choose_action(s2)
                    except Exception:
                        break
                    total += 1
                    if _sig(a_on) != _sig(a_off):
                        changed += 1
                    # 本流は prune OFF で進める(公平な軌道)
                    try:
                        apply_action(state, a_off)
                    except Exception:
                        break
                else:
                    ai = opp if cur != hero_seat else GreedyAI(rng=random.Random(seed + 2), deck_analysis={"deck_slug": hero_slug})
                    acts = legal_actions(state)
                    if not acts:
                        break
                    try:
                        apply_action(state, ai.choose_action(state) if hasattr(ai, "choose_action") else acts[0])
                    except Exception:
                        break
                n += 1
            games += 1
    rate = changed / max(1, total) * 100
    print(f"margin={MARGIN}  hero MAIN 決定 {total} 件中、prune で選択が変わった: {changed} ({rate:.1f}%)")
    print("0% = 挙動 no-op(複利は立ち上がらない) / >0% = 方策シフト有り")


if __name__ == "__main__":
    main()
