# -*- coding: utf-8 -*-
"""打倒カルガラ self-play: エネル(learning) vs カルガラ(fixed) で、 AI が *自力で* 勝ち筋
(= リーダー pump → 殴る)を発見・学習して勝率が登るかを検証 (ohtsuki: いこう)。

selfplay_climb.py の非対称版。 learning 側 (エネル) だけ value を学習:
  - 生成: エネル(value-AI + ε探索) vs カルガラ(固定 GreedyAI)。 エネル視点 (features, 勝敗) を記録。
  - 学習: 蓄積データで GBM 再学習。
  - 評価: エネル(value-AI, ε=0) vs カルガラ。 勝率 + エネルの AttachDonToLeader/AttackLeader 回数。
勝率が登り、 かつ pump 回数が増えれば = AI が手チューニングなしに勝ち筋を発見・学習した = 本物の打倒。

  .venv/bin/python scripts/selfplay_vs_target.py --deck cardrush_1467 --opp tcgportal_calgara \
      --iters 10 --games 150 --eval 60 --epsilon 0.2 --workers 12
"""
from __future__ import annotations

import argparse
import json
import pickle
import random
import sys
import time
import multiprocessing as mp
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.game import (setup_game, play_until_main, legal_actions, apply_action,
                         EndPhase, AttachDonToLeader, AttackLeader)
from engine.ai import GreedyAI, play_one_action
from engine.plan_search import fast_clone
from engine.gbm_value import features

_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")
_MODEL_CACHE: dict = {}
_DECK = "cardrush_1467"
_OPP = "tcgportal_calgara"


def _load_model(path):
    if not path:
        return None
    if path not in _MODEL_CACHE:
        with open(path, "rb") as f:
            _MODEL_CACHE[path] = pickle.load(f)
    return _MODEL_CACHE[path]


def _dl(slug):
    return DeckList.from_json(ROOT / "decks" / f"{slug}.json", _REPO)


def _ana(slug):
    p = ROOT / "decks" / f"{slug}.analysis.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _opp_gbm():
    """opp の per-deck GBM path (= 固定の強い 1-ply 仮想敵)。 無ければ None → GreedyAI。"""
    p = ROOT / "db" / f"value_gbm_{_OPP}.pkl"
    return str(p) if p.exists() else None


def _make_opp(seed):
    """固定 opp (= カルガラ)。 per-deck GBM があれば 1-ply value-greedy (= 強)、 無ければ GreedyAI。"""
    g = _opp_gbm()
    da = {**_ana(_OPP), "deck_slug": _OPP}
    if g:
        return ValueGreedyAI(rng=random.Random(seed + 7), deck_analysis=da, epsilon=0.0, model_path=g)
    return GreedyAI(rng=random.Random(seed + 7), deck_analysis=da)


class ValueGreedyAI(GreedyAI):
    """1-ply value-greedy + ε探索 (= 学習側 エネル)。 value = GBM P(win) / board_eval。"""

    def __init__(self, rng=None, deck_analysis=None, *, epsilon=0.0, model_path=None):
        super().__init__(rng=rng, deck_analysis=deck_analysis)
        self.epsilon = epsilon
        self.model_path = model_path

    def _value(self, state, me):
        if getattr(state, "game_over", False):
            w = getattr(state, "winner", -1)
            return 1.0 if w == me else (0.0 if w is not None else 0.5)
        model = _load_model(self.model_path)
        if model is None:
            from engine.eval import compute_score
            return compute_score(state, me)
        return float(model.predict_proba([features(state, me, rich=True)])[0][1])

    def choose_action(self, state):
        acts = legal_actions(state)
        if not acts:
            return EndPhase()
        if len(acts) == 1:
            return acts[0]
        rng = self.rng or random
        if rng.random() < self.epsilon:
            return rng.choice(acts)
        me = state.turn_player_idx
        best, best_v = None, None
        for a in acts:
            c = fast_clone(state)
            try:
                apply_action(c, a)
            except Exception:
                continue
            v = self._value(c, me)
            if best_v is None or v > best_v:
                best_v, best = v, a
        return best if best is not None else acts[0]


def _setup(enel_first, seed):
    """エネル/カルガラを並べて setup。 (state, enel_idx) を返す。 先攻は交互。"""
    if enel_first:
        state = setup_game(_dl(_DECK), _dl(_OPP), rng=random.Random(seed), first_player=0,
                           effects_overlay=_OVERLAY, deck1_analysis=_ana(_DECK), deck2_analysis=_ana(_OPP))
        return state, 0
    else:
        state = setup_game(_dl(_OPP), _dl(_DECK), rng=random.Random(seed), first_player=0,
                           effects_overlay=_OVERLAY, deck1_analysis=_ana(_OPP), deck2_analysis=_ana(_DECK))
        return state, 1


