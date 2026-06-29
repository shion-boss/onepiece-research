# -*- coding: utf-8 -*-
"""matchup-conditioned value (v5) vs agnostic value (v2) の A/B 実験。

ohtsuki 案 (2026-06-26)『評価関数の数値を相手デッキの攻略情報によって可変的にする +
攻略方法の学習の精度を高める』の検証。 = 学習 value 自体を matchup-条件付きにする
(hand-rule 注入は学習 value に負ける、 [[project_leader_aware_matchup_ai]] -4.6pt)。

手法 (= 完全 isolation、 column-slice trick):
  1. 多相手 self-play で v5(34-dim) data を 1 度だけ収集 (= deck vs 多様な opp 集合、 deck は
     配備 beam+ε で neutral に打つ、 opp は配備)。 feature に opp leader tag 13 列が乗る。
  2. 同一 data で 2 model を学習: v2 = cols[:21] (= agnostic baseline)、 v5 = 全34 (= matchup条件付き)。
     data/label が完全同一・特徴の有無だけが差 = feature 効果の純粋 isolation。
  3. held-out AUC で pre-filter (= v5 が予測を改善するか。 同等なら feature 無信号 → 早期終了)。
  4. db/_selfplay/{prefix}{v2,v5}.pkl に保存。 deploy A/B は別途:
       test_learned_value_deploy.py --deck <deck> --opp <each opp> --arms default,v2,v5 --pkl-prefix <prefix>
     を per-opp で回す (= 配備忠実 16/10 両 seat)。 v5 が v2 を平均で超えれば仮説 validated。

  .venv/bin/python scripts/matchup_value_ab.py \
      --deck cardrush_1342 \
      --opps tcgportal_calgara,tcgportal_bonney,cardrush_1385,cardrush_1453,cardrush_1454 \
      --games 400 --epsilon 0.15 --workers 12 --prefix mcab_1342_
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import random
import sys
import time
import multiprocessing as mp
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# ⭐ collection で v8(=v6 + opp role-composition)feature を記録。 v8[:38]=v6, v8[:34]=v5, v8[:21]=v2 の
# column-slice 不変性で 1 収集から v2/v5/v6/v8 を同一 data 学習 (= 完全 isolation)。
os.environ.setdefault("ONEPIECE_GBM_V8", "1")

from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.game import (setup_game, play_until_main, legal_actions,
                         AttachDonToLeader, AttackLeader)
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI
from engine.gbm_value import features, FEATURE_KEYS_V2, FEATURE_KEYS_V5, FEATURE_KEYS_V6, FEATURE_KEYS_V8

_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")

DECK = "cardrush_1342"
OPPS = ["tcgportal_calgara"]
BEAM_W, BEAM_D = 8, 6  # collection は moderate beam (速度)。 deploy A/B は別途 16/10。


def _dl(s):
    return DeckList.from_json(ROOT / "decks" / f"{s}.json", _REPO)


def _ana(s):
    p = ROOT / "decks" / f"{s}.analysis.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


class ExploreBeamAI(ExploitBeamAI):
    """配備 beam (= 配備 v2 GBM auto-load) + ε探索。 = neutral collection 行動方策。
    ε で state coverage を稼ぐ。 vd OFF (速度)。"""

    def __init__(self, rng=None, deck_analysis=None, *, epsilon=0.0, **kw):
        super().__init__(rng=rng, deck_analysis=deck_analysis, **kw)
        self.epsilon = epsilon
        self._value_defense = False

    def choose_action(self, state):
        rng = self.rng or random
        if self.epsilon > 0 and rng.random() < self.epsilon:
            acts = legal_actions(state)
            if acts:
                return rng.choice(acts)
        return super().choose_action(state)


def _setup(deck_first, seed, opp):
    if deck_first:
        st = setup_game(_dl(DECK), _dl(opp), rng=random.Random(seed), first_player=0,
                        effects_overlay=_OVERLAY, deck1_analysis=_ana(DECK), deck2_analysis=_ana(opp))
        return st, 0
    st = setup_game(_dl(opp), _dl(DECK), rng=random.Random(seed), first_player=0,
                    effects_overlay=_OVERLAY, deck1_analysis=_ana(opp), deck2_analysis=_ana(DECK))
    return st, 1


def _wire(st, ei, deck_ai, opp_ai):
    ais = [None, None]
    ais[ei] = deck_ai
    ais[1 - ei] = opp_ai
    for i, x in enumerate(ais):
        if hasattr(x, "set_ai_opp"):
            x.set_ai_opp(ais[1 - i])
    return ais


def gen_one(task):
    epsilon, seed = task
    opp = OPPS[seed % len(OPPS)]  # 多様な opp を rotate
    st, ei = _setup(seed % 2 == 0, seed, opp)
    play_until_main(st)
    deck_ai = ExploreBeamAI(rng=random.Random(seed),
                            deck_analysis={**_ana(DECK), "deck_slug": DECK},
                            epsilon=epsilon, beam_width=BEAM_W, max_depth=BEAM_D)
    opp_ai = ExploitBeamAI(rng=random.Random(seed + 7),
                           deck_analysis={**_ana(opp), "deck_slug": opp},
                           beam_width=BEAM_W, max_depth=BEAM_D)
    ais = _wire(st, ei, deck_ai, opp_ai)
    recs = []
    n = 0
    while not st.game_over and n < 400:
        me = st.turn_player_idx
        try:
            recs.append(features(st, ei, v8=True))  # 46-dim: v6 + opp role-composition
        except Exception:
            pass
        try:
            play_one_action(st, ais[me], ais[1 - me])
        except Exception:
            break
        n += 1
    w = getattr(st, "winner", -1)
    y = 1 if w == ei else 0
    return [(fv, y) for fv in recs]


def train_gbm(X, y):
    from sklearn.ensemble import GradientBoostingClassifier
    m = GradientBoostingClassifier(n_estimators=150, max_depth=3, learning_rate=0.05,
                                   subsample=0.8, random_state=0)
    m.fit(X, y)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="cardrush_1342")
    ap.add_argument("--opps", default="tcgportal_calgara,tcgportal_bonney,cardrush_1385,cardrush_1453,cardrush_1454",
                    help="多様な opp 集合 (comma)。 aggro/control/midrange を混ぜると条件付けの伸びしろが出る")
    ap.add_argument("--games", type=int, default=400)
    ap.add_argument("--epsilon", type=float, default=0.15)
    ap.add_argument("--beam-width", type=int, default=8)
    ap.add_argument("--max-depth", type=int, default=6)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--prefix", default=None, help="pkl prefix。 既定 mcab_<deck>_")
    ap.add_argument("--seed", type=int, default=20260626)
    a = ap.parse_args()
    global DECK, OPPS, BEAM_W, BEAM_D
    DECK = a.deck
    OPPS = [s.strip() for s in a.opps.split(",")]
    BEAM_W, BEAM_D = a.beam_width, a.max_depth
    prefix = a.prefix if a.prefix else f"mcab_{DECK}_"
    outdir = ROOT / "db" / "_selfplay"
    outdir.mkdir(exist_ok=True)

    print(f"[collect] {DECK}(beam {BEAM_W}/{BEAM_D}+ε{a.epsilon}, v5 features) vs {OPPS} | "
          f"games={a.games} workers={a.workers}", flush=True)
    t0 = time.time()
    tasks = [(a.epsilon, a.seed + g) for g in range(a.games)]
    with mp.Pool(a.workers) as p:
        res = p.map(gen_one, tasks, chunksize=2)
    data = [r for game in res for r in game]
    X = [d[0] for d in data]
    y = [d[1] for d in data]
    n_pos = sum(y)
    print(f"[collect] samples={len(X)} (pos={n_pos}/{len(y)}={n_pos/max(1,len(y))*100:.0f}%) "
          f"dim={len(X[0]) if X else 0} ({time.time()-t0:.0f}s)", flush=True)
    assert X and len(X[0]) == len(FEATURE_KEYS_V8), f"expected v8 dim {len(FEATURE_KEYS_V8)}, got {len(X[0]) if X else 0}"

    # held-out AUC pre-filter: v2(cols[:21]) / v5(cols[:34]) / v6(full 38) を同一 split で
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import roc_auc_score
    n21 = len(FEATURE_KEYS_V2); n34 = len(FEATURE_KEYS_V5); n38 = len(FEATURE_KEYS_V6)
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, random_state=1, stratify=y if 0 < n_pos < len(y) else None)
    slices = {"v2": n21, "v6": n38, "v8": len(FEATURE_KEYS_V8)}
    models = {}
    for arm, nf in slices.items():
        models[arm] = train_gbm([r[:nf] for r in Xtr], ytr)
    aucs = {arm: roc_auc_score(yte, [p[1] for p in models[arm].predict_proba([r[:slices[arm]] for r in Xte])])
            for arm in slices}
    print(f"[AUC held-out] v2={aucs['v2']:.4f}  v6={aucs['v6']:.4f}(Δ{aucs['v6']-aucs['v2']:+.4f})  "
          f"v8={aucs['v8']:.4f}(Δvs_v6 {aucs['v8']-aucs['v6']:+.4f})", flush=True)
    TURN_IDX = 16
    em = [i for i, r in enumerate(Xte) if r[TURN_IDX] <= 8]
    if len(set(yte[i] for i in em)) == 2 and len(em) >= 30:
        ye = [yte[i] for i in em]
        ea = {arm: roc_auc_score(ye, [models[arm].predict_proba([Xte[i][:slices[arm]]])[0][1] for i in em]) for arm in slices}
        print(f"[AUC turn<=8 (n={len(em)})] v2={ea['v2']:.4f}  v6={ea['v6']:.4f}  v8={ea['v8']:.4f} "
              f"(v8-v6 Δ={ea['v8']-ea['v6']:+.4f})", flush=True)
    # importance: v8 の opp role-composition 8列が selection 信号として効いたか
    imp = list(getattr(models["v8"], "feature_importances_", []))
    if imp:
        print(f"[v8 importance] opprole8={sum(imp[n38:]):.3f}  v6part38={sum(imp[:n38]):.3f}", flush=True)
        rk = list(FEATURE_KEYS_V8[n38:])
        top = sorted(zip(rk, imp[n38:]), key=lambda z: -z[1])[:5]
        print("   top opp-role:", ", ".join(f"{k}={v:.3f}" for k, v in top if v > 0), flush=True)

    # full data で deploy 用 model を再学習・保存
    for arm, nf in slices.items():
        m = train_gbm([r[:nf] for r in X], y)
        pickle.dump(m, open(outdir / f"{prefix}{arm}.pkl", "wb"))
    print(f"[saved] {prefix}{{v2(21)/v6(38)/v8(46)}}.pkl", flush=True)
    print(f"\n[next] deploy A/B: scripts/matchup_value_deploy_ab.py --deck {DECK} "
          f"--opps {','.join(OPPS)} --prefix {prefix} --arms default,v6,v8 --n 50", flush=True)


if __name__ == "__main__":
    main()
