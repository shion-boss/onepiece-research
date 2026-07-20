# -*- coding: utf-8 -*-
"""打倒カルガラ self-play (beam-in-the-loop): 配備 beam で *プレイしながら* value を学習。

deployable test で判明: 1-ply 学習 value は beam に transfer しない (= 学習分布が違う)。
AlphaZero の原則どおり、 **beam が生成する分布** で value を学習する:
  - 生成: エネル(ExploitBeam + ε探索 + 学習value) vs カルガラ(配備)。 beam play の盤面を記録。
  - 学習: 蓄積 (features, outcome) で GBM 再学習。
  - 評価: エネル(beam + 学習value, ε=0) vs カルガラ(配備)。 board_eval(iter0) を baseline に比較。
learned value が beam で board_eval を超え、 iteration で登れば = deployable な打倒カルガラ。
速度のため value_defense は OFF (= offense value の学習に集中)。

  .venv/bin/python scripts/selfplay_beam_loop.py --iters 6 --games 40 --eval 50 \
      --epsilon 0.25 --eps-end 0.05 --workers 12
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
from engine.game import (setup_game, play_until_main, legal_actions,
                         AttachDonToLeader, AttackLeader)
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI
from engine.gbm_value import features

_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")
DECK = "cardrush_1467"
OPPS = ["tcgportal_calgara"]  # 訓練相手の集合 = 現#1 + 過去の#1 を累積 (= 単一相手の過適合を防ぐ、 ohtsuki「ループで汎化」)
OPP = OPPS[0]  # primary 標的 = #1 (in-loop eval / 命名用)
BEAM_W, BEAM_D = 8, 6  # 既定 moderate(速度)。 配備忠実 deploy 用に main で 16/10 に上げられる
TRAIN_POSTOPP_TURNS = 1  # 訓練時の手選択の多ターン探索深さ (1=現挙動)。 >1 で多ターン探索データ生成
TRAIN_TEMP = 0.0  # 訓練時の温度探索 (0=argmax)。 >0 で beam 候補を softmax サンプル = uncertain な手を試す
OPP_AI = "exploitbeam"  # 相手 AI。 "racer"=AggressiveRacerAI(顔詰め)で消極性を罰し「圧をかける/受ける」を学ばせる
FEATURE_VER = "v2"  # 学習 feature version (--feature-ver)。 "v2"=既定(21dim)/"v13"=reserve×lethal(42dim)


def _dl(s):
    return DeckList.from_json(ROOT / "decks" / f"{s}.json", _REPO)


def _ana(s):
    p = ROOT / "decks" / f"{s}.analysis.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


class ExploreBeamAI(ExploitBeamAI):
    """配備 beam + ε探索 + 学習 value (= gbm_path)。 vd OFF (速度)。 = 学習側 エネル。"""

    def __init__(self, rng=None, deck_analysis=None, *, epsilon=0.0, learn_gbm=None, **kw):
        # learn_gbm を gbm_path に渡す (= beam の leaf value を学習 GBM に)。 None → board_eval。
        super().__init__(rng=rng, deck_analysis=deck_analysis, gbm_path=learn_gbm, **kw)
        self.epsilon = epsilon
        self._value_defense = False  # 速度: 防御 sim を切る (offense value 学習に集中)

    def choose_action(self, state):
        rng = self.rng or random
        if self.epsilon > 0 and rng.random() < self.epsilon:
            acts = legal_actions(state)
            if acts:
                return rng.choice(acts)
        return super().choose_action(state)


def _mk_enel(seed, epsilon, learn_gbm, postopp_turns=1, plan_temperature=0.0):
    # postopp_turns>1 = 多ターン探索で手選択。 plan_temperature>0 = 温度サンプルで uncertain な手も試す
    # (= AlphaZero self-play 探索、 打ってみないと良し悪しは分からない)。 どちらも**訓練時のみ**、
    # eval(配備)は postopp_turns=1 + temperature=0(argmax)= 高速 value 推論。
    return ExploreBeamAI(rng=random.Random(seed), deck_analysis={**_ana(DECK), "deck_slug": DECK},
                         epsilon=epsilon, learn_gbm=learn_gbm, beam_width=BEAM_W, max_depth=BEAM_D,
                         postopp_turns=postopp_turns, plan_temperature=plan_temperature)


def _mk_cal(seed, opp):
    # 攻撃的相手で self-play (ohtsuki 提案)。 racer=弱(greedy+顔)/ beamracer=強(ExploitBeam+顔)。
    # ⚠ 弱 racer は強い ExploitBeam に一蹴され 98% 天井=学習 signal 無し。 beamracer は 75% まで
    #   落とせる=学習余地あり(2026-07-08 実測)。 訓練は beamracer 推奨。
    if OPP_AI == "racer":
        from engine.ai_experimental import AggressiveRacerAI
        return AggressiveRacerAI(rng=random.Random(seed + 7),
                                 deck_analysis={**_ana(opp), "deck_slug": opp})
    if OPP_AI == "beamracer":
        from engine.ai_experimental import AggressiveBeamRacerAI
        return AggressiveBeamRacerAI(rng=random.Random(seed + 7),
                                     deck_analysis={**_ana(opp), "deck_slug": opp},
                                     beam_width=BEAM_W, max_depth=BEAM_D)
    return ExploitBeamAI(rng=random.Random(seed + 7), deck_analysis={**_ana(opp), "deck_slug": opp},
                         beam_width=BEAM_W, max_depth=BEAM_D)


def _setup(deck_first, seed, opp):
    if deck_first:
        st = setup_game(_dl(DECK), _dl(opp), rng=random.Random(seed), first_player=0,
                        effects_overlay=_OVERLAY, deck1_analysis=_ana(DECK), deck2_analysis=_ana(opp))
        return st, 0
    st = setup_game(_dl(opp), _dl(DECK), rng=random.Random(seed), first_player=0,
                    effects_overlay=_OVERLAY, deck1_analysis=_ana(opp), deck2_analysis=_ana(DECK))
    return st, 1


def _wire(st, ei, enel, cal):
    ais = [None, None]
    ais[ei] = enel
    ais[1 - ei] = cal
    for i, x in enumerate(ais):
        if hasattr(x, "set_ai_opp"):
            x.set_ai_opp(ais[1 - i])
    return ais


def gen_one(task):
    learn_gbm, epsilon, seed = task
    opp = OPPS[seed % len(OPPS)]  # 累積相手集合から rotate (= 多様化、 過適合防止)
    st, ei = _setup(seed % 2 == 0, seed, opp)
    play_until_main(st)
    # 訓練の手選択: 多ターン探索(TRAIN_POSTOPP_TURNS) + 温度探索(TRAIN_TEMP、 uncertain な手を試す)。
    ais = _wire(st, ei, _mk_enel(seed, epsilon, learn_gbm, postopp_turns=TRAIN_POSTOPP_TURNS,
                                 plan_temperature=TRAIN_TEMP), _mk_cal(seed, opp))
    recs = []
    n = 0
    while not st.game_over and n < 400:
        me = st.turn_player_idx
        try:
            # FEATURE_VER で学習 feature version を切替 (v13 = reserve×lethal board-interactive、 42dim)。
            recs.append(features(st, ei, rich=True, v13=(FEATURE_VER == "v13")))
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


def eval_one(task):
    learn_gbm, seed = task
    st, ei = _setup(seed % 2 == 0, seed, OPP)  # eval は primary #1 vs で一貫
    play_until_main(st)
    ais = _wire(st, ei, _mk_enel(seed, 0.0, learn_gbm), _mk_cal(seed, OPP))
    n_pump = n_atk = n = 0
    while not st.game_over and n < 400:
        me = st.turn_player_idx
        try:
            act = play_one_action(st, ais[me], ais[1 - me])
        except Exception:
            break
        if me == ei:
            if isinstance(act, AttachDonToLeader):
                n_pump += 1
            elif isinstance(act, AttackLeader):
                n_atk += 1
        n += 1
    w = getattr(st, "winner", -1)
    return (1 if w == ei else 0, 1 if (w is not None and w != ei) else 0, n_pump, n_atk)


def train_gbm(data):
    from sklearn.ensemble import GradientBoostingClassifier
    m = GradientBoostingClassifier(n_estimators=150, max_depth=3, learning_rate=0.05,
                                   subsample=0.8, random_state=0)
    m.fit([d[0] for d in data], [d[1] for d in data])
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="cardrush_1467")
    ap.add_argument("--opp", default="tcgportal_calgara",
                    help="標的 #1。 comma 区切りで複数可 = 累積相手集合(現#1+過去#1)で訓練→汎化。 eval/gateは先頭(primary)")
    ap.add_argument("--opp-ai", default="exploitbeam", choices=["exploitbeam", "racer", "beamracer"],
                    help="相手 AI。 racer=弱(greedy+顔、 98%天井)/ beamracer=強(ExploitBeam+顔、 75%=学習余地あり、 推奨)")
    ap.add_argument("--beam-width", type=int, default=8, help="8=moderate(速)/16=配備忠実")
    ap.add_argument("--max-depth", type=int, default=6, help="6=moderate/10=配備忠実")
    ap.add_argument("--iters", type=int, default=6)
    ap.add_argument("--games", type=int, default=40)
    ap.add_argument("--eval", type=int, default=50)
    ap.add_argument("--epsilon", type=float, default=0.25)
    ap.add_argument("--eps-end", type=float, default=0.05)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--train-postopp-turns", type=int, default=1,
                    help="訓練時の手選択の多ターン探索深さ (1=現挙動/2=多ターン探索でデータ生成)。 eval は常に 1(高速配備)")
    ap.add_argument("--train-temp", type=float, default=0.0,
                    help="訓練時の温度探索 (0=argmax/0.5〜1.0=uncertain な手を試す)。 eval は常に 0(argmax配備)")
    ap.add_argument("--feature-ver", default="v2", choices=["v2", "v13"],
                    help="学習 feature version。 v2=既定(21dim)/v13=reserve×lethal board-interactive(42dim、 パターンA修正)")
    ap.add_argument("--arm", default=None,
                    help="候補 pkl の arm 名 (= 出力を db/_selfplay/mcab_<deck>_<arm>.pkl にも保存)")
    a = ap.parse_args()
    global DECK, OPP, OPPS, TRAIN_POSTOPP_TURNS, TRAIN_TEMP, OPP_AI, FEATURE_VER
    DECK = a.deck
    FEATURE_VER = a.feature_ver
    OPPS = [s.strip() for s in a.opp.split(",")]  # comma list = 累積相手集合
    OPP = OPPS[0]  # primary 標的 (eval/gate/命名)
    TRAIN_POSTOPP_TURNS = a.train_postopp_turns
    TRAIN_TEMP = a.train_temp
    OPP_AI = a.opp_ai
    global BEAM_W, BEAM_D
    BEAM_W, BEAM_D = a.beam_width, a.max_depth
    outdir = ROOT / "db" / "_selfplay"
    outdir.mkdir(exist_ok=True)
    print(f"beam-in-loop: {DECK}(beam learn) vs {'+'.join(OPPS)}(配備、 eval=primary {OPP}) | "
          f"iters={a.iters} games={a.games} eval={a.eval} eps={a.epsilon}->{a.eps_end}", flush=True)
    data: list = []
    learn_gbm = None
    hist = []
    for it in range(a.iters):
        t0 = time.time()
        eps = a.epsilon + (a.eps_end - a.epsilon) * (it / max(1, a.iters - 1))
        gt = [(learn_gbm, eps, 7000 * it + g) for g in range(a.games)]
        with mp.Pool(a.workers) as p:
            res = p.map(gen_one, gt, chunksize=1)
        data.extend([r for game in res for r in game])
        try:
            model = train_gbm(data)
            learn_gbm = str(outdir / f"beamloop_{DECK}_iter{it}.pkl")
            with open(learn_gbm, "wb") as f:
                pickle.dump(model, f)
            if a.arm:  # arm 名指定時は候補 pkl にも保存 (= A/B の arm slot)
                arm_path = str(outdir / f"mcab_{DECK}_{a.arm}.pkl")
                with open(arm_path, "wb") as f:
                    pickle.dump(model, f)
        except ValueError:
            print("    (単一クラス、 学習skip)", flush=True)
        et = [(learn_gbm, 90000 + it * 1000 + e) for e in range(a.eval)]
        with mp.Pool(a.workers) as p:
            er = p.map(eval_one, et, chunksize=1)
        w = sum(r[0] for r in er); l = sum(r[1] for r in er)
        wr = w / max(1, a.eval) * 100
        hist.append(wr)
        tag = " (=board_eval baseline)" if it == 0 else ""
        print(f"  iter {it}: エネル(beam) vs カルガラ {w}-{l}/{a.eval} = {wr:.0f}%  "
              f"pump={sum(r[2] for r in er)/max(1,a.eval):.1f} atk={sum(r[3] for r in er)/max(1,a.eval):.1f}"
              f"  (samples={len(data)}) {time.time()-t0:.0f}s{tag}", flush=True)
    print(f"=== SLOPE: {[f'{h:.0f}%' for h in hist]} ===", flush=True)
    if len(hist) >= 2:
        base = hist[0]
        best = max(hist[1:]) if len(hist) > 1 else hist[0]
        print(f"  board_eval(iter0)={base:.0f}% → 学習value best={best:.0f}% (Δ={best-base:+.0f}pt) "
              f"= {'beam で deployable に改善' if best > base + 5 else '改善不明瞭'}")


if __name__ == "__main__":
    main()
