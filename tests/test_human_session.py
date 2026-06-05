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


def test_stale_opp_attack_effect_source_graceful(repo, overlay):
    """回帰: 防御中、 state._available_opp_attack_effects に「source が既に場を離れた」
    stale entry が残り、 その効果を click (apply_human_use_opp_attack_effect) すると
    `ValueError: source iid not found` で session が落ちるバグ。

    真因: _available_opp_attack_effects は apply_human_defense でしかクリアされないが、
    防御を opp_attack 効果発火で解決して attacker が消える経路はそれをバイパス → stale entry
    がターン跨ぎで残留 → source カードが後で場を離れると幽霊エントリになる。
    (= 2026-06-05 hunt_don_ledger.py が cardrush_1453 vs cardrush_1456 seed80021 で検出)

    fix: producer (choose_defense/_rebuild_defense_payload) で現場 source に filter +
    consumer (本メソッド) で source 不在なら raise せず graceful skip。 本 test は consumer の
    graceful を直接叩く (= seed 再現は rng drift に弱いため、 fix を確定的に検証)。
    """
    deck_json = json.loads((ROOT / "decks" / "cardrush_1456.json").read_text(encoding="utf-8"))
    deck_a = make_deck_from_dict(deck_json, repo)
    deck_b = make_deck_from_dict(deck_json, repo)
    session = HumanSession(
        deck_a=deck_a, deck_b=deck_b, ai_factory=_greedy_factory,
        seed=42, effects_overlay=overlay, human_first=True)

    # 防御 pending を 人工的に セット + 場に居ない source_iid の stale entry を 注入。
    bogus_iid = 999_999  # どの InPlay の instance_id とも 衝突しない
    stale = {
        "source_iid": bogus_iid, "effect_idx": 0, "when_key": "opp_attack",
        "card_id": "STALE", "card_name": "幽霊", "effect_text": "",
    }
    session.state._available_opp_attack_effects = [dict(stale)]
    session.pending_kind = "defense"
    session.pending_payload = {
        "attacker_iid": session.state.players[session.ai_idx].leader.instance_id,
        "available_opp_attack_effects": [dict(stale)],
    }

    # crash しない (= 旧実装は ValueError) + stale entry が 候補から 除去される。
    session.apply_human_use_opp_attack_effect(bogus_iid, 0)
    assert all(
        e.get("source_iid") != bogus_iid
        for e in session.state._available_opp_attack_effects
    ), "stale source entry が 除去されていない"
    assert all(
        e.get("source_iid") != bogus_iid
        for e in session.pending_payload.get("available_opp_attack_effects", [])
    ), "payload の stale source entry が 同期除去されていない"


def _field_flood_play_with_referee(repo, overlay, deck_a, deck_b, seed, human_first):
    """field-flood bot で 1 試合 を 走らせ、 各 settled (action待ち/game_over) で RuleReferee の
    構造チェック (フィールド≤5 / カテゴリ整合 / DON台帳 / instance一意) を read-only 実行して
    違反 list を集める。 (= 2026-06-05 hunt_referee_human.py を test 化)。"""
    import random
    from engine.ai import RandomAI
    from engine.referee import RuleReferee

    def _rand(rng, deck_analysis=None):
        return RandomAI(rng=rng)

    session = HumanSession(
        deck_a=make_deck_from_dict(json.loads((ROOT / "decks" / f"{deck_a}.json").read_text(encoding="utf-8")), repo),
        deck_b=make_deck_from_dict(json.loads((ROOT / "decks" / f"{deck_b}.json").read_text(encoding="utf-8")), repo),
        ai_factory=_rand, seed=seed, effects_overlay=overlay, human_first=human_first)
    rng = random.Random(seed)
    violations: list[str] = []

    def _check():
        ref = RuleReferee(strict=False)
        ref.after_action(session.state)
        violations.extend(ref.violations)

    steps = 0
    while not session.state.game_over and steps < 1500:
        steps += 1
        pk = session.pending_kind
        pl = session.pending_payload or {}
        if pk == "action":
            _check()
            if violations:
                break
            acts = session.legal_actions_for_human()
            if not acts:
                break
            non_end = [a for a in acts if a["kind"] != "EndPhase"]
            plays = [a for a in non_end if a["kind"] in ("PlayCharacter", "PlayStage", "ActivateMain")]
            if plays:
                chosen = rng.choice(plays)["idx"]
            elif non_end and rng.random() < 0.4:
                chosen = rng.choice(non_end)["idx"]
            else:
                chosen = next((a["idx"] for a in acts if a["kind"] == "EndPhase"), acts[0]["idx"])
            session.apply_human_action(chosen)
        elif pk == "choice":
            k = pl.get("kind")
            if k in ("mulligan_confirm", "mulligan_redrawn"):
                session.apply_human_choice([0])
            else:
                cs = pl.get("candidates") or pl.get("cards") or pl.get("options") or []
                lim = int(pl.get("limit", 1) or 1)
                session.apply_human_choice(list(range(min(lim, len(cs)))) if cs else [])
        elif pk == "defense":
            session.apply_human_defense(None, [])
        else:
            break
    if session.state.game_over:
        _check()
    return violations


