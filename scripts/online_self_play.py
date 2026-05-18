#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 2: online self-play + 1 試合ごと評価関数学習。

各試合終了時に snapshot を蓄積、 ridge regression で 重み再学習、
DEFAULT_WEIGHTS を更新 → 次試合は新重みで実行 (= AlphaZero 的 mini-iter)。

batch (= collect 5000 → train 1 回) と違い、 試合中に AI が成長していく。
弱い AI による「無駄なデータ」 を最小化、 学習効率高い。

per-game timeout (= 60s default) で重試合 (= plan_search 組合せ爆発) は損切り。

Usage:
  .venv/bin/python scripts/online_self_play.py --n-games 1000 --output db/online_snapshots.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import signal
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.ai import (  # noqa: E402
    DeepPlanningAI, GreedyAI, LightDeepPlanningAI,
    LookaheadAI, RandomAI, play_one_action,
)
from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.effects import load_effect_overlay  # noqa: E402
from engine import eval as eval_mod  # noqa: E402
from engine.eval import compute_breakdown  # noqa: E402
from engine.game import play_until_main, setup_game  # noqa: E402

# train_eval_weights.py の FEATURE_TO_WEIGHT_FIELD と同一
from scripts.train_eval_weights import FEATURE_TO_WEIGHT_FIELD  # noqa: E402


OPP_POOL = [
    ("LightDeepPlanningAI", LightDeepPlanningAI, 0.334),
    ("LookaheadAI", LookaheadAI, 0.222),
    ("GreedyAI", GreedyAI, 0.222),
    ("RandomAI", RandomAI, 0.222),
]


class GameTimeout(BaseException):
    """SIGALRM 由来の timeout。 BaseException 継承で `except Exception` に吸収されない。"""
    pass


def _timeout_handler(signum, frame):
    raise GameTimeout()


def play_one_game_with_timeout(
    deck_a: DeckList, ana_a: Optional[dict],
    deck_b: DeckList, ana_b: Optional[dict],
    opp_factory: type, overlay: dict,
    rng: random.Random,
    timeout_s: int = 60,
    max_actions: int = 200,
    max_turns: int = 15,
) -> tuple[list[dict], int, bool]:
    """1 ゲーム実行。 timeout_s 秒で abandon。

    Returns: (snapshots, winner, completed)
      completed=False の試合は学習データに含めない (= 損切り)。
    """
    state = setup_game(
        deck_a, deck_b, rng=rng, first_player=0,
        effects_overlay=overlay,
        deck1_analysis=ana_a, deck2_analysis=ana_b,
    )
    state.record_action_evals = False
    play_until_main(state)

    deepai = LightDeepPlanningAI(rng=rng)
    opp = opp_factory(rng=rng)
    ais = [deepai, opp]
    for i, ai in enumerate(ais):
        if hasattr(ai, "set_ai_opp"):
            ai.set_ai_opp(ais[1 - i])

    snapshots: list[dict] = []
    actions = 0
    completed = True
    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(timeout_s)
    try:
        while (
            not state.game_over
            and actions < max_actions
            and state.turn_number <= max_turns
        ):
            me = state.turn_player_idx
            opp_idx = 1 - me
            try:
                play_one_action(state, ais[me], ais[opp_idx], referee=None)
            except Exception as e:
                state.declare_winner(opp_idx, f"engine error: {e}")
                break
            actions += 1
            try:
                bd = compute_breakdown(state, 0)
                snap_features = {k: float(v["diff"]) for k, v in bd.items()}
                snapshots.append({
                    "turn": state.turn_number,
                    "actor_idx": me,
                    "features": snap_features,
                })
            except Exception:
                continue
    except GameTimeout:
        completed = False
    finally:
        signal.alarm(0)

    if state.winner is None:
        winner = 0
    else:
        winner = 1 if state.winner == 0 else -1
    return snapshots, winner, completed


def select_opponent(rng: random.Random) -> tuple[str, type]:
    r = rng.random()
    cum = 0.0
    for name, factory, p in OPP_POOL:
        cum += p
        if r < cum:
            return name, factory
    return OPP_POOL[-1][0], OPP_POOL[-1][1]


def load_deck_pool() -> list[tuple[str, DeckList, Optional[dict]]]:
    from engine.harness import _try_load_deck_analysis
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    decks = []
    for pat in ("cardrush_*.json", "tcgportal_*.json"):
        for path in sorted((ROOT / "decks").glob(pat)):
            if path.name.endswith(".analysis.json"):
                continue
            slug = path.stem
            try:
                deck = DeckList.from_json(path, repo)
                deck.slug = slug
                ana = _try_load_deck_analysis(deck)
                decks.append((slug, deck, ana))
            except Exception:
                pass
    return decks


