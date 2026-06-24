# -*- coding: utf-8 -*-
"""self-play 複利ループの「登るか」検証 (ohtsuki: できる範囲でまず傾きを測る)。

既存 online_self_play.py が登らない理由 = (1) 線形 weight 学習 (argmax 不変、 [[feedback_weight_nn_limit]])
+ (2) action 探索なし。 本 script はその2つを直す最小ループ:
  - 探索: ε-greedy (= 確率 ε で legal action をランダム選択 → 未踏の手を試す)
  - 表現力: GBM value (= 非線形、 特徴交互作用)。 P(win) を学習
  - 複利: 蓄積 (features, outcome) で GBM 再学習 → 次世代の自己対戦を生成 → 反復
各 iteration 後、 value-greedy AI (ε=0) を **固定 baseline (GreedyAI)** と対戦させ勝率を測る。
勝率が iteration 毎に **登れば** = 自己改善が成立 (= ohtsuki の「やった分だけ強くなる」 が実証)。

  .venv/bin/python scripts/selfplay_climb.py --deck cardrush_1342 --iters 8 \
      --games 150 --eval 40 --epsilon 0.2 --workers 12
"""
from __future__ import annotations

import argparse
import os
import pickle
import random
import sys
import time
import multiprocessing as mp
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import json
from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main, legal_actions, apply_action, EndPhase
from engine.ai import GreedyAI, play_one_action
from engine.plan_search import fast_clone
from engine.gbm_value import features

_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")
_MODEL_CACHE: dict = {}


def _load_model(path):
    if not path:
        return None
    if path not in _MODEL_CACHE:
        with open(path, "rb") as f:
            _MODEL_CACHE[path] = pickle.load(f)
    return _MODEL_CACHE[path]


class ValueGreedyAI(GreedyAI):
    """1-ply value-greedy + ε探索。 value = GBM P(win) (= model_path)、 無ければ board_eval。
    defense は GreedyAI ヒューリスティック継承 (= 学習対象は offense value)。"""

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
        x = [features(state, me, rich=True)]
        return float(model.predict_proba(x)[0][1])

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


def _deck():
    return DeckList.from_json(ROOT / "decks" / f"{_DECK}.json", _REPO)


def _ana():
    p = ROOT / "decks" / f"{_DECK}.analysis.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


_DECK = "cardrush_1342"


def gen_one(task):
    """mirror self-play 1試合 → [(features, outcome), ...]。 ε探索付き value-greedy 両側。"""
    model_path, epsilon, seed = task
    rng = random.Random(seed)
    a0 = ValueGreedyAI(rng=random.Random(seed), deck_analysis={**_ana(), "deck_slug": _DECK},
                       epsilon=epsilon, model_path=model_path)
    a1 = ValueGreedyAI(rng=random.Random(seed + 7), deck_analysis={**_ana(), "deck_slug": _DECK},
                       epsilon=epsilon, model_path=model_path)
    state = setup_game(_deck(), _deck(), rng=rng, first_player=seed % 2,
                       effects_overlay=_OVERLAY, deck1_analysis=_ana(), deck2_analysis=_ana())
    play_until_main(state)
    ais = [a0, a1]
    for i, a in enumerate(ais):
        if hasattr(a, 'set_ai_opp'):
            a.set_ai_opp(ais[1 - i])
    recs = []
    n = 0
    while not state.game_over and n < 400:
        me = state.turn_player_idx
        try:
            recs.append((features(state, me, rich=True), me))
        except Exception:
            pass
        try:
            play_one_action(state, ais[me], ais[1 - me])
        except Exception:
            break
        n += 1
    w = getattr(state, "winner", -1)
    return [(fv, 1 if w == p else 0) for fv, p in recs]


