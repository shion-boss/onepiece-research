# -*- coding: utf-8 -*-
"""温度レアァストライク ST29-015 の【カウンター】 friendly +2000 が 喪失する bug の
regression guard。

2026-06-11 (赤黄ボニー tcgportal_bonney campaign 中に発見): power_pump primitive が
target の human pick で pending_choice を立てた直後に halt せず +N を [] に適用 →
後続 do (= 「その後、 自ライフ1以下で 相手 -2000」) の pick が pending_choice を上書きし、
friendly +2000 が完全に喪失 (= 防御カウンターが効かず被弾、 自リーダー +2000 が乗らない)
していた。 power_pump_multi は halt check を持つが 通常 power_pump に欠落していた。

修正: power_pump も _resolve_target が pending_choice を立てたら return (halt) →
run_do_array が残り do を _continuation に退避 → 2 段 pick (friendly +2000 → opp -2000)。
"""
from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import load_effect_overlay, resolve_pending_choice
from engine.game import _fire_counter_events

ROOT = Path(__file__).resolve().parent.parent


def _setup():
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    p0 = Player(name="P0", leader=InPlay.of(repo.get("EB04-001"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("EB04-001"), sickness=False))
    p0.deck = [repo.get("OP07-099")] * 30
    p1.deck = [repo.get("OP07-099")] * 30
    p0.hand = [repo.get("ST29-015")]      # 温度レアァストライク (counter event)
    p0.don_active = 5
    p0.life = [repo.get("OP07-099")]      # life 1 (≤1 → -2000 rider 有効)
    st = GameState(players=[p0, p1], phase=Phase.MAIN,
                   rng=random.Random(1), effects_overlay=overlay)
    st.human_player_idx = 0
    st.turn_player_idx = 1                # opp (p1) ターン中、 p0 が防御で counter
    return st, p0, p1


def test_ondo_friendly_pump_and_opp_debuff_both_apply():
    """温度 counter: friendly +2000 (自リーダー) と opp -2000 が 両方 適用される。
    旧 bug では friendly +2000 の pick が halt せず [] に適用 → 喪失していた。"""
    st, p0, p1 = _setup()

    _fire_counter_events(st, p0, p1, (0,))   # 温度 を hand idx0 から発動

    # 1) ★ 修正の核心: friendly +2000 の target pick modal が halt して立つ
    #    (= 旧 bug では立たず、 +2000 が [] に 適用され 喪失し、 後続 -2000 に 上書きされていた)
    assert st.pending_choice is not None, "friendly +2000 の pick modal が立っていない (halt 失敗 = bug 再発)"
    assert st.pending_choice.get("kind") == "target_pick"
    assert st.pending_choice["primitive_value"].get("amount") == 2000, (
        "先頭 pick が friendly +2000 でない (= -2000 に 潰されている = bug 再発)"
    )
    cand = st.pending_choice["candidates"]
    leader_pos = next(i for i, c in enumerate(cand)
                      if c["iid"] == p0.leader.instance_id)
    resolve_pending_choice(st, [leader_pos])

    # friendly +2000 が 自リーダー に 適用された (= battle_buff +2000)。 リーダー自身の
    # life≤1 静的バフ (+2000) と 重なる ため power 直接比較 でなく battle_buff を 検査。
    assert p0.leader.battle_buff == 2000, (
        f"friendly +2000 未適用: battle_buff={p0.leader.battle_buff} (期待 2000)"
    )

    # 2) continuation で opp -2000 が 適用された (= 「その後、 相手 -2000」 rider が 生きている)
    assert p1.leader.turn_buff == -2000, (
        f"opp -2000 未適用: opp turn_buff={p1.leader.turn_buff} (期待 -2000)"
    )
