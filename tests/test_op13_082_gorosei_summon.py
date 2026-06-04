# -*- coding: utf-8 -*-
"""OP13-082 五老星 起動メイン (= トラッシュから五老星5体登場) の regression。

公式: 「自分のトラッシュからパワー5000の**カード名の異なる**特徴《五老星》を持つ
キャラカード5枚までを、登場させる。」

bug (2026-06-04 修正前): play_from_trash の **人間 pick path** が unique_name を
enforce しておらず、 modal で同名の五老星を複数選ぶと **重複登場できてしまった**
(= AI path のみ enforce していた)。 また OP13-082 は速攻を付与しないので、 登場キャラは
召喚酔い (= 当ターン攻撃不可) でなければならない。
"""
from __future__ import annotations

from engine.effects import execute_effect

import tests.test_effects as T


def _setup():
    repo, overlay = T._repo(), T._overlay()
    state = T._make_state(repo, "OP01-001", overlay=overlay)
    me, opp = state.players[0], state.players[1]
    state.turn_number = 5
    me.characters = []
    # トラッシュ: 同名 (OP13-080) 2 枚 + 別名 2 枚 (= 全て power5000 五老星)
    me.trash = [
        repo.get("OP13-080"),  # イーザンバロン
        repo.get("OP13-080"),  # イーザンバロン (同名 dup)
        repo.get("OP13-083"),  # サターン
        repo.get("OP13-089"),  # ウォーキュリー
    ]
    return state, me, opp, repo


def test_gorosei_summon_no_duplicate_names_human_pick():
    """人間 pick (= _picks_idx) で同名を複数選んでも、 重複名は登場しない。"""
    state, me, opp, repo = _setup()
    spec = {
        "filter": {"feature": "五老星", "power_eq": 5000, "category": "CHARACTER"},
        "limit": 5,
        "unique_name": True,
        "_picks_idx": [0, 1, 2, 3],  # 同名(0,1) を含めて全部選ぶ
    }
    execute_effect({"play_from_trash": spec}, state, me, opp, None)

    names = [ip.card.name for ip in me.characters]
    assert len(names) == len(set(names)), f"同名が重複登場した: {names}"
    # 同名 2 枚 + 別名 2 枚 → 登場は 3 種 (イーザンバロン1 + サターン + ウォーキュリー)
    assert len(me.characters) == 3, f"登場数が想定外: {len(me.characters)} ({names})"


def test_summoned_conditional_rush_applies_via_human_modal():
    """人間 modal 解決 (resolve_pending_choice) で召喚した OP13-080 イーザンバロンに、
    自トラッシュ7枚以上の条件付き【速攻】が即反映される (= 召喚後に静的効果が再計算される)。

    bug (2026-06-04 修正前): apply_action は finally で _recompute_static するが、 人間の
    play_from_trash は modal 解決の外で召喚されるため再計算されず、 トラッシュ7+でも
    is_rush_now=False のままで「速攻なのに攻撃できない」 状態だった。
    """
    from engine.effects import resolve_pending_choice
    repo, overlay = T._repo(), T._overlay()
    state = T._make_state(repo, "OP13-079", overlay=overlay)  # leader イム
    me = state.players[0]
    state.turn_player_idx = 0
    state.turn_number = 6
    me.characters = []
    # トラッシュ: 五老星3 (on_play 無し) + filler 8 = 11 → 召喚3後 = 8 (≥7 で速攻条件)
    gorosei = ["OP13-080", "OP13-089", "OP13-084"]  # イーザンバロン/ウォーキュリー/ピーター
    me.trash = [repo.get(c) for c in gorosei] + [repo.get("OP13-096")] * 8

    # play_from_trash_pick modal を立てて 人間 が 3 体選ぶ → resolve
    state.pending_choice = {
        "kind": "play_from_trash_pick",
        "candidates": [
            {"trash_idx": i, "card_id": me.trash[i].card_id, "name": me.trash[i].name}
            for i in range(3)
        ],
        "primitive_value": {
            "filter": {"feature": "五老星", "power_eq": 5000, "category": "CHARACTER"},
            "limit": 5, "unique_name": True,
        },
        "source_iid": None,
    }
    resolve_pending_choice(state, [0, 1, 2])  # 3 体 召喚

    ez = next((ip for ip in me.characters if ip.card.card_id == "OP13-080"), None)
    assert ez is not None, "イーザンバロンが召喚されていない"
    assert len(me.trash) >= 7, f"トラッシュ {len(me.trash)} 枚 (<7 だと速攻条件外でテスト不成立)"
    # ⭐ 手動 recompute なしで 速攻 が 付いている (= resolve_pending_choice が再計算)
    assert ez.is_rush_now, "召喚後にトラッシュ7+でも速攻が付いていない (静的効果 未再計算)"
    # 速攻なので 召喚酔いでも 攻撃可能
    assert (not ez.summoning_sickness) or ez.is_rush_now


def test_gorosei_summoned_have_summoning_sickness():
    """OP13-082 は速攻を付与しない → 登場キャラは召喚酔い (= 当ターン攻撃不可)。"""
    state, me, opp, repo = _setup()
    spec = {
        "filter": {"feature": "五老星", "power_eq": 5000, "category": "CHARACTER"},
        "limit": 5,
        "unique_name": True,
        "_picks_idx": [0, 2, 3],
    }
    execute_effect({"play_from_trash": spec}, state, me, opp, None)
    assert me.characters, "1 体も登場していない"
    for ip in me.characters:
        assert ip.summoning_sickness, f"{ip.card.name} が召喚酔いでない (= 誤って速攻)"
        assert not ip.is_rush_now, f"{ip.card.name} が速攻を持っている (= 誤付与)"
