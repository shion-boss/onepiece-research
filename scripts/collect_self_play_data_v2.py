#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Plan Phase E (= v2): NN policy + state-encoder 学習用 self-play データ収集。

collect_self_play_data.py の改造版。 v1 (= 78 dim features dict) に加えて:
- state_encoded: engine.state_encoder.encode_state 172 dim list (= state-encoder 学習用)
- action_idx: ACTION_CATEGORY_TO_IDX[type(action).__name__] int (= policy head 学習用)

を各 snapshot に追加記録する。 これにより:
- (3) state encoder 化 NN 学習 (= 172 dim 入力モデル)
- (4) policy head 本気学習 (= action_idx を target)

の両方が 1 度の self-play 再走で揃う。

サイズ目安: 1 snapshot あたり ~1.5KB 増 (= 172 float)、 30 万 snapshot で +450MB。
旧 695MB + 450MB = 約 1.1GB 出力。

Usage:
  .venv/bin/python scripts/collect_self_play_data_v2.py --n-games 5000 --workers 8
  .venv/bin/python scripts/collect_self_play_data_v2.py --n-games 100 --output /tmp/test_v2.jsonl --workers 4
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import random
import sys
import time
import traceback
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.ai import DeepPlanningAI, GreedyAI, LightDeepPlanningAI, LookaheadAI, RandomAI, play_one_action  # noqa: E402
from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.effects import load_effect_overlay  # noqa: E402
from engine.eval import compute_breakdown  # noqa: E402
from engine.game import play_until_main, setup_game  # noqa: E402
from engine.harness import _construct_ai, _try_load_deck_analysis  # noqa: E402
from engine.nn_eval import ACTION_CATEGORIES, ACTION_CATEGORY_TO_IDX  # noqa: E402  (= v2 追加)
from engine.state_encoder import encode_state, encoded_dim  # noqa: E402  (= v2 追加)


# (name, factory, sampling_probability) — 計画書: peer 33% + others 22% × 3
# 軽量 DeepAI + Lookahead/Greedy/Random rotation で 5000 試合 ~14h 想定
OPP_POOL = [
    # Step 2 (= 2026-05-16/17): 軽量化のため LightDeepPlanningAI 削除
    # variant pool 157 deck で hand_estimator pool 計算が爆増、 14h hang した。
    # plan Step 6 (= NN 推論最適化) 後に LightDeep 復活予定。
    ("GreedyAI", GreedyAI, 0.50),
    ("LookaheadAI", LookaheadAI, 0.30),
    ("RandomAI", RandomAI, 0.20),
]


# --------------------------------------------------------------------------- #
# worker-side global (= initializer で 1 度だけロード)
# --------------------------------------------------------------------------- #
_WORKER_REPO: Optional[CardRepository] = None
_WORKER_OVERLAY: Optional[dict] = None
_WORKER_DECK_POOL: Optional[list[tuple[str, DeckList, Optional[dict]]]] = None


def _worker_init() -> None:
    """各 worker で 1 度だけ呼ばれる。 重いリソース (= cards.json / overlay / deck pool) をロード。

    Step 2 (= 2026-05-16): Phase 8 で導入された `decks/<leader_slug>/variant_*.json` も pool に
    含めて 132 leader × 1-4 variant ≒ 157 構築の cross matchup を可能にする。
    """
    global _WORKER_REPO, _WORKER_OVERLAY, _WORKER_DECK_POOL
    _WORKER_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
    _WORKER_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")
    _WORKER_DECK_POOL = []
    seen_slugs: set[str] = set()

    def _try_add(path):
        if path.name.endswith(".analysis.json"):
            return
        slug = path.stem if path.parent.name == "decks" else f"{path.parent.name}__{path.stem}"
        if slug in seen_slugs:
            return
        try:
            deck = DeckList.from_json(path, _WORKER_REPO)
            deck.slug = slug
            ana = _try_load_deck_analysis(deck)
            _WORKER_DECK_POOL.append((slug, deck, ana))
            seen_slugs.add(slug)
        except Exception:
            pass

    # 既存 16 デッキ (= cardrush_/tcgportal_)
    for pattern in ("cardrush_*.json", "tcgportal_*.json"):
        for path in sorted((ROOT / "decks").glob(pattern)):
            _try_add(path)

    # Phase 8 (= 2026-05-16): variant 構築 (= decks/<leader_slug>/variant_*.json)
    for variant_path in sorted((ROOT / "decks").glob("*/variant_*.json")):
        if variant_path.name.endswith(".analysis.json"):
            continue
        _try_add(variant_path)


