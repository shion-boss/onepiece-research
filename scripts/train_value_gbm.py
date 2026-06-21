#!/usr/bin/env python3
"""beam-vs-greedy の (盤面features, 勝敗) を集めて GBM value を学習 (= 2026-06-04, 70% 探索)。

beam は board_eval (= 線形 winrate-tune) で 62.5% 飽和。 非線形 GBM を beam-vs-greedy の
盤面→勝敗で学習し、 beam の leaf eval に使えば線形の天井を破れるか試す。
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import pickle
import random
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import numpy as np

from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import Phase, advance_phase, setup_game, play_until_main
from engine.ai import GreedyAI, DeepPlanningAI, play_one_action
from engine.gbm_value import features
from engine.turn_plan_enumerator import fast_clone

_REPO = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(REPO_ROOT / "db" / "card_effects.json")

_W: dict = {}


def _load(slug: str):
    return make_deck_from_dict(
        __import__("json").loads((REPO_ROOT / "decks" / f"{slug}.json").read_text(encoding="utf-8")),
        _REPO)


def _winit(slug: str) -> None:
    _W["slug"] = slug


def _make_beam(seed: int):
    # policy iteration: ONEPIECE_GBM_COLLECT_POLICY=exploitbeam で強いAI自身でデータ生成。
    if os.environ.get("ONEPIECE_GBM_COLLECT_POLICY") == "exploitbeam":
        from engine.exploit_beam_ai import ExploitBeamAI
        return ExploitBeamAI(rng=random.Random(seed * 5 + 1), beam_width=16, max_depth=10)
    ai = DeepPlanningAI(rng=random.Random(seed * 5 + 1), beam_width=8, max_depth=8,
                        adaptive=False, max_turns=1)
    ai.set_ai_opp(GreedyAI(rng=random.Random(seed * 7 + 3)))
    return ai


def _make_rollout_ai(rng, slug: str):
    """rollout policy を env ONEPIECE_GBM_ROLLOUT_AI で切替 (= 改善のツマミ)。
    greedy(既定/高速) → light/beam(強policy・policy整合↑) → exploitbeam(配備同等・最重)。
    policy が配備(ExploitBeam)に近いほどラベルが policy 整合 → メタGBM超えを狙える。"""
    kind = os.environ.get("ONEPIECE_GBM_ROLLOUT_AI", "greedy")
    if kind == "light":
        from engine.ai import LightDeepPlanningAI
        ai = LightDeepPlanningAI(rng=rng, beam_width=4, max_depth=6, adaptive=False, max_turns=1)
        ai.set_ai_opp(GreedyAI(rng=rng))
        return ai
    if kind == "beam":
        ai = DeepPlanningAI(rng=rng, beam_width=4, max_depth=6, adaptive=False, max_turns=1)
        ai.set_ai_opp(GreedyAI(rng=rng))
        return ai
    if kind == "exploitbeam":
        from engine.exploit_beam_ai import ExploitBeamAI
        return ExploitBeamAI(rng=rng, deck_analysis={"deck_slug": slug})
    return GreedyAI(rng=rng)


def _rollout_winrate(snapshot, me_idx: int, n: int, base_seed: int) -> float:
    """snapshot から rollout policy 同士で最後まで n 回 playout → me_idx の勝率 (= 低分散ラベル)。
    = 検証ハーネス(validate_better_moves)の rollout を value ラベル生成に転用。 policy は
    ONEPIECE_GBM_ROLLOUT_AI で切替 (= 既定 greedy)。"""
    slug = _W.get("slug", "")
    wins = 0
    start_turn = snapshot.turn_number
    for i in range(n):
        rng = random.Random(base_seed * 1009 + i)
        st = fast_clone(snapshot)
        st.rng = random.Random(base_seed * 7919 + i)
        ais = {0: _make_rollout_ai(rng, slug), 1: _make_rollout_ai(random.Random(base_seed * 13 + i), slug)}
        guard = 0
        while not st.game_over and guard < 800:
            guard += 1
            if st.turn_number > start_turn + 40:
                break
            tp = st.turn_player_idx
            if st.phase == Phase.MAIN:
                try:
                    play_one_action(st, ais[tp], ais[1 - tp])
                except Exception:
                    break
            else:
                advance_phase(st)
        if st.game_over and getattr(st, "winner", -1) == me_idx:
            wins += 1
    return wins / max(1, n)


def _collect_game(seed: int) -> list:
    slug = _W["slug"]
    fp = seed % 2
    state = setup_game(_load(slug), _load(slug), rng=random.Random(seed),
                       first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    test_idx = 0 if fp == 0 else 1
    selfplay = os.environ.get("ONEPIECE_GBM_SELFPLAY") == "1"
    record_all = os.environ.get("ONEPIECE_GBM_RECORD_ALL") == "1"
    ais = [None, None]
    ais[test_idx] = _make_beam(seed)        # = value を使う側
    # self-play: 相手も同じ強いAI (= ExploitBeam)。 さもなくば greedy。
    if selfplay:
        ais[1 - test_idx] = _make_beam(seed * 3 + 99)
    else:
        ais[1 - test_idx] = GreedyAI(rng=random.Random(seed * 5 + 2))
    rollout_n = int(os.environ.get("ONEPIECE_GBM_ROLLOUT_N", "0"))
    feats: list = []
    seen_turns: set = set()
    n = 0
    while not state.game_over and state.turn_number < 50 and n < 1500:
        cur = state.turn_player_idx
        # record_all: 自ターン中の全盤面 (= beam の葉分布をカバー)。 さもなくば MAIN 開始のみ。
        if cur == test_idx and state.phase == Phase.MAIN:
            if record_all or state.turn_number not in seen_turns:
                seen_turns.add(state.turn_number)
                try:
                    fv = features(state, test_idx)
                    if rollout_n > 0:
                        # 検証ハーネス組み込み: この局面から greedy で N 回 playout した勝率を
                        # 低分散ラベルにする (= 単一試合 outcome 0/1 の高分散を置換)。
                        w = _rollout_winrate(fast_clone(state), test_idx, rollout_n,
                                             base_seed=seed * 1000 + state.turn_number)
                        feats.append((fv, w))
                    else:
                        feats.append(fv)
                except Exception:
                    pass
        try:
            play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    if rollout_n > 0:
        # ラベルは rollout 由来なので recorder ゲームの終局は不要。 (features, winrate) を返す。
        return feats
    if not state.game_over:
        return []
    won = 1 if getattr(state, "winner", -1) == test_idx else 0
    return [(f, won) for f in feats]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="cardrush_1342")
    ap.add_argument("--games", type=int, default=500)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "db" / "value_gbm_cardrush_1342.pkl")
    ap.add_argument("--rich", action=argparse.BooleanOptionalAction, default=True,
                    help="rich(v2=21特徴: lethal+counter)で学習 (既定)。 --no-rich で v1(17特徴)")
    ap.add_argument("--v3", action="store_true",
                    help="v3(23特徴: v2 + raw active DON)で学習。 --rich を上書きで有効化")
    ap.add_argument("--rollout-label", type=int, default=0,
                    help="各局面を N 回 rollout の勝率でラベル付け (= 検証ハーネス組込、 "
                         "低分散ラベル。 0=従来の単一試合outcome 0/1)")
    ap.add_argument("--rollout-ai", default="greedy",
                    choices=["greedy", "light", "beam", "exploitbeam"],
                    help="rollout policy (= 改善のツマミ。 配備に近いほどメタGBM超えを狙える、 ただし重い)")
    ap.add_argument("--record-all", action="store_true",
                    help="全葉局面を記録 (= 葉カバレッジ。 効果まちまち+A/Bノイズ大、 要 high-N 検証)")
    args = ap.parse_args()

    # rich/v3 を worker spawn 前に env で伝播 (= fork 継承、 gbm_value.features が読む)。
    os.environ["ONEPIECE_GBM_RICH"] = "1" if (args.rich or args.v3) else "0"
    os.environ["ONEPIECE_GBM_V3"] = "1" if args.v3 else "0"
    os.environ["ONEPIECE_GBM_ROLLOUT_N"] = str(args.rollout_label)
    os.environ["ONEPIECE_GBM_ROLLOUT_AI"] = args.rollout_ai
    # 葉カバレッジ (= RECORD_ALL): beam が評価する多様な葉局面を value がカバー。 1466 で
    # 6.2%→31.2% の改善を見たが fleet では効果まちまち + A/B ノイズ大 → 既定 OFF の明示フラグ。
    if args.record_all:
        os.environ["ONEPIECE_GBM_RECORD_ALL"] = "1"

    _tag = "v3" if args.v3 else ("rich-v2" if args.rich else "v1")
    print(f"=== collect beam-vs-greedy ({args.deck}, {args.games} games, "
          f"{_tag}) ===", flush=True)
    t0 = time.perf_counter()
    seeds = list(range(800000, 800000 + args.games))
    rows: list = []
    with mp.Pool(args.workers, initializer=_winit, initargs=(args.deck,)) as pool:
        for i, out in enumerate(pool.imap_unordered(_collect_game, seeds, chunksize=1)):
            rows.extend(out)
            if (i + 1) % 50 == 0:
                print(f"  {i+1}/{args.games} games, {len(rows)} samples", flush=True)
    print(f"collected {len(rows)} samples in {time.perf_counter()-t0:.0f}s", flush=True)
    if len(rows) < 200:
        print("ERROR: too few samples", flush=True)
        return

    X = np.array([r[0] for r in rows], dtype=float)
    from sklearn.model_selection import cross_val_score
    args.out.parent.mkdir(parents=True, exist_ok=True)

    if args.rollout_label > 0:
        # rollout 勝率 (連続) を回帰 (= 検証ハーネス組込)。 推論 gbm_score は regressor を predict で扱う。
        y = np.array([r[1] for r in rows], dtype=float)
        print(f"X shape {X.shape}, mean rollout winrate {y.mean():.3f} "
              f"(std {y.std():.3f}, n_pos {len(y)})", flush=True)
        from sklearn.ensemble import GradientBoostingRegressor
        model = GradientBoostingRegressor(n_estimators=200, max_depth=3, learning_rate=0.05,
                                          subsample=0.8, random_state=0)
        cv = cross_val_score(model, X, y, cv=4, scoring="r2")
        print(f"CV R2 (winrate回帰): {cv.mean():.3f} +/- {cv.std():.3f}", flush=True)
    else:
        y = np.array([r[1] for r in rows], dtype=int)
        print(f"X shape {X.shape}, win rate {y.mean():.1%}", flush=True)
        from sklearn.ensemble import GradientBoostingClassifier
        model = GradientBoostingClassifier(n_estimators=200, max_depth=3, learning_rate=0.05,
                                           subsample=0.8, random_state=0)
        cv = cross_val_score(model, X, y, cv=4, scoring="roc_auc")
        print(f"CV ROC-AUC: {cv.mean():.3f} +/- {cv.std():.3f}", flush=True)

    model.fit(X, y)
    with open(args.out, "wb") as f:
        pickle.dump(model, f)
    print(f"saved GBM -> {args.out}", flush=True)


if __name__ == "__main__":
    main()
