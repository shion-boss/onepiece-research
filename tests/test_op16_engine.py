# -*- coding: utf-8 -*-
"""OP16 取り込みで追加した engine 拡張の behavior test。

新規 condition / target / primitive / トリガー heuristic が、 正しい対象・数量・
条件 false で不発、 を満たすことを確認する (= 公式テキスト忠実主義のゲート)。
"""
from __future__ import annotations

import json
from pathlib import Path

from engine.core import Category, GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    resolve_triggers,
    eval_condition,
    evaluate_static_effects,
    execute_effect,
    load_effect_overlay,
    trigger_on_ko,
)

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _raw():
    return json.load(open(ROOT / "db" / "cards.json", encoding="utf-8"))


def _state(repo, overlay, l0="OP01-001", l1="OP01-001", turn=0):
    p0 = Player(name="P0", leader=InPlay.of(repo.get(l0), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(l1), sickness=False))
    s = GameState(players=[p0, p1])
    s.turn_player_idx = turn
    s.phase = Phase.MAIN
    s.effects_overlay = overlay
    return s, p0, p1


def test_self_inplay_cost_ge_reads_current_cost():
    """OP16-084: self_inplay_cost_ge は base_cost (= コスト修正込み) で判定。
    しのぶ OP16-087 の cost_minus -20 (= コスト+20) を受けて 20 以上になる。"""
    repo, overlay = _repo(), _overlay()
    s, p0, p1 = _state(repo, overlay)
    momo = InPlay.of(repo.get("OP16-084"))  # 印刷コスト 5
    p0.characters = [momo]
    assert not eval_condition({"self_inplay_cost_ge": 20}, s, p0, momo)
    execute_effect(
        {"cost_minus": {"target": {"type": "all_self_chara_filtered",
                                    "filter": {"name": "光月モモの助"}, "limit": 1},
                        "amount": -20, "duration": "turn"}},
        s, p0, p1, None,
    )
    assert momo.base_cost == momo.card.cost + 20
    assert eval_condition({"self_inplay_cost_ge": 20}, s, p0, momo)


def test_leader_name_contains():
    """OP16-015: leader_name_contains は部分一致 + D/Ｄ 正規化。"""
    repo, overlay = _repo(), _overlay()
    # エース を含むリーダー名 を探す
    ace_leaders = [c["card_id"] for c in _raw()
                   if c["category"] == "LEADER" and "エース" in c["name"]]
    if not ace_leaders:
        return  # 環境にエースリーダーが無ければ skip
    s, p0, p1 = _state(repo, overlay, l0=ace_leaders[0])
    assert eval_condition({"leader_name_contains": "エース"}, s, p0, None)
    s2, q0, q1 = _state(repo, overlay, l0="OP01-001")  # モンキー・D・ルフィ
    assert not eval_condition({"leader_name_contains": "エース"}, s2, q0, None)


def test_opp_chara_ko_this_turn_counter():
    """OP16-100: 相手キャラ KO で opp 側 counter が増え、 条件 True。 未 KO は False。"""
    repo, overlay = _repo(), _overlay()
    s, p0, p1 = _state(repo, overlay)
    assert not eval_condition({"opp_chara_ko_this_turn": True}, s, p0, None)
    c1 = next(c["card_id"] for c in _raw() if c["category"] == "CHARACTER")
    victim = InPlay.of(repo.get(c1))
    p1.characters = [victim]
    p1.trash = []
    trigger_on_ko(s, p1, p0, victim.card, overlay, by_opp_effect=True)
    resolve_triggers(s)  # KO グループは enqueue のみ = 実経路と同じくここでドレイン
    assert p1.chara_ko_taken_this_turn >= 1
    assert eval_condition({"opp_chara_ko_this_turn": True}, s, p0, None)  # me=p0 視点


def test_self_distinct_name_count_filtered_ge():
    """OP16-038: 「カード名の異なる」 数で判定 (= 同名は1としてカウント)。"""
    repo, overlay = _repo(), _overlay()
    s, p0, p1 = _state(repo, overlay)
    seen, picks = set(), []
    for c in _raw():
        cd = repo.get(c["card_id"])
        if (cd.category.value == "CHARACTER"
                and any("インペルダウン" in f for f in cd.features)
                and cd.name not in seen):
            seen.add(cd.name)
            picks.append(c["card_id"])
        if len(picks) >= 5:
            break
    assert len(picks) >= 5, "テスト前提: 異名インペルダウン5枚"
    p0.characters = [InPlay.of(repo.get(x)) for x in picks]
    spec = {"self_distinct_name_count_filtered_ge": {"filter": {"feature": "インペルダウン"}, "count": 5}}
    assert eval_condition(spec, s, p0, None)
    p0.characters = [InPlay.of(repo.get(x)) for x in picks[:4]]
    assert not eval_condition(spec, s, p0, None)