def _categorize_action_name(class_name: Optional[str]) -> Optional[str]:
    """Action class 名から ACTION_CATEGORIES キーへ簡易マップ (= 関数 11 学習用)。"""
    if not class_name:
        return None
    name_upper = class_name.upper()
    if "PLAY" in name_upper and "CHAR" in name_upper:
        return "PlayCharacter"
    if "PLAY" in name_upper and "EVENT" in name_upper:
        return "PlayEvent"
    if "PLAY" in name_upper and "STAGE" in name_upper:
        return "PlayStage"
    if "ACTIVATE" in name_upper:
        return "ActivateMain"
    if "ATTACK" in name_upper and "LEADER" in name_upper:
        return "AttackLeader"
    if "ATTACK" in name_upper:
        return "AttackCharacter"
    if "DON" in name_upper or "ATTACH" in name_upper:
        return "AttachDon"
    if "PASS" in name_upper:
        return "PassMain"
    if "END" in name_upper:
        return "EndPhase"
    return "Other"


def _play_one_game(
    deck_a: DeckList,
    ana_a: Optional[dict],
    deck_b: DeckList,
    ana_b: Optional[dict],
    opp_factory: type,
    overlay: dict,
    rng: random.Random,
    max_actions: int = 200,
    max_turns: int = 15,
) -> tuple[list[dict], int]:
    """1 ゲーム実行。 LightDeepAI = P0、 opp = P1 (= snapshot は P0 視点)。

    Returns (snapshots, winner_for_lightdeepai) where winner = 1 / -1 / 0(draw).

    OPTCG は通常 6-9 ターンで終わるので max_turns=15 でほぼ全試合をカバー。
    ループ抑止と peer 対戦の長期化対策で max_actions=200 も併用。
    """
    state = setup_game(
        deck_a, deck_b, rng=rng, first_player=0,
        effects_overlay=overlay,
        deck1_analysis=ana_a, deck2_analysis=ana_b,
    )
    state.record_action_evals = False
    play_until_main(state)

    # 直接構築 (= deck_analysis 経由の重い init を避ける)。
    # Step 2 (= 2026-05-17): P0 も LightDeepPlanningAI → GreedyAI に軽量化。
    # variant pool 拡大で LightDeep は 6-10 分/g → hang した。 GreedyAI は ~3s/g。
    # plan Step 6 後に DeepPlanning 復活予定。
    p0_ai = GreedyAI(rng=rng)
    opp = opp_factory(rng=rng)
    ais = [p0_ai, opp]
    for i, ai in enumerate(ais):
        if hasattr(ai, "set_ai_opp"):
            ai.set_ai_opp(ais[1 - i])

    # Step 2 (= 2026-05-16): action info も snapshot に記録するため action_evals を有効化
    state.record_action_evals = True

    snapshots: list[dict] = []
    actions = 0
    prev_eval_count = 0
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
        except Exception:
            continue
        snap_features = {k: float(v["diff"]) for k, v in bd.items()}

        # action info 取得 (= action_evals の最新 entry から)
        last_action_taken: Optional[str] = None
        last_action_category: Optional[str] = None
        last_action_idx: int = -1  # v2: -1 = unknown / Other
        if len(state.action_evals) > prev_eval_count:
            latest = state.action_evals[-1]
            last_action_taken = latest.get("action")
            # v2: class 名は engine.game の 9 種類と完全一致 → 直接 lookup
            if last_action_taken in ACTION_CATEGORY_TO_IDX:
                last_action_category = last_action_taken
                last_action_idx = ACTION_CATEGORY_TO_IDX[last_action_taken]
            else:
                # 想定外 class (= 通常起きないが defensive fallback)
                last_action_category = _categorize_action_name(last_action_taken)
                last_action_idx = ACTION_CATEGORY_TO_IDX.get(last_action_category, -1)
        prev_eval_count = len(state.action_evals)

        # v2: state_encoded 172 dim list (= state-encoder 学習用)
        try:
            state_encoded = encode_state(state, me)
        except Exception:
            state_encoded = [0.0] * encoded_dim()

        snapshots.append({
            "turn": state.turn_number,
            "phase": state.phase.name if hasattr(state.phase, "name") else str(state.phase),
            "actor_idx": me,
            "features": snap_features,
            # Phase 8 (= 2026-05-16): action info for 関数 11 (= action_likelihood) 学習
            "action_taken": last_action_taken,
            "action_category": last_action_category,
            # v2 追加 (= Plan Phase E):
            "action_idx": last_action_idx,
            "state_encoded": state_encoded,
        })

    if state.winner is None:
        winner = 0
    else:
        winner = 1 if state.winner == 0 else -1
    return snapshots, winner


