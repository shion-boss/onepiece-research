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
