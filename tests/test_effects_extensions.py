# -*- coding: utf-8 -*-
"""効果 DSL 拡張ユニットテスト (X2: 条件評価器 + X3: プリミティブ拡張)。

X2 追加条件:
- don_count_ge / don_count_le (alias of self_don_ge / self_don_le)
- opp_don_count_ge / opp_don_count_le (相手のドン合算)
- opp_leader_feature (leader_feature の opp 版)
- once_per_turn (top-level effect spec の【ターン1回】 guard)

X3 追加プリミティブ:
- trash_to_deck (trash → deck top/bottom + filter + shuffle)
- play_from_hand_choice (手札から filter 一致 1 枚を選んで登場)
- replace_ko 分岐 (= replace_ko_complex)
- look_top_reorder 拡張 (split: match を一方向、 残りを他方向へ)
- add_don_active (add_don の alias 確認)
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import eval_condition, execute_effect

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _make_state(repo, leader_id, opp_leader_id="OP01-001"):
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
# don_count_ge / don_count_le (自分)
# --------------------------------------------------------------------------- #
def test_don_count_ge_alias():
    """don_count_ge: 自分のドン!! 合算 (active+rested+attached) ≥ N"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    me.don_active = 3
    me.don_rested = 2
    # 合計 5
    assert eval_condition({"don_count_ge": 5}, state, me) is True
    assert eval_condition({"don_count_ge": 6}, state, me) is False
    # 既存 self_don_ge と一致
    assert eval_condition({"self_don_ge": 5}, state, me) is True


def test_don_count_le_alias():
    """don_count_le: 自分のドン!! 合算 ≤ N"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    me.don_active = 4
    me.don_rested = 0
    assert eval_condition({"don_count_le": 4}, state, me) is True
    assert eval_condition({"don_count_le": 3}, state, me) is False


def test_don_count_includes_attached():
    """don_count_ge は leader / character 付与ドンも合算する"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    me.don_active = 1
    me.don_rested = 1
    me.leader.attached_dons = 2
    me.characters.append(InPlay.of(repo.get("OP01-013"), sickness=False))
    me.characters[0].attached_dons = 3
    # 合計 7
    assert eval_condition({"don_count_ge": 7}, state, me) is True
    assert eval_condition({"don_count_ge": 8}, state, me) is False


# --------------------------------------------------------------------------- #
# opp_don_count_ge / opp_don_count_le (相手)
# --------------------------------------------------------------------------- #
def test_opp_don_count_ge():
    """opp_don_count_ge: 相手のドン合算 ≥ N"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    opp = state.players[1]
    opp.don_active = 2
    opp.don_rested = 3
    assert eval_condition({"opp_don_count_ge": 5}, state, me) is True
    assert eval_condition({"opp_don_count_ge": 6}, state, me) is False


def test_opp_don_count_le():
    """opp_don_count_le: 相手のドン合算 ≤ N"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    opp = state.players[1]
    opp.don_active = 1
    opp.don_rested = 1
    assert eval_condition({"opp_don_count_le": 2}, state, me) is True
    assert eval_condition({"opp_don_count_le": 1}, state, me) is False


# --------------------------------------------------------------------------- #
# opp_leader_feature
# --------------------------------------------------------------------------- #
def test_opp_leader_feature_str():
    """opp_leader_feature: 相手リーダーが指定特徴を持つか (str)"""
    repo = _repo()
    state = _make_state(repo, "OP01-003", opp_leader_id="OP01-001")
    me = state.players[0]
    opp = state.players[1]
    feats = opp.leader.card.features
    assert len(feats) > 0
    chosen = feats[0]
    assert eval_condition({"opp_leader_feature": chosen}, state, me) is True
    assert eval_condition({"opp_leader_feature": "存在しない特徴_XYZ"}, state, me) is False


