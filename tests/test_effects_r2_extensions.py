# -*- coding: utf-8 -*-
"""R2 効果 DSL 拡張テスト (sev≥8 カード支援用)。

R2 で追加された engine 拡張のスモークテスト。
1. optional_cost_then.cost に return_self_don_to_deck
2. on_self_chara_ko トリガー
3. cannot_attack_target_except 静的効果
4. discard_hand_with_filter cost (activate_main / optional_cost_then)
5. set_base_cost_filtered_static 静的効果
6. optional_cost_then.cost に power_pump (リーダー弱体化)
7. rest_self_target_name cost (activate_main / optional_cost_then)
8. give_keyword / give_rush の 特徴フィルタ target (parametric + dict)
9. opp_event_or_trigger_fired トリガー
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    CardEffectBundle,
    eval_condition,
    execute_effect,
    evaluate_static_effects,
    _can_pay_activate_cost,
    fire_activate_main,
    _matches_filter,
    _resolve_target,
)

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _make_state(repo, leader_id="OP01-003", opp_leader_id="OP01-001"):
    leader = repo.get(leader_id)
    p1 = Player(name="P0", leader=InPlay.of(leader, sickness=False))
    p2 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p1.deck = [repo.get("OP01-013")] * 30
    p2.deck = [repo.get("OP01-013")] * 30
    return GameState(
        players=[p1, p2],
        phase=Phase.MAIN,
        rng=random.Random(1),
        effects_overlay={},
    )


def _bundle(card_id, effects):
    return CardEffectBundle(card_id=card_id, effects=effects)


# --------------------------------------------------------------------------- #
# 1. optional_cost_then.cost に return_self_don_to_deck
# --------------------------------------------------------------------------- #
def test_optional_cost_then_with_return_don_pays_when_enough():
    """場のドンが N 枚以上あれば return_self_don_to_deck cost を支払い、 効果が発動する。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    me.don_active = 3
    me.don_remaining_in_deck = 7
    hand_before = len(me.hand)
    execute_effect(
        {"optional_cost_then": {
            "cost": [{"return_self_don_to_deck": 2}],
            "effect": [{"draw": 1}],
        }},
        state, me, opp, None,
    )
    # ドン 2 枚がデッキへ戻る + 1 ドロー
    assert me.don_active == 1
    assert me.don_remaining_in_deck == 9
    assert len(me.hand) == hand_before + 1


