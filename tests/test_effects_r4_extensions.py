# -*- coding: utf-8 -*-
"""R4 効果 DSL 拡張テスト (sev>=8 + 頻出 _unimplemented 解消用)。

R4 で追加された engine 拡張のスモークテスト。
1. attach_don / attach_rested_don の per_target (= 「全員に 1 枚ずつ」)
2. reveal_hand_with_filter cost (実消費なし) for activate_main
3. reveal_hand_with_filter cost in optional_cost_then (on_play 等)
4. mill_self_life_to_trash cost in optional_cost_then
5. play_from_hand_named_set primitive (= 「N1 と N2 と N3 それぞれ 1 枚ずつ」)
6. reveal_top_then primitive (= 「デッキ上 N 公開し、 filter 一致なら 効果X、 その後 (上/下/トラッシュ)」)
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import CardDef, Category, GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    CardEffectBundle,
    execute_effect,
    _can_pay_activate_cost,
    fire_activate_main,
    _matches_filter,
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


# --------------------------------------------------------------------------- #
# 1. attach_don per_target
# --------------------------------------------------------------------------- #
def test_attach_don_per_target_distributes_evenly():
    """per_target=true: leader + 各キャラに 1 枚ずつ付与 (= OP14-105 ゴルゴン三姉妹)。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    # 自キャラ 2 体を場へ
    chara_card = repo.get("OP01-013")
    me.characters.append(InPlay.of(chara_card, sickness=False))
    me.characters.append(InPlay.of(chara_card, sickness=False))
    me.don_active = 5
    # leader + 2 chara = 3 体に 1 枚ずつ → 3 枚消費
    execute_effect(
        {"attach_don": {"target": "all_self_team", "count": 1, "per_target": True}},
        state, me, opp, None,
    )
    assert me.don_active == 2
    assert me.leader.attached_dons == 1
    assert me.characters[0].attached_dons == 1
    assert me.characters[1].attached_dons == 1


def test_attach_rested_don_per_target_partial_when_low_supply():
    """per_target=true: 残ドン不足の時、 先頭から付与し残りは未付与。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    chara_card = repo.get("OP01-013")
    me.characters.append(InPlay.of(chara_card, sickness=False))
    me.characters.append(InPlay.of(chara_card, sickness=False))
    me.don_rested = 2  # 不足: 3 体に 1 枚ずつ → leader + chara0 のみ
    execute_effect(
        {"attach_rested_don": {"target": "all_self_team", "count": 1, "per_target": True}},
        state, me, opp, None,
    )
    assert me.don_rested == 0
    # leader と最初のキャラのみ +1
    assert me.leader.attached_dons == 1
    assert me.characters[0].attached_dons == 1
    assert me.characters[1].attached_dons == 0


def test_attach_don_backward_compat_no_per_target():
    """per_target なしのときは従来通り (1 体目に全部付与)。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    me.don_active = 5
    execute_effect(
        {"attach_don": {"target": "self_leader", "count": 2}},
        state, me, opp, None,
    )
    assert me.don_active == 3
    assert me.leader.attached_dons == 2


# --------------------------------------------------------------------------- #
# 2. reveal_hand_with_filter cost for activate_main (実消費なし)
# --------------------------------------------------------------------------- #
def test_reveal_hand_with_filter_payability_check_pass():
    """手札に filter 一致が count 以上 → 支払可。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    # 手札に 「アマゾン・リリー」 特徴を含むカード探す → 簡易: 任意の 3 枚を入れる
    # cards.json から特徴持ちを 1 枚探す
    target_feat = "アマゾン・リリー"
    cands = [c for c in repo._by_id.values() if target_feat in c.features]
    assert cands, f"特徴 {target_feat} を持つカードが db に存在しない"
    me.hand = [cands[0], cands[0], cands[0]]
    cost = {
        "reveal_hand_with_filter": {
            "filter": {"feature": target_feat},
            "count": 3,
        }
    }
    assert _can_pay_activate_cost(state, me, me.leader, cost) is True


def test_reveal_hand_with_filter_payability_check_fail():
    """手札に filter 一致が count 未満 → 支払不可。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    # 手札 1 枚しか持たない (count=3 要求)
    target_feat = "アマゾン・リリー"
    cands = [c for c in repo._by_id.values() if target_feat in c.features]
    assert cands
    me.hand = [cands[0]]
    cost = {
        "reveal_hand_with_filter": {
            "filter": {"feature": target_feat},
            "count": 3,
        }
    }
    assert _can_pay_activate_cost(state, me, me.leader, cost) is False


