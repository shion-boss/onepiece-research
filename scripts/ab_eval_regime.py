# -*- coding: utf-8 -*-
"""eval-regime de-bias (2026-07-28、 Stage 1 Angle 2)。

deck-eval バイアス(control が AI 評価で過小)は、 eval が self-mirror(全 beam=aggro 寄り field)
だから、 という仮説。 control(hero=beam+agnostic 固定)を (A) 全 beam field vs (B) style 多様な強 field
(beam_big/force_big/beam_threat/beam_press)と対戦させ、 勝率が上がるかを見る。 上がれば「control は
多様な強 field には良いマッチを持つ = 現 eval(mirror)が過小評価」の証拠 = intransitivity の実測。

  ER_HERO=cardrush_1342 ER_N=120 ER_WORKERS=12 .venv/bin/python scripts/ab_eval_regime.py
"""
import sys, os, random, time, json
import multiprocessing as mp
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main, legal_actions, PlayCharacter
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI

ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")
HERO = os.environ.get("ER_HERO", "cardrush_1342")
POOL = ["cardrush_1385", "cardrush_1392", "cardrush_1399", "cardrush_1439", "cardrush_1453",
        "cardrush_1454", "cardrush_1455", "tcgportal_bonney", "tcgportal_hancock",
        "tcgportal_op11_luffy", "tcgportal_op13_luffy"]
_BIG = {"OP14-069", "OP10-071"}
_DL = {}


def _dl(slug):
    if slug not in _DL:
        _DL[slug] = make_deck_from_dict(json.loads((ROOT / "decks" / f"{slug}.json").read_text()), _REPO)
    return _DL[slug]


class _ForceBig(ExploitBeamAI):
    def choose_action(self, state):
        me = state.players[state.turn_player_idx]; best = None
        for a in legal_actions(state):
            if isinstance(a, PlayCharacter) and 0 <= getattr(a, "hand_idx", -1) < len(me.hand):
                if getattr(me.hand[a.hand_idx], "card_id", None) in _BIG:
                    c = getattr(me.hand[a.hand_idx], "cost", 0)
                    if best is None or c > best[1]:
                        best = (a, c)
        return best[0] if best else super().choose_action(state)


def _opp(kind, seed, slug):
    da = {"deck_slug": slug}
    ai = (_ForceBig if kind == "force_big" else ExploitBeamAI)(
        rng=random.Random(seed), beam_width=16, max_depth=10, deck_analysis=da)
    if kind == "beam_big":
        ai._big_deploy_w = 0.8
    elif kind == "beam_threat":
        ai._threat_removal_w = 0.6
    elif kind == "beam_press":
        ai._pressure_w = 0.4
    return ai


def _play(seed, opp_slug, opp_kind):
    fp = seed % 2
    state = setup_game(_dl(HERO), _dl(opp_slug), rng=random.Random(seed), first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    h_idx = 0 if fp == 0 else 1
    o_idx = 1 - h_idx
    ais = [None, None]
    ais[h_idx] = ExploitBeamAI(rng=random.Random(seed * 5 + 1), beam_width=16, max_depth=10,
                               deck_analysis={"deck_slug": HERO})
    ais[o_idx] = _opp(opp_kind, seed * 7 + 3, opp_slug)
    n = 0
    while not state.game_over and state.turn_number < 42 and n < 700:
        cur = state.turn_player_idx
        try:
            play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    if not state.game_over:
        return None
    return "W" if getattr(state, "winner", -1) == h_idx else "L"


STYLES = ["beam_big", "force_big", "beam_threat", "beam_press"]


def _one(seed):
    r = random.Random(seed); opp = r.choice(POOL)
    style = r.choice(STYLES)
    return (_play(seed, opp, style), _play(seed, opp, "beam"))  # (diverse field, mirror field)


def main():
    n = int(os.environ.get("ER_N", "120"))
    workers = int(os.environ.get("ER_WORKERS", "12"))
    seeds = list(range(80000, 80000 + n))
    t0 = time.time()
    print(f"[ab_eval_regime] hero={HERO}(control, beam+agnostic 固定)  N={n}", flush=True)
    with mp.Pool(workers) as p:
        res = p.map(_one, seeds)
    dw = sum(1 for a, b in res if a == "W"); dl = sum(1 for a, b in res if a == "L")
    mw = sum(1 for a, b in res if b == "W"); ml = sum(1 for a, b in res if b == "L")
    wr_d = dw / max(1, dw + dl) * 100
    wr_m = mw / max(1, mw + ml) * 100
    print(f"[ab_eval_regime] vs 多様強field {wr_d:.1f}% ({dw}-{dl})  |  "
          f"vs 全beam(mirror)field {wr_m:.1f}% ({mw}-{ml})  |  Δ={wr_d-wr_m:+.1f}pt  ({time.time()-t0:.0f}s)",
          flush=True)


if __name__ == "__main__":
    main()