def test_opp_leader_feature_list():
    """opp_leader_feature: list (OR) でいずれかの特徴を持つか"""
    repo = _repo()
    state = _make_state(repo, "OP01-003", opp_leader_id="OP01-001")
    me = state.players[0]
    opp = state.players[1]
    chosen = opp.leader.card.features[0]
    assert eval_condition(
        {"opp_leader_feature": [chosen, "存在しない_XYZ"]}, state, me
    ) is True
    assert eval_condition(
        {"opp_leader_feature": ["存在しない_A", "存在しない_B"]}, state, me
    ) is False


# --------------------------------------------------------------------------- #
# once_per_turn guard (top-level effect spec)
# --------------------------------------------------------------------------- #
def _make_overlay_bundle(card_id, effects):
    """簡易 CardEffectBundle ファクトリ (テスト用)。"""
    from engine.effects import CardEffectBundle
    return CardEffectBundle(card_id=card_id, effects=effects)


def test_once_per_turn_blocks_second_fire():
    """once_per_turn=True は instance 単位で 1 回 (= 公式 SKILL 7-5-3 / 10-2-13-4
    「同名カードが複数枚あっても各 1 回」)。 同一 instance の 2 回目は blocked、
    別個体 (= 別 instance) は 独立して 各 1 回 発動可。"""
    from engine.effects import trigger_on_play
    repo = _repo()
    overlay = {
        "OP01-013": _make_overlay_bundle("OP01-013", [{
            "when": "on_play",
            "once_per_turn": True,
            "do": [{"draw": 1}],
        }]),
    }
    state = _make_state(repo, "OP01-003")
    state.effects_overlay = overlay
    me = state.players[0]
    opp = state.players[1]
    hand_before = len(me.hand)
    # instance A: 発動
    ip1 = InPlay.of(repo.get("OP01-013"), sickness=True)
    me.characters.append(ip1)
    trigger_on_play(state, me, opp, ip1, overlay)
    assert len(me.hand) == hand_before + 1
    # 同一 instance A の 2 回目: once_per_turn でブロック
    trigger_on_play(state, me, opp, ip1, overlay)
    assert len(me.hand) == hand_before + 1, "同一 instance の 2 回目は blocked"
    # 別個体 instance B (同 card_id): 公式「各 1 回」 で 独立 発動可
    ip2 = InPlay.of(repo.get("OP01-013"), sickness=True)
    me.characters.append(ip2)
    trigger_on_play(state, me, opp, ip2, overlay)
    assert len(me.hand) == hand_before + 2, "別個体は独立して 各 1 回 発動可 (公式 7-5-3)"


def test_once_per_turn_explicit_key_shared():
    """once_per_turn=<str>: 異なる効果でも同一キーを共有でき、 排他制御できる。"""
    from engine.effects import trigger_on_play
    repo = _repo()
    overlay = {
        "OP01-013": _make_overlay_bundle("OP01-013", [
            {
                "when": "on_play",
                "once_per_turn": "shared_key_X",
                "do": [{"draw": 1}],
            },
            {
                "when": "on_play",
                "once_per_turn": "shared_key_X",
                "do": [{"draw": 2}],
            },
        ]),
    }
    state = _make_state(repo, "OP01-003")
    state.effects_overlay = overlay
    me = state.players[0]
    opp = state.players[1]
    hand_before = len(me.hand)
    ip = InPlay.of(repo.get("OP01-013"), sickness=True)
    me.characters.append(ip)
    trigger_on_play(state, me, opp, ip, overlay)
    # 同キーなので片方しか発火しない (draw 1 のみ)
    assert len(me.hand) == hand_before + 1


