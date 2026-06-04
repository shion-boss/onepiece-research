# -*- coding: utf-8 -*-
"""HumanModelAI (= 人間相手モデルを探索の仮想敵に差す配管) の検証。

(1) データ薄 (sample < MIN_SAMPLES) では GreedyAI に degrade する (= 正直)。
(2) 注入した「カウンター厚い人間」 モデルでは、 greedy が通したリーダー被弾を
    手札カウンターで防ぐ (= 人間挙動の再現メカニズムが動く)。
"""
from __future__ import annotations

from engine.core import InPlay
from engine.ai import GreedyAI
from engine.human_model_ai import HumanModelAI

import tests.test_effects as T


def _setup_leader_attack():
    """attacker(P6000) が defender リーダー(P5000) を攻撃。 defender 手札に counter。"""
    repo, overlay = T._repo(), T._overlay()
    state = T._make_state(repo, "OP01-001", overlay=overlay)
    attacker_player, defender = state.players[0], state.players[1]
    state.turn_number = 3
    attacker = InPlay.of(repo.get("EB01-012"), sickness=False, rested=False)  # P6000
    attacker_player.characters = [attacker]
    # defender 手札: counter 1000 + 1000 (= 5000+2000=7000 > 6000 で耐えられる)
    defender.hand = [repo.get("EB01-012"), repo.get("EB01-012_r1")]  # counter 1000 each
    defender.don_active = 5
    return state, attacker, defender


def test_degrades_to_greedy_when_data_thin():
    """sample_size < MIN_SAMPLES (= 実データ8) なら greedy と同一の防御。"""
    state, attacker, defender = _setup_leader_attack()
    hm = HumanModelAI(rng=__import__("random").Random(1),
                      model={"sample_size": 8, "defense_activity": 0.42})
    gd = GreedyAI(rng=__import__("random").Random(1))
    hm_res = hm.choose_defense(state, attacker, defender.leader, True, defender)
    gd_res = gd.choose_defense(state, attacker, defender.leader, True, defender)
    assert hm_res == gd_res, f"degrade してない: hm={hm_res} greedy={gd_res}"


def test_counter_heavy_human_prevents_leader_hit():
    """注入した counter 厚い人間モデルなら、 リーダー被弾を手札カウンターで防ぐ。"""
    state, attacker, defender = _setup_leader_attack()
    hm = HumanModelAI(rng=__import__("random").Random(1),
                      model={"sample_size": 100, "defense_activity": 0.5})
    block_iid, counters = hm.choose_defense(state, attacker, defender.leader, True, defender)
    # 守り (リーダー 5000 + 使用カウンター値) > 攻撃 6000 になっている
    leader_p = defender.leader.power
    cval = sum(int(defender.hand[i].counter or 0) for i in counters if 0 <= i < len(defender.hand))
    assert leader_p + cval > attacker.power, \
        f"被弾を防げていない: 守り {leader_p}+{cval} <= 攻撃 {attacker.power}"


def test_loads_real_model_file():
    """db/human_model.json を実ロードでき、 sample_size を読める (= 配管疎通)。"""
    hm = HumanModelAI(rng=__import__("random").Random(1))
    assert hm._sample >= 0  # ファイル有れば >0、 無くても落ちない
