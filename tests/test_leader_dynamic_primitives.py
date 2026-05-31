# -*- coding: utf-8 -*-
"""task#11 新 primitive 群の regression。

[[project_16deck_inline_audit_done]] の残課題として集約実装した leader 固有の動的効果:
- OP15-119 ルフィ: reveal_self_life_top_pump_per_cost (= ライフ上公開コスト×per_cost で自己パンプ)
- OP08-098 カルガラ: play_from_hand の cost_le_dynamic + then_life_to_hand
  (= 場ドン枚数以下コストの《シャンドラの戦士》登場、 登場できた場合のみライフ上1枚を手札へ)
- OP15-002 ルーシー: self_event_cost_used_ge (= このターン中コストN以上のイベント使用判定)
"""
from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    eval_condition,
    execute_effect,
    fire_activate_main,
    load_effect_overlay,
    resolve_triggers,
    trigger_on_play,
)

ROOT = Path(__file__).resolve().parent.parent


def _setup(leader_id, opp_id="OP01-001"):
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    p1 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p2 = Player(name="P1", leader=InPlay.of(repo.get(opp_id), sickness=False))
    st = GameState(players=[p1, p2], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    return repo, overlay, st, p1, p2


def test_op15_119_reveal_life_pump_per_cost():
    """ライフ上 cost4 公開 → 自身 +4000 (= per_cost 1000 × cost 4)。"""
    repo, ov, st, p1, p2 = _setup("OP15-098")
    luffy = InPlay.of(repo.get("OP15-119"), sickness=False)
    p1.characters = [luffy]
    p1.life = [repo.get("OP08-040")]  # cost4
    pow0 = luffy.power
    execute_effect({"reveal_self_life_top_pump_per_cost": {"per_cost": 1000}},
                   st, p1, p2, luffy)
    assert luffy.power == pow0 + 4000, f"cost4 公開で +4000 期待, got {luffy.power-pow0}"


def test_op15_119_no_life_no_pump():
    """ライフ 0 枚なら公開できず パンプ 0。"""
    repo, ov, st, p1, p2 = _setup("OP15-098")
    luffy = InPlay.of(repo.get("OP15-119"), sickness=False)
    p1.characters = [luffy]
    p1.life = []
    pow0 = luffy.power
    execute_effect({"reveal_self_life_top_pump_per_cost": {"per_cost": 1000}},
                   st, p1, p2, luffy)
    assert luffy.power == pow0, "ライフ無しで パンプ してはいけない"


_KARGARA_DO = {"play_from_hand": {
    "filter": {"feature": "シャンドラの戦士", "cost_le_dynamic": "self_don_total"},
    "limit": 1, "then_life_to_hand": 1}}


def test_op08_098_play_within_field_don_then_life():
    """場ドン ≥ cost なら《シャンドラの戦士》登場 + 登場できたのでライフ上1枚を手札へ。"""
    repo, ov, st, p1, p2 = _setup("OP08-098")
    shandra = repo.get("OP08-099")  # シャンドラの戦士 (cost6)
    p1.don_active = shandra.cost + 1
    p1.hand = [shandra]
    p1.life = [repo.get("OP01-013")] * 2
    execute_effect(_KARGARA_DO, st, p1, p2, p1.leader)
    assert len(p1.characters) == 1, "場ドン十分なら登場するべき"
    assert len(p1.life) == 1, "登場できた場合ライフ上1枚が手札へ"
    assert len(p1.hand) == 1, "登場で手札-1, ライフ獲得で手札+1 = 差し引き1枚"


def test_op08_098_no_play_when_cost_exceeds_field_don():
    """場ドン < cost なら登場不可 → ライフも減らない (= 「登場させた場合」 前文不成立)。"""
    repo, ov, st, p1, p2 = _setup("OP08-098")
    shandra = repo.get("OP08-099")  # cost6
    p1.don_active = shandra.cost - 1  # 不足
    p1.hand = [shandra]
    p1.life = [repo.get("OP01-013")] * 2
    execute_effect(_KARGARA_DO, st, p1, p2, p1.leader)
    assert len(p1.characters) == 0, "コスト超過なら登場しない"
    assert len(p1.life) == 2, "登場0なのでライフを手札に加えてはいけない"


def test_op15_002_self_event_cost_used_ge_condition():
    """eval_condition 単体: このターン中の最大イベントコストで真偽。"""
    repo, ov, st, p1, p2 = _setup("OP15-002")
    p1.max_event_cost_this_turn = 3
    assert eval_condition({"self_event_cost_used_ge": 3}, st, p1, p2) is True
    p1.max_event_cost_this_turn = 2
    assert eval_condition({"self_event_cost_used_ge": 3}, st, p1, p2) is False


def _lucy_activate_draw(max_event_cost):
    """OP15-002 起動メインを実経路 (fire_activate_main) で発火し draw 枚数を返す。"""
    repo, ov, st, p1, p2 = _setup("OP15-002")
    p1.deck = [repo.get("OP01-013")] * 10
    p1.hand = []
    p1.max_event_cost_this_turn = max_event_cost
    am = [e for e in ov["OP15-002"].effects if e.get("when") == "activate_main"][0]
    fire_activate_main(st, p1, p2, p1.leader, am)
    resolve_triggers(st)
    return len(p1.hand)


def test_op15_002_activate_main_draw_gated_real_path():
    """実経路: 「if」 gate が起動メインdraw を正しく塞ぐ (= 旧 condition[singular] dead bug の回帰防止)。

    eval_condition 単体テストだけでは entry-gate の key 名 (condition vs if) 誤りを
    検出できず dead gate を見逃した。 必ず fire_activate_main 経由で検証する。
    """
    assert _lucy_activate_draw(3) == 1, "cost3 イベント使用済なら 1 ドロー"
    assert _lucy_activate_draw(2) == 0, "cost2 までしか使っていなければ ドローしない"
    assert _lucy_activate_draw(0) == 0, "イベント未使用なら ドローしない"


def test_eb03_053_nami_on_play_mill_gated_by_opp_life():
    """EB03-053 ナミ 登場時: 相手ライフ≥3 の場合のみ 相手ライフ上1を相手手札へ (= 旧 _if_clause dead bug)。"""
    repo, ov, st0, p0, p0o = _setup("OP01-001")

    def mill(opp_life):
        repo2 = CardRepository.from_json(ROOT / "db" / "cards.json")
        overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
        p1 = Player(name="P0", leader=InPlay.of(repo2.get("OP01-001"), sickness=False))
        p2 = Player(name="P1", leader=InPlay.of(repo2.get("OP01-001"), sickness=False))
        nami = InPlay.of(repo2.get("EB03-053"), sickness=True)
        p1.characters = [nami]
        p2.life = [repo2.get("OP01-013")] * opp_life
        p2.hand = []
        st = GameState(players=[p1, p2], phase=Phase.MAIN, rng=random.Random(1),
                       effects_overlay=overlay)
        trigger_on_play(st, p1, p2, nami, overlay)
        resolve_triggers(st)
        return len(p2.life), len(p2.hand)

    assert mill(3) == (2, 1), "相手ライフ3なら 上1枚が相手手札へ (life3→2, hand0→1)"
    assert mill(2) == (2, 0), "相手ライフ2なら 不発 (= 「3枚以上の場合」 前文不成立)"
