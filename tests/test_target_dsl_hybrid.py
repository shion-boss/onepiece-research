"""Plan H ハイブリッド 4-tier lookup の unit test (= 2026-05-25)。

Tier 1 (= opp_leader_id 厳密一致、 weight 1.0) /
Tier 2 (= opp_archetype 一致、 weight 0.7) /
Tier 3 (= 純 wildcard、 weight 0.5) の 各 path が 期待通り 動く こと を 検証。

generic.json merge / per-deck spec 不在時 の generic-only / archetype lookup 失敗時 の
fallback も cover。
"""
from __future__ import annotations

import pytest

from engine.target_dsl import (
    clear_archetype_cache,
    clear_target_spec_cache,
    compute_target_match_bonus,
    find_matching_entries,
    get_archetype_by_slug,
    load_target_spec,
)


@pytest.fixture(autouse=True)
def _reset_caches():
    """各テストで cache をクリア (= test 間 の 状態漏れ 防止)。"""
    clear_target_spec_cache()
    clear_archetype_cache()
    yield
    clear_target_spec_cache()
    clear_archetype_cache()


# ============================================================================
# Tier 1: opp_leader_id 厳密一致 → weight 1.0
# ============================================================================


def test_tier1_leader_exact_match():
    spec = {
        "entries": [
            {
                "turn": 5,
                "opp_leader_id": "L1",
                "self_condition": "even",
                "targets": [{"priority": 1, "if": {}, "bonus": 1000}],
            }
        ]
    }
    matches = find_matching_entries(spec, 5, "L1", "even", opp_archetype=None)
    assert len(matches) == 1
    _, w = matches[0]
    assert w == pytest.approx(1.0)


def test_tier1_leader_mismatch_skipped():
    """leader 指定 が ある entry で leader 不一致 → skip (= archetype 一致 でも 取らない)。"""
    spec = {
        "entries": [
            {
                "turn": 5,
                "opp_leader_id": "L_DIFF",
                "self_condition": "even",
                "targets": [{"priority": 1, "if": {}, "bonus": 1000}],
            }
        ]
    }
    matches = find_matching_entries(spec, 5, "L1", "even", opp_archetype="コントロール")
    assert matches == []


# ============================================================================
# Tier 2: opp_archetype 一致 → weight 0.7
# ============================================================================


def test_tier2_archetype_match():
    spec = {
        "entries": [
            {
                "turn": 5,
                "opp_archetype": "コントロール",
                "self_condition": "even",
                "targets": [{"priority": 1, "if": {}, "bonus": 800}],
            }
        ]
    }
    matches = find_matching_entries(spec, 5, "L1", "even", opp_archetype="コントロール")
    assert len(matches) == 1
    _, w = matches[0]
    assert w == pytest.approx(0.7)


def test_tier2_archetype_mismatch_skipped():
    spec = {
        "entries": [
            {
                "turn": 5,
                "opp_archetype": "アグロ",
                "self_condition": "even",
                "targets": [{"priority": 1, "if": {}, "bonus": 800}],
            }
        ]
    }
    matches = find_matching_entries(spec, 5, "L1", "even", opp_archetype="コントロール")
    assert matches == []


def test_tier2_archetype_none_state_skipped():
    """state opp_archetype=None (= 未知 deck) で entry に archetype 指定 → skip。"""
    spec = {
        "entries": [
            {
                "turn": 5,
                "opp_archetype": "コントロール",
                "self_condition": "even",
                "targets": [{"priority": 1, "if": {}, "bonus": 800}],
            }
        ]
    }
    matches = find_matching_entries(spec, 5, "L1", "even", opp_archetype=None)
    assert matches == []


# ============================================================================
# Tier 3: 純 wildcard (= leader/archetype 両方 null) → weight 0.5
# ============================================================================


def test_tier3_pure_wildcard():
    spec = {
        "entries": [
            {
                "turn": 5,
                "self_condition": "even",
                "targets": [{"priority": 1, "if": {}, "bonus": 500}],
            }
        ]
    }
    matches = find_matching_entries(spec, 5, "L1", "even", opp_archetype="コントロール")
    assert len(matches) == 1
    _, w = matches[0]
    assert w == pytest.approx(0.5)