def test_optional_cost_then_with_return_don_skips_when_insufficient():
    """場のドンが N 枚未満なら cost 不能 → 効果不発。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    me.don_active = 1
    me.don_rested = 0
    hand_before = len(me.hand)
    result = execute_effect(
        {"optional_cost_then": {
            "cost": [{"return_self_don_to_deck": 2}],
            "effect": [{"draw": 1}],
        }},
        state, me, opp, None,
    )
    # cost 不能 → 不発
    assert result is False
    assert me.don_active == 1
    assert len(me.hand) == hand_before


# --------------------------------------------------------------------------- #
# 2. on_self_chara_ko トリガー
# --------------------------------------------------------------------------- #
def test_on_self_chara_ko_fires_when_own_chara_kod_by_effect():
    """自キャラが相手の効果で KO された時、 on_self_chara_ko が発火する (場の効果)。
    OP10-042 ウソップ系。 KO された側 (= victim_owner) の場に on_self_chara_ko を持つ
    リーダー / キャラがあれば発火。"""
    from engine.effects import trigger_on_self_chara_ko
    repo = _repo()
    overlay = {
        # リーダー OP01-003 (= victim_owner 側) が on_self_chara_ko で draw 1 する設計
        "OP01-003": _bundle("OP01-003", [{
            "when": "on_self_chara_ko",
            "do": [{"draw": 1}],
        }]),
    }
    state = _make_state(repo)
    state.effects_overlay = overlay
    victim_owner = state.players[0]  # 自キャラが KO される側
    actor = state.players[1]
    hand_before = len(victim_owner.hand)
    trigger_on_self_chara_ko(state, victim_owner, actor, overlay)
    # トリガー発火で 1 ドロー
    assert len(victim_owner.hand) == hand_before + 1


def test_on_self_chara_ko_fired_via_ko_primitive_from_opp_effect():
    """ko primitive で相手キャラを KO した時、 on_self_chara_ko が victim_owner 側で発火。
    KO した側からの ko primitive 経由の発火経路を確認。"""
    repo = _repo()
    overlay = {
        # opp leader (= 被害側) の on_self_chara_ko で draw 1
        "OP01-001": _bundle("OP01-001", [{
            "when": "on_self_chara_ko",
            "do": [{"draw": 1}],
        }]),
    }
    state = _make_state(repo)
    state.effects_overlay = overlay
    me = state.players[0]
    opp = state.players[1]
    # opp に低コストキャラ追加 (KO 対象)
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters.append(victim)
    opp_hand_before = len(opp.hand)
    # me が ko を発動 (相手キャラを KO)
    execute_effect(
        {"ko": "one_opponent_character_le_5000"},
        state, me, opp, None,
    )
    # opp 側の on_self_chara_ko が発火 → opp が 1 ドロー
    assert victim not in opp.characters
    assert len(opp.hand) == opp_hand_before + 1


# --------------------------------------------------------------------------- #
# 3. cannot_attack_target_except 静的効果
# --------------------------------------------------------------------------- #
def test_cannot_attack_target_except_sets_taunt_on_named():
    """cannot_attack_target_except: 場の me.characters のうち name 一致を attack_taunt=True に。"""
    repo = _repo()
    overlay = {
        # リーダー (= 静的効果源) が on_attached_don n=0 で cannot_attack_target_except 発動
        "OP01-003": _bundle("OP01-003", [{
            "when": "on_attached_don",
            "n": 0,
            "do": [{"cannot_attack_target_except": {"name": "サンジ"}}],
        }]),
    }
    state = _make_state(repo)
    state.effects_overlay = overlay
    me = state.players[0]
    # name=サンジ (OP01-013) + name 不一致のキャラを場に
    sanji = InPlay.of(repo.get("OP01-013"), sickness=False)  # name=サンジ
    other = InPlay.of(repo.get("OP01-016"), sickness=False)  # name=ナミ
    me.characters.append(sanji)
    me.characters.append(other)
    evaluate_static_effects(state, overlay)
    # name 一致だけ attack_taunt=True
    assert sanji.attack_taunt is True
    assert other.attack_taunt is False


def test_cannot_attack_target_except_no_match_no_taunt():
    """cannot_attack_target_except: name 一致キャラがいなければ制約なし。"""
    repo = _repo()
    overlay = {
        "OP01-003": _bundle("OP01-003", [{
            "when": "on_attached_don",
            "n": 0,
            "do": [{"cannot_attack_target_except": {"name": "存在しないキャラ_XYZ"}}],
        }]),
    }
    state = _make_state(repo)
    state.effects_overlay = overlay
    me = state.players[0]
    sanji = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters.append(sanji)
    evaluate_static_effects(state, overlay)
    # 制約 0 件
    assert sanji.attack_taunt is False


# --------------------------------------------------------------------------- #
# 4. discard_hand_with_filter cost
# --------------------------------------------------------------------------- #
def test_discard_hand_with_filter_can_pay_with_matching():
    """手札に filter 一致が count 以上あれば cost 支払可。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    # 麦わらの一味 特徴を持つ OP01-013 (サンジ) を 2 枚 + 一致しない非リーダー枠カード
    # (OP01-001 はリーダーカードで 麦わらの一味 特徴を持つので一致してしまう → 除外)。
    me.hand = [repo.get("OP01-013"), repo.get("OP01-013")]
    ip = me.leader  # 起動メイン source の代わり
    cost = {"discard_hand_with_filter": {"filter": {"feature": "麦わらの一味"}, "count": 2}}
    assert _can_pay_activate_cost(state, me, ip, cost) is True
    cost_fail = {"discard_hand_with_filter": {"filter": {"feature": "麦わらの一味"}, "count": 3}}
    assert _can_pay_activate_cost(state, me, ip, cost_fail) is False


