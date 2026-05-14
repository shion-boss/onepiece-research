# -*- coding: utf-8 -*-
"""
matchup_model の単体テスト
==========================

- infer_opponent_archetype: leader_id 逆引き + fallback
- MatchupProfile + role 派生
- load_matchup_strategies / lookup_matchup_overrides
- GreedyAI への統合 (= 上書きが適用される)
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.ai import GreedyAI
from engine.core import Category, GameState, InPlay, Phase, Player, CardDef
from engine.deck import CardRepository
from engine.matchup_model import (
    ARCHETYPES,
    MatchupProfile,
    _reset_caches_for_testing,
    build_matchup_profile,
    infer_opponent_archetype,
    load_matchup_strategies,
    lookup_matchup_overrides,
)

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _make_state(repo, my_leader: str = "OP01-001", opp_leader: str = "OP01-001") -> GameState:
    p1 = Player(name="P0", leader=InPlay.of(repo.get(my_leader), sickness=False))
    p2 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader), sickness=False))
    p1.deck = [repo.get("OP01-013")] * 30
    p2.deck = [repo.get("OP01-013")] * 30
    return GameState(
        players=[p1, p2],
        phase=Phase.MAIN,
        rng=random.Random(0),
        effects_overlay={},
    )


# -----------------------------------------------------------------------------
# infer_opponent_archetype
# -----------------------------------------------------------------------------

def test_infer_archetype_known_leader():
    """既知 leader (decks/*.json) は analysis.json の archetype を返す。

    V2 (2026-05-14): tcg-portal top-16 pool 化で recipe 更新、 自動分類が再評価される。
    紫エネル は 旧「アグロ」 → 新「ミッドレンジ」 (= analyze_deck 自動分類)
    緑ミホーク は ミッドレンジ 維持。
    青黄ナミ は コントロール 維持。
    """
    repo = _repo()
    _reset_caches_for_testing()
    # cardrush_1454 (紫エネル) = ミッドレンジ (V2 で再分類)
    state = _make_state(repo, opp_leader="OP15-058")
    assert infer_opponent_archetype(state, 1) == "ミッドレンジ"
    # cardrush_1453 (緑ミホーク) = ミッドレンジ
    state = _make_state(repo, opp_leader="OP14-020")
    assert infer_opponent_archetype(state, 1) == "ミッドレンジ"
    # cardrush_1439 (青黄ナミ) = コントロール
    state = _make_state(repo, opp_leader="OP11-041")
    assert infer_opponent_archetype(state, 1) == "コントロール"


def test_infer_archetype_unknown_leader_fallback():
    """未知 leader は fallback で ミッドレンジ を返す (場が空 = 推定不可)。"""
    repo = _repo()
    _reset_caches_for_testing()
    # OP01-001 は cardrush_*.json には登録されていない (主要メタデッキ外)
    state = _make_state(repo, opp_leader="OP01-001")
    assert infer_opponent_archetype(state, 1) == "ミッドレンジ"


# -----------------------------------------------------------------------------
# MatchupProfile + role
# -----------------------------------------------------------------------------

def test_build_matchup_profile_returns_dataclass():
    repo = _repo()
    _reset_caches_for_testing()
    # V2 (2026-05-14): 紫エネル は ミッドレンジ に再分類
    state = _make_state(repo, opp_leader="OP15-058")
    profile = build_matchup_profile(state, 0, my_archetype="コントロール")
    assert isinstance(profile, MatchupProfile)
    assert profile.my_archetype == "コントロール"
    assert profile.opp_archetype == "ミッドレンジ"
    # コントロール vs ミッドレンジ = balance (or control 寄り)
    # 実装に応じて (control/balance のどちらか)、 アグロでなくなったため race ではない
    assert profile.role in ("control", "balance")


def test_role_derivation_combinations():
    """role が (my, opp) ペアで期待通り決まる。

    V2 (2026-05-14): 紫エネル がアグロ → ミッドレンジ に再分類されたので、
    アグロ vs アグロ の検証には OP15-058 が使えない。 アーキタイプ別 role 導出のみ確認。
    """
    repo = _repo()
    _reset_caches_for_testing()
    # 紫エネル = ミッドレンジ (V2)
    state = _make_state(repo, opp_leader="OP15-058")

    # アグロ vs ミッドレンジ = beatdown (= 攻めて削る)
    profile = build_matchup_profile(state, 0, my_archetype="アグロ")
    assert profile.role == "beatdown"

    # ミッドレンジ vs ミッドレンジ = balance (= ミラー)
    profile = build_matchup_profile(state, 0, my_archetype="ミッドレンジ")
    assert profile.role == "balance"

    # ランプ vs ミッドレンジ = control 寄り (= ramp で先行)
    profile = build_matchup_profile(state, 0, my_archetype="ランプ")
    # ramp 寄り (= control 系)
    assert profile.role in ("control", "balance", "ramp_control")

    # コントロール vs ミッドレンジ = control (耐える)
    profile = build_matchup_profile(state, 0, my_archetype="コントロール")
    assert profile.role in ("control", "balance")


# -----------------------------------------------------------------------------
# load_matchup_strategies / lookup_matchup_overrides
# -----------------------------------------------------------------------------

def test_load_matchup_strategies_returns_full_4x4():
    """db/matchup_strategies.json が 4×4=16 マッチアップを定義している。"""
    _reset_caches_for_testing()
    strategies = load_matchup_strategies()
    matchups = strategies.get("matchups", {})
    for my in ARCHETYPES:
        assert my in matchups, f"my={my} がない"
        for opp in ARCHETYPES:
            assert opp in matchups[my], f"my={my}, opp={opp} がない"
            entry = matchups[my][opp]
            assert "attack_gap_tolerance" in entry
            assert "defense_thresholds" in entry
            assert "finisher_hold_life" in entry


def test_lookup_matchup_overrides_aggro_vs_control():
    """アグロ vs コントロール は最も攻撃的な override。"""
    _reset_caches_for_testing()
    override = lookup_matchup_overrides("アグロ", "コントロール")
    assert override is not None
    # tolerance は強くネガティブ (= 力差不足でも攻撃)
    assert override["attack_gap_tolerance"] <= -2000
    # finisher_hold_life は低い (= 早期に finisher 切る)
    assert override["finisher_hold_life"] <= 3


def test_lookup_matchup_overrides_unknown_returns_none():
    """未定義の組み合わせは None。"""
    _reset_caches_for_testing()
    assert lookup_matchup_overrides("UNKNOWN", "アグロ") is None
    assert lookup_matchup_overrides("アグロ", "UNKNOWN") is None


# -----------------------------------------------------------------------------
# GreedyAI 統合
# -----------------------------------------------------------------------------

def test_greedy_ai_applies_matchup_override_on_first_choose():
    """初回 choose_action で MatchupProfile が構築され、 overrides が適用される。"""
    repo = _repo()
    _reset_caches_for_testing()

    # 自分: コントロール、 相手: ミッドレンジ (= cardrush_1454 紫エネル、 V2 で再分類)
    state = _make_state(repo, my_leader="OP01-001", opp_leader="OP15-058")
    ai = GreedyAI(rng=random.Random(0))
    # 手動で archetype を コントロール に設定 (deck_analysis 経由を簡略化)
    ai.archetype = "コントロール"
    # コントロール の base defense (engine/ai.py 由来) を控えのため記録
    base_defense_life4 = ai.defense_thresholds.get(4)

    # 初回 choose_action 呼出
    ai.choose_action(state)

    # MatchupProfile が構築されている
    assert ai._matchup_overrides_applied
    assert ai._matchup_profile is not None
    assert ai._matchup_profile.my_archetype == "コントロール"
    # V2 (2026-05-14): 紫エネル は ミッドレンジ に再分類
    assert ai._matchup_profile.opp_archetype == "ミッドレンジ"
    assert ai._matchup_profile.role in ("control", "balance")

    # defense_thresholds が override で 設定されている (= 何らかの値が入る)
    new_defense_life4 = ai.defense_thresholds.get(4)
    assert new_defense_life4 is not None
    # コントロール vs ミッドレンジ で life=4 は base コントロール (5000, 2) 〜 override 値
    assert new_defense_life4[0] >= 3000, f"override が適用されていない: {new_defense_life4}"


def test_greedy_ai_no_matchup_for_unknown_opp():
    """未知 opp で fallback (ミッドレンジ) が適用される (例外なし)。"""
    repo = _repo()
    _reset_caches_for_testing()
    state = _make_state(repo, my_leader="OP01-001", opp_leader="OP01-001")
    ai = GreedyAI(rng=random.Random(0))
    ai.archetype = "アグロ"

    ai.choose_action(state)

    # アグロ vs ミッドレンジ の override が適用されている
    assert ai._matchup_overrides_applied
    assert ai._matchup_profile is not None
    assert ai._matchup_profile.opp_archetype == "ミッドレンジ"
