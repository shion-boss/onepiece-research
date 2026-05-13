# -*- coding: utf-8 -*-
"""
研究セッション 中核 (Phase R)
=============================

進化的探索エンジン。 backround thread で世代ループを実行し、 各世代で:
1. 上位 K 候補に変異 (mutations) を適用 → 新候補生成
2. 各候補を target_deck と N 試合評価
3. 全候補から上位 K を次世代へ

公開 API:
- start_research(target_slug, ...) -> session_id
- pause_session(session_id)
- resume_session(session_id)
- stop_session(session_id)
- get_session_status(session_id) -> dict (= research_storage.get_session)
"""

from __future__ import annotations

import json
import random
import threading
import time
from collections import Counter as _Counter
from pathlib import Path
from typing import Optional

from . import card_role, explorer, mutations, research_storage
from .deck import CardRepository, DeckList, make_deck_from_dict
from .effects import load_effect_overlay
from .harness import run_matchup


_ROOT = Path(__file__).resolve().parent.parent
_DECKS_DIR = _ROOT / "decks"

# 同時実行セッション数 = 1 (= CPU 飽和回避)
# global registry で thread を管理
_ACTIVE_THREADS: dict[str, threading.Thread] = {}
_PAUSE_FLAGS: dict[str, threading.Event] = {}
_STOP_FLAGS: dict[str, threading.Event] = {}
_REGISTRY_LOCK = threading.Lock()


# ============================================================================ #
# Helper: deck_dict 変換
# ============================================================================ #

def _deck_to_dict(deck: DeckList) -> dict:
    """DeckList → JSON シリアライズ可能 dict (= main は count 集計形式)。"""
    counts: _Counter[str] = _Counter(c.card_id for c in deck.main)
    return {
        "name": deck.name,
        "leader": deck.leader.card_id,
        "leader_name": deck.leader.name,
        "main": [{"card_id": cid, "count": n} for cid, n in sorted(counts.items())],
        "regulation": deck.regulation,
    }


def _dict_to_deck(d: dict, repo: CardRepository) -> DeckList:
    return make_deck_from_dict(d, repo)


def _load_target_deck(slug: str, repo: CardRepository) -> Optional[DeckList]:
    p = _DECKS_DIR / f"{slug}.json"
    if not p.exists():
        return None
    try:
        return make_deck_from_dict(json.loads(p.read_text(encoding="utf-8")), repo)
    except Exception:
        return None


# ============================================================================ #
# 公開 API: start / pause / resume / stop
# ============================================================================ #

def start_research(
    target_slug: str,
    *,
    leader_filter: Optional[list[str]] = None,
    must_include: Optional[list[str]] = None,
    target_winrate: float = 0.7,
    max_generations: int = 50,
    n_games_per_eval: int = 50,
    initial_population: int = 20,
    mutations_per_top: int = 3,
    top_k: int = 5,
    seed: int = 42,
) -> str:
    """新規研究セッションを開始 → session_id 返却 + thread 起動。"""
    config = {
        "leader_filter": leader_filter,
        "must_include": must_include,
        "target_winrate": target_winrate,
        "max_generations": max_generations,
        "n_games_per_eval": n_games_per_eval,
        "initial_population": initial_population,
        "mutations_per_top": mutations_per_top,
        "top_k": top_k,
        "seed": seed,
    }
    session_id = research_storage.create_session(target_slug, config)

    # thread 起動
    pause_flag = threading.Event()  # set = paused, clear = running
    stop_flag = threading.Event()   # set = stop requested
    pause_flag.clear()
    stop_flag.clear()
    with _REGISTRY_LOCK:
        _PAUSE_FLAGS[session_id] = pause_flag
        _STOP_FLAGS[session_id] = stop_flag
        thread = threading.Thread(
            target=_run_session,
            args=(session_id, target_slug, config),
            daemon=True,
        )
        _ACTIVE_THREADS[session_id] = thread
        thread.start()
    return session_id


def pause_session(session_id: str) -> bool:
    """進行中セッションを一時停止 (= 次世代頭で待機)。"""
    with _REGISTRY_LOCK:
        flag = _PAUSE_FLAGS.get(session_id)
    if flag is None:
        return False
    flag.set()
    research_storage.update_session_status(session_id, "paused")
    return True


def resume_session(session_id: str) -> bool:
    """一時停止セッションを再開。"""
    with _REGISTRY_LOCK:
        flag = _PAUSE_FLAGS.get(session_id)
    if flag is None:
        # メモリに無い (= server 再起動後など) → 再 spawn
        s = research_storage.get_session(session_id)
        if s is None:
            return False
        if s["status"] not in ("paused", "stopped"):
            return False
        return _resume_from_db(session_id, s)
    flag.clear()
    research_storage.update_session_status(session_id, "running")
    return True