def test_once_per_turn_resets_on_refresh():
    """once_per_turn のフラグは REFRESH 時にクリアされる。"""
    from engine.effects import trigger_on_play
    repo = _repo()
    overlay = {
        "OP01-013": _make_overlay_bundle("OP01-013", [{
            "when": "on_play",
            "once_per_turn": True,
            "do": [{"draw": 1}],
        }]),
    }
    state = _make_state(repo, "OP01-003")
    state.effects_overlay = overlay
    me = state.players[0]
    opp = state.players[1]
    hand_before = len(me.hand)
    ip1 = InPlay.of(repo.get("OP01-013"), sickness=True)
    me.characters.append(ip1)
    trigger_on_play(state, me, opp, ip1, overlay)
    assert me.once_per_turn_used, "発動後はフラグセット"
    # 直接 set をクリアして再発動を確認 (REFRESH 相当)
    me.once_per_turn_used.clear()
    ip2 = InPlay.of(repo.get("OP01-013"), sickness=True)
    me.characters.append(ip2)
    trigger_on_play(state, me, opp, ip2, overlay)
    assert len(me.hand) == hand_before + 2, "クリア後は再発動"


def test_once_per_turn_per_player_isolated():
    """once_per_turn のフラグはプレイヤー毎に独立。 相手の発動は自分に影響しない。"""
    from engine.effects import trigger_on_play
    repo = _repo()
    overlay = {
        "OP01-013": _make_overlay_bundle("OP01-013", [{
            "when": "on_play",
            "once_per_turn": True,
            "do": [{"draw": 1}],
        }]),
    }
    state = _make_state(repo, "OP01-003")
    state.effects_overlay = overlay
    me = state.players[0]
    opp = state.players[1]
    me_hand_before = len(me.hand)
    opp_hand_before = len(opp.hand)
    # me 側 instance で発動
    ip_me = InPlay.of(repo.get("OP01-013"), sickness=True)
    me.characters.append(ip_me)
    trigger_on_play(state, me, opp, ip_me, overlay)
    assert len(me.hand) == me_hand_before + 1
    # opp 側でも同カードを発動 (相手プレイヤーの instance は独立)
    ip_opp = InPlay.of(repo.get("OP01-013"), sickness=True)
    opp.characters.append(ip_opp)
    trigger_on_play(state, opp, me, ip_opp, overlay)
    assert len(opp.hand) == opp_hand_before + 1
    # 同一 instance ip_me の 2 回目は blocked (= per-instance 1 回)
    trigger_on_play(state, me, opp, ip_me, overlay)
    assert len(me.hand) == me_hand_before + 1, "同一 instance は使用済みのまま"


# --------------------------------------------------------------------------- #
# X3: trash_to_deck primitive
# --------------------------------------------------------------------------- #
def test_trash_to_deck_bottom_default():
    """trash_to_deck: 既定で trash → deck bottom (デッキ末尾) に N 枚"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    opp = state.players[1]
    me.trash = [repo.get("OP01-013"), repo.get("OP01-016")]
    me.deck = [repo.get("OP01-001")] * 3
    deck_len_before = len(me.deck)
    execute_effect(
        {"trash_to_deck": {"limit": 1, "filter": {}}},
        state, me, opp, None,
    )
    assert len(me.deck) == deck_len_before + 1
    assert len(me.trash) == 1
    # 戻ったカードは deck の末尾
    assert me.deck[-1].card_id in ("OP01-013", "OP01-016")


def test_trash_to_deck_top():
    """trash_to_deck: to='top' で deck 先頭に挿入"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    opp = state.players[1]
    target = repo.get("OP01-013")
    me.trash = [target]
    sentinel = repo.get("OP01-001")
    me.deck = [sentinel, sentinel, sentinel]
    execute_effect(
        {"trash_to_deck": {"limit": 1, "to": "top"}},
        state, me, opp, None,
    )
    # 先頭が trash から戻ったカード
    assert me.deck[0].card_id == "OP01-013"


