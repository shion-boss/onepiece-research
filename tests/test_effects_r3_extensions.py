# -*- coding: utf-8 -*-
"""R3 効果 DSL 拡張テスト (sev≥8 カード支援用)。

R3 で追加された engine 拡張のスモークテスト。
1. _matches_filter に trigger: true フィルタ
2. stage_to_deck_bottom cost (optional_cost_then.cost)
3. return_self_chara_to_deck_bottom cost (optional_cost_then.cost)
4. mill_opp_life_to_trash primitive
5. one_opp_chara_or_don target spec (rest primitive 拡張)
6. replace_leave_by_opp_effect cost (= replace_leave + discard_hand_with_filter)
7. play_multi_from_trash w/ unique_name (= play_from_trash の name 重複排除)
8. replace_ko の cost に discard_hand_with_filter
9. on_attached_don n=0 + if {opp_turn, leader_feature} → give_keyword + power_pump
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import CardDef, Category, GameState, InPlay, Phase, Player
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
    try_replace_ko,
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
# 1. _matches_filter trigger: true alias
# --------------------------------------------------------------------------- #
def test_trigger_true_filter_matches_card_with_trigger():
    """trigger: true filter は cards.json の trigger フィールドが空でない場合に True。"""
    repo = _repo()
    # 【トリガー】 を持つカードを 1 枚探す
    triggered_card = None
    for cid in ("OP01-013", "OP01-001", "OP01-006", "OP02-002", "OP01-016"):
        try:
            c = repo.get(cid)
            if c.trigger:
                triggered_card = c
                break
        except Exception:
            continue
    # 確実なフォールバック: cards.json を直接走査
    if triggered_card is None:
        for c in list(repo._by_id.values())[:200]:
            if c.trigger:
                triggered_card = c
                break
    assert triggered_card is not None, "テスト前提: トリガー持ちカードが見つからない"

    # trigger: true で True
    assert _matches_filter(triggered_card, {"trigger": True}) is True

    # トリガー無しカード (CardDef を直接生成)
    plain = CardDef(
        card_id="TEST_NOTRIG",
        name="dummy",
        category=Category.CHARACTER,
        cost=1,
        power=1000,
        counter=0,
        color=("赤",),
        features=(),
        text="",
        trigger="",
        attribute="",
    )
    assert _matches_filter(plain, {"trigger": True}) is False


def test_trigger_true_filter_compatible_with_has_trigger():
    """trigger: true と has_trigger: true は同等に振る舞う (既存後方互換)。"""
    plain = CardDef(
        card_id="X", name="d", category=Category.CHARACTER, cost=0, power=0,
        counter=0, color=("赤",), features=(), text="", trigger="", attribute="",
    )
    triggered = CardDef(
        card_id="Y", name="d", category=Category.CHARACTER, cost=0, power=0,
        counter=0, color=("赤",), features=(), text="",
        trigger="【トリガー】カード1枚を引く。", attribute="",
    )
    # has_trigger と trigger は同じ結果を返す
    assert _matches_filter(triggered, {"has_trigger": True}) is True
    assert _matches_filter(triggered, {"trigger": True}) is True
    assert _matches_filter(plain, {"has_trigger": True}) is False
    assert _matches_filter(plain, {"trigger": True}) is False


# --------------------------------------------------------------------------- #
# 2. stage_to_deck_bottom cost
# --------------------------------------------------------------------------- #
def test_stage_to_deck_bottom_pays_when_matching_stage_exists():
    """場のステージが cost_eq=1 で 1 枚以上あれば cost 支払可、 デッキ底へ。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    # ステージカードを探す
    stage_cost1 = None
    for c in repo._by_id.values():
        if c.category == Category.STAGE and c.cost == 1:
            stage_cost1 = c
            break
    if stage_cost1 is None:
        # フォールバック: 適当な stage を作る
        stage_cost1 = CardDef(
            card_id="TEST_STAGE", name="dummy_stage", category=Category.STAGE,
            cost=1, power=0, counter=0, color=("赤",), features=(), text="",
            trigger="", attribute="",
        )
    stage_ip = InPlay.of(stage_cost1, sickness=False)
    me.stages.append(stage_ip)
    me.deck = [repo.get("OP01-013")] * 30
    hand_before = len(me.hand)
    result = execute_effect(
        {"optional_cost_then": {
            "cost": [{"stage_to_deck_bottom": {"cost_eq": 1, "count": 1}}],
            "effect": [{"draw": 1}],
        }},
        state, me, opp, None,
    )
    assert result is not False
    # stage が場から消え、 デッキ底に追加 (deck の末尾が 該当 stage カード)
    assert stage_ip not in me.stages
    # draw 1 が末尾ではなく先頭 (= 通常 draw は先頭から) なので、 deck 末尾は stage_cost1 のまま
    assert me.deck[-1].card_id == stage_cost1.card_id
    # 効果発動 (1 ドロー)
    assert len(me.hand) == hand_before + 1