def _worker_play(args: tuple) -> dict:
    """worker から呼ばれる。 task = (game_idx, seed, opp_idx_in_pool, a_idx, b_idx, max_actions, max_turns)"""
    game_idx, seed, opp_idx_in_pool, a_idx, b_idx, max_actions, max_turns = args
    rng = random.Random(seed)
    opp_name, opp_factory, _ = OPP_POOL[opp_idx_in_pool]
    deck_a_slug, deck_a, ana_a = _WORKER_DECK_POOL[a_idx]
    deck_b_slug, deck_b, ana_b = _WORKER_DECK_POOL[b_idx]
    t0 = time.time()
    try:
        snapshots, winner = _play_one_game(
            deck_a, ana_a, deck_b, ana_b,
            opp_factory, _WORKER_OVERLAY, rng,
            max_actions=max_actions, max_turns=max_turns,
        )
        return {
            "game_idx": game_idx,
            "snapshots": snapshots,
            "winner": winner,
            "opp_name": opp_name,
            "deck_a": deck_a_slug,
            "deck_b": deck_b_slug,
            "elapsed": time.time() - t0,
        }
    except Exception as e:
        traceback.print_exc()
        return {
            "game_idx": game_idx,
            "snapshots": [],
            "winner": 0,
            "opp_name": opp_name,
            "deck_a": deck_a_slug,
            "deck_b": deck_b_slug,
            "elapsed": time.time() - t0,
            "error": str(e),
        }