def test_self_chara_filtered_count_ge_current_power():
    """OP16-005: filter の current_power_ge は InPlay の現在パワーで判定。"""
    repo, overlay = _repo(), _overlay()
    s, p0, p1 = _state(repo, overlay)
    wb = next(c["card_id"] for c in _raw()
              if repo.get(c["card_id"]).category.value == "CHARACTER"
              and any("白ひげ海賊団" in f for f in repo.get(c["card_id"]).features)
              and (repo.get(c["card_id"]).power or 0) >= 8000)
    p0.characters = [InPlay.of(repo.get(wb))]
    spec = {"self_chara_filtered_count_ge": {
        "filter": {"feature_contains": "白ひげ海賊団", "current_power_ge": 8000}, "count": 1}}
    assert eval_condition(spec, s, p0, None)
    spec_hi = {"self_chara_filtered_count_ge": {
        "filter": {"feature_contains": "白ひげ海賊団", "current_power_ge": 99000}, "count": 1}}
    assert not eval_condition(spec_hi, s, p0, None)


def test_power_pump_self_distinct_chara_name_count():
    """OP16-034: カード名の異なるキャラ1枚につき +1000 (= self target)。"""
    repo, overlay = _repo(), _overlay()
    s, p0, p1 = _state(repo, overlay)
    luffy = InPlay.of(repo.get("OP16-034"))
    luffy.attached_dons = 1
    # 異名キャラ 3 体 (luffy 含む)
    others = [c["card_id"] for c in _raw()
              if repo.get(c["card_id"]).category.value == "CHARACTER"
              and repo.get(c["card_id"]).name not in ("モンキー・Ｄ・ルフィ", "モンキー・D・ルフィ")][:2]
    p0.characters = [luffy] + [InPlay.of(repo.get(x)) for x in others]
    distinct = len({c.card.name for c in p0.characters})
    evaluate_static_effects(s, overlay)
    assert luffy.static_buff == distinct * 1000


def test_search_top_n_destination_life():
    """OP16-119: destination life でライフ上に裏向きで加える。"""
    repo, overlay = _repo(), _overlay()
    s, p0, p1 = _state(repo, overlay)
    p0.deck = [repo.get("OP01-001") for _ in range(5)]
    before = len(p0.life)
    execute_effect({"search_top_n": {"depth": 3, "filter": {}, "limit": 1,
                                       "destination": "life", "rest_remain": "bottom"}},
                   s, p0, p1, None)
    assert len(p0.life) == before + 1


def test_hand_or_trash_to_self_life_trash_faceup():
    """OP16-108: from_zone=trash で手札を無視、 face_up で表向きライフ。"""
    repo, overlay = _repo(), _overlay()
    s, p0, p1 = _state(repo, overlay)
    bh = next(c["card_id"] for c in _raw()
              if any("黒ひげ海賊団" in f for f in repo.get(c["card_id"]).features)
              and (repo.get(c["card_id"]).cost or 99) <= 6)
    p0.trash = [repo.get(bh)]
    p0.hand = [repo.get(bh)]  # 手札にも該当があるが from_zone=trash なので無視されるべき
    p0.life = [repo.get("OP01-001")]
    execute_effect({"hand_or_trash_to_self_life": {
        "from_zone": "trash", "face_up": True,
        "filter": {"feature": "黒ひげ海賊団", "cost_le": 6}, "count": 1}}, s, p0, p1, None)
    assert len(p0.life) == 2
    assert p0.face_up_life_count >= 1
    assert len(p0.trash) == 0  # trash から取った
    assert len(p0.hand) == 1   # 手札は触らない


def test_play_from_hand_or_trash_stage():
    """OP16-102: filter.category=STAGE で ステージ として登場。"""
    repo, overlay = _repo(), _overlay()
    s, p0, p1 = _state(repo, overlay)
    p0.trash = [repo.get("OP09-099")]  # ハチノス (STAGE)
    execute_effect({"play_from_hand_or_trash": {
        "filter": {"category": "STAGE", "name": "ハチノス"}, "limit": 1}}, s, p0, p1, None)
    assert len(p0.stages) == 1
    assert p0.stages[-1].card.category == Category.STAGE
    assert len(p0.trash) == 0


def test_should_fire_trigger_includes_play():
    """OP16-105/111/113: play_self / play_from_trash を含むトリガーは AI auto-fire 対象。"""
    from engine.effects import should_fire_trigger
    repo, overlay = _repo(), _overlay()
    s, p0, p1 = _state(repo, overlay)
    p0.life = []  # self_life_le:2 を満たす (= 111 サンダーソニア trigger)
    # 111 サンダーソニア: trigger play_self (self_life_le:2)
    assert should_fire_trigger(s, p0, repo.get("OP16-111"), overlay)