def sgd_update_weights(
    weights: dict, snapshots: list[dict], winner: int,
    feature_names: list[str], lr: float, target_scale: float,
    max_delta: float = 10.0,
) -> tuple[dict, float]:
    """SGD で base 重みを微調整 (= ユーザ指示「初期値から ±10 くらいで何回も」)。

    1 試合 = 1 SGD step (= snapshot 平均化)。

    Algorithm:
        avg_feature = mean(snapshot.features for snap in snapshots)
        pred = sum(avg_feature[k] * weights[k] for k)
        pred_norm = tanh(pred / target_scale)        # ±1 に bound
        target = winner                              # ±1
        error = target - pred_norm                   # ±2
        for k:
            delta = lr * error * avg_feature[k]
            delta = clip(delta, -max_delta, +max_delta)
            weights[k] += delta

    pred を tanh で正規化 + per-step clip で爆発を防ぐ (= 元実装は pred ±数万 / error ±数万
    で 1 step あたり 重み が 数千ずれる現象あり)。

    Returns: (updates_dict, normalized_error)
    """
    import math
    if not snapshots:
        return {}, 0.0

    # 試合の snapshot を平均化
    avg = {name: 0.0 for name in feature_names}
    for snap in snapshots:
        feat = snap.get("features", {})
        for name in feature_names:
            avg[name] += float(feat.get(name, 0.0))
    n = len(snapshots)
    for name in feature_names:
        avg[name] /= n

    # 予測 score (= 既存重みで)
    pred = 0.0
    for name in feature_names:
        wfield = FEATURE_TO_WEIGHT_FIELD.get(name)
        if wfield and wfield in weights:
            pred += avg[name] * weights[wfield]

    # tanh 正規化 (= ±1 に bound、 target_scale で steepness 調整)
    pred_norm = math.tanh(pred / target_scale)
    target = float(winner)  # ±1 / 0
    error = target - pred_norm  # ±2 max

    # SGD step (= 各重みを ±lr * error * feature で更新、 clip)
    updates = {}
    for name in feature_names:
        wfield = FEATURE_TO_WEIGHT_FIELD.get(name)
        if wfield and wfield in weights:
            delta = lr * error * avg[name]
            if delta > max_delta:
                delta = max_delta
            elif delta < -max_delta:
                delta = -max_delta
            new_val = weights[wfield] + delta
            updates[wfield] = new_val
    return updates, error


def apply_in_memory_weights(updates: dict, weights_dict: dict) -> None:
    """eval_mod.DEFAULT_WEIGHTS と weights_dict 両方を update。
    plan_search が次試合で新重みを参照する。
    """
    for k, v in updates.items():
        weights_dict[k] = v
        if hasattr(eval_mod.DEFAULT_WEIGHTS, k):
            setattr(eval_mod.DEFAULT_WEIGHTS, k, int(round(v)))