def select_opponent_idx(rng: random.Random) -> int:
    r = rng.random()
    cum = 0.0
    for i, (_, _, p) in enumerate(OPP_POOL):
        cum += p
        if r < cum:
            return i
    return len(OPP_POOL) - 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n-games", type=int, default=5000)
    ap.add_argument(
        "--output",
        type=Path,
        default=ROOT / "db" / "self_play_snapshots_v2.jsonl",  # v2: 別 path で旧 snapshot 維持
    )
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--verbose-every", type=int, default=50)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--max-actions", type=int, default=200, help="1 試合の action 上限 (= ~13-15 ターン相当)")
    ap.add_argument("--max-turns", type=int, default=15, help="1 試合のターン上限 (= 公式平均 6-9 の 1.5-2x)")
    ap.add_argument("--sequential", action="store_true", help="mp.Pool 使わず single process で sequential 実行 (= mp の hang/slow を回避)")
    args = ap.parse_args()

    rng_master = random.Random(args.seed)

    # deck pool を main process でも一度ロード (= count 表示用)
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    n_decks = 0
    for pattern in ("cardrush_*.json", "tcgportal_*.json"):
        for path in (ROOT / "decks").glob(pattern):
            if not path.name.endswith(".analysis.json"):
                n_decks += 1
    # Phase 8 variant 構築
    for variant_path in (ROOT / "decks").glob("*/variant_*.json"):
        if not variant_path.name.endswith(".analysis.json"):
            n_decks += 1
    print(f"deck pool: {n_decks} decks (= incl variant), {args.workers} workers, {args.n_games} games")

    # === resume: 既存 output から完了済 game_idx を集める ===
    args.output.parent.mkdir(parents=True, exist_ok=True)
    completed_idxs: set[int] = set()
    if args.output.exists():
        with args.output.open("r", encoding="utf-8") as rf:
            for line in rf:
                try:
                    snap = json.loads(line)
                    gi = snap.get("game_idx")
                    if gi is not None:
                        completed_idxs.add(int(gi))
                except json.JSONDecodeError:
                    continue
        print(f"resume: existing {args.output.name} → {len(completed_idxs)} games completed, skipping")

    # task list 生成 (= 全 game_idx 0..n_games-1 から完了済を除外)
    tasks: list[tuple] = []
    for g in range(args.n_games):
        seed = rng_master.randrange(2**31)
        if g in completed_idxs:
            continue
        sub_rng = random.Random(seed)
        opp_idx = select_opponent_idx(sub_rng)
        a_idx = sub_rng.randrange(n_decks)
        b_idx = sub_rng.randrange(n_decks)
        tasks.append((g, seed, opp_idx, a_idx, b_idx, args.max_actions, args.max_turns))
    print(f"tasks to run: {len(tasks)} (= {args.n_games} - {len(completed_idxs)} completed)")

    if not tasks:
        print("nothing to do (all games complete)")
        return

    # 既存があれば append、 なければ create で開始
    f = args.output.open("a", encoding="utf-8")

    t0 = time.time()
    n_snapshots = 0
    n_done_session = 0
    win_counts = {name: [0, 0, 0] for name, _, _ in OPP_POOL}  # [W, L, D]
    elapsed_per_game: list[float] = []

    pool = None
    if args.sequential:
        # mp なしで main process 内で sequential 実行 (= mp.Pool 経由で 1 試合 100s+ 化する
        # 問題が解消できない場合の確実 path、 single-thread 7.9s/g 想定)。
        _worker_init()
        results_iter = (_worker_play(t) for t in tasks)
    else:
        # maxtasksperchild=10: 10 試合ごとに worker process を再起動。
        # 累積メモリリーク / stale state 抑制。 init コストは 0.1s なので overhead 少。
        pool = mp.Pool(processes=args.workers, initializer=_worker_init, maxtasksperchild=10)
        results_iter = pool.imap_unordered(_worker_play, tasks, chunksize=1)

    try:
            for i, res in enumerate(results_iter):
                snapshots = res["snapshots"]
                winner = res["winner"]
                opp_name = res["opp_name"]
                game_idx = res["game_idx"]
                for snap in snapshots:
                    snap["game_idx"] = game_idx
                    snap["deck_a"] = res["deck_a"]
                    snap["deck_b"] = res["deck_b"]
                    snap["opp_type"] = opp_name
                    snap["final_winner"] = winner
                    f.write(json.dumps(snap, ensure_ascii=False, separators=(",", ":")) + "\n")
                # === per-game flush + fsync (= crash 耐性) ===
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
                n_snapshots += len(snapshots)
                n_done_session += 1
                elapsed_per_game.append(res["elapsed"])

                if winner == 1:
                    win_counts[opp_name][0] += 1
                elif winner == -1:
                    win_counts[opp_name][1] += 1
                else:
                    win_counts[opp_name][2] += 1

                if (i + 1) % args.verbose_every == 0 or (i + 1) == len(tasks):
                    elapsed = time.time() - t0
                    rate = (i + 1) / elapsed
                    eta = (len(tasks) - i - 1) / rate if rate else 0
                    avg_g = sum(elapsed_per_game) / len(elapsed_per_game)
                    print(
                        f"  [{i+1}/{len(tasks)}] (= total {len(completed_idxs)+i+1}/{args.n_games}) "
                        f"{n_snapshots} snapshots this session, "
                        f"{rate:.2f} g/s wall (avg {avg_g:.1f}s/g raw), "
                        f"ETA {eta/60:.1f}min"
                    )
                    for k, (w, l, d) in win_counts.items():
                        tot = w + l + d
                        wr = w / tot if tot else 0
                        print(f"    vs {k}: {w}W-{l}L-{d}D ({wr:.1%})")
    finally:
        f.close()
        if pool is not None:
            pool.close()
            pool.terminate()
            pool.join()
        elapsed = time.time() - t0
        print(
            f"DONE: {args.n_games} games / {n_snapshots} snapshots "
            f"in {elapsed/60:.1f}min ({elapsed/3600:.1f}h)"
        )
        print(f"output: {args.output}")


if __name__ == "__main__":
    # spawn context 強制 (= fork で global state 競合 / hang 回避)。
    # fork だと 14 worker 全部が 99% CPU で 5+ 分 1 試合も完了しない現象に遭遇。
    # spawn は worker 起動が遅い (= 5-10s × maxtasksperchild サイクル) が安定。
    mp.set_start_method("spawn", force=True)
    main()
