# -*- coding: utf-8 -*-
"""value-policy vs EBV2 の1試合を turn 進行付きで実況(2026-07-28、 drag 診断)。
  DP_SLUG=cardrush_1385 DP_VALUE=db/_selfplay/value_rollout_v14.pkl .venv/bin/python scripts/diag_policy_game.py
"""
import sys, os, random, time, json, pickle
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import (setup_game, play_until_main, legal_actions, apply_action,
                         AttachDonToLeader, AttachDonToCharacter)
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI
from engine.plan_search import fast_clone
from engine.gbm_value import features

ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")
SLUG = os.environ.get("DP_SLUG", "cardrush_1385")
VALUE = os.environ.get("DP_VALUE", "db/_selfplay/value_rollout_v14.pkl")
FEAT = os.environ.get("DP_FEAT", "v14")
_M = pickle.load(open(ROOT / VALUE, "rb"))


def _dl(s):
    return make_deck_from_dict(json.loads((ROOT / "decks" / f"{s}.json").read_text()), _REPO)


class PolicyAI(ExploitBeamAI):
    def choose_action(self, state):
        me = state.turn_player_idx
        acts = legal_actions(state)
        if len(acts) <= 1:
            return acts[0] if acts else super().choose_action(state)
        non_don, don = [], []
        for i, a in enumerate(acts):
            (don if isinstance(a, (AttachDonToLeader, AttachDonToCharacter)) else non_don).append(i)
        keep = set(non_don) | set(don[:3])
        feats, idxs, scores = [], [], {}
        for i in keep:
            post = fast_clone(state)
            try:
                apply_action(post, legal_actions(post)[i])
            except Exception:
                continue
            if getattr(post, "game_over", False):
                w = getattr(post, "winner", -1)
                scores[i] = 1.5 if w == me else (-1.5 if w == (1 - me) else 0.5)
            else:
                kw = {"rich": True, FEAT: True}
                feats.append(features(post, me, **kw)); idxs.append(i)
        if feats:
            probs = _M.predict_proba(feats)[:, 1]
            for j, i in enumerate(idxs):
                scores[i] = float(probs[j])
        return acts[max(scores, key=scores.get)] if scores else super().choose_action(state)


def _play(seed):
    # 先攻バイアス相殺: seed 偶奇で policy を P0/P1 に振る
    pol_p0 = (seed % 2 == 0)
    st = setup_game(_dl(SLUG), _dl(SLUG), rng=random.Random(seed), first_player=0, effects_overlay=_OVERLAY)
    play_until_main(st)
    A = PolicyAI(rng=random.Random(seed * 5 + 1), beam_width=16, max_depth=10, deck_analysis={"deck_slug": SLUG})
    B = ExploitBeamAI(rng=random.Random(seed * 7 + 3), beam_width=16, max_depth=10, deck_analysis={"deck_slug": SLUG})
    pol_idx = 0 if pol_p0 else 1
    ais = [None, None]
    ais[pol_idx] = A; ais[1 - pol_idx] = B
    n = 0
    while not st.game_over and st.turn_number < 60 and n < 2000:
        play_one_action(st, ais[st.turn_player_idx], ais[1 - st.turn_player_idx]); n += 1
    if not st.game_over:
        return None
    w = getattr(st, "winner", -1)
    return (1 if w == pol_idx else 0, st.turn_number)


def main():
    import multiprocessing as mp
    N = int(os.environ.get("DP_N", "40"))
    seeds = list(range(200000, 200000 + N))
    t0 = time.time()
    with mp.Pool(int(os.environ.get("DP_WORKERS", "12"))) as p:
        res = [r for r in p.map(_play, seeds) if r]
    wins = sum(w for w, _ in res)
    turns = [t for _, t in res]
    print(f"[diag] {SLUG} mirror  value-policy 勝率 {wins/max(1,len(res))*100:.1f}% ({wins}/{len(res)})  "
          f"avg_turn={sum(turns)/max(1,len(turns)):.1f}  max_turn={max(turns) if turns else 0}  ({time.time()-t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