def test_stage_to_deck_bottom_skips_when_no_matching_stage():
    """場に対象 stage が無ければ cost 不能 → 不発。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    hand_before = len(me.hand)
    result = execute_effect(
        {"optional_cost_then": {
            "cost": [{"stage_to_deck_bottom": {"cost_eq": 1, "count": 1}}],
            "effect": [{"draw": 1}],
        }},
        state, me, opp, None,
    )
    assert result is False
    assert len(me.hand) == hand_before


# --------------------------------------------------------------------------- #
# 3. return_self_chara_to_deck_bottom cost
# --------------------------------------------------------------------------- #
def test_return_self_chara_to_deck_bottom_pays_when_chara_exists():
    """自キャラがあれば cost 支払可、 キャラがデッキ底へ。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    chara = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters.append(chara)
    # 別カードでデッキを埋める (= 末尾検証で chara 追加判別できる)
    me.deck = [repo.get("OP01-016")] * 30  # ナミ × 30
    hand_before = len(me.hand)
    result = execute_effect(
        {"optional_cost_then": {
            "cost": [{"return_self_chara_to_deck_bottom": {"count": 1}}],
            "effect": [{"draw": 1}],
        }},
        state, me, opp, None,
    )
    assert result is not False
    assert chara not in me.characters
    # deck 末尾は サンジ (= 返したキャラ)、 draw は先頭 ナミから
    assert me.deck[-1].card_id == "OP01-013"
    assert len(me.hand) == hand_before + 1


def test_return_self_chara_to_deck_bottom_skips_when_no_chara():
    """自キャラが無ければ cost 不能 → 不発。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    hand_before = len(me.hand)
    result = execute_effect(
        {"optional_cost_then": {
            "cost": [{"return_self_chara_to_deck_bottom": {"count": 1}}],
            "effect": [{"draw": 1}],
        }},
        state, me, opp, None,
    )
    assert result is False
    assert len(me.hand) == hand_before


# --------------------------------------------------------------------------- #
# 4. mill_opp_life_to_trash primitive
# --------------------------------------------------------------------------- #
def test_mill_opp_life_to_trash_one_card():
    """相手ライフ上 1 枚をトラッシュへ。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    # 相手ライフを 3 枚分用意 (deck から)
    opp.life = [repo.get("OP01-013")] * 3
    trash_before = len(opp.trash)
    life_before = len(opp.life)
    execute_effect({"mill_opp_life_to_trash": 1}, state, me, opp, None)
    assert len(opp.life) == life_before - 1
    assert len(opp.trash) == trash_before + 1


def test_mill_opp_life_to_trash_multi():
    """相手ライフ上 2 枚をトラッシュへ。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    opp.life = [repo.get("OP01-013")] * 3
    execute_effect({"mill_opp_life_to_trash": 2}, state, me, opp, None)
    assert len(opp.life) == 1
    assert len(opp.trash) == 2


def test_mill_opp_life_to_trash_empty_life():
    """相手ライフが空なら no-op。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    opp.life = []
    execute_effect({"mill_opp_life_to_trash": 1}, state, me, opp, None)
    assert len(opp.life) == 0
    assert len(opp.trash) == 0