def test_reveal_hand_with_filter_does_not_consume_hand():
    """fire_activate_main で reveal_hand_with_filter を含む cost を払っても 手札数は減らない。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    me.don_active = 3
    target_feat = "アマゾン・リリー"
    cands = [c for c in repo._by_id.values() if target_feat in c.features]
    assert cands
    me.hand = [cands[0], cands[0], cands[0]]
    hand_before = len(me.hand)

    leader_id = state.players[0].leader.card.card_id
    eff = {
        "when": "activate_main",
        "cost": {
            "once_per_turn": True,
            "reveal_hand_with_filter": {
                "filter": {"feature": target_feat},
                "count": 3,
            },
        },
        "do": [
            {"attach_rested_don": {
                "target": "all_self_team", "count": 1, "per_target": True
            }},
        ],
    }
    bundle = CardEffectBundle(card_id=leader_id, effects=[eff])
    state.effects_overlay = {leader_id: bundle}

    # 払えるか?
    assert _can_pay_activate_cost(state, me, me.leader, eff["cost"]) is True
    me.don_rested = 1
    # 起動メイン発火
    fire_activate_main(state, me, opp, me.leader, eff)
    # 手札は減らない
    assert len(me.hand) == hand_before
    # 効果 (リーダーへ rested don 付与) は発動 (don_rested 1 → 0)
    assert me.don_rested == 0
    assert me.leader.attached_dons == 1


# --------------------------------------------------------------------------- #
# 3. reveal_hand_with_filter cost in optional_cost_then
# --------------------------------------------------------------------------- #
def test_optional_cost_then_with_reveal_hand_with_filter():
    """optional_cost_then.cost で reveal_hand_with_filter (公開のみ) → 手札維持 + 効果発動。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    # 手札に「イベント」を 2 枚 (OP12-003 クロッカス相当)
    event_cands = [
        c for c in repo._by_id.values() if c.category == Category.EVENT
    ]
    assert len(event_cands) >= 2
    me.hand = [event_cands[0], event_cands[1]]
    hand_before = len(me.hand)
    me.don_active = 0

    execute_effect(
        {
            "optional_cost_then": {
                "cost": [
                    {"reveal_hand_with_filter": {
                        "filter": {"category": "EVENT"},
                        "count": 2,
                    }}
                ],
                "effect": [
                    {"draw": 1},
                ],
            }
        },
        state, me, opp, None,
    )
    # 公開のみ → 手札は減っていない (ドロー 1 → 手札 +1)
    assert len(me.hand) == hand_before + 1


def test_optional_cost_then_reveal_hand_with_filter_insufficient_skips():
    """手札 filter 一致が count 未満 → cost 不能 → effect 不発 (公式 4-10)。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    # 手札 0 枚 (= filter 一致なし)
    me.hand = []
    deck_before = len(me.deck)

    execute_effect(
        {
            "optional_cost_then": {
                "cost": [
                    {"reveal_hand_with_filter": {
                        "filter": {"category": "EVENT"},
                        "count": 2,
                    }}
                ],
                "effect": [
                    {"draw": 1},
                ],
            }
        },
        state, me, opp, None,
    )
    # 効果は発動していない
    assert len(me.deck) == deck_before
    assert len(me.hand) == 0


# --------------------------------------------------------------------------- #
# 4. mill_self_life_to_trash cost in optional_cost_then
# --------------------------------------------------------------------------- #
def test_optional_cost_then_with_mill_self_life_to_trash():
    """ST13-005 相当: ライフ 1 枚をトラッシュへ → 効果発動。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    # ライフを 4 枚, 手札 1 枚, 残デッキ
    life_card = repo.get("OP01-013")
    me.life = [life_card] * 4
    me.hand = [life_card]

    life_before = len(me.life)
    trash_before = len(me.trash)
    hand_before = len(me.hand)

    execute_effect(
        {
            "optional_cost_then": {
                "cost": [
                    {"mill_self_life_to_trash": 1}
                ],
                "effect": [
                    {"draw": 1},
                ],
            }
        },
        state, me, opp, None,
    )
    # ライフ -1 / トラッシュ +1 / ドロー で 手札 +1
    assert len(me.life) == life_before - 1
    assert len(me.trash) == trash_before + 1
    assert len(me.hand) == hand_before + 1


