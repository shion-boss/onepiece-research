# -*- coding: utf-8 -*-
"""
lethal_planner Phase 7J テスト (= 2026-05-14)
==============================================

戦略原理:
- ドン均等化 + ±2k マージン
- 偶数 k 差 / 1k 差 / 階段戦略
- 過剰打点を burner 配置
"""

from __future__ import annotations

from engine.lethal_planner import (
    AttackPlan,
    PlannedAttack,
    compute_demand_value,
    mark_overkill_as_burners,
    plan_optimal_attack_sequence,
)


# ─────────────────────────────────────────────────────
# compute_demand_value
# ─────────────────────────────────────────────────────


def test_demand_value_single_attack():
    """単一攻撃の demand = ceil((atk - leader) / 1000)。"""
    # 7000 attack vs 5000 leader → 2000 gap = 2 demand
    assert compute_demand_value([7000], 5000) == 2
    # 6000 attack → 1 demand
    assert compute_demand_value([6000], 5000) == 1
    # 5000 attack → 0 demand (= 同値、 attacker 勝ち)
    assert compute_demand_value([5000], 5000) == 0


def test_demand_value_multi_attacks():
    """複数攻撃の demand 合計。"""
    # 6000 + 7000 vs 5000 → 1 + 2 = 3 demand
    assert compute_demand_value([6000, 7000], 5000) == 3


def test_demand_value_ceiling_edge():
    """ceil 端数処理: 1001 gap でも 2 demand。"""
    assert compute_demand_value([6001], 5000) == 2  # ceil(1001/1000) = 2


def test_demand_value_zero_for_low_attacks():
    """opp_leader 以下の攻撃は demand 0。"""
    assert compute_demand_value([4000, 3000], 5000) == 0


# ─────────────────────────────────────────────────────
# plan_optimal_attack_sequence: ドン均等化
# ─────────────────────────────────────────────────────


def test_plan_distributes_don_evenly():
    """3 attacker + 6 DON → 各 attacker に 2 DON ずつ均等振り。"""
    attackers = [(1, 4000), (2, 4000), (3, 4000)]
    plan = plan_optimal_attack_sequence(
        attackers, available_don=6, opp_leader_power=5000, opp_shields=4,
    )
    dons = [p.dons_to_attach for p in plan.sequence]
    # 余りなし均等 = (2, 2, 2)
    assert sorted(dons) == [2, 2, 2], f"均等振り期待 (2,2,2) got {dons}"
    # 各 attacker は 4000 + 2000 = 6000
    powers = [p.effective_power for p in plan.sequence]
    assert all(p == 6000 for p in powers)


def test_plan_extra_don_to_weakest():
    """余り DON は最弱 attacker へ。"""
    # attacker 4000 と 5000、 DON 3 個
    # 4000 → +1000 で 5000 → +1000 で 6000 → +1000 で 7000 = 5000 にも振る
    # 最弱優先で 4000 が +2 (= 6000) になり、 5000 は +1 (= 6000)
    attackers = [(1, 4000), (2, 5000)]
    plan = plan_optimal_attack_sequence(
        attackers, available_don=3, opp_leader_power=5000, opp_shields=4,
    )
    # 最弱 4000 が +2 で 6000、 5000 が +1 で 6000 (= 均等)
    powers = sorted(p.effective_power for p in plan.sequence)
    assert powers == [6000, 6000], f"均等化期待 [6000, 6000] got {powers}"


def test_plan_respects_max_don_per_attacker():
    """1 attacker に DON は max 4 まで。"""
    attackers = [(1, 3000)]
    plan = plan_optimal_attack_sequence(
        attackers, available_don=10, opp_leader_power=5000, opp_shields=4,
    )
    # 3000 + 4 × 1000 = 7000、 DON 6 個余る
    assert plan.sequence[0].dons_to_attach == 4
    assert plan.sequence[0].effective_power == 7000


# ─────────────────────────────────────────────────────
# Lethal 判定 + 順序付け
# ─────────────────────────────────────────────────────


def test_lethal_detected_when_enough_hits():
    """3 attacker × 6000 power vs life=3 → lethal 成立。"""
    attackers = [(1, 6000), (2, 6000), (3, 6000)]
    plan = plan_optimal_attack_sequence(
        attackers, available_don=0, opp_leader_power=5000, opp_shields=3,
    )
    assert plan.is_lethal


def test_not_lethal_when_not_enough_attackers():
    """1 attacker vs life=3 → lethal 不成立 (hits 1 < shields 3)。"""
    attackers = [(1, 6000)]
    plan = plan_optimal_attack_sequence(
        attackers, available_don=0, opp_leader_power=5000, opp_shields=3,
    )
    assert not plan.is_lethal


def test_sequence_weak_to_strong():
    """攻撃順序は 弱→強 (= counter 吸わせから本命)。"""
    attackers = [(1, 4000), (2, 8000), (3, 6000)]
    plan = plan_optimal_attack_sequence(
        attackers, available_don=0, opp_leader_power=5000, opp_shields=3,
    )
    powers = [p.effective_power for p in plan.sequence]
    # 単調非減少
    for i in range(len(powers) - 1):
        assert powers[i] <= powers[i + 1], f"弱→強 順序 NG: {powers}"


# ─────────────────────────────────────────────────────
# burner mark
# ─────────────────────────────────────────────────────


def test_burner_mark_for_3plus_attackers():
    """3 以上の attacker で 下位 1/3 を burner mark。"""
    attackers = [(1, 4000), (2, 5000), (3, 6000), (4, 7000)]
    plan = plan_optimal_attack_sequence(
        attackers, available_don=0, opp_leader_power=5000, opp_shields=3,
    )
    plan = mark_overkill_as_burners(plan)
    burners = [p for p in plan.sequence if p.is_burner]
    # 下位 1/3 = floor(4/3) = 1 だが max(1, ...) で 1 体は確保
    assert len(burners) >= 1


def test_no_burner_for_2_attackers():
    """2 attacker 未満では burner mark しない。"""
    attackers = [(1, 4000), (2, 6000)]
    plan = plan_optimal_attack_sequence(
        attackers, available_don=0, opp_leader_power=5000, opp_shields=3,
    )
    plan = mark_overkill_as_burners(plan)
    burners = [p for p in plan.sequence if p.is_burner]
    assert len(burners) == 0


# ─────────────────────────────────────────────────────
# empty / edge cases
# ─────────────────────────────────────────────────────


def test_empty_attackers_returns_empty_plan():
    plan = plan_optimal_attack_sequence(
        [], available_don=5, opp_leader_power=5000, opp_shields=3,
    )
    assert plan.sequence == []
    assert plan.total_demand == 0
    assert not plan.is_lethal


def test_zero_don_uses_base_powers():
    """DON 0 でも attacker.base_power のまま動作。"""
    attackers = [(1, 6000), (2, 7000)]
    plan = plan_optimal_attack_sequence(
        attackers, available_don=0, opp_leader_power=5000, opp_shields=2,
    )
    powers = sorted(p.effective_power for p in plan.sequence)
    assert powers == [6000, 7000]
