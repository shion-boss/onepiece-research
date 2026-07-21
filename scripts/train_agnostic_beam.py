#!/usr/bin/env python3
"""deck非依存 (agnostic) value を beam-in-loop で再学習する。

動機 (2026-07-21): archetype gate 緩和で全 pkl無しデッキ (=ユーザー自作 + pros02 の一部) が
agnostic value を使う → agnostic を強くすれば全デッキの底が同時に上がる (最大波及レバー)。

現 db/value_gbm_agnostic.pkl は **greedy self-play** 産 (scripts/value_agnostic.py)。 だが配備は
beam(ExploitBeam)。 AlphaZero 原則『探索の分布で学習せよ』([[project_selfplay_self_improvement_engine]]):
greedy 分布で学んだ value は beam に非 transfer。 → **多様デッキ × beam-in-loop** で 21dim value を
学習し直せば beam 分布に整合 = 現 greedy-agnostic を超える見込み (luffy_gb 単一で board_eval→+22pt
を得たのと同原理を、 単一でなく多デッキ pool に汎化)。

設計:
  - learn 側 = 多様デッキ pool から rotate (= deck非依存性を担保、 過適合防止)。 両者とも beam+学習value。
  - epsilon-greedy 探索 + 温度で分布を広げる。 iter 毎に GBM 再学習 → 次 iter の beam leaf に使う。
  - feature = gbm_value.features(rich=True) = 21dim (= 現 agnostic と同一次元、 drop-in 互換)。
出力 = db/_selfplay/agnostic_beam_iter<N>.pkl。 held-out A/B (gate_hypothesis_ab.py の agn arm に差す)
で現 agnostic 超えを確認してから db/value_gbm_agnostic.pkl に昇格。

  .venv/bin/python scripts/train_agnostic_beam.py --pool cardrush_1385,cardrush_1454,tcgportal_bonney,pros02_zoro_g \
      --iters 5 --games 40 --workers 12
"""
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
from engine.game import setup_game, play_until_main
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI
from engine.gbm_value import features

_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")

POOL: list = []
BEAM_W = 8
BEAM_D = 6
_DL_CACHE = {}
_ANA_CACHE = {}


def _dl(s):
    if s not in _DL_CACHE:
        _DL_CACHE[s] = DeckList.from_json(ROOT / "decks" / f"{s}.json", _REPO)
    return _DL_CACHE[s]


def _ana(s):
    if s not in _ANA_CACHE:
        p = ROOT / "decks" / f"{s}.analysis.json"
        _ANA_CACHE[s] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return _ANA_CACHE[s]


def _mk_ai(seed, gbm_path, epsilon=0.0):
    """beam AI。 gbm_path=学習中 value (None=board_eval)。 agnostic 学習なので deck_slug を
    渡さず、 gbm_path 明示で per-deck pkl 解決を回避 (= pure agnostic leaf)。"""
    ai = ExploitBeamAI(rng=random.Random(seed), deck_analysis={"deck_slug": "__agnostic_train__"},
                       beam_width=BEAM_W, max_depth=BEAM_D, gbm_path=gbm_path)
    ai._use_agnostic_gbm = (gbm_path is None)  # gbm 無ければ agnostic fallback を許す
    ai._epsilon = epsilon
    return ai


