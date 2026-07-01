"""リーダー効果 type + 使い方 prior (engine/leader_effect_profile.py) のテスト。

合成モデルで API 契約を、 ビルド済 artifact で実データの妥当性を確認する。
"""

from __future__ import annotations

import pytest

from engine.leader_effect_profile import (
    USAGE_HINTS,
    LeaderEffectProfileModel,
    get_default_model,
)


def _synthetic() -> LeaderEffectProfileModel:
    data = {
        "meta": {},
        "leaders": {
            "ENGINE": {
                "leader_name": "Engine",
                "color": "紫",
                "n_effects": 1,
                "when_decision": True,
                "primary_role": "ramp",
                "primary_usage": "engine_use_often",
                "effects": [
                    {"when": "activate_main", "timing": "active",
                     "roles": ["ramp"], "primary_role": "ramp",
                     "usage_pattern": "engine_use_often", "gating": {}, "text": ""},
                ],
            },
            "DEF": {
                "leader_name": "Defender",
                "color": "青",
                "n_effects": 1,
                "when_decision": False,
                "primary_role": "defense",
                "primary_usage": "reactive_defense",
                "effects": [
                    {"when": "opp_attack", "timing": "reactive",
                     "roles": ["defense"], "primary_role": "defense",
                     "usage_pattern": "reactive_defense", "gating": {}, "text": ""},
                ],
            },
        },
    }
    return LeaderEffectProfileModel(data)


def test_primary_usage_and_role():
    m = _synthetic()
    assert m.primary_usage("ENGINE") == "engine_use_often"
    assert m.primary_role("ENGINE") == "ramp"
    assert m.primary_usage("DEF") == "reactive_defense"


def test_when_decision_flag():
    m = _synthetic()
    assert m.when_decision("ENGINE") is True   # activate_main を持つ
    assert m.when_decision("DEF") is False      # reactive のみ


def test_usage_hint_nonempty_for_known_patterns():
    m = _synthetic()
    assert "エンジン" in m.usage_hint("ENGINE")
    assert m.usage_hint("DEF")  # 非空
    assert m.usage_hint("UNKNOWN") == ""


def test_active_effects_filters_timing():
    m = _synthetic()
    assert len(m.active_effects("ENGINE")) == 1
    assert m.active_effects("DEF") == []        # reactive は active でない


def test_unknown_leader():
    m = _synthetic()
    assert m.has_leader("NOPE") is False
    assert m.profile("NOPE") is None
    assert m.primary_usage("NOPE") is None
    assert m.when_decision("NOPE") is False


def test_all_usage_patterns_have_hints():
    """artifact が出す全 usage_pattern に hint 文が定義されているか。"""
    m = get_default_model()
    for lid in m.leaders:
        usage = m.primary_usage(lid)
        assert usage in USAGE_HINTS, f"{lid}: usage {usage!r} に hint 未定義"


def test_default_model_real_data():
    """ビルド済 artifact があれば既知 leader を正しく分類しているか。無ければ skip。"""
    m = get_default_model()
    if not m.leaders:
        pytest.skip("leader_effect_profiles.json 未ビルド")
    # エネル = ramp engine (毎ターン起動)
    if m.has_leader("OP15-058"):
        assert m.primary_role("OP15-058") == "ramp"
        assert m.primary_usage("OP15-058") == "engine_use_often"
        assert m.when_decision("OP15-058") is True
    # ドフラ = 相手アタック時の redirect = 防御
    if m.has_leader("OP14-060"):
        assert m.primary_usage("OP14-060") == "reactive_defense"
        assert m.when_decision("OP14-060") is False
