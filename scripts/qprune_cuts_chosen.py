# -*- coding: utf-8 -*-
"""「切った手が"打つ手"なら必ず挙動が変わる」(ohtsuki) を直接検証。

各 hero root 決定で: (1) 素のビームが実際に選ぶ手 chosen、(2) root legal actions の Q、
(3) chosen が margin で「切られる側」(Q < best-margin) か? を測る。

chosen が切られない ⟹ 挙動は変わらない ⟹ prune は「打とうとしてない手」を切ってる(=value冗長)。
chosen の Q 順位も見る(0=最良)。強い beam の選ぶ手が常に高Q なら、Q と value は一致=改善余地なし。

  QP_MARGIN=0.04 .venv/bin/python scripts/qprune_cuts_chosen.py
"""
import sys, os, random, json, pickle
import numpy as np
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main, legal_actions, apply_action
from engine.ai import GreedyAI
from engine.exploit_beam_ai import ExploitBeamAI
from engine.gbm_value import features as _feat
from engine.q_prune import _encode_action_live

ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OV = load_effect_overlay(ROOT / "db" / "card_effects.json")
MARGIN = float(os.environ.get("QP_MARGIN", "0.04"))
_M = pickle.load(open("db/q_prune_model.pkl", "rb"))["model"]
PAIRS = [("cardrush_1342", "tcgportal_calgara"), ("cardrush_1454", "tcgportal_bonney")]


def _load(s):
    return make_deck_from_dict(json.loads((ROOT / "decks" / f"{s}.json").read_text(encoding="utf-8")), _REPO)


def _sig(a):
    return (type(a).__name__, getattr(a, "attacker_iid", None), getattr(a, "target_iid", None),
            getattr(a, "card_iid", None), getattr(a, "target_kind", None))


def _q_of_actions(state, me_idx, actions):
    me = state.players[me_idx]
    feat = [float(x) for x in _feat(state, me_idx, v6=True)]
    rows = np.array([feat + _encode_action_live(a, me) for a in actions], dtype=float)
    return _M.predict_proba(rows)[:, 1]


def main():
    cut = 0; total = 0; ranks = []; frac_at_top = 0
    for hero_slug, opp_slug in PAIRS:
        for g in range(6):
            seed = 5000 + g
            state = setup_game(_load(hero_slug), _load(opp_slug), rng=random.Random(seed),
                               first_player=g % 2, effects_overlay=_OV)
            play_until_main(state)
            hero_seat = 0 if g % 2 == 0 else 1
            opp = GreedyAI(rng=random.Random(seed + 1), deck_analysis={"deck_slug": opp_slug})
            hero = ExploitBeamAI(rng=random.Random(777), beam_width=16, max_depth=10,
                                 deck_analysis={"deck_slug": hero_slug})
            n = 0
            while not state.game_over and state.turn_number < 40 and n < 400:
                cur = state.turn_player_idx
                if cur == hero_seat and state.phase.name == "MAIN":
                    acts = legal_actions(state)
                    if len(acts) >= 3:
                        try:
                            chosen = hero.choose_action(state)  # 素の beam の実選択
                            qs = _q_of_actions(state, hero_seat, acts)
                        except Exception:
                            break
                        best = float(qs.max())
                        # chosen の Q と順位
                        ci = next((i for i, a in enumerate(acts) if _sig(a) == _sig(chosen)), None)
                        if ci is not None:
                            total += 1
                            cq = float(qs[ci])
                            rank = int((qs > cq).sum())  # 0=最良
                            ranks.append(rank)
                            if rank == 0:
                                frac_at_top += 1
                            if cq < best - MARGIN:   # chosen が「切られる側」か
                                cut += 1
                        try:
                            apply_action(state, chosen)
                        except Exception:
                            break
                        n += 1
                        continue
                # 非hero or 非MAIN
                a = opp if cur != hero_seat else hero
                acts = legal_actions(state)
                if not acts:
                    break
                try:
                    apply_action(state, a.choose_action(state))
                except Exception:
                    break
                n += 1
    print(f"margin={MARGIN}  hero root 決定 {total} 件:")
    print(f"  ビームが選ぶ手が「切られる側」(Q<best-margin): {cut} ({cut/max(1,total)*100:.1f}%)")
    print(f"    → これが挙動変化率とほぼ一致するはず(切られる=打てない=別の手)")
    print(f"  選んだ手の Q 順位が最良(rank0)だった割合: {frac_at_top/max(1,total)*100:.1f}%")
    print(f"  選んだ手の Q 平均順位: {np.mean(ranks):.2f} (候補数の中で。0=Q最良)")


if __name__ == "__main__":
    main()