def test_discard_hand_with_filter_payment_drops_matching():
    """fire_activate_main で filter 一致カードを count 枚 trash に送る。"""
    repo = _repo()
    overlay = {
        "OP01-003": _bundle("OP01-003", [{
            "when": "activate_main",
            "cost": {
                "discard_hand_with_filter": {"filter": {"feature": "麦わらの一味"}, "count": 1},
                "once_per_turn": True,
            },
            "do": [{"draw": 2}],
        }]),
    }
    state = _make_state(repo)
    state.effects_overlay = overlay
    me = state.players[0]
    opp = state.players[1]
    me.hand = [
        repo.get("OP01-013"),  # 麦わらの一味
        repo.get("OP01-001"),  # 麦わら 持ちでない (リーダー)
    ]
    eff = overlay["OP01-003"].effects[0]
    fire_activate_main(state, me, opp, me.leader, eff)
    # 麦わらの一味 1 枚 が trash へ
    assert any(c.card_id == "OP01-013" for c in me.trash)
    # 残り手札に OP01-001 がいる (= 非一致は残る)
    assert any(c.card_id == "OP01-001" for c in me.hand)


def test_discard_hand_with_filter_in_optional_cost_then():
    """optional_cost_then.cost でも discard_hand_with_filter を扱える。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    me.hand = [repo.get("OP01-013")]  # 麦わら 1 枚
    execute_effect(
        {"optional_cost_then": {
            "cost": [{"discard_hand_with_filter": {"filter": {"feature": "麦わらの一味"}, "count": 1}}],
            "effect": [{"draw": 2}],
        }},
        state, me, opp, None,
    )
    # 麦わら捨て + 2 ドロー
    assert len(me.trash) == 1
    assert len(me.hand) == 2  # 1 - 1 + 2


# --------------------------------------------------------------------------- #
# 5. set_base_cost_filtered_static
# --------------------------------------------------------------------------- #
def test_set_base_cost_filtered_static_applies_delta():
    """filter 一致のキャラに base_cost +N が静的に適用される。"""
    repo = _repo()
    overlay = {
        "OP01-003": _bundle("OP01-003", [{
            "when": "on_attached_don",
            "n": 0,
            "do": [{
                "set_base_cost_filtered_static": {
                    "filter": {"feature": "麦わらの一味", "cost_ge": 1},
                    "delta": 1,
                },
            }],
        }]),
    }
    state = _make_state(repo)
    state.effects_overlay = overlay
    me = state.players[0]
    sanji = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost=2, 麦わら
    me.characters.append(sanji)
    evaluate_static_effects(state, overlay)
    # 元コスト 2 + delta 1 = 3
    assert sanji.base_cost == 3
    assert sanji.base_cost_override == 3


def test_set_base_cost_filtered_static_no_match_no_change():
    """filter 不一致のキャラには影響なし。"""
    repo = _repo()
    overlay = {
        "OP01-003": _bundle("OP01-003", [{
            "when": "on_attached_don",
            "n": 0,
            "do": [{
                "set_base_cost_filtered_static": {
                    "filter": {"feature": "存在しない特徴_XYZ"},
                    "delta": 5,
                },
            }],
        }]),
    }
    state = _make_state(repo)
    state.effects_overlay = overlay
    me = state.players[0]
    sanji = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters.append(sanji)
    evaluate_static_effects(state, overlay)
    # filter 不一致なので override されない (None のまま、 base_cost = card.cost)
    assert sanji.base_cost_override is None
    assert sanji.base_cost == sanji.card.cost


# --------------------------------------------------------------------------- #
# 6. optional_cost_then.cost に power_pump (リーダー弱体化)
# --------------------------------------------------------------------------- #
def test_optional_cost_then_with_leader_self_pump_negative():
    """power_pump (target=self_leader, amount=-5000) を optional cost として実行できる。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    leader_p_before = me.leader.power
    hand_before = len(me.hand)
    execute_effect(
        {"optional_cost_then": {
            "cost": [{"power_pump": {"target": "self_leader", "amount": -5000, "duration": "turn"}}],
            "effect": [{"draw": 1}],
        }},
        state, me, opp, None,
    )
    # リーダーパワー -5000 + 1 ドロー
    assert me.leader.power == leader_p_before - 5000
    assert len(me.hand) == hand_before + 1