def test_tier3_wildcard_works_with_unknown_archetype():
    """archetype 不明 (= None) でも 純 wildcard は 動く。"""
    spec = {
        "entries": [
            {
                "turn": 5,
                "self_condition": "even",
                "targets": [{"priority": 1, "if": {}, "bonus": 500}],
            }
        ]
    }
    matches = find_matching_entries(spec, 5, "L1", "even", opp_archetype=None)
    assert len(matches) == 1


# ============================================================================
# 排他: Tier 1 が match したら Tier 2/3 は drop される (= 2026-05-25 修正)
# ============================================================================


def test_external_generic_dropped_when_tier1_match():
    """per-deck Tier 1 match があれば、 _external_generic flag 付き entry のみ drop。
    per-deck 内部 wildcard (= v1 spec の 一部) は 常時 残る。"""
    spec = {
        "entries": [
            # per-deck Tier 1
            {
                "turn": 5, "opp_leader_id": "L1", "self_condition": "even",
                "targets": [{"priority": 1, "if": {}, "bonus": 1000}],
            },
            # per-deck 内部 wildcard (= no _external_generic flag、 v1 spec の attack 必須 generic 想定)
            {
                "turn": 5, "self_condition": "even",
                "targets": [{"priority": 1, "if": {}, "bonus": 700}],
            },
            # 外部 generic (= _external_generic=True)
            {
                "turn": 5, "opp_archetype": "コントロール", "self_condition": "even",
                "_external_generic": True,
                "targets": [{"priority": 1, "if": {}, "bonus": 800}],
            },
            {
                "turn": 5, "self_condition": "even",
                "_external_generic": True,
                "targets": [{"priority": 1, "if": {}, "bonus": 500}],
            },
        ]
    }
    matches = find_matching_entries(spec, 5, "L1", "even", opp_archetype="コントロール")
    # per-deck Tier 1 (= 1) + per-deck 内部 wildcard (= 1) = 2、 外部 generic 2 件 は drop
    assert len(matches) == 2
    has_external = any(e.get("_external_generic") for e, _ in matches)
    assert has_external is False


def test_external_generic_used_when_no_tier1():
    """per-deck Tier 1 match が 0 件 の とき、 外部 generic が fallback として 効く。"""
    spec = {
        "entries": [
            # leader 別 → 不一致 で skip
            {
                "turn": 5, "opp_leader_id": "L_OTHER", "self_condition": "even",
                "targets": [{"priority": 1, "if": {}, "bonus": 1000}],
            },
            # per-deck 内部 wildcard
            {
                "turn": 5, "self_condition": "even",
                "targets": [{"priority": 1, "if": {}, "bonus": 700}],
            },
            # 外部 generic Tier 2
            {
                "turn": 5, "opp_archetype": "コントロール", "self_condition": "even",
                "_external_generic": True,
                "targets": [{"priority": 1, "if": {}, "bonus": 800}],
            },
            # 外部 generic Tier 3
            {
                "turn": 5, "self_condition": "even",
                "_external_generic": True,
                "targets": [{"priority": 1, "if": {}, "bonus": 500}],
            },
        ]
    }
    matches = find_matching_entries(spec, 5, "L1", "even", opp_archetype="コントロール")
    # per-deck 内部 wildcard (1) + 外部 generic Tier 2 (1) + 外部 generic Tier 3 (1) = 3
    assert len(matches) == 3
    n_external = sum(1 for e, _ in matches if e.get("_external_generic"))
    assert n_external == 2


def test_external_generic_flag_set_at_load_time():
    """load_target_spec で 外部 generic.json entries に _external_generic=True が 付与 される。"""
    spec = load_target_spec("cardrush_1456")
    assert spec is not None
    entries = spec.get("entries", [])
    # 外部 generic が flag 付き で 含まれる
    external = [e for e in entries if e.get("_external_generic")]
    assert len(external) > 0
    # per-deck 由来 entries は flag が 無い
    per_deck = [e for e in entries if not e.get("_external_generic")]
    assert len(per_deck) > 0


# ============================================================================
# Turn / condition 隣接度
# ============================================================================


