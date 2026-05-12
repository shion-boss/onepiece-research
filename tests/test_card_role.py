# -*- coding: utf-8 -*-
"""engine/card_role.py のユニットテスト。

主要 primitive → primary_role / tags の派生が正しいか、
および特殊ケース (cost ≥ 6 finisher / blocker keyword / 複数 role) を検証。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.card_role import (
    derive_card_role,
    has_role_or_tag,
    load_card_role_db,
)
from engine.core import CardDef, Category
from engine.deck import CardRepository
from engine.effects import CardEffectBundle, load_effect_overlay

ROOT = Path(__file__).resolve().parent.parent


# ============================================================================ #
# fixtures
# ============================================================================ #

@pytest.fixture(scope="module")
def repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


@pytest.fixture(scope="module")
def overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _make_card(
    card_id: str = "TEST-001",
    name: str = "テストカード",
    category: Category = Category.CHARACTER,
    cost: int = 3,
    power: int = 4000,
    counter: int = 1000,
    text: str = "",
    features: tuple = ("テスト",),
) -> CardDef:
    return CardDef(
        card_id=card_id, name=name, category=category, color=("赤",),
        cost=cost, power=power, counter=counter, features=features, text=text,
    )


def _make_overlay(card_id: str, effects: list[dict]) -> dict:
    return {card_id: CardEffectBundle(card_id=card_id, effects=effects)}


# ============================================================================ #
# 単一 primitive → primary_role 派生
# ============================================================================ #

def test_search_primary():
    card = _make_card(cost=1)
    ov = _make_overlay("TEST-001", [{"when": "on_play", "do": [
        {"search": {"filter": {"feature": "麦わら"}, "limit": 1, "depth": 5}}
    ]}])
    cr = derive_card_role(card, ov)
    assert cr.primary_role == "search"


def test_draw_primary():
    card = _make_card(cost=2)
    ov = _make_overlay("TEST-001", [{"when": "on_play", "do": [{"draw": 2}]}])
    cr = derive_card_role(card, ov)
    assert cr.primary_role == "draw"


def test_removal_ko_primary():
    card = _make_card(cost=4)
    ov = _make_overlay("TEST-001", [{"when": "on_play", "do": [
        {"ko": "one_opponent_character_cost_le_5cost"}
    ]}])
    cr = derive_card_role(card, ov)
    assert cr.primary_role == "removal"


def test_removal_return_to_hand_primary():
    card = _make_card(cost=3)
    ov = _make_overlay("TEST-001", [{"when": "on_play", "do": [
        {"return_to_hand": "one_opponent_character"}
    ]}])
    cr = derive_card_role(card, ov)
    assert cr.primary_role == "removal"


def test_ramp_add_don_primary():
    card = _make_card(cost=5)
    ov = _make_overlay("TEST-001", [{"when": "on_play", "do": [{"add_don": 1}]}])
    cr = derive_card_role(card, ov)
    assert cr.primary_role == "ramp"


def test_ramp_untap_don_primary():
    card = _make_card(cost=4)
    ov = _make_overlay("TEST-001", [{"when": "on_play", "do": [{"untap_don": 2}]}])
    cr = derive_card_role(card, ov)
    assert cr.primary_role == "ramp"


def test_recovery_life_to_hand_primary():
    card = _make_card(cost=2)
    ov = _make_overlay("TEST-001", [{"when": "activate_main", "do": [
        {"life_to_hand": 1}
    ]}])
    cr = derive_card_role(card, ov)
    assert cr.primary_role == "recovery"


def test_recovery_put_top_to_life_primary():
    card = _make_card(cost=3)
    ov = _make_overlay("TEST-001", [{"when": "on_play", "do": [
        {"put_top_to_life": 1}
    ]}])
    cr = derive_card_role(card, ov)
    assert cr.primary_role == "recovery"


def test_disruption_trash_opp_hand_primary():
    card = _make_card(cost=3)
    ov = _make_overlay("TEST-001", [{"when": "on_play", "do": [
        {"trash_opp_hand_random": 1}
    ]}])
    cr = derive_card_role(card, ov)
    assert cr.primary_role == "disruption"


def test_disruption_rest_opp_don_primary():
    card = _make_card(cost=4)
    ov = _make_overlay("TEST-001", [{"when": "on_play", "do": [{"rest_opp_don": 2}]}])
    cr = derive_card_role(card, ov)
    assert cr.primary_role == "disruption"


def test_negation_negate_effect_primary():
    card = _make_card(cost=1, category=Category.EVENT)
    ov = _make_overlay("TEST-001", [{"when": "main_event", "do": [
        {"negate_effect": "one_opponent_event"}
    ]}])
    cr = derive_card_role(card, ov)
    assert cr.primary_role == "negation"


def test_negation_immune_negate_primary():
    card = _make_card(cost=2)
    ov = _make_overlay("TEST-001", [{"when": "on_play", "do": [
        {"set_immune_attribute_in_battle": {"target": "self", "negate": True}}
    ]}])
    cr = derive_card_role(card, ov)
    assert cr.primary_role == "negation"


# ============================================================================ #
# blocker / finisher 特殊判定
# ============================================================================ #

def test_blocker_keyword_in_text():
    """text に "ブロッカー" が含まれていれば overlay 無くても primary=blocker。"""
    card = _make_card(cost=3, text="【ブロッカー】(相手のアタック時、 このキャラをレストにすることで...)")
    cr = derive_card_role(card, overlay=None)
    assert cr.primary_role == "blocker"


def test_blocker_give_keyword_self():
    card = _make_card(cost=2, text="")
    ov = _make_overlay("TEST-001", [{"when": "on_play", "do": [
        {"give_keyword": {"target": "self", "keyword": "ブロッカー", "duration": "permanent"}}
    ]}])
    cr = derive_card_role(card, ov)
    assert cr.primary_role == "blocker"


def test_finisher_cost_ge_6():
    """cost ≥ 6 character は overlay 無くても primary=finisher。"""
    card = _make_card(cost=8, power=8000)
    cr = derive_card_role(card, overlay=None)
    assert cr.primary_role == "finisher"


def test_finisher_extra_turn():
    card = _make_card(cost=4, category=Category.EVENT)
    ov = _make_overlay("TEST-001", [{"when": "main_event", "do": [{"extra_turn": True}]}])
    cr = derive_card_role(card, ov)
    assert cr.primary_role == "finisher"


def test_finisher_give_rush():
    card = _make_card(cost=3)
    ov = _make_overlay("TEST-001", [{"when": "on_play", "do": [
        {"give_rush": {"target": "self"}}
    ]}])
    cr = derive_card_role(card, ov)
    assert cr.primary_role == "finisher"


def test_finisher_leader_pump():
    card = _make_card(cost=2, category=Category.EVENT)
    ov = _make_overlay("TEST-001", [{"when": "main_event", "do": [
        {"power_pump": {"target": "self_leader", "amount": 4000, "duration": "turn"}}
    ]}])
    cr = derive_card_role(card, ov)
    assert cr.primary_role == "finisher"


# ============================================================================ #
# priority: cost ≥ 6 + KO は finisher が優先 (removal は tag に降格)
# ============================================================================ #

def test_finisher_overrides_removal_when_cost_high():
    card = _make_card(cost=10, power=12000)
    ov = _make_overlay("TEST-001", [{"when": "on_play", "do": [
        {"ko": "one_opponent_character_cost_le_8cost"}
    ]}])
    cr = derive_card_role(card, ov)
    assert cr.primary_role == "finisher"
    assert "removal" in cr.tags


def test_ramp_with_draw_in_tags():
    """on_play +don, on_ko 2-draw のような複合 effect。 ramp が primary、 draw は tag。"""
    card = _make_card(cost=5)
    ov = _make_overlay("TEST-001", [
        {"when": "on_play", "do": [{"add_don": 1}]},
        {"when": "on_ko", "do": [{"draw": 2}, {"add_don": 2}]},
    ])
    cr = derive_card_role(card, ov)
    assert cr.primary_role == "ramp"
    assert "draw" in cr.tags


# ============================================================================ #
# default: synergy
# ============================================================================ #

def test_synergy_default_for_low_cost_no_effect():
    """low-cost character with features but no effect → synergy。"""
    card = _make_card(cost=2, text="")
    cr = derive_card_role(card, overlay=None)
    assert cr.primary_role == "synergy"


def test_synergy_default_for_vanilla_no_features():
    card = _make_card(cost=4, text="", features=())
    cr = derive_card_role(card, overlay=None)
    assert cr.primary_role == "synergy"


# ============================================================================ #
# 補助 tags
# ============================================================================ #

def test_tag_redirect():
    card = _make_card(cost=3)
    ov = _make_overlay("TEST-001", [{"when": "opp_attack", "do": [
        {"redirect_attack": {"target": "self_leader_or_chara"}}
    ]}])
    cr = derive_card_role(card, ov)
    assert "redirect" in cr.tags


def test_tag_keyword_grant():
    card = _make_card(cost=4)
    ov = _make_overlay("TEST-001", [{"when": "on_play", "do": [
        {"give_keyword": {"target": "one_self_chara", "keyword": "速攻", "duration": "turn"}}
    ]}])
    cr = derive_card_role(card, ov)
    assert "keyword_grant" in cr.tags


def test_tag_protection():
    card = _make_card(cost=2)
    ov = _make_overlay("TEST-001", [{"when": "on_play", "do": [
        {"set_ko_immune": {"target": "self", "duration": "turn"}}
    ]}])
    cr = derive_card_role(card, ov)
    assert "protection" in cr.tags


def test_tag_cost_reduction():
    card = _make_card(cost=3)
    ov = _make_overlay("TEST-001", [{"when": "on_play", "do": [
        {"reduce_play_cost": {"target": "next_chara", "amount": 2}}
    ]}])
    cr = derive_card_role(card, ov)
    assert "cost_reduction" in cr.tags


def test_tag_tempo_swing_large_pump():
    card = _make_card(cost=4)
    ov = _make_overlay("TEST-001", [{"when": "on_attack", "do": [
        {"power_pump": {"target": "self", "amount": 4000, "duration": "turn"}}
    ]}])
    cr = derive_card_role(card, ov)
    assert "tempo_swing" in cr.tags


def test_tag_combo_piece():
    card = _make_card(cost=3)
    ov = _make_overlay("TEST-001", [{"when": "on_play", "do": [
        {"optional_cost_then": {"cost": [{"discard_hand": 1}], "do": [{"draw": 2}]}}
    ]}])
    cr = derive_card_role(card, ov)
    assert "combo_piece" in cr.tags


def test_tag_discard_engine():
    """trash_self_hand_random + draw を同時に持つカードは discard_engine タグ。"""
    card = _make_card(cost=3)
    ov = _make_overlay("TEST-001", [{"when": "on_play", "do": [
        {"trash_self_hand_random": 1},
        {"draw": 2},
    ]}])
    cr = derive_card_role(card, ov)
    assert "discard_engine" in cr.tags


# ============================================================================ #
# threat_level / speed_class
# ============================================================================ #

def test_threat_level_cost_based():
    card = _make_card(cost=5)
    cr = derive_card_role(card, overlay=None)
    assert cr.threat_level >= 5


def test_threat_level_finisher_bonus():
    card = _make_card(cost=8)
    cr = derive_card_role(card, overlay=None)
    assert cr.primary_role == "finisher"
    # cost 8 + finisher bonus +1 = 9
    assert cr.threat_level == 9


def test_speed_class():
    assert derive_card_role(_make_card(cost=1), None).speed_class == "early"
    assert derive_card_role(_make_card(cost=4), None).speed_class == "mid"
    assert derive_card_role(_make_card(cost=7), None).speed_class == "late"


# ============================================================================ #
# 後方互換 wrapper
# ============================================================================ #

def test_has_role_or_tag_primary():
    card = _make_card(cost=2)
    ov = _make_overlay("TEST-001", [{"when": "on_play", "do": [{"draw": 2}]}])
    assert has_role_or_tag(card, ov, "draw") is True
    assert has_role_or_tag(card, ov, "removal") is False


def test_has_role_or_tag_in_tags():
    """primary 以外の役割でも tag に入っていれば True。"""
    card = _make_card(cost=10)
    ov = _make_overlay("TEST-001", [{"when": "on_play", "do": [
        {"ko": "one_opponent_character_cost_le_8cost"}
    ]}])
    # primary=finisher (cost ≥ 6 優先)、 removal は tag
    assert has_role_or_tag(card, ov, "finisher") is True
    assert has_role_or_tag(card, ov, "removal") is True


# ============================================================================ #
# 実カードの分類 (回帰テスト)
# ============================================================================ #

def test_real_card_dofla_finisher(repo, overlay):
    """OP14-069 ドフラ 10 コス: cost ≥ 6 + KO → finisher + removal tag。"""
    card = repo.get("OP14-069")
    cr = derive_card_role(card, overlay)
    assert cr.primary_role == "finisher"
    assert "removal" in cr.tags


def test_real_card_sugar_search(repo, overlay):
    """OP10-065 シュガー: search プリミティブ → primary=search。"""
    card = repo.get("OP10-065")
    cr = derive_card_role(card, overlay)
    assert cr.primary_role == "search"


def test_real_card_treasol_ramp(repo, overlay):
    """OP14-068 トレーボル: add_rested_don → primary=ramp。"""
    card = repo.get("OP14-068")
    cr = derive_card_role(card, overlay)
    assert cr.primary_role == "ramp"


# ============================================================================ #
# JSON DB ロード
# ============================================================================ #

def test_load_card_role_db_excludes_meta():
    """db/card_roles.json の _meta などは除外される。"""
    db = load_card_role_db()
    assert "_meta" not in db
    # 実カードが入っている
    assert "OP14-069" in db
    entry = db["OP14-069"]
    assert entry["primary_role"] == "finisher"


def test_load_card_role_db_all_4518_cards():
    db = load_card_role_db()
    # 全 4,518 カードが分類済
    assert len(db) == 4518
    # primary_role 未設定が無い
    unset = [cid for cid, v in db.items() if not v.get("primary_role")]
    assert unset == [], f"未設定: {unset[:5]}..."