# --------------------------------------------------------------------------- #
# 7. rest_self_target_name cost
# --------------------------------------------------------------------------- #
def test_rest_self_target_name_can_pay():
    """場に name 一致 + アクティブなキャラがあれば cost 支払可。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    # name=サンジ (OP01-013) を場に追加
    sanji = InPlay.of(repo.get("OP01-013"), sickness=False, rested=False)
    me.characters.append(sanji)
    cost_ok = {"rest_self_target_name": "サンジ"}
    assert _can_pay_activate_cost(state, me, me.leader, cost_ok) is True
    # rest 状態なら不可
    sanji.rested = True
    assert _can_pay_activate_cost(state, me, me.leader, cost_ok) is False


def test_rest_self_target_name_in_activate_main_pays_and_rests():
    """fire_activate_main で name 一致キャラを rest にする。"""
    repo = _repo()
    overlay = {
        "OP01-003": _bundle("OP01-003", [{
            "when": "activate_main",
            "cost": {
                "rest_self_target_name": "サンジ",
                "once_per_turn": True,
            },
            "do": [{"draw": 1}],
        }]),
    }
    state = _make_state(repo)
    state.effects_overlay = overlay
    me = state.players[0]
    opp = state.players[1]
    sanji = InPlay.of(repo.get("OP01-013"), sickness=False, rested=False)
    me.characters.append(sanji)
    eff = overlay["OP01-003"].effects[0]
    fire_activate_main(state, me, opp, me.leader, eff)
    # サンジが rest に
    assert sanji.rested is True


def test_rest_self_target_name_in_optional_cost_then():
    """optional_cost_then.cost でも rest_self_target_name を扱える。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    sanji = InPlay.of(repo.get("OP01-013"), sickness=False, rested=False)
    me.characters.append(sanji)
    hand_before = len(me.hand)
    execute_effect(
        {"optional_cost_then": {
            "cost": [{"rest_self_target_name": "サンジ"}],
            "effect": [{"draw": 1}],
        }},
        state, me, opp, None,
    )
    assert sanji.rested is True
    assert len(me.hand) == hand_before + 1


# --------------------------------------------------------------------------- #
# 8. give_keyword / give_rush の 特徴フィルタ target
# --------------------------------------------------------------------------- #
def test_one_self_character_feature_target_parametric():
    """one_self_character_feature_X parametric target で特徴 X 持ち 1 体を解決。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    sanji = InPlay.of(repo.get("OP01-013"), sickness=False)  # 麦わらの一味
    me.characters.append(sanji)
    targets = _resolve_target("one_self_character_feature_麦わらの一味", state, me, opp, None)
    assert len(targets) == 1
    assert targets[0] is sanji


def test_give_keyword_with_feature_filter_target():
    """give_keyword + feature filter parametric target で 速攻 を付与。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    sanji = InPlay.of(repo.get("OP01-013"), sickness=True)  # 麦わら、 召喚酔い
    me.characters.append(sanji)
    execute_effect(
        {"give_keyword": {
            "target": "one_self_character_feature_麦わらの一味",
            "keyword": "速攻：キャラ",
        }},
        state, me, opp, None,
    )
    assert "速攻：キャラ" in sanji.granted_keywords


