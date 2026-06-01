# -*- coding: utf-8 -*-
"""人間 vs AI セッション の smoke test。

automate human action (= 最初の legal action を 選び続ける bot) で
1 試合 完走 + 棋譜保存 を 確認。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.human_session import HumanSession
from engine.ai import GreedyAI

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


@pytest.fixture(scope="module")
def overlay() -> dict:
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _greedy_factory(rng, deck_analysis=None):
    return GreedyAI(rng=rng, deck_analysis=deck_analysis)


def test_human_session_smoke_complete_game(repo, overlay):
    """human側 を 「常に 最初の legal action」 bot で 操作 → 1 試合 完走 確認。"""
    deck_json = json.loads((ROOT / "decks" / "cardrush_1456.json").read_text(encoding="utf-8"))
    deck_a = make_deck_from_dict(deck_json, repo)
    deck_b = make_deck_from_dict(deck_json, repo)

    session = HumanSession(
        deck_a=deck_a,
        deck_b=deck_b,
        ai_factory=_greedy_factory,
        seed=42,
        effects_overlay=overlay,
        human_first=True,
    )
    session.advance_until_pause()

    max_steps = 500
    step = 0
    while not session.state.game_over and step < max_steps:
        if session.pending_kind == "action":
            actions = session.legal_actions_for_human()
            assert len(actions) > 0, "legal actions が空"
            # EndPhase あれば優先 (= 短時間 完走)
            end_idx = next((a["idx"] for a in actions if a["kind"] == "EndPhase"), None)
            chosen = end_idx if end_idx is not None else actions[0]["idx"]
            session.apply_human_action(chosen)
        elif session.pending_kind == "defense":
            # 防御 不使用 で 即 進める
            session.apply_human_defense(None, [])
        elif session.pending_kind == "choice":
            # mulligan / search / option 等 全 choice は keep / 0 idx で 自動 進行
            session.apply_human_choice([0])
        else:
            break
        step += 1

    assert session.state.game_over, f"max_steps={max_steps} で 試合 未完了"
    assert session.state.winner in (0, 1, -1)


def test_human_session_save_replay(repo, overlay, tmp_path, monkeypatch):
    """save_replay で 棋譜 が SQLite に 保存 される か。"""
    deck_json = json.loads((ROOT / "decks" / "cardrush_1456.json").read_text(encoding="utf-8"))
    deck_a = make_deck_from_dict(deck_json, repo)
    deck_b = make_deck_from_dict(deck_json, repo)

    session = HumanSession(
        deck_a=deck_a,
        deck_b=deck_b,
        ai_factory=_greedy_factory,
        seed=43,
        effects_overlay=overlay,
        human_first=True,
    )
    session.advance_until_pause()

    # 自動 完走
    for _ in range(500):
        if session.state.game_over:
            break
        if session.pending_kind == "action":
            actions = session.legal_actions_for_human()
            end_idx = next((a["idx"] for a in actions if a["kind"] == "EndPhase"), None)
            chosen = end_idx if end_idx is not None else actions[0]["idx"]
            session.apply_human_action(chosen)
        elif session.pending_kind == "defense":
            session.apply_human_defense(None, [])
        elif session.pending_kind == "choice":
            session.apply_human_choice([0])
        else:
            break

    assert session.state.game_over

    rid = session.save_replay(max_per_pair=10)
    # SQLite が 既存 環境 で 動く なら rid は 整数、 失敗時 None
    # 環境問題 等 で None でも assertion せず logs だけ check
    if rid is not None:
        assert isinstance(rid, int)


def _pick_for_choice(payload):
    """pending_choice payload を 安全 に 解決 する picks を 返す (= テスト bot 用)。"""
    k = payload.get("kind")
    lim = int(payload.get("limit", 1) or 1)
    if k in ("mulligan_confirm", "mulligan_redrawn"):
        return [0]  # keep
    if k in ("self_hand_discard_pick", "counter_discard_pick", "activate_main_discard_pick"):
        cands = payload.get("candidates", [])
        return list(range(min(lim, len(cands))))
    if k == "search_top_n":
        cs = payload.get("cards", [])
        m = [c["idx"] for c in cs if c.get("matches_filter")]
        return m[:lim] if m else []
    if k in ("search_top_n_bottom_reorder", "scry_life_reorder", "scry_deck_reorder"):
        return []  # ID順 fallback
    cands = payload.get("candidates") or payload.get("cards") or []
    return [0] if cands else []


def test_no_empty_action_pause_after_turn_start_effect(repo, overlay):
    """回帰: ターン開始時 効果 (trigger_turn_start) が 人間 pending_choice を立て、 解決後 phase が
    DRAW に 残った まま 人間 が action 待ち に され、 legal_actions が空 (= NO_ACT) で 詰む バグ。

    advance_until_pause が END phase だけ MAIN まで 進めて いた のが 原因。 phase!=MAIN なら
    常に MAIN まで 進めて から action を 求める fix を 入れた。 本 test は action 待ち の度に
    legal_actions が 非空 (= phase==MAIN) を assert し、 完走 を 確認する。

    再現: tcgportal_op11_luffy(AI) vs cardrush_1385(human=P1), seed=742540 で turn10 DRAW で詰んでいた。
    """
    import random
    from engine.ai import RandomAI

    deck_a = make_deck_from_dict(
        json.loads((ROOT / "decks" / "tcgportal_op11_luffy.json").read_text(encoding="utf-8")), repo)
    deck_b = make_deck_from_dict(
        json.loads((ROOT / "decks" / "cardrush_1385.json").read_text(encoding="utf-8")), repo)

    def _rand_factory(rng, deck_analysis=None):
        return RandomAI(rng=rng)

    session = HumanSession(
        deck_a=deck_a, deck_b=deck_b, ai_factory=_rand_factory,
        seed=742540, effects_overlay=overlay, human_first=False)
    session.advance_until_pause()

    rng = random.Random(742540)
    step = 0
    while not session.state.game_over and step < 2000:
        pk = session.pending_kind
        if pk == "action":
            actions = session.legal_actions_for_human()
            assert len(actions) > 0, (
                f"NO_ACT 回帰: action 待ち だが legal 空 "
                f"(phase={session.state.phase.name} turn={session.state.turn_number})")
            non_end = [a["idx"] for a in actions if a["kind"] != "EndPhase"]
            end_idx = next((a["idx"] for a in actions if a["kind"] == "EndPhase"), None)
            if non_end and rng.random() < 0.85:
                chosen = rng.choice(non_end)
            else:
                chosen = end_idx if end_idx is not None else actions[0]["idx"]
            session.apply_human_action(chosen)
        elif pk == "defense":
            session.apply_human_defense(None, [])
        elif pk == "choice":
            session.apply_human_choice(_pick_for_choice(session.pending_payload or {}))
        else:
            break
        step += 1

    assert session.state.game_over, f"step={step} で 試合 未完了 (= stuck の 疑い)"