# --------------------------------------------------------------------------- #
# 5. one_opp_chara_or_don target spec (rest primitive)
# --------------------------------------------------------------------------- #
def test_one_opp_chara_or_don_rest_chara_first():
    """相手にアクティブキャラがある場合は そちらを優先 rest。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    chara = InPlay.of(repo.get("OP01-013"), sickness=False, rested=False)
    opp.characters.append(chara)
    opp.don_active = 3
    execute_effect({"rest": "one_opp_chara_or_don"}, state, me, opp, None)
    # キャラ優先で rest
    assert chara.rested is True
    # don は変化なし
    assert opp.don_active == 3
    assert opp.don_rested == 0


def test_one_opp_chara_or_don_rest_don_when_no_chara():
    """相手キャラが無くアクティブドンがあるならドンを 1 枚 rest。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    opp.don_active = 3
    opp.don_rested = 0
    execute_effect({"rest": "one_opp_chara_or_don"}, state, me, opp, None)
    assert opp.don_active == 2
    assert opp.don_rested == 1


def test_one_opp_chara_or_don_no_target_returns_false():
    """相手キャラ無し + アクティブドン無し → 不発。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    opp.don_active = 0
    opp.don_rested = 5
    result = execute_effect({"rest": "one_opp_chara_or_don"}, state, me, opp, None)
    assert result is False
    # don 状態は不変
    assert opp.don_active == 0
    assert opp.don_rested == 5


# --------------------------------------------------------------------------- #
# 6. replace_leave_by_opp_effect (replace_leave + cost discard_hand_with_filter)
# --------------------------------------------------------------------------- #
def test_replace_leave_with_discard_cost_blocks_return_to_hand():
    """replace_leave + discard_hand cost で相手の return_to_hand 効果を阻止。"""
    repo = _repo()
    # ボルサリーノ系: replace_leave で 手札 1 枚捨てて場に残る
    overlay = {
        "OP01-013": _bundle("OP01-013", [{
            "when": "replace_leave",
            "if": {"target": "self", "by_opp_effect": True},
            "cost": [{"discard_hand_with_filter": {"filter": {}, "count": 1}}],
        }]),
    }
    state = _make_state(repo)
    state.effects_overlay = overlay
    me = state.players[0]
    opp = state.players[1]
    # me.characters に サンジ (OP01-013) を置き、 手札に 1 枚 (任意)
    sanji = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters.append(sanji)
    me.hand = [repo.get("OP01-016")]
    # opp が return_to_hand 効果を発動 (target = me.sanji)。
    # 「me が opp、 opp が me」 の視点で execute_effect を呼ぶ。
    hand_before = len(me.hand)
    result = execute_effect(
        {"return_to_hand": "one_opponent_character_any"},
        state, opp, me, None,  # 視点入替: opp が active player
    )
    # sanji は場に残る (= 置換成功)、 me.hand は 1 → 0 (cost で捨てた)
    assert sanji in me.characters
    assert len(me.hand) == hand_before - 1


def test_replace_leave_blocks_ko_too():
    """replace_leave は KO 経路でも発火する (= 「場を離れる」は KO 含む)。"""
    repo = _repo()
    overlay = {
        "OP01-013": _bundle("OP01-013", [{
            "when": "replace_leave",
            "if": {"target": "self", "by_opp_effect": True},
            "cost": [{"discard_hand_with_filter": {"filter": {}, "count": 1}}],
        }]),
    }
    state = _make_state(repo)
    state.effects_overlay = overlay
    me = state.players[0]
    opp = state.players[1]
    sanji = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters.append(sanji)
    me.hand = [repo.get("OP01-016")]
    # opp が KO 効果を発動
    execute_effect(
        {"ko": "one_opponent_character_any"},
        state, opp, me, None,
    )
    # sanji が場に残り、 hand 捨てている
    assert sanji in me.characters
    assert len(me.hand) == 0


def test_replace_leave_skips_when_no_hand():
    """cost (discard_hand) を払えない (手札 0) → 置換失敗 → 通常通り KO。"""
    repo = _repo()
    overlay = {
        "OP01-013": _bundle("OP01-013", [{
            "when": "replace_leave",
            "if": {"target": "self", "by_opp_effect": True},
            "cost": [{"discard_hand_with_filter": {"filter": {}, "count": 1}}],
        }]),
    }
    state = _make_state(repo)
    state.effects_overlay = overlay
    me = state.players[0]
    opp = state.players[1]
    sanji = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters.append(sanji)
    me.hand = []  # 手札 0 で支払い不能
    execute_effect(
        {"ko": "one_opponent_character_any"},
        state, opp, me, None,
    )
    # cost 払えないので普通に KO される
    assert sanji not in me.characters


# --------------------------------------------------------------------------- #
# 7. play_multi_from_trash unique_name
# --------------------------------------------------------------------------- #
def test_play_multi_from_trash_unique_name():
    """unique_name=true で カード名が重複しないよう N 体登場。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    # トラッシュに 同名 2 枚 + 別名 1 枚
    sanji1 = repo.get("OP01-013")  # サンジ
    sanji2 = repo.get("OP01-013")
    nami = repo.get("OP01-016")  # ナミ
    me.trash = [sanji1, sanji2, nami]
    me.characters = []
    execute_effect(
        {"play_multi_from_trash": {
            "filter": {"category": "CHARACTER"},
            "limit": 4,
            "unique_name": True,
        }},
        state, me, opp, None,
    )
    # 2 体登場 (サンジ 1 + ナミ 1)、 サンジ 1 枚はトラッシュに残る
    assert len(me.characters) == 2
    names = sorted(ip.card.name for ip in me.characters)
    assert names == ["サンジ", "ナミ"]
    assert len(me.trash) == 1  # サンジ 1 枚 残る