def test_give_rush_with_feature_filter_target_dict():
    """give_rush + dict-form target (= one_self_chara_filtered + feature_in)。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    sanji = InPlay.of(repo.get("OP01-013"), sickness=True)  # 麦わら
    me.characters.append(sanji)
    execute_effect(
        {"give_rush": {
            "type": "one_self_chara_filtered",
            "filter": {"feature_in": ["麦わらの一味", "存在しない特徴"]},
        }},
        state, me, opp, None,
    )
    # summoning_sickness が解除される
    assert sanji.summoning_sickness is False


def test_feature_in_filter_or_semantics():
    """_matches_filter feature_in: OR セマンティクス確認。"""
    repo = _repo()
    sanji = repo.get("OP01-013")  # 麦わらの一味
    # 一致 (1 個目)
    assert _matches_filter(sanji, {"feature_in": ["麦わらの一味", "海軍"]}) is True
    # 一致 (2 個目)
    assert _matches_filter(sanji, {"feature_in": ["海軍", "麦わらの一味"]}) is True
    # 不一致
    assert _matches_filter(sanji, {"feature_in": ["海軍", "FOXY海賊団"]}) is False
    # 単一文字列でも OK
    assert _matches_filter(sanji, {"feature_in": "麦わらの一味"}) is True


# --------------------------------------------------------------------------- #
# 9. opp_event_or_trigger_fired トリガー
# --------------------------------------------------------------------------- #
def test_opp_event_or_trigger_fired_fires_on_main_event():
    """相手がメインイベントを発動した時、 opp_event_or_trigger_fired が opp 側で発火。"""
    from engine.effects import trigger_main_event
    repo = _repo()
    # 適当な EVENT カード を見つける
    event_card = None
    for c in repo._by_id.values() if hasattr(repo, '_by_id') else []:
        if c.category.value == "EVENT":
            event_card = c
            break
    if event_card is None:
        # Fallback: テストでは bundle dict があれば OK なので疑似カード使う
        from engine.core import CardDef, Category
        event_card = CardDef(
            card_id="TEST_EVT",
            name="TEST EVENT",
            category=Category.EVENT,
            cost=1,
            power=0,
            counter=0,
            color=("赤",),
            features=(),
            text="",
            trigger="",
            attribute="",
        )
    overlay = {
        # opp の leader が opp_event_or_trigger_fired で draw 1
        "OP01-001": _bundle("OP01-001", [{
            "when": "opp_event_or_trigger_fired",
            "do": [{"draw": 1}],
        }]),
    }
    state = _make_state(repo)
    state.effects_overlay = overlay
    me = state.players[0]
    opp = state.players[1]
    opp_hand_before = len(opp.hand)
    trigger_main_event(state, me, opp, event_card, overlay)
    # opp (= 効果保有側) が 1 ドロー
    assert len(opp.hand) == opp_hand_before + 1


def test_opp_event_or_trigger_fired_fires_on_lifecard_trigger():
    """相手のライフトリガーが発動した時、 attacker 側で opp_event_or_trigger_fired が発火。
    defender = トリガー発火、 attacker_player の場で発火する設計。"""
    from engine.effects import trigger_lifecard_trigger
    repo = _repo()
    # トリガー効果を持つカード (= when=trigger) を仮想で持たせる
    trigger_card = repo.get("OP01-013")  # 任意
    overlay = {
        # トリガー発火するカードに【トリガー】効果
        trigger_card.card_id: _bundle(trigger_card.card_id, [{
            "when": "trigger",
            "do": [{"draw": 1}],
        }]),
        # attacker 側 leader が opp_event_or_trigger_fired で 1 ドロー
        "OP01-003": _bundle("OP01-003", [{
            "when": "opp_event_or_trigger_fired",
            "do": [{"draw": 1}],
        }]),
    }
    state = _make_state(repo)
    state.effects_overlay = overlay
    me = state.players[0]      # attacker
    opp = state.players[1]     # defender (トリガー発火側)
    me_hand_before = len(me.hand)
    trigger_lifecard_trigger(state, opp, me, trigger_card, overlay, auto_fire=True)
    # me (= attacker) の leader 効果で 1 ドロー
    assert len(me.hand) >= me_hand_before + 1