def stop_session(session_id: str) -> bool:
    """セッションを停止 (= 不可逆、 次世代頭で完全終了)。"""
    with _REGISTRY_LOCK:
        flag = _STOP_FLAGS.get(session_id)
    if flag:
        flag.set()
    research_storage.update_session_status(
        session_id, "stopped", completion_reason="user_stop",
    )
    return True


def get_session_status(session_id: str) -> Optional[dict]:
    """status + 進捗 + best deck を返す (= research_storage.get_session 委譲)。"""
    return research_storage.get_session(session_id)


def _resume_from_db(session_id: str, session_dict: dict) -> bool:
    """DB から状態を読み出して thread を再 spawn。"""
    config = session_dict["config"]
    target_slug = session_dict["target_slug"]
    pause_flag = threading.Event()
    stop_flag = threading.Event()
    with _REGISTRY_LOCK:
        _PAUSE_FLAGS[session_id] = pause_flag
        _STOP_FLAGS[session_id] = stop_flag
        thread = threading.Thread(
            target=_run_session,
            args=(session_id, target_slug, config, session_dict["current_generation"]),
            daemon=True,
        )
        _ACTIVE_THREADS[session_id] = thread
        thread.start()
    research_storage.update_session_status(session_id, "running")
    return True


# ============================================================================ #
# Internal: 世代ループ
# ============================================================================ #

def _run_session(
    session_id: str,
    target_slug: str,
    config: dict,
    start_generation: int = 0,
) -> None:
    """thread main: 世代ループ実行。"""
    pause_flag = _PAUSE_FLAGS[session_id]
    stop_flag = _STOP_FLAGS[session_id]

    repo = CardRepository.from_json(_ROOT / "db" / "cards.json")
    overlay = load_effect_overlay(_ROOT / "db" / "card_effects.json")
    target_deck = _load_target_deck(target_slug, repo)
    if target_deck is None:
        research_storage.update_session_status(
            session_id, "stopped", completion_reason=f"target deck not found: {target_slug}",
        )
        return

    role_db = card_role.load_card_role_db()
    eff_db = card_role.load_effectiveness_db()
    rng = random.Random(config.get("seed", 42))

    target_winrate = config["target_winrate"]
    max_gen = config["max_generations"]
    n_games = config["n_games_per_eval"]
    init_pop = config["initial_population"]
    mut_per_top = config["mutations_per_top"]
    top_k = config["top_k"]
    leader_filter = config.get("leader_filter")
    must_include = config.get("must_include")
    must_set = set(must_include) if must_include else None

    # state: 「現世代の top K candidates (= candidate row 含む id)」
    current_top: list[dict] = []  # [{id, deck, winrate, ...}]

    # Resume: start_generation > 0 なら DB から top_k 復元
    if start_generation > 0:
        prev = research_storage.get_top_candidates_in_generation(
            session_id, start_generation - 1, top_k=top_k,
        )
        current_top = prev

    try:
        for gen in range(start_generation, max_gen):
            # 終了/中断チェック
            if stop_flag.is_set():
                break
            while pause_flag.is_set():
                if stop_flag.is_set():
                    break
                time.sleep(2)
            if stop_flag.is_set():
                break

            # 世代開始時に current_generation を即更新 (= UI の「実行中の世代」 を最新化)
            best_now = research_storage.get_best_candidate(session_id)
            research_storage.update_session_progress(
                session_id, generation=gen,
                best_winrate=best_now["winrate"] if best_now else None,
                best_deck=best_now["deck"] if best_now else None,
            )

            # === 世代 0: 初期母集団 (explorer) ===
            if gen == 0 and not current_top:
                candidates = _generate_initial(
                    target_deck, repo, overlay, init_pop,
                    leader_filter, must_include, role_db, eff_db,
                )
                # candidate を DB に保存 + 評価
                for idx, cand_deck in enumerate(candidates):
                    if stop_flag.is_set():
                        break
                    cid = research_storage.insert_candidate(
                        session_id, generation=0, candidate_idx=idx,
                        deck_dict=_deck_to_dict(cand_deck),
                        mutation_type="initial",
                    )
                    winrate = _evaluate(cand_deck, target_deck, overlay, n_games, rng)
                    research_storage.update_candidate_evaluation(cid, winrate, n_games)
                    # 各候補評価後に best 更新 (= UI live progress)
                    _maybe_update_best(session_id, gen)
                # 上位 K 取得
                current_top = research_storage.get_top_candidates_in_generation(
                    session_id, 0, top_k=top_k,
                )
            else:
                # === 世代 N+1: 上位 K に mutations ===
                new_candidates: list[tuple[DeckList, str, int]] = []  # (deck, mut_type, parent_id)
                for top_cand in current_top:
                    parent_id = top_cand["id"]
                    parent_deck = _dict_to_deck(top_cand["deck"], repo)
                    # mut_per_top 回 mutation
                    for _ in range(mut_per_top):
                        if stop_flag.is_set():
                            break
                        result = mutations.random_mutation(
                            parent_deck, "ミッドレンジ", repo, role_db, eff_db, rng,
                            must_include=must_set, leader_filter=leader_filter,
                        )
                        if result is None:
                            continue
                        new_deck, mut_type = result
                        new_candidates.append((new_deck, mut_type, parent_id))

                # 評価
                for idx, (new_deck, mut_type, parent_id) in enumerate(new_candidates):
                    if stop_flag.is_set():
                        break
                    cid = research_storage.insert_candidate(
                        session_id, generation=gen, candidate_idx=idx,
                        deck_dict=_deck_to_dict(new_deck),
                        parent_id=parent_id, mutation_type=mut_type,
                    )
                    winrate = _evaluate(new_deck, target_deck, overlay, n_games, rng)
                    research_storage.update_candidate_evaluation(cid, winrate, n_games)
                    # 各候補評価後に best 更新 (= UI live progress)
                    _maybe_update_best(session_id, gen)

                # 親 + 子 を結合し、 上位 K 選択
                # (= 親も評価済みなので、 mutation で改善しなければ親が残る = elitism)
                all_evaluated = research_storage.get_candidates(
                    session_id, only_evaluated=True,
                )
                # 直近 2 世代分から top_k (= 親 1 世代 + 子 1 世代)
                recent = [c for c in all_evaluated if c["generation"] >= max(0, gen - 1)]
                recent.sort(key=lambda c: -c["winrate"] if c["winrate"] is not None else 0)
                current_top = recent[:top_k]

            # 進捗更新
            best = research_storage.get_best_candidate(session_id)
            if best:
                research_storage.update_session_progress(
                    session_id, generation=gen,
                    best_winrate=best["winrate"],
                    best_deck=best["deck"],
                )
                # 目標到達?
                if best["winrate"] is not None and best["winrate"] >= target_winrate:
                    research_storage.update_session_status(
                        session_id, "completed",
                        completion_reason=f"target_reached:{best['winrate']:.0%}",
                    )
                    return

        # max_generations 到達
        research_storage.update_session_status(
            session_id, "completed", completion_reason="max_generations",
        )
    except Exception as e:
        research_storage.update_session_status(
            session_id, "stopped", completion_reason=f"engine_error:{e}",
        )
    finally:
        with _REGISTRY_LOCK:
            _ACTIVE_THREADS.pop(session_id, None)
            _PAUSE_FLAGS.pop(session_id, None)
            _STOP_FLAGS.pop(session_id, None)