def test_play_multi_from_trash_without_unique_name():
    """unique_name=false (デフォルト) は既存 play_from_trash と同じ挙動 (同名複数 OK)。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    me.trash = [repo.get("OP01-013")] * 3  # 同名 3 枚
    me.characters = []
    execute_effect(
        {"play_multi_from_trash": {
            "filter": {"category": "CHARACTER"},
            "limit": 3,
            # unique_name 未指定 = false
        }},
        state, me, opp, None,
    )
    # 3 体すべて登場 (5 枚上限ガード未抵触)
    assert len(me.characters) == 3
    assert all(ip.card.card_id == "OP01-013" for ip in me.characters)


# --------------------------------------------------------------------------- #
# 8. replace_ko の cost に discard_hand_with_filter
# --------------------------------------------------------------------------- #
def test_replace_ko_with_discard_filter_cost_blocks_ko():
    """replace_ko + cost (discard_hand_with_filter power_le=6000) で KO を阻止。"""
    repo = _repo()
    overlay = {
        "OP15-003": _bundle("OP15-003", [{
            "when": "replace_ko",
            "if": {"target": "self"},
            "cost": [{"discard_hand_with_filter": {
                "filter": {"category": "CHARACTER", "power_le": 6000},
                "count": 1,
            }}],
        }]),
    }
    state = _make_state(repo)
    state.effects_overlay = overlay
    me = state.players[0]
    opp = state.players[1]
    # OP15-003 アルビダ が場に
    try:
        alvida_card = repo.get("OP15-003")
    except KeyError:
        # アルビダ無ければ任意のキャラで代替
        alvida_card = repo.get("OP01-013")
        overlay = {
            alvida_card.card_id: _bundle(alvida_card.card_id, overlay["OP15-003"].effects),
        }
        state.effects_overlay = overlay
    alvida_ip = InPlay.of(alvida_card, sickness=False)
    me.characters.append(alvida_ip)
    # 手札: power 5000 (=6000 以下) のキャラ 1 枚
    me.hand = [repo.get("OP01-013")]  # サンジ power=2000、 充足

    # opp の効果で KO される
    execute_effect(
        {"ko": {"type": "one_opponent_character_filtered",
                "filter": {"category": "CHARACTER"}}},
        state, opp, me, None,
    )
    # 置換成功 → アルビダ場に残り、 手札捨て
    assert alvida_ip in me.characters
    assert len(me.hand) == 0


def test_replace_ko_with_discard_filter_cost_fails_when_no_matching_hand():
    """手札に filter (power_le=6000) 一致が無いと cost 不能 → 通常 KO される。"""
    repo = _repo()
    overlay = {
        "OP01-013": _bundle("OP01-013", [{
            "when": "replace_ko",
            "if": {"target": "self"},
            "cost": [{"discard_hand_with_filter": {
                "filter": {"category": "CHARACTER", "power_le": 6000},
                "count": 1,
            }}],
        }]),
    }
    state = _make_state(repo)
    state.effects_overlay = overlay
    me = state.players[0]
    opp = state.players[1]
    target_ip = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters.append(target_ip)
    # 手札に CHARACTER 持ち かつ power 7000 のカードを探す
    high_power_card = None
    for c in list(repo._by_id.values())[:1000]:
        if c.category == Category.CHARACTER and c.power >= 7000:
            high_power_card = c
            break
    if high_power_card is None:
        # フォールバック: 仮想カード
        high_power_card = CardDef(
            card_id="TEST_HIGH", name="big", category=Category.CHARACTER,
            cost=8, power=9000, counter=0, color=("赤",), features=(),
            text="", trigger="", attribute="",
        )
    me.hand = [high_power_card]
    execute_effect(
        {"ko": {"type": "one_opponent_character_filtered",
                "filter": {"category": "CHARACTER"}}},
        state, opp, me, None,
    )
    # cost 不能 → 通常 KO
    assert target_ip not in me.characters


# --------------------------------------------------------------------------- #
# 9. on_attached_don n=0 + if {opp_turn, leader_feature} → blocker + power_pump
# --------------------------------------------------------------------------- #
def test_borsalino_static_blocker_during_opp_turn_with_navy_leader():
    """ボルサリーノ (OP12-053) 静的: 相手ターン中 + リーダー海軍 → ブロッカー + パワー+1000。"""
    repo = _repo()
    # 海軍リーダーを使う (OP01-002 = 海軍 (赤紫)) もしくは適当な カードで代替
    leader_card = None
    for c in repo._by_id.values():
        if c.category == Category.LEADER and "海軍" in c.features:
            leader_card = c
            break
    assert leader_card is not None, "海軍リーダーが見つからない"

    overlay = {
        # 仮想 ボルサリーノ overlay (実 OP12-053 の overlay とは独立)
        "OP01-013": _bundle("OP01-013", [{
            "when": "on_attached_don",
            "n": 0,
            "if": {"opp_turn": True, "leader_feature": "海軍"},
            "do": [
                {"give_keyword": {"target": "self", "keyword": "ブロッカー"}},
                {"power_pump": {"target": "self", "amount": 1000, "duration": "static"}},
            ],
        }]),
    }
    leader = leader_card
    p1 = Player(name="P0", leader=InPlay.of(leader, sickness=False))
    p2 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1.deck = [repo.get("OP01-013")] * 30
    p2.deck = [repo.get("OP01-013")] * 30
    state = GameState(
        players=[p1, p2],
        phase=Phase.MAIN,
        rng=random.Random(1),
        effects_overlay=overlay,
    )
    # opp ターン (= p1 にとっての相手のターン) にするため turn_player を p2 に
    state.turn_player_idx = 1
    me = state.players[0]
    opp = state.players[1]
    chara = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters.append(chara)
    base_power = chara.card.power

    evaluate_static_effects(state, overlay)
    # 静的ブロッカー獲得 + パワー +1000
    assert chara.is_blocker_now is True
    assert chara.power == base_power + 1000


def test_borsalino_static_disabled_during_self_turn():
    """自ターン中は opp_turn=False のため 静的ブロッカー獲得しない。"""
    repo = _repo()
    leader_card = None
    for c in repo._by_id.values():
        if c.category == Category.LEADER and "海軍" in c.features:
            leader_card = c
            break
    assert leader_card is not None

    overlay = {
        "OP01-013": _bundle("OP01-013", [{
            "when": "on_attached_don",
            "n": 0,
            "if": {"opp_turn": True, "leader_feature": "海軍"},
            "do": [
                {"give_keyword": {"target": "self", "keyword": "ブロッカー"}},
                {"power_pump": {"target": "self", "amount": 1000, "duration": "static"}},
            ],
        }]),
    }
    p1 = Player(name="P0", leader=InPlay.of(leader_card, sickness=False))
    p2 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1.deck = [repo.get("OP01-013")] * 30
    p2.deck = [repo.get("OP01-013")] * 30
    state = GameState(
        players=[p1, p2],
        phase=Phase.MAIN,
        rng=random.Random(1),
        effects_overlay=overlay,
    )
    # 自分のターン (= p1)
    state.turn_player_idx = 0
    me = state.players[0]
    chara = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters.append(chara)
    base_power = chara.card.power

    evaluate_static_effects(state, overlay)
    # 自ターンでは静的効果 OFF
    # card 自体が blocker でなければ ブロッカー扱いなし
    if not chara.card.is_blocker:
        assert chara.is_blocker_now is False
    assert chara.power == base_power