def test_trash_to_deck_shuffle():
    """trash_to_deck: shuffle=True で戻した後シャッフル (deck 件数は同じ)"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    opp = state.players[1]
    me.trash = [repo.get("OP01-013")] * 3
    me.deck = [repo.get("OP01-001")] * 2
    execute_effect(
        {"trash_to_deck": {"limit": 3, "to": "bottom", "shuffle": True}},
        state, me, opp, None,
    )
    assert len(me.deck) == 5
    assert len(me.trash) == 0


def test_trash_to_deck_no_match_returns_false():
    """trash_to_deck: filter 一致 0 件で False (公式 4-10 「場合」 不発)"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    opp = state.players[1]
    me.trash = [repo.get("OP01-013")]
    deck_len_before = len(me.deck)
    trash_len_before = len(me.trash)
    result = execute_effect(
        {"trash_to_deck": {"limit": 1, "filter": {"feature": "存在しない_XYZ"}}},
        state, me, opp, None,
    )
    assert result is False
    assert len(me.deck) == deck_len_before  # 変化なし
    assert len(me.trash) == trash_len_before


def test_trash_to_deck_respects_limit():
    """trash_to_deck: limit を超えるカードは残す"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    opp = state.players[1]
    me.trash = [repo.get("OP01-013")] * 5
    me.deck = []
    execute_effect(
        {"trash_to_deck": {"limit": 2, "to": "bottom"}},
        state, me, opp, None,
    )
    assert len(me.deck) == 2
    assert len(me.trash) == 3


# --------------------------------------------------------------------------- #
# X3: play_from_hand_choice primitive
# --------------------------------------------------------------------------- #
def test_play_from_hand_choice_basic():
    """play_from_hand_choice: 手札から filter 一致のキャラ 1 枚を 0 コストで登場"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    opp = state.players[1]
    me.hand = [repo.get("OP01-013"), repo.get("OP01-016")]
    hand_before = len(me.hand)
    chara_before = len(me.characters)
    execute_effect(
        {"play_from_hand_choice": {"filter": {"cost_le": 5}, "limit": 1}},
        state, me, opp, None,
    )
    assert len(me.characters) == chara_before + 1
    assert len(me.hand) == hand_before - 1


def test_play_from_hand_choice_picks_highest_cost():
    """play_from_hand_choice: 複数候補があれば cost 降順で 1 枚を選ぶ (ヒューリスティック)"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    opp = state.players[1]
    # cost が異なる 2 種のキャラ
    low_cost = repo.get("OP01-016")  # cost 2
    high_cost = repo.get("OP01-013")  # cost 2 だが power 異なる
    me.hand = [low_cost, high_cost]
    execute_effect(
        {"play_from_hand_choice": {"filter": {}, "limit": 1}},
        state, me, opp, None,
    )
    assert len(me.characters) == 1
    # cost 同点なら power 高い方が選ばれる
    chosen = me.characters[0].card
    expected = max([low_cost, high_cost], key=lambda c: (c.cost, c.power))
    assert chosen.card_id == expected.card_id


def test_play_from_hand_choice_no_match_returns_false():
    """play_from_hand_choice: 一致なしなら False (場に変化なし)"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    opp = state.players[1]
    me.hand = [repo.get("OP01-013")]
    hand_before = len(me.hand)
    chara_before = len(me.characters)
    result = execute_effect(
        {"play_from_hand_choice": {"filter": {"feature": "存在しない_XYZ"}}},
        state, me, opp, None,
    )
    assert result is False
    assert len(me.characters) == chara_before
    assert len(me.hand) == hand_before


def test_play_from_hand_choice_rested():
    """play_from_hand_choice: rested=True なら登場時レスト"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    opp = state.players[1]
    me.hand = [repo.get("OP01-013")]
    execute_effect(
        {"play_from_hand_choice": {"filter": {}, "limit": 1, "rested": True}},
        state, me, opp, None,
    )
    assert len(me.characters) == 1
    assert me.characters[0].rested is True


def test_play_from_hand_choice_skips_events():
    """play_from_hand_choice: 既定 category=CHARACTER なのでイベントは選ばれない"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    opp = state.players[1]
    # OP01-013 はキャラ、 OP01-029 (ゴムゴムのジェットピストル) はイベント
    chara_card = repo.get("OP01-013")
    event_card = repo.get("OP01-029")
    me.hand = [event_card, chara_card]
    execute_effect(
        {"play_from_hand_choice": {"filter": {}, "limit": 1}},
        state, me, opp, None,
    )
    # キャラ 1 体のみ場に
    assert len(me.characters) == 1
    assert me.characters[0].card.card_id == chara_card.card_id