def test_optional_cost_then_mill_self_life_to_trash_insufficient():
    """ライフ 0 枚 → 支払不能 → 不発。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    me.life = []
    hand_before = len(me.hand)

    execute_effect(
        {
            "optional_cost_then": {
                "cost": [
                    {"mill_self_life_to_trash": 1}
                ],
                "effect": [
                    {"draw": 1},
                ],
            }
        },
        state, me, opp, None,
    )
    # 効果不発
    assert len(me.hand) == hand_before


# --------------------------------------------------------------------------- #
# 5. play_from_hand_named_set primitive
# --------------------------------------------------------------------------- #
def test_play_from_hand_named_set_plays_each_once():
    """ST13-006 相当: 手札の N1 と N2 と N3 をそれぞれ 1 枚ずつ登場 (各 name 重複可)。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    # 同名複数のテスト用カードを 3 種類 探す (cost に依存しない汎用テスト)
    cands_by_name: dict[str, list] = {}
    for c in repo._by_id.values():
        if c.category != Category.CHARACTER:
            continue
        cands_by_name.setdefault(c.name, []).append(c)
    # 3 つ別名のキャラを取得
    names_picked: list[str] = []
    cards_picked: list = []
    for name, cs in cands_by_name.items():
        if len(names_picked) >= 3:
            break
        names_picked.append(name)
        cards_picked.append(cs[0])
    assert len(names_picked) == 3

    # 各キャラを手札に + 同名2枚目もテスト
    me.hand = list(cards_picked) + [cards_picked[0]]  # name[0] が 2 枚

    chars_before = len(me.characters)
    execute_effect(
        {"play_from_hand_named_set": {
            "names": names_picked,
        }},
        state, me, opp, None,
    )
    # 各 name 1 枚だけ登場 → 3 体
    assert len(me.characters) == chars_before + 3
    # name[0] の 2 枚目は手札に残る
    assert any(c.name == names_picked[0] for c in me.hand)


def test_play_from_hand_named_set_partial_when_some_missing():
    """指定 name の一部が手札にない場合、 手札にあるものだけ登場 (公式 「~まで」)。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    cands = [c for c in repo._by_id.values() if c.category == Category.CHARACTER]
    assert len(cands) >= 2
    # name[0] のみ手札にある
    me.hand = [cands[0]]
    target_names = [cands[0].name, "存在しない名前A", "存在しない名前B"]
    chars_before = len(me.characters)
    execute_effect(
        {"play_from_hand_named_set": {"names": target_names}},
        state, me, opp, None,
    )
    assert len(me.characters) == chars_before + 1
    assert me.characters[-1].card.name == cands[0].name


# --------------------------------------------------------------------------- #
# 6. reveal_top_then primitive
# --------------------------------------------------------------------------- #
def test_reveal_top_then_match_fires_then():
    """ST17-001 相当: デッキ上 1 枚公開 → 王下七武海持つ場合 then 発動。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    # 王下七武海特徴のカードを探す
    target_feat = "王下七武海"
    matches = [c for c in repo._by_id.values() if target_feat in c.features]
    assert matches, "王下七武海 特徴を持つカードが db に存在しない"
    # デッキ先頭に target カード, 残り通常
    me.deck = [matches[0]] + [repo.get("OP01-013")] * 5
    deck_before = len(me.deck)
    hand_before = len(me.hand)

    execute_effect(
        {"reveal_top_then": {
            "depth": 1,
            "filter": {"feature": target_feat},
            "then": [{"draw": 2}],
            "rest_remain": "top",
        }},
        state, me, opp, None,
    )
    # 公開した 1 枚は再度 デッキ上に戻る → deck 数同じ
    # draw 2 だけ手札 +2 (= 公開されたカード自身も含まれる場合あるが top に戻したので draw 対象)
    # 公開: pop して then 発動、 その後 top に戻す。
    # draw 2 のあとデッキは元と同じ枚数 - 2 (draw した分)。
    # rest_remain=top → 公開分 1 枚を上に戻すので net deck = deck_before - 2 (draw 分)
    assert len(me.hand) == hand_before + 2
    assert len(me.deck) == deck_before - 2


def test_reveal_top_then_no_match_skips_then():
    """公開したカードが filter 不一致 → then 不発 / else 発動 (else 指定時)。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    # デッキ先頭に絶対 マッチしない カード
    me.deck = [repo.get("OP01-013")] * 5
    deck_before = len(me.deck)
    hand_before = len(me.hand)
    execute_effect(
        {"reveal_top_then": {
            "depth": 1,
            "filter": {"feature": "存在しない特徴ZZZ"},
            "then": [{"draw": 2}],
            "else": [{"draw": 1}],
            "rest_remain": "bottom",
        }},
        state, me, opp, None,
    )
    # else 発動 → draw 1
    assert len(me.hand) == hand_before + 1
    # 公開分はデッキ底に戻る → deck 数: -1 (draw) -1 (公開→底→そのまま) +1 (戻り) = -1
    assert len(me.deck) == deck_before - 1


def test_reveal_top_then_empty_deck_returns_false():
    """デッキ空 → reveal 不能 → False (公式 4-10 不発)。"""
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    opp = state.players[1]
    me.deck = []
    hand_before = len(me.hand)
    result = execute_effect(
        {"reveal_top_then": {
            "depth": 1,
            "filter": {},
            "then": [{"draw": 1}],
        }},
        state, me, opp, None,
    )
    # then 不発: 手札変化なし
    assert len(me.hand) == hand_before
    # 戻り False
    assert result is False
