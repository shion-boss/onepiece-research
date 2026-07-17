# -*- coding: utf-8 -*-
"""value_defense の lethal-survival ガード テスト (= 2026-07-09)。

不変条件: 攻撃を素通しすると敗北 (life < dmg) かつ 生存できる手が存在するなら、
value_defense (board_eval 採点) は「受けて即負け」を選んではならない = 必ず生存する。

背景: Enel vs Bonney 実測で value_defense (GBM無=board_eval) が「受けたら即負け」を
-∞ と評価せず、 守れる致死打を守らず自滅する負け筋 (3/12敗) を検出 → 修正。
"""
from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.exploit_beam_ai import ExploitBeamAI

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _lethal_state(repo, atk_power=6000):
    """defender(me) が life=0 (= 次の連結で敗北)、 attacker(opp) が atk_power で攻撃。
    me は生存可能な counter (2000×2) を手札に持つ。"""
    me = Player(name="defender", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    opp = Player(name="attacker", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    me.life = []  # 0 life = 素通し=敗北
    me.deck = [repo.get("OP01-013")] * 30
    opp.deck = [repo.get("OP01-013")] * 30
    # 生存に十分な counter (leader 5000 + 2000 = 7000 > 6000)
    me.hand = [repo.get("OP03-044"), repo.get("OP03-044")]  # 2000 counter ×2
    attacker = InPlay.of(repo.get("OP01-013"), sickness=False)
    attacker.attached_dons = max(0, (atk_power - 3000) // 1000)  # opp ターンなので DON 有効
    opp.characters = [attacker]
    state = GameState(players=[me, opp], phase=Phase.MAIN, rng=random.Random(1))
    state.turn_player_idx = 1  # opp = アタッカー
    return state, me, attacker


def _survives(me, attacker, block_iid, counters) -> bool:
    if block_iid is not None:
        return True
    ctot = sum(int(getattr(me.hand[i], "counter", 0) or 0) for i in counters if 0 <= i < len(me.hand))
    return me.leader.power + ctot > attacker.power


def test_value_defense_never_self_destructs_at_lethal():
    repo = _repo()
    state, me, attacker = _lethal_state(repo, atk_power=6000)
    ai = ExploitBeamAI(rng=random.Random(1), deck_analysis={"deck_slug": "cardrush_1467"})
    ai._value_defense = True  # value 駆動防御を強制
    block_iid, counters = ai.choose_defense(state, attacker, me.leader, True, me)
    # 致死局面で生存できる手があるのに「受けて負け」を選んでいない
    assert _survives(me, attacker, block_iid, counters), (
        f"lethal 局面で生存せず自滅した: block={block_iid} counters={counters}"
    )


def test_value_defense_takes_chip_when_safe():
    """安全ライフ (life≥3) では素受け可 = ガードは lethal のみ発火し過剰防御しない。"""
    repo = _repo()
    state, me, attacker = _lethal_state(repo, atk_power=6000)
    me.life = [repo.get("OP01-013")] * 3  # 安全圏
    ai = ExploitBeamAI(rng=random.Random(1), deck_analysis={"deck_slug": "cardrush_1467"})
    ai._value_defense = True
    # クラッシュせず何らかの合法な防御を返す (素受け=(None, ()) も可)
    block_iid, counters = ai.choose_defense(state, attacker, me.leader, True, me)
    assert isinstance(counters, tuple)


# --- counter-event での lethal 生存 (= 2026-07-17、 ohtsuki「負けとイベントカウンターを
#     天秤にかけたら絶対負けを選ぶな」)。 shield-counter では届かず counter-event でのみ
#     凌げる致死打を、 value_defense が「受けて即負け」せず必ず event で生存すること。 ---

def _lethal_only_event_survives(repo, overlay, leader_id, event_id, atk_power):
    """defender(me) life=0、 shield-counter は 0 (fodder は counter=0 のゾロ)、
    counter-event でのみ生存可能な致死のリーダー攻撃を組む。"""
    me = Player(name="def", leader=InPlay.of(repo.get(leader_id), sickness=False))
    opp = Player(name="atk", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    me.life = []  # 0 = 素通し敗北
    me.deck = [repo.get("OP01-013")] * 30
    opp.deck = [repo.get("OP01-013")] * 30
    # counter-event + counter=0 の捨て札 (= shield では届かない)
    me.hand = [repo.get(event_id), repo.get("OP01-025")]  # OP01-025 ゾロ = counter 0
    me.don_active = 3
    attacker = InPlay.of(repo.get("OP01-013"), sickness=False)
    attacker.attached_dons = max(0, (atk_power - 3000) // 1000)
    opp.characters = [attacker]
    state = GameState(players=[me, opp], phase=Phase.MAIN, rng=random.Random(1))
    state.turn_player_idx = 1
    state.effects_overlay = overlay
    return state, me, attacker


def _overlay():
    from engine.effects import load_effect_overlay
    return load_effect_overlay(str(ROOT / "db" / "card_effects.json"))


def test_value_defense_survives_lethal_with_counter_event_self_inplay():
    """神避 (self_inplay +3000) でのみ凌げる致死打を、 value_defense が使って生存する。"""
    repo = _repo()
    # 神避: leader 5000 + 3000 = 8000 > 7000。 shield 0 では 5000 < 7000 で死ぬ。
    state, me, attacker = _lethal_only_event_survives(
        repo, _overlay(), "OP01-001", "OP13-076", atk_power=7000
    )
    ai = ExploitBeamAI(rng=random.Random(1), deck_analysis={"deck_slug": "cardrush_1467"})
    ai._value_defense = True
    block_iid, counters = ai.choose_defense(state, attacker, me.leader, True, me)
    assert ai._defense_survives_sim(
        state, attacker, me.leader, True, block_iid, counters, 0
    ), f"counter-event で生存できるのに自滅した: block={block_iid} counters={counters}"


def test_value_defense_survives_with_named_leader_counter_event():
    """放電 (self_chara_or_leader_named「エネル」+2000) を、 エネルリーダー防御で認識し生存する。
    旧実装は named target を認識できず、 この守備札を死蔵して敗北していた (= ohtsuki 実戦報告)。"""
    repo = _repo()
    # エネルリーダー OP15-058 (5000) + 放電 +2000 = 7000 > 6000。 shield 0 では死ぬ。
    state, me, attacker = _lethal_only_event_survives(
        repo, _overlay(), "OP15-058", "OP15-074", atk_power=6000
    )
    ai = ExploitBeamAI(rng=random.Random(1), deck_analysis={"deck_slug": "cardrush_1467"})
    ai._value_defense = True
    # まず認識できていること (= 旧実装は [] だった)
    assert ai._counter_event_options(state, me), "named-leader counter-event を認識できていない"
    block_iid, counters = ai.choose_defense(state, attacker, me.leader, True, me)
    assert ai._defense_survives_sim(
        state, attacker, me.leader, True, block_iid, counters, 0
    ), f"named counter-event で生存できるのに自滅した: counters={counters}"


def test_pump_can_save_leader_recognition():
    """_pump_can_save_leader: string self + named(リーダー名一致) を認識、 無関係 named は False。"""
    repo = _repo()
    me = Player(name="me", leader=InPlay.of(repo.get("OP15-058"), sickness=False))  # エネル
    f = ExploitBeamAI._pump_can_save_leader
    assert f("self_leader", me)
    assert f("self_inplay", me)
    assert f({"type": "self_chara_or_leader_named", "name": "エネル"}, me)
    assert not f({"type": "self_chara_or_leader_named", "name": "ルフィ"}, me)
    assert not f({"type": "one_opp_chara_any"}, me)