# --------------------------------------------------------------------------- #
# X3: replace_ko_complex primitive (条件分岐 replace_ko)
# --------------------------------------------------------------------------- #
def test_replace_ko_complex_first_match_wins():
    """replace_ko_complex: 上から順に if を評価し、 最初に True になった branch のみ実行"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")  # 麦わらの一味 リーダー
    me = state.players[0]
    opp = state.players[1]
    me.life = [repo.get("OP01-001")] * 3
    me.hand = []
    execute_effect(
        {"replace_ko_complex": {
            "branches": [
                {
                    "if": {"leader_feature": "麦わらの一味"},
                    "do": [{"life_to_hand": 1}],  # ライフ→手札
                },
                {
                    "if": {},
                    "do": [{"draw": 2}],  # フォールバック
                },
            ],
        }},
        state, me, opp, None,
    )
    # branch_a (life_to_hand) が選ばれた → ライフ 2 / 手札 1
    assert len(me.life) == 2
    assert len(me.hand) == 1


def test_replace_ko_complex_fallback_default():
    """replace_ko_complex: 最初の branch が不成立 → 次の (default) branch を実行"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    opp = state.players[1]
    me.life = [repo.get("OP01-001")] * 3
    me.hand = []
    execute_effect(
        {"replace_ko_complex": {
            "branches": [
                {
                    "if": {"leader_feature": "存在しない_XYZ"},
                    "do": [{"life_to_hand": 1}],
                },
                {
                    "if": {},  # default
                    "do": [{"draw": 2}],
                },
            ],
        }},
        state, me, opp, None,
    )
    # branch_b (draw 2) が選ばれた → ライフ 3 / 手札 2
    assert len(me.life) == 3
    assert len(me.hand) == 2


def test_replace_ko_complex_no_default_returns_false():
    """replace_ko_complex: どの branch も不成立で default も無い → False (不発)"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    opp = state.players[1]
    me.life = [repo.get("OP01-001")] * 3
    me.hand = []
    result = execute_effect(
        {"replace_ko_complex": {
            "branches": [
                {
                    "if": {"leader_feature": "存在しない_A"},
                    "do": [{"draw": 1}],
                },
                {
                    "if": {"leader_feature": "存在しない_B"},
                    "do": [{"draw": 1}],
                },
            ],
        }},
        state, me, opp, None,
    )
    assert result is False
    # 何も実行されず、 ライフ / 手札も変化なし
    assert len(me.life) == 3
    assert len(me.hand) == 0


# --------------------------------------------------------------------------- #
# X3: look_top_reorder 拡張 (split mode)
# --------------------------------------------------------------------------- #
def test_look_top_reorder_split_match_to_hand():
    """look_top_reorder split: match を hand、 remain を deck bottom"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    opp = state.players[1]
    # デッキ上 3 枚を意図的に配置: OP01-013 (cost 2) / OP01-016 (cost 2) / OP01-001 (リーダー)
    me.hand = []
    top1 = repo.get("OP01-013")
    top2 = repo.get("OP01-016")
    top3 = repo.get("OP01-001")
    me.deck = [top1, top2, top3] + me.deck
    hand_before = len(me.hand)
    deck_before = len(me.deck)
    execute_effect(
        {"look_top_reorder": {
            "depth": 3,
            "to": "split",
            "match_filter": {"category": "CHARACTER"},
            "match_to": "hand",
            "remain_to": "bottom",
        }},
        state, me, opp, None,
    )
    # CHARACTER 2 枚 (OP01-013/016) は手札へ、 OP01-001 (LEADER) は底へ
    assert len(me.hand) == hand_before + 2
    # デッキ枚数は変わらず (1 枚 deck → bottom 移動 + 2 枚 deck → hand 移動)
    # = (deck_before - 3) + 1 = deck_before - 2
    assert len(me.deck) == deck_before - 2