# ============================================================================ #
# Internal: 初期母集団生成 / 評価
# ============================================================================ #

def _generate_initial(
    target_deck: DeckList,
    repo: CardRepository,
    overlay: dict,
    n: int,
    leader_filter: Optional[list[str]],
    must_include: Optional[list[str]],
    role_db: dict,
    eff_db: dict,
) -> list[DeckList]:
    """explorer.generate_counter_candidates の wrapper。"""
    candidates = explorer.generate_counter_candidates(
        target_deck, repo, overlay,
        n_candidates=n,
        leader_filter=leader_filter,
        must_include=must_include,
        diversity="archetype",
        role_db=role_db,
        eff_db=eff_db,
    )
    return [c.deck for c in candidates]


def _maybe_update_best(session_id: str, gen: int) -> None:
    """各候補評価後の進捗更新 (= 現状ベスト + 進行中世代を即時反映)。

    target_reached 判定もここで行う (= 早期完了)。
    """
    best = research_storage.get_best_candidate(session_id)
    if not best:
        return
    research_storage.update_session_progress(
        session_id, generation=gen,
        best_winrate=best["winrate"],
        best_deck=best["deck"],
    )


def _evaluate(
    candidate_deck: DeckList,
    target_deck: DeckList,
    overlay: dict,
    n_games: int,
    rng: random.Random,
) -> float:
    """candidate vs target の N 試合 → winrate。"""
    try:
        rep = run_matchup(
            candidate_deck, target_deck,
            n_games=n_games,
            seed=rng.randint(0, 2**31),
            effects_overlay=overlay,
        )
        return rep.deck1_winrate
    except Exception:
        return 0.0