def eval_one(task):
    """value-AI(ε=0) vs GreedyAI、 value-AI 視点 (W,L,D)。 first_player 交互。"""
    model_path, seed = task
    val_first = seed % 2 == 0
    rng = random.Random(seed)
    val_ai = ValueGreedyAI(rng=random.Random(seed), deck_analysis={**_ana(), "deck_slug": _DECK},
                           epsilon=0.0, model_path=model_path)
    base_ai = GreedyAI(rng=random.Random(seed + 7), deck_analysis={**_ana(), "deck_slug": _DECK})
    if val_first:
        ais = [val_ai, base_ai]; val_idx = 0
    else:
        ais = [base_ai, val_ai]; val_idx = 1
    state = setup_game(_deck(), _deck(), rng=rng, first_player=0,
                       effects_overlay=_OVERLAY, deck1_analysis=_ana(), deck2_analysis=_ana())
    play_until_main(state)
    for i, a in enumerate(ais):
        if hasattr(a, 'set_ai_opp'):
            a.set_ai_opp(ais[1 - i])
    n = 0
    while not state.game_over and n < 400:
        me = state.turn_player_idx
        try:
            play_one_action(state, ais[me], ais[1 - me])
        except Exception:
            break
        n += 1
    w = getattr(state, "winner", -1)
    return (1 if w == val_idx else 0, 1 if (w is not None and w != val_idx) else 0)


def train_gbm(data):
    from sklearn.ensemble import GradientBoostingClassifier
    X = [d[0] for d in data]
    y = [d[1] for d in data]
    model = GradientBoostingClassifier(n_estimators=150, max_depth=3, learning_rate=0.05,
                                       subsample=0.8, random_state=0)
    model.fit(X, y)
    return model


def main():
    global _DECK
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="cardrush_1342")
    ap.add_argument("--iters", type=int, default=8)
    ap.add_argument("--games", type=int, default=150)
    ap.add_argument("--eval", type=int, default=40)
    ap.add_argument("--epsilon", type=float, default=0.2)
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    _DECK = a.deck
    outdir = ROOT / "db" / "_selfplay"
    outdir.mkdir(exist_ok=True)

    print(f"self-play climb: deck={_DECK} iters={a.iters} games/iter={a.games} "
          f"eval={a.eval} epsilon={a.epsilon}", flush=True)
    data: list = []
    model_path = None  # iter 0 = board_eval value
    history = []
    for it in range(a.iters):
        t0 = time.time()
        # --- generate (ε探索付き mirror self-play、 現 value で) ---
        gtasks = [(model_path, a.epsilon, 1000 * it + g) for g in range(a.games)]
        with mp.Pool(a.workers) as p:
            results = p.map(gen_one, gtasks, chunksize=2)
        new = [rec for game in results for rec in game]
        data.extend(new)
        # --- train GBM on accumulated data ---
        model = train_gbm(data)
        model_path = str(outdir / f"model_iter{it}.pkl")
        with open(model_path, "wb") as f:
            pickle.dump(model, f)
        # --- evaluate value-AI(ε=0) vs GreedyAI baseline ---
        etasks = [(model_path, 50000 + it * 1000 + e) for e in range(a.eval)]
        with mp.Pool(a.workers) as p:
            eres = p.map(eval_one, etasks, chunksize=2)
        w = sum(r[0] for r in eres); l = sum(r[1] for r in eres)
        wr = w / max(1, a.eval) * 100
        history.append(wr)
        print(f"  iter {it}: vs GreedyAI {w}-{l}/{a.eval} = {wr:.0f}%  "
              f"(samples={len(data)}, +{len(new)})  {time.time()-t0:.0f}s", flush=True)
    print(f"=== SLOPE: {[f'{h:.0f}%' for h in history]} ===", flush=True)
    if len(history) >= 2:
        print(f"  iter0={history[0]:.0f}% → iter{len(history)-1}={history[-1]:.0f}%  "
              f"(Δ={history[-1]-history[0]:+.0f}pt) = {'登ってる' if history[-1]>history[0]+5 else '平ら/不明瞭'}")


if __name__ == "__main__":
    main()