def test_look_top_reorder_split_match_to_trash():
    """look_top_reorder split: match を trash, remain を deck bottom"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    opp = state.players[1]
    me.deck = [repo.get("OP01-013")] * 3 + [repo.get("OP01-001")] * 2 + me.deck
    trash_before = len(me.trash)
    execute_effect(
        {"look_top_reorder": {
            "depth": 5,
            "to": "split",
            "match_filter": {"category": "CHARACTER"},
            "match_to": "trash",
            "remain_to": "bottom",
        }},
        state, me, opp, None,
    )
    assert len(me.trash) == trash_before + 3


def test_look_top_reorder_split_match_to_top():
    """look_top_reorder split: match を top (= deck 先頭), remain を bottom"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    opp = state.players[1]
    chara = repo.get("OP01-013")
    leader = repo.get("OP01-001")
    me.deck = [chara, leader, chara] + me.deck
    execute_effect(
        {"look_top_reorder": {
            "depth": 3,
            "to": "split",
            "match_filter": {"category": "CHARACTER"},
            "match_to": "top",
            "remain_to": "bottom",
        }},
        state, me, opp, None,
    )
    # 先頭 2 枚は chara (CHARACTER), 最後尾あたりに leader
    assert me.deck[0].card_id == chara.card_id
    assert me.deck[1].card_id == chara.card_id


def test_look_top_reorder_legacy_to_bottom_still_works():
    """既存 to='bottom' は壊れていない (regression check)"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    opp = state.players[1]
    a = repo.get("OP01-013")
    b = repo.get("OP01-016")
    me.deck = [a, b] + me.deck
    deck_before = len(me.deck)
    execute_effect(
        {"look_top_reorder": {"depth": 2, "to": "bottom"}},
        state, me, opp, None,
    )
    # 上 2 枚が底へ移動 (枚数不変)
    assert len(me.deck) == deck_before
    # 末尾 2 枚が a, b の順
    assert me.deck[-2].card_id == a.card_id
    assert me.deck[-1].card_id == b.card_id


# --------------------------------------------------------------------------- #
# X3: add_don_active alias (= add_don)
# --------------------------------------------------------------------------- #
def test_add_don_active_alias_basic():
    """add_don_active: add_don と同じくドンデッキから N 枚をアクティブで追加"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    opp = state.players[1]
    active_before = me.don_active
    rested_before = me.don_rested
    deck_before = me.don_remaining_in_deck
    execute_effect({"add_don_active": 2}, state, me, opp, None)
    assert me.don_active == active_before + 2
    assert me.don_rested == rested_before, "レスト側は変化しない"
    assert me.don_remaining_in_deck == deck_before - 2


def test_add_don_vs_add_rested_don_distinct():
    """add_don (アクティブ) と add_rested_don (レスト) は別ストリーム"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    opp = state.players[1]
    a_before = me.don_active
    r_before = me.don_rested
    execute_effect({"add_don": 1}, state, me, opp, None)
    execute_effect({"add_rested_don": 1}, state, me, opp, None)
    assert me.don_active == a_before + 1
    assert me.don_rested == r_before + 1


def test_add_don_active_respects_remaining_in_deck():
    """add_don_active: ドンデッキ残量を超えて追加できない"""
    repo = _repo()
    state = _make_state(repo, "OP01-003")
    me = state.players[0]
    opp = state.players[1]
    me.don_remaining_in_deck = 1
    me.don_active = 0
    execute_effect({"add_don_active": 5}, state, me, opp, None)
    # 残量 1 のみ追加
    assert me.don_active == 1
    assert me.don_remaining_in_deck == 0