def test_turn_neighbor_partial_match():
    """turn ±1 → 0.6 (turn_weight)。"""
    spec = {
        "entries": [
            {
                "turn": 4,  # state turn 5 から -1
                "opp_leader_id": "L1",
                "self_condition": "even",
                "targets": [{"priority": 1, "if": {}, "bonus": 1000}],
            }
        ]
    }
    matches = find_matching_entries(spec, 5, "L1", "even", opp_archetype=None)
    assert len(matches) == 1
    _, w = matches[0]
    assert w == pytest.approx(1.0 * 0.6 * 1.0)  # leader 1.0 × turn 0.6 × cond 1.0


def test_turn_far_skipped():
    """turn ±2 以上 → skip。"""
    spec = {
        "entries": [
            {
                "turn": 3,  # state turn 5 から -2
                "opp_leader_id": "L1",
                "self_condition": "even",
                "targets": [{"priority": 1, "if": {}, "bonus": 1000}],
            }
        ]
    }
    matches = find_matching_entries(spec, 5, "L1", "even", opp_archetype=None)
    assert matches == []


# ============================================================================
# get_archetype_by_slug (= db/deck_archetypes.json lookup)
# ============================================================================


def test_archetype_lookup_known_deck():
    """build_deck_archetypes.py で生成済の map を 読む。"""
    arch = get_archetype_by_slug("cardrush_1456")
    assert arch in {"アグロ", "ミッドレンジ", "コントロール", "ランプ", "ハイブリッド"}


def test_archetype_lookup_unknown_deck():
    """未知 deck → None (= Tier 2 skip)。"""
    arch = get_archetype_by_slug("totally_unknown_deck_xyz")
    assert arch is None


def test_archetype_lookup_empty_slug():
    """空 / None → None。"""
    assert get_archetype_by_slug(None) is None
    assert get_archetype_by_slug("") is None


# ============================================================================
# load_target_spec merge (= per-deck + generic)
# ============================================================================


def test_load_per_deck_merges_generic():
    """既知 deck の spec に generic entries が merge される。"""
    spec = load_target_spec("cardrush_1456")
    assert spec is not None
    entries = spec.get("entries", [])
    # generic 由来 entry (= opp_leader_id is None) が 含まれる
    generic_entries = [e for e in entries if e.get("opp_leader_id") is None]
    assert len(generic_entries) >= 30  # generic file は 75 entry 程度


def test_load_unknown_deck_returns_generic_only():
    """未知 deck で per-deck spec 不在 → generic だけ で spec 成立。"""
    spec = load_target_spec("definitely_unknown_deck_qwerty")
    assert spec is not None
    entries = spec.get("entries", [])
    # 全 entry が generic 由来
    assert all(e.get("opp_leader_id") is None for e in entries)
    assert len(entries) > 0


# ============================================================================
# compute_target_match_bonus end-to-end (= state 経由)
# ============================================================================


def test_bonus_cap_applied():
    """bonus 合計 が cap で 抑えられる (= Tier 1 排他 後 でも 複数 Tier 1 entries で 暴走 防止)。"""
    spec = {
        "entries": [
            {
                "turn": 5, "opp_leader_id": "L1", "self_condition": "even",
                "targets": [{"priority": 1, "if": {}, "bonus": 5000}],
            },
            {
                "turn": 5, "opp_leader_id": "L1", "self_condition": "advantage",
                # 隣接 condition で weight 0.5
                "targets": [{"priority": 1, "if": {}, "bonus": 5000}],
            },
        ]
    }
    matches = find_matching_entries(spec, 5, "L1", "even", opp_archetype=None)
    # 全 Tier 1、 重畳 で 2 件 返る (= 同 tier 内 で 並列 評価)
    assert len(matches) == 2


def test_no_match_returns_empty():
    """全 entry skip → 空 list。"""
    spec = {
        "entries": [
            {
                "turn": 99, "opp_leader_id": "L_OTHER", "self_condition": "even",
                "targets": [{"priority": 1, "if": {}, "bonus": 1000}],
            },
        ]
    }
    matches = find_matching_entries(spec, 5, "L1", "even", opp_archetype=None)
    assert matches == []


def test_empty_spec_returns_empty():
    """spec 自体 が None / empty → 空 list。"""
    assert find_matching_entries(None, 5, "L1", "even", opp_archetype=None) == []
    assert find_matching_entries({}, 5, "L1", "even", opp_archetype=None) == []
    assert find_matching_entries({"entries": []}, 5, "L1", "even", opp_archetype=None) == []