def gen_one(task):
    """1 game beam self-play。 learn/opp を pool から seed で選び、 両者 beam。
    毎ターン頭で turn_player の 21dim feature をサンプル → 勝敗ラベル。"""
    gbm_path, epsilon, seed = task
    rng = random.Random(seed)
    d_learn = POOL[seed % len(POOL)]
    d_opp = POOL[(seed // len(POOL) + 1) % len(POOL)]
    first = seed % 2
    a, b = (d_learn, d_opp) if first == 0 else (d_opp, d_learn)
    st = setup_game(_dl(a), _dl(b), rng=random.Random(seed), first_player=0,
                    effects_overlay=_OVERLAY, deck1_analysis=_ana(a), deck2_analysis=_ana(b))
    play_until_main(st)
    ai0 = _mk_ai(seed, gbm_path, epsilon)
    ai1 = _mk_ai(seed + 1, gbm_path, epsilon)
    ais = [ai0, ai1]
    recs = []  # (feature, player_idx) — ラベルは終局で付ける
    n = 0
    while not st.game_over and n < 400:
        me = st.turn_player_idx
        try:
            recs.append((features(st, me, rich=True), me))
        except Exception:
            pass
        try:
            play_one_action(st, ais[me], ais[1 - me])
        except Exception:
            break
        n += 1
    w = getattr(st, "winner", -1)
    return [(fv, 1 if w == pi else 0) for fv, pi in recs]


def eval_one(task):
    """held-out 的な eval: pool 内 mirror でなく、 学習 value vs board_eval を同 pool で戦わせ
    勝率を見る (= value が board_eval に勝つか = 学習が効いたか)。"""
    gbm_path, seed = task
    d_a = POOL[seed % len(POOL)]
    d_b = POOL[(seed // len(POOL) + 1) % len(POOL)]
    st = setup_game(_dl(d_a), _dl(d_b), rng=random.Random(seed), first_player=0,
                    effects_overlay=_OVERLAY, deck1_analysis=_ana(d_a), deck2_analysis=_ana(d_b))
    play_until_main(st)
    learn_ai = _mk_ai(seed, gbm_path)          # P0 = 学習 value
    board_ai = _mk_ai(seed + 1, None)          # P1 = board_eval
    ais = [learn_ai, board_ai]
    n = 0
    while not st.game_over and n < 400:
        me = st.turn_player_idx
        try:
            play_one_action(st, ais[me], ais[1 - me])
        except Exception:
            break
        n += 1
    w = getattr(st, "winner", -1)
    return 1 if w == 0 else 0   # 学習 value(P0) が勝ったか


def train_gbm(data):
    from sklearn.ensemble import GradientBoostingClassifier
    m = GradientBoostingClassifier(n_estimators=150, max_depth=3, learning_rate=0.05,
                                   subsample=0.8, random_state=0)
    m.fit([d[0] for d in data], [d[1] for d in data])
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default="cardrush_1385,cardrush_1454,tcgportal_bonney,pros02_zoro_g,cardrush_1342,tcgportal_calgara")
    ap.add_argument("--iters", type=int, default=5)
    ap.add_argument("--games", type=int, default=40)
    ap.add_argument("--eval", type=int, default=40)
    ap.add_argument("--epsilon", type=float, default=0.25)
    ap.add_argument("--eps-end", type=float, default=0.05)
    ap.add_argument("--beam-width", type=int, default=8)
    ap.add_argument("--max-depth", type=int, default=6)
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    global POOL, BEAM_W, BEAM_D
    POOL = [s.strip() for s in a.pool.split(",")]
    BEAM_W, BEAM_D = a.beam_width, a.max_depth
    outdir = ROOT / "db" / "_selfplay"
    outdir.mkdir(exist_ok=True)
    print(f"agnostic beam-in-loop: pool={POOL} | iters={a.iters} games={a.games} "
          f"beam={BEAM_W}/{BEAM_D} eps={a.epsilon}->{a.eps_end}", flush=True)
    data = []
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
            learn_gbm = str(outdir / f"agnostic_beam_iter{it}.pkl")
            with open(learn_gbm, "wb") as f:
                pickle.dump(model, f)
        except ValueError:
            print("    (単一クラス、 学習 skip)", flush=True)
            continue
        et = [(learn_gbm, 90000 + it * 1000 + e) for e in range(a.eval)]
        with mp.Pool(a.workers) as p:
            er = p.map(eval_one, et, chunksize=1)
        wr = sum(er) / max(1, a.eval) * 100
        hist.append(wr)
        tag = " (=board_eval baseline は 50%)" if it == 0 else ""
        print(f"  iter {it}: 学習value vs board_eval {sum(er)}-{a.eval-sum(er)}/{a.eval} = {wr:.0f}%  "
              f"(samples={len(data)}) {time.time()-t0:.0f}s{tag}", flush=True)
    print(f"=== SLOPE (学習value vs board_eval 勝率): {[f'{h:.0f}%' for h in hist]} ===", flush=True)
    if hist:
        best_it = max(range(len(hist)), key=lambda i: hist[i])
        print(f"  best = iter{best_it} ({hist[best_it]:.0f}% vs board_eval) → "
              f"db/_selfplay/agnostic_beam_iter{best_it}.pkl")
        print(f"  次: gate_hypothesis_ab.py の agn arm に差して現 agnostic 超えを確認 → 昇格")


if __name__ == "__main__":
    main()