def persist_weights_to_json(weights_dict: dict, path: Path, note: str = "") -> None:
    """ai_params.json に書き出し (= 永続化、 次回起動時に load される)。"""
    if path.exists():
        doc = json.loads(path.read_text(encoding="utf-8"))
    else:
        doc = {"version": "1", "params": {}}
    p = doc.get("params", {})
    for wfield, val in weights_dict.items():
        p[wfield.lower()] = int(round(val))
    doc["params"] = p
    doc["saved_at"] = datetime.now(timezone.utc).isoformat()
    doc["note"] = f"online_self_play SGD 更新: {note}"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def load_initial_weights() -> dict:
    """eval_mod.DEFAULT_WEIGHTS から W_ field を全部 dict 化 (= float で精度維持)。"""
    out = {}
    for fname in dir(eval_mod.DEFAULT_WEIGHTS):
        if fname.startswith("W_") and fname != "W_GAME_OVER":
            out[fname] = float(getattr(eval_mod.DEFAULT_WEIGHTS, fname))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n-games", type=int, default=1000)
    ap.add_argument(
        "--output",
        type=Path,
        default=ROOT / "db" / "online_snapshots.jsonl",
    )
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--timeout-s", type=int, default=60, help="1 試合 timeout (秒)")
    ap.add_argument("--max-actions", type=int, default=200)
    ap.add_argument("--max-turns", type=int, default=15)
    ap.add_argument("--lr", type=float, default=1.0, help="SGD 学習率 (= 1 step あたり ±数 の更新)")
    ap.add_argument(
        "--target-scale", type=float, default=5000.0,
        help="pred を tanh(pred/target_scale) で ±1 正規化する steepness パラメータ",
    )
    ap.add_argument(
        "--max-delta", type=float, default=10.0,
        help="1 step あたり 重み 変動の上限 clip (= 爆発防止)",
    )
    ap.add_argument(
        "--persist-every", type=int, default=50,
        help="N 試合ごと ai_params.json に永続化 (= crash 耐性)",
    )
    ap.add_argument(
        "--warmup-games", type=int, default=20,
        help="序盤 N 試合は学習スキップ (= 重み固定で初期 baseline データ)",
    )
    args = ap.parse_args()

    rng_master = random.Random(args.seed)
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    deck_pool = load_deck_pool()
    print(f"deck pool: {len(deck_pool)} decks, n_games={args.n_games}, timeout={args.timeout_s}s")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    f_jsonl = args.output.open("a", encoding="utf-8")

    feature_names = list(FEATURE_TO_WEIGHT_FIELD.keys())
    weights_dict = load_initial_weights()  # base 重み を起点に SGD update
    print(f"initial weights loaded ({len(weights_dict)} fields)")
    print(f"  w_life={weights_dict.get('W_LIFE', 0):.0f}, "
          f"w_lethal={weights_dict.get('W_LETHAL', 0):.0f}, "
          f"w_blocker={weights_dict.get('W_BLOCKER', 0):.0f}")

    t0 = time.time()
    n_completed = 0
    n_timeout = 0
    win_counts = {name: [0, 0, 0] for name, _, _ in OPP_POOL}
    error_history: list[float] = []

    ai_params_path = ROOT / "db" / "ai_params.json"

    try:
        for g in range(args.n_games):
            seed = rng_master.randrange(2**31)
            sub_rng = random.Random(seed)
            opp_name, opp_factory = select_opponent(sub_rng)
            a_idx = sub_rng.randrange(len(deck_pool))
            b_idx = sub_rng.randrange(len(deck_pool))
            deck_a_slug, deck_a, ana_a = deck_pool[a_idx]
            deck_b_slug, deck_b, ana_b = deck_pool[b_idx]
            game_t0 = time.time()
            try:
                snaps, winner, completed = play_one_game_with_timeout(
                    deck_a, ana_a, deck_b, ana_b,
                    opp_factory, overlay, sub_rng,
                    timeout_s=args.timeout_s,
                    max_actions=args.max_actions,
                    max_turns=args.max_turns,
                )
            except Exception as e:
                print(f"  [g{g}] failed: {e}")
                traceback.print_exc()
                continue
            game_elapsed = time.time() - game_t0

            if not completed:
                n_timeout += 1
                print(f"  [g{g}] TIMEOUT after {game_elapsed:.1f}s "
                      f"({deck_a_slug} vs {deck_b_slug}, opp={opp_name})")
                continue

            n_completed += 1
            if winner == 1:
                win_counts[opp_name][0] += 1
            elif winner == -1:
                win_counts[opp_name][1] += 1
            else:
                win_counts[opp_name][2] += 1

            # snapshot を file に追加
            for snap in snaps:
                snap.update({
                    "game_idx": g, "deck_a": deck_a_slug, "deck_b": deck_b_slug,
                    "opp_type": opp_name, "final_winner": winner,
                })
                f_jsonl.write(json.dumps(snap, ensure_ascii=False, separators=(",", ":")) + "\n")
            f_jsonl.flush()

            # === SGD 学習 (= warmup 後、 各試合 1 step) ===
            if g >= args.warmup_games and snaps:
                updates, error = sgd_update_weights(
                    weights_dict, snaps, winner,
                    feature_names, args.lr, args.target_scale,
                    max_delta=args.max_delta,
                )
                apply_in_memory_weights(updates, weights_dict)
                error_history.append(error)

                if (g + 1) % 10 == 0 or g + 1 == args.n_games:
                    elapsed = time.time() - t0
                    rate = (g + 1) / elapsed
                    eta = (args.n_games - g - 1) / rate if rate else 0
                    avg_err = sum(error_history[-50:]) / max(1, min(50, len(error_history)))
                    # 主要重みの 現在値 を表示 (= 進化を追う)
                    print(
                        f"  [g{g+1}/{args.n_games}] err_avg(last50)={avg_err:+.0f}, "
                        f"timeouts={n_timeout}, completed={n_completed}, "
                        f"rate={rate:.2f}g/s, ETA {eta/60:.1f}min, "
                        f"w_life={weights_dict['W_LIFE']:.0f}, "
                        f"w_lethal={weights_dict['W_LETHAL']:.0f}, "
                        f"w_blocker={weights_dict['W_BLOCKER']:.0f}"
                    )

            # 永続化
            if (g + 1) % args.persist_every == 0 and g >= args.warmup_games:
                persist_weights_to_json(
                    weights_dict, ai_params_path,
                    note=f"g{g+1}/{args.n_games} SGD lr={args.lr}",
                )
                print(f"  ✔ persisted weights to {ai_params_path.name}")
    finally:
        f_jsonl.close()
        elapsed = time.time() - t0
        print(
            f"\nDONE: {n_completed} completed / {n_timeout} timeouts / {args.n_games} total "
            f"in {elapsed/60:.1f}min ({elapsed/3600:.2f}h)"
        )
        for k, (w, l, d) in win_counts.items():
            tot = w + l + d
            wr = w / tot if tot else 0
            print(f"  vs {k}: {w}W-{l}L-{d}D ({wr:.1%})")


if __name__ == "__main__":
    main()