def gen_one(task):
    """エネル(value-AI+ε) vs カルガラ(GreedyAI) 1試合 → エネル視点 [(features, outcome)]。"""
    model_path, epsilon, seed = task
    state, ei = _setup(seed % 2 == 0, seed)
    play_until_main(state)
    enel = ValueGreedyAI(rng=random.Random(seed), deck_analysis={**_ana(_DECK), "deck_slug": _DECK},
                         epsilon=epsilon, model_path=model_path)
    cal = _make_opp(seed)
    ais = [None, None]
    ais[ei] = enel
    ais[1 - ei] = cal
    recs = []
    n = 0
    while not state.game_over and n < 400:
        me = state.turn_player_idx
        try:
            recs.append(features(state, ei, rich=True))  # 常にエネル視点
        except Exception:
            pass
        try:
            play_one_action(state, ais[me], ais[1 - me])
        except Exception:
            break
        n += 1
    w = getattr(state, "winner", -1)
    y = 1 if w == ei else 0
    return [(fv, y) for fv in recs]


def eval_one(task):
    """エネル(value-AI ε=0) vs カルガラ(GreedyAI)。 (win, loss, n_pump, n_atk) エネル視点。"""
    model_path, seed = task
    state, ei = _setup(seed % 2 == 0, seed)
    play_until_main(state)
    enel = ValueGreedyAI(rng=random.Random(seed), deck_analysis={**_ana(_DECK), "deck_slug": _DECK},
                         epsilon=0.0, model_path=model_path)
    cal = _make_opp(seed)
    ais = [None, None]
    ais[ei] = enel
    ais[1 - ei] = cal
    n_pump = n_atk = 0
    n = 0
    while not state.game_over and n < 400:
        me = state.turn_player_idx
        try:
            act = play_one_action(state, ais[me], ais[1 - me])
        except Exception:
            break
        if me == ei:
            if isinstance(act, AttachDonToLeader):
                n_pump += 1
            elif isinstance(act, AttackLeader):
                n_atk += 1
        n += 1
    w = getattr(state, "winner", -1)
    return (1 if w == ei else 0, 1 if (w is not None and w != ei) else 0, n_pump, n_atk)


def train_gbm(data):
    from sklearn.ensemble import GradientBoostingClassifier
    X = [d[0] for d in data]
    y = [d[1] for d in data]
    m = GradientBoostingClassifier(n_estimators=150, max_depth=3, learning_rate=0.05,
                                   subsample=0.8, random_state=0)
    m.fit(X, y)
    return m


def main():
    global _DECK, _OPP
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="cardrush_1467")
    ap.add_argument("--opp", default="tcgportal_calgara")
    ap.add_argument("--iters", type=int, default=10)
    ap.add_argument("--games", type=int, default=150)
    ap.add_argument("--eval", type=int, default=60)
    ap.add_argument("--epsilon", type=float, default=0.3, help="ε探索の開始値 (= iter0)")
    ap.add_argument("--eps-end", type=float, default=0.05, help="ε探索の終了値 (= 最終iter、 decay)")
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    _DECK, _OPP = a.deck, a.opp
    outdir = ROOT / "db" / "_selfplay"
    outdir.mkdir(exist_ok=True)
    print(f"self-play vs target: {_DECK}(learn) vs {_OPP}(GreedyAI fixed) | iters={a.iters} "
          f"games={a.games} eval={a.eval} eps={a.epsilon}->{a.eps_end}", flush=True)
    data: list = []
    model_path = None
    hist = []
    for it in range(a.iters):
        t0 = time.time()
        # ε-decay: 序盤は探索多め(未踏の手を試す)、 終盤は exploitation でラベルを綺麗に。
        frac = it / max(1, a.iters - 1)
        eps_it = a.epsilon + (a.eps_end - a.epsilon) * frac
        gt = [(model_path, eps_it, 1000 * it + g) for g in range(a.games)]
        with mp.Pool(a.workers) as p:
            res = p.map(gen_one, gt, chunksize=2)
        new = [r for game in res for r in game]
        data.extend(new)
        try:
            model = train_gbm(data)
            model_path = str(outdir / f"enel_iter{it}.pkl")
            with open(model_path, "wb") as f:
                pickle.dump(model, f)
        except ValueError:
            print("    (単一クラスのため学習skip、 前 model 継続)", flush=True)
        et = [(model_path, 50000 + it * 1000 + e) for e in range(a.eval)]
        with mp.Pool(a.workers) as p:
            er = p.map(eval_one, et, chunksize=2)
        w = sum(r[0] for r in er); l = sum(r[1] for r in er)
        pump = sum(r[2] for r in er) / max(1, a.eval)
        atk = sum(r[3] for r in er) / max(1, a.eval)
        wr = w / max(1, a.eval) * 100
        hist.append(wr)
        print(f"  iter {it}: エネル vs カルガラ {w}-{l}/{a.eval} = {wr:.0f}%  "
              f"pump={pump:.1f} atk={atk:.1f}/game  (samples={len(data)})  {time.time()-t0:.0f}s",
              flush=True)
    print(f"=== SLOPE winrate: {[f'{h:.0f}%' for h in hist]} ===", flush=True)
    if len(hist) >= 2:
        print(f"  iter0={hist[0]:.0f}% → iter{len(hist)-1}={hist[-1]:.0f}% (Δ={hist[-1]-hist[0]:+.0f}pt) "
              f"= {'登ってる' if hist[-1] > hist[0] + 5 else '平ら/不明瞭'}")


if __name__ == "__main__":
    main()
