# -*- coding: utf-8 -*-
"""AIParams の load/save と既存ハードコード値との同一性テスト。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.ai_params import AIParams, DEFAULT_PATH
from engine.eval import BoardEvalWeights, _load_weights_from_ai_params


ROOT = Path(__file__).resolve().parent.parent


def test_default_matches_eval_module_defaults():
    """デフォルト AIParams が BoardEvalWeights のデフォルトと一致する。"""
    p = AIParams()
    w_default = BoardEvalWeights()
    w_from_p = p.eval_weights()
    assert w_from_p.W_LIFE == w_default.W_LIFE == 1500
    assert w_from_p.W_FIELD_COUNT == w_default.W_FIELD_COUNT == 1200
    assert w_from_p.W_HAND == w_default.W_HAND == 250
    assert w_from_p.W_DON == w_default.W_DON == 200
    assert w_from_p.W_LETHAL == w_default.W_LETHAL == 5000


def test_default_thresholds_match_ai_module_hardcoded():
    """デフォルト AIParams の閾値が ai.py の旧ハードコード値と一致する。"""
    p = AIParams()
    # ai.py 旧 defense_thresholds default
    assert p.defense_threshold_life_le_1 == 99999
    assert p.defense_threshold_life_eq_2 == 8000
    assert p.defense_threshold_life_eq_3 == 6000
    assert p.defense_threshold_life_ge_4 == 2000
    # ai.py ミッドレンジ default attack_gap_tolerance
    assert p.attack_gap_tolerance_default == -500
    # 学習対象の新フィールド: デフォルトでは挙動を変えない
    assert p.activate_main_min_payoff_global == 0
    assert p.activate_main_don_compensated_strict is False


def test_load_from_default_path():
    """db/ai_params.json が存在すれば load する。"""
    p = AIParams.load()
    # ファイル内容と一致
    assert isinstance(p.w_life, int)
    assert p.w_life > 0


def test_load_missing_file_returns_default(tmp_path):
    """ファイルが無ければ default に fallback。"""
    p = AIParams.load(tmp_path / "no_such_file.json")
    assert p.w_life == 1500


def test_save_then_load_roundtrip(tmp_path):
    """save → load で値が保持される。"""
    target = tmp_path / "ai_params.json"
    original = AIParams(w_life=1234, activate_main_min_payoff_global=777)
    original.save(target, history_note="test save")
    loaded = AIParams.load(target)
    assert loaded.w_life == 1234
    assert loaded.activate_main_min_payoff_global == 777


def test_save_appends_history(tmp_path):
    """連続 save で _history に過去版が積まれる。"""
    target = tmp_path / "ai_params.json"
    AIParams(w_life=1000).save(target, history_note="v1")
    AIParams(w_life=2000).save(target, history_note="v2")
    AIParams(w_life=3000).save(target, history_note="v3")
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["params"]["w_life"] == 3000
    # _history は古いものから積まれる (最新は append 順)
    notes = [h.get("note") for h in data["_history"]]
    assert "v1" in notes
    assert "v2" in notes


def test_eval_module_default_weights_loaded_from_json():
    """engine.eval.DEFAULT_WEIGHTS が db/ai_params.json から構築される。"""
    weights = _load_weights_from_ai_params()
    assert isinstance(weights, BoardEvalWeights)
    # ファイル内容と一致
    data = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
    expected = data["params"]["w_life"]
    assert weights.W_LIFE == expected


def test_defense_threshold_helper():
    """defense_threshold_for_life が life に応じた値を返す。"""
    p = AIParams()
    assert p.defense_threshold_for_life(1) == 99999
    assert p.defense_threshold_for_life(2) == 8000
    assert p.defense_threshold_for_life(3) == 6000
    assert p.defense_threshold_for_life(4) == 2000
    assert p.defense_threshold_for_life(5) == 2000  # 4 以上は同じ


def test_greedy_ai_works_without_deck_analysis():
    """GreedyAI を deck_analysis=None で作っても、 全シグナル系属性が初期化される。

    regression: keep_field_synergy_only / preferred_search_target_ids が
    _apply_archetype_profile 内のみで初期化され、 deck_analysis=None で
    AttributeError を起こすバグの再発防止。
    """
    from engine.ai import GreedyAI
    ai = GreedyAI(deck_analysis=None)
    # signal 由来の属性が全て存在することを確認
    assert hasattr(ai, "synergy_feature")
    assert hasattr(ai, "tank_lifeup_ok")
    assert hasattr(ai, "avoid_life_loss")
    assert hasattr(ai, "blocker_scarce")
    assert hasattr(ai, "early_finisher_hold_ids")
    assert hasattr(ai, "counter_aggression")
    assert hasattr(ai, "keep_field_synergy_only")
    assert hasattr(ai, "preferred_search_target_ids")
    # デフォルト値
    assert ai.keep_field_synergy_only is None
    assert ai.preferred_search_target_ids == []


def test_reload_default_weights_after_file_update():
    """db/ai_params.json を書き換えた後、 reload_default_weights() が反映する。

    学習サイクル (grid search) で各候補値を試すときに使うフローを最小確認。
    既存 ai_params.json はテスト後に必ず復元する。
    """
    from engine.eval import DEFAULT_WEIGHTS, reload_default_weights
    backup = DEFAULT_PATH.read_bytes()
    original_w_life = DEFAULT_WEIGHTS.W_LIFE
    try:
        modified = AIParams.load()
        modified.w_life = 9999
        modified.save(DEFAULT_PATH, history_note="test reload")
        new_weights = reload_default_weights()
        assert new_weights.W_LIFE == 9999
        # 旧値とは異なる (= 上書きされた)
        assert new_weights.W_LIFE != original_w_life
    finally:
        DEFAULT_PATH.write_bytes(backup)
        reload_default_weights()