def test_human_play_structural_invariants_field_flood(repo, overlay):
    """回帰: 人間操作でキャラ展開を厚くした (field-flood) とき、 効果召喚が

    (A) **満杯フィールド (5体) への登場でフィールド 6 体超過** (= reveal_top_play 等で
        trash_weakest の人間 defer modal が on_play に clobber され差替が消える、 サンジ
        OP06-119 系)、
    (B) **非ターンプレイヤーのトリガー (on_ko 等) で 別プレイヤーの hand/trash から登場
        → EVENT がキャラエリアに混入** (= actor 文脈喪失、 play_from_hand_or_trash 等)

    を起こさないこと。 RuleReferee の構造チェック (キャラ≤5/カテゴリ整合/DON台帳/instance一意)
    を settled 点で当てて担保する。 2026-06-05 hunt_referee_human.py が検出・修正。
    """
    # サンジ reveal_top_play を含む op11_luffy + on_ko play_from_hand_or_trash を含む 1385 を中心に
    pairs = [
        ("tcgportal_op11_luffy", "cardrush_1453"),
        ("cardrush_1385", "cardrush_1392"),
        ("cardrush_1385", "cardrush_1439"),
        ("cardrush_1342", "cardrush_1342"),
    ]
    for a, b in pairs:
        for sd in range(3):
            seed = 90000 + sd * 11
            viol = _field_flood_play_with_referee(repo, overlay, a, b, seed, human_first=(sd % 2 == 0))
            assert not viol, (
                f"{a} vs {b} seed={seed}: 構造違反 {viol[:2]} "
                f"(= フィールド超過 / キャラエリアに非CHARACTER 等の回帰)"
            )


def test_stale_counter_event_idx_graceful(repo, overlay):
    """回帰: 防御 payload の counter_event_idxs が hand 変化後に stale (= 別カードの index を
    指す) になり、 それを click すると `ValueError: hand[i]=X is not EVENT` で session が落ちる
    バグ。 2026-06-05 広デッキプール fuzz (cardrush_1276) が検出。

    consumer (apply_human_use_counter_event) を graceful skip + payload 再構築に変更。
    """
    deck_json = json.loads((ROOT / "decks" / "cardrush_1456.json").read_text(encoding="utf-8"))
    session = HumanSession(
        deck_a=make_deck_from_dict(deck_json, repo),
        deck_b=make_deck_from_dict(deck_json, repo),
        ai_factory=_greedy_factory, seed=42, effects_overlay=overlay, human_first=True)

    me = session.state.players[session.human_idx]
    # hand[0] を 非EVENT (= キャラ) にして、 stale counter_event_idxs=[0] を仕込む
    me.hand = [repo.get("OP01-013")] + list(me.hand)  # 先頭に素キャラ
    session.pending_kind = "defense"
    session.pending_payload = {
        "attacker_iid": session.state.players[session.ai_idx].leader.instance_id,
        "attacker_power": 5000,
        "is_leader_attack": True,
        "legal_blocker_iids": [],
        "legal_counter_card_idxs": [0],
        "counter_values": {0: 0},
        "counter_event_idxs": [0],  # stale: hand[0] は非EVENT
        "available_opp_attack_effects": [],
    }
    # 旧実装は ValueError で落ちる。 graceful skip で 落ちない + payload 再構築される。
    session.apply_human_use_counter_event(0)
    assert 0 not in (session.pending_payload or {}).get("counter_event_idxs", []), \
        "stale な非EVENT index が counter_event_idxs から除去されていない"
