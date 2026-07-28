# -*- coding: utf-8 -*-
"""population-diverse value 学習データ収集 (2026-07-28、 Stage 1 = self-play degeneracy 対策)。

現 corpus は beam-vs-beam(homogeneous pilot)= value は aggro 寄り state しか見ていない
(= AI-vs-AI が aggro 局所最適に嵌る textbook degeneracy、 arXiv 2408.01072)。
対策: pilot を population 化(greedy/human-model/beam/beam+big_deploy/force-big)して多様な state
分布を訪れ、 各 state を features(21dim agnostic)+ eventual 勝敗で記録 → value を多様分布で再学習。

  POP_N=1500 POP_WORKERS=12 .venv/bin/python scripts/collect_population_data.py
出力: db/_selfplay/population_corpus.jsonl ({f:[21], y, hero, opp, ph, po})
"""
import sys, os, random, time, json
import multiprocessing as mp
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main, legal_actions, PlayCharacter
from engine.ai import play_one_action, GreedyAI
from engine.human_model_ai import HumanModelAI
from engine.exploit_beam_ai import ExploitBeamAI
from engine.gbm_value import features

ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")
OUT = ROOT / (os.environ.get("POP_OUT") or "db/_selfplay/population_corpus.jsonl")
POOL = ["cardrush_1342", "cardrush_1385", "cardrush_1392", "cardrush_1399", "cardrush_1439",
        "cardrush_1453", "cardrush_1454", "cardrush_1455", "cardrush_1456",
        "tcgportal_bonney", "tcgportal_calgara", "tcgportal_coby", "tcgportal_corazon",
        "tcgportal_hancock", "tcgportal_op11_luffy", "tcgportal_op13_luffy"]
_BIG = {"OP14-069", "OP10-071"}  # ドフラ大型(force-big 用)
_DL = {}


def _dl(slug):
    if slug not in _DL:
        _DL[slug] = make_deck_from_dict(json.loads((ROOT / "decks" / f"{slug}.json").read_text()), _REPO)
    return _DL[slug]


class _ForceBig(ExploitBeamAI):
    """大型が legal なら即展開(control style pilot)。"""
    def choose_action(self, state):
        me = state.players[state.turn_player_idx]
        best = None
        for a in legal_actions(state):
            if isinstance(a, PlayCharacter) and 0 <= getattr(a, "hand_idx", -1) < len(me.hand):
                if getattr(me.hand[a.hand_idx], "card_id", None) in _BIG:
                    cst = getattr(me.hand[a.hand_idx], "cost", 0)
                    if best is None or cst > best[1]:
                        best = (a, cst)
        return best[0] if best else super().choose_action(state)


# pilot population(名前 → factory(seed, slug))。 多様な state 分布を作る。
def _mk(kind, seed, slug):
    da = {"deck_slug": slug}
    if kind == "greedy":
        return GreedyAI(rng=random.Random(seed))
    if kind == "human":
        return HumanModelAI(rng=random.Random(seed), deck_analysis=da)
    if kind == "beam":
        return ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10, deck_analysis=da)
    if kind == "beam_big":  # control 寄り: big_deploy bonus
        ai = ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10, deck_analysis=da)
        ai._big_deploy_w = 0.8
        return ai
    if kind == "force_big":  # control style: 大型即展開
        return _ForceBig(rng=random.Random(seed), beam_width=16, max_depth=10, deck_analysis=da)
    if kind == "beam_threat":  # removal 寄り
        ai = ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10, deck_analysis=da)
        ai._threat_removal_w = 0.6
        return ai
    if kind == "beam_press":  # aggression 寄り
        ai = ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10, deck_analysis=da)
        ai._pressure_w = 0.4
        return ai
    return GreedyAI(rng=random.Random(seed))


# POP_STRONG=1 で「強い×style 多様」pilot のみ(弱 pilot が value 校正を崩す仮説の対策)。
if os.environ.get("POP_STRONG") == "1":
    PILOTS = ["beam", "beam", "beam_big", "force_big", "beam_threat", "beam_press"]
else:
    PILOTS = ["greedy", "human", "beam", "beam", "beam_big", "force_big"]  # beam を厚めに


def _one(seed):
    rng = random.Random(seed)
    hslug, oslug = rng.sample(POOL, 2)
    ph, po = rng.choice(PILOTS), rng.choice(PILOTS)
    fp = seed % 2
    state = setup_game(_dl(hslug), _dl(oslug), rng=random.Random(seed), first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    # setup は先攻を index0 に置く。 hslug(deck1) は fp==0→idx0 / fp==1→idx1
    h_idx = 0 if fp == 0 else 1
    ais = [None, None]
    ais[h_idx] = _mk(ph, seed * 5 + 1, hslug)
    ais[1 - h_idx] = _mk(po, seed * 7 + 3, oslug)
    samples = []  # (f21, capture_player_idx, turn)
    n, last_turn = 0, -1
    while not state.game_over and state.turn_number < 55 and n < 1500:
        cur = state.turn_player_idx
        if state.turn_number != last_turn:
            last_turn = state.turn_number
            # 手番 player の main state を capture(both players が交互に手番を持つ)
            try:
                f = features(state, cur, rich=True, v3=False, v4=False, v5=False, v6=False,
                             v7=False, v8=False, v10=False)[:21]
                samples.append((f, cur, state.turn_number))
            except Exception:
                pass
        try:
            play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    if not state.game_over:
        return []
    w = getattr(state, "winner", -1)
    if w < 0:
        return []
    rows = []
    for f, pidx, _t in samples:
        rows.append({"f": [round(x, 5) for x in f], "y": 1 if pidx == w else 0,
                     "hero": hslug if pidx == h_idx else oslug,
                     "ph": ph if pidx == h_idx else po})
    return rows


def main():
    N = int(os.environ.get("POP_N", "1500"))
    W = int(os.environ.get("POP_WORKERS", "12"))
    seeds = list(range(60000, 60000 + N))
    t0 = time.time()
    print(f"[collect_population] N={N} games, pilots={set(PILOTS)}, workers={W}", flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with open(OUT, "w", encoding="utf-8") as fout, mp.Pool(W) as p:
        for i, rows in enumerate(p.imap_unordered(_one, seeds, chunksize=4)):
            for r in rows:
                fout.write(json.dumps(r, ensure_ascii=False) + "\n")
            total += len(rows)
            if (i + 1) % 200 == 0:
                print(f"  {i+1}/{N} games, {total} samples, {time.time()-t0:.0f}s", flush=True)
    print(f"[collect_population] DONE {total} samples from {N} games ({time.time()-t0:.0f}s) → {OUT}", flush=True)


if __name__ == "__main__":
    main()
