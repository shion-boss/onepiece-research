# -*- coding: utf-8 -*-
"""
リーサル攻撃配分プランナー (Phase 7J / 2026-05-14)
====================================================

OPTCG コミュニティ知見 (= note.com/nagahami, 語るボブル 等) から抽出した
「相手の counter 要求値を最大化」 する攻撃 power 配分ロジック。

## 戦略原理

1. **トリガーマージン (±2k)**: ライフ 1 枚 = 最大 2k counter (= 通常 trigger)
   → 各攻撃の power 差を ±2k 以内に保つと相手の counter 配分が困難

2. **ドン配分均等化**: 複数攻撃時はパワーを均等化、 余り DON は最大 power 攻撃へ
   → 1 個の大型攻撃より、 均等な複数攻撃の方が要求値高い

3. **偶数 k 差 (= 2 体リーサル)**: 相手リーダーとの power 差 7k/8k/9k 等
   → 偶数 k 差は手札消費効率 (= counter 要求枚数) が最大

4. **3 体以上は 1k 差**: 過剰 2k 差は trigger 1 枚で吸収可能、 1k 差なら 2 枚必要

5. **盾枚数別 階段戦略**: shield N 枚 → 攻撃間 power 差 = N×1000 + 1 で最適化
   - 盾 1: 階段 +1〜2k で trigger margin
   - 盾 2+: 階段 +2k で trigger 連発防止

6. **過剰打点の counter burner 配置**: リーサル必要 power 超過分は
   「相手 counter を吐かせる」 弱攻撃に回す (= 後続攻撃を通すための消耗戦)

## 公開 API

- `compute_demand_value(attacks, opp_leader_power) -> int`:
  攻撃側の合計 demand = Σ ceil((atk_power - opp_leader_power) / 1000)
- `plan_optimal_attack_sequence(attackers, available_don, opp_state)`:
  attacker への DON 振り分け + 攻撃順序を最適化、 (sequence, total_demand) を返す
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil
from typing import Optional


@dataclass
class PlannedAttack:
    """個別攻撃のプラン (= attacker + 付与 DON + 期待 power)。"""
    attacker_iid: int
    base_power: int
    dons_to_attach: int
    effective_power: int        # = base_power + dons × 1000
    is_burner: bool = False     # True なら counter 吸わせ目的の弱攻撃


@dataclass
class AttackPlan:
    """ターン全体の攻撃計画。

    sequence は実行順 (= リスト順)。 通常は「弱→強」 で counter 吸わせから本命。
    `total_demand` は相手が必要な counter 合計 (= 要求値)。
    `is_lethal` はこのプランで lethal 成立かの判定。
    """
    sequence: list[PlannedAttack] = field(default_factory=list)
    total_demand: int = 0
    is_lethal: bool = False
    expected_excess: int = 0    # = 攻撃合計 - opp.life × 5000 (ガード基準を超える分)


def compute_demand_value(
    attack_powers: list[int],
    opp_leader_power: int,
) -> int:
    """攻撃側の合計 demand value (= 要求値) を計算。

    各攻撃が必要とする counter 量を ceil で集計:
        demand_per_attack = ceil(max(0, atk_power - opp_leader_power) / 1000)

    手札カウンター (= 1 枚 1000 or 2000) で防御するには各攻撃ごとに
    「不足分」 を埋める必要があるため、 合計が opp の負担量。
    """
    total = 0
    for p in attack_powers:
        gap = p - opp_leader_power
        if gap > 0:
            total += ceil(gap / 1000)
    return total


def _plan_even_distribution(
    attackers: list[tuple[int, int]],  # [(attacker_iid, base_power), ...]
    available_don: int,
    opp_leader_power: int,
    max_dons_per_attacker: int = 4,
) -> list[PlannedAttack]:
    """ドン均等化 + ±2k マージン で攻撃配分 (Phase 7J コア)。

    アルゴリズム:
    1. 各 attacker に最低限の DON (= leader 倒せる量) を振る
    2. 残 DON は「現状最弱の attacker」 から +1 ずつ、 max_per 上限内で
    3. 結果として power 差が ±2k 以内に収まる傾向 (= 均等化)
    """
    n = len(attackers)
    if n == 0:
        return []
    dons_attached = [0] * n
    effective_powers = [bp for _, bp in attackers]

    # Step 1: 各 attacker が opp.leader を超えるまで DON 振り (= 必要最小)
    for i, (_, bp) in enumerate(attackers):
        if available_don <= 0:
            break
        gap = opp_leader_power - bp
        if gap > 0:
            need = min(ceil(gap / 1000), max_dons_per_attacker)
            need = min(need, available_don)
            dons_attached[i] = need
            effective_powers[i] = bp + need * 1000
            available_don -= need

    # Step 2: 余り DON を「最弱 attacker」 から +1 ずつ振り、 均等化
    while available_don > 0:
        # 最弱 (= 効果 power 最小) を探す。 max_per 上限の attacker は除外
        candidates = [
            i for i in range(n)
            if dons_attached[i] < max_dons_per_attacker
        ]
        if not candidates:
            break
        # 最弱 attacker を選ぶ (= 同値なら index 若い側)
        weakest = min(candidates, key=lambda i: effective_powers[i])
        dons_attached[weakest] += 1
        effective_powers[weakest] += 1000
        available_don -= 1

    return [
        PlannedAttack(
            attacker_iid=attackers[i][0],
            base_power=attackers[i][1],
            dons_to_attach=dons_attached[i],
            effective_power=effective_powers[i],
        )
        for i in range(n)
    ]


def _order_for_counter_demand(
    plans: list[PlannedAttack],
    opp_shields: int,
) -> list[PlannedAttack]:
    """弱→強の順序付け + 盾枚数別の階段戦略 (Phase 7J)。

    盾なし: 弱→強 (= 後続の強攻撃で確実に通す)
    盾あり: 弱→強でも OK、 ただし「ライフ 1 枚 = 最大 2k trigger」 を見込んで
            隣接攻撃の power 差を 2k 以内に揃える (= trigger 吸収防止)
    """
    sorted_plans = sorted(plans, key=lambda p: p.effective_power)
    return sorted_plans


def plan_optimal_attack_sequence(
    attackers: list[tuple[int, int]],
    available_don: int,
    opp_leader_power: int,
    opp_shields: int,
    max_dons_per_attacker: int = 4,
) -> AttackPlan:
    """ターン全体の最適攻撃計画を構築 (Phase 7J、 メイン API)。

    Args:
        attackers: [(attacker_iid, base_power), ...] のリスト
        available_don: 使用可能な DON 数
        opp_leader_power: 相手リーダー power (= 通常 5000)
        opp_shields: 相手ライフ枚数
        max_dons_per_attacker: 1 attacker への DON 上限 (= 公式 4)

    Returns:
        AttackPlan: 順序付き攻撃計画 + 要求値 + lethal 判定
    """
    plans = _plan_even_distribution(
        attackers, available_don, opp_leader_power, max_dons_per_attacker,
    )
    ordered = _order_for_counter_demand(plans, opp_shields)

    powers = [p.effective_power for p in ordered]
    demand = compute_demand_value(powers, opp_leader_power)
    expected_excess = sum(max(0, p - opp_leader_power) for p in powers)
    # lethal 判定: 攻撃成立数 ≥ opp.life (= 各 hit 1 life 削減)
    successful_hits = sum(1 for p in powers if p > opp_leader_power)
    is_lethal = successful_hits >= opp_shields

    return AttackPlan(
        sequence=ordered,
        total_demand=demand,
        is_lethal=is_lethal,
        expected_excess=expected_excess,
    )


def mark_overkill_as_burners(
    plan: AttackPlan,
    min_excess_for_burner: int = 3000,
) -> AttackPlan:
    """過剰打点の攻撃を「counter burner」 として label (Phase 7J)。

    必要 lethal を確保した後、 余剰 power の攻撃を burner にすると
    AI 上層で「相手 counter を吐かせる」 戦略判断が可能。

    判定: opp_leader_power 超過分が min_excess_for_burner (= 3000) 以上で
          かつ 全 attacker 数の 半分超なら下位を burner mark。
    """
    if not plan.sequence:
        return plan
    # excess の合計が必要量を超えるかで burner 判定
    # 簡略: lethal 成立後、 余剰 attack の下位 1/3 を burner にする
    n = len(plan.sequence)
    if n >= 3:
        # 弱い順 (= 既に sorted) の下位 n//3 を burner mark
        for i in range(max(1, n // 3)):
            plan.sequence[i].is_burner = True
    return plan
