# -*- coding: utf-8 -*-
"""Phase 2 runtime invariant checker (= engine/audit_invariants.py) の test。

- Bug 1 (= cannot_be_rested_buff + attacker) を 機械的 に catch できる か
- 正常 state で false-positive が 出ない か
- state 全体 invariant (life range, hand nonneg, don total) の 動作
"""

from __future__ import annotations

import os
import random
from pathlib import Path

from engine.audit_invariants import (
    AuditViolation,
    check_legal_actions_invariants,
    check_state_invariants,
    run_all_checks,
)
from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _make_state(repo, leader_id="OP01-001"):
    leader = repo.get(leader_id)
    p1 = Player(name="P0", leader=InPlay.of(leader, sickness=False))
    p2 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1.deck = [repo.get("OP01-013")] * 30
    p2.deck = [repo.get("OP01-013")] * 30
    return GameState(players=[p1, p2], phase=Phase.MAIN, rng=random.Random(1))


# ============================================================
# state invariant tests
# ============================================================
def test_state_invariants_clean():
    """正常 state で 違反 0。"""
    repo = _repo()
    state = _make_state(repo)
    violations = list(check_state_invariants(state))
    assert violations == [], f"clean state で 違反 検出: {violations}"


def test_state_invariant_life_nonneg_only():
    """life > 5 は 公式 で 許される (= 「ライフ追加」 系 effect) → 違反 出さない。"""
    repo = _repo()
    state = _make_state(repo)
    state.players[0].life = [repo.get("OP01-013")] * 6  # > 5 は 公式 OK
    violations = list(check_state_invariants(state))
    assert not any(v.rule_id == "INV-life-range" for v in violations)
    assert not any(v.rule_id == "INV-life-nonneg" for v in violations)


def test_state_invariant_don_too_many():
    """don total > 10 で INV-don-total 検出。"""
    repo = _repo()
    state = _make_state(repo)
    state.players[0].don_active = 8
    state.players[0].don_rested = 5  # total 13 > 10
    violations = list(check_state_invariants(state))
    assert any(v.rule_id == "INV-don-total" for v in violations)


# ============================================================
# legal_actions invariant tests (= Bug 1 catch)
# ============================================================
def test_legal_actions_clean():
    """通常 attack actions で 違反 0。"""
    from engine.game import AttackLeader, AttackCharacter
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    ch = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [ch]
    actions = [
        AttackLeader(attacker_iid=ch.instance_id),
        AttackCharacter(attacker_iid=ch.instance_id, target_iid=999),
    ]
    violations = list(check_legal_actions_invariants(state, actions))
    assert violations == [], f"通常 attacker で 違反: {violations}"


def test_legal_actions_catches_bug1_cannot_be_rested():
    """Bug 1 catch: cannot_be_rested_buff=True で attacker iid が legal actions に
    含まれる → INV-cannot-rest-no-attack 違反 検出。

    これは 「もし Bug 1 修正 前 の engine で legal_actions が cannot_be_rested の chara を
    attacker に 含めて しまった 場合、 invariant が 即 catch する」 ことを 保証 する test。
    """
    from engine.game import AttackLeader
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    ch = InPlay.of(repo.get("OP01-013"), sickness=False)
    ch.cannot_be_rested_buff = True
    ch.cannot_be_rested_applier_idx = 1
    ch.cannot_be_rested_applied_turn = 4
    me.characters = [ch]
    # 故意 に cannot_be_rested chara を attacker に 含める (= Bug 1 状況 を 模擬)
    actions = [AttackLeader(attacker_iid=ch.instance_id)]
    violations = list(check_legal_actions_invariants(state, actions))
    assert any(v.rule_id == "INV-cannot-rest-no-attack" for v in violations), (
        f"Bug 1 を catch できなかった: {violations}"
    )


def test_legal_actions_catches_rested_attacker():
    """rested=True の chara が attacker に 含まれる → INV-rested-no-attack 違反。"""
    from engine.game import AttackLeader
    repo = _repo()
    state = _make_state(repo)
    me = state.players[0]
    ch = InPlay.of(repo.get("OP01-013"), sickness=False)
    ch.rested = True
    me.characters = [ch]
    actions = [AttackLeader(attacker_iid=ch.instance_id)]
    violations = list(check_legal_actions_invariants(state, actions))
    assert any(v.rule_id == "INV-rested-no-attack" for v in violations)


# ============================================================
# integration: legal_actions 経由 で 自動 catch
# ============================================================
def test_legal_actions_integration_audit_disabled():
    """default (= audit OFF) では state.audit_violations は 空 のまま。"""
    from engine.game import legal_actions
    repo = _repo()
    state = _make_state(repo)
    state.turn_number = 5
    state.players[0].don_active = 5
    # 環境変数 OFF を 強制
    os.environ.pop("ONEPIECE_AUDIT_INVARIANTS", None)
    legal_actions(state)
    assert state.audit_violations == []


def test_legal_actions_integration_audit_enabled():
    """audit ON で 違反 状態 を legal_actions 呼出 で 自動 catch。

    注意: 現在 の engine (= Bug 1 修正 後) は cannot_be_rested chara を attackers から 除外
    する ので 違反 起きない。 → 「engine が 正しく fix されている と invariant が clean」 を
    確認 する control test。
    """
    from engine.game import legal_actions
    repo = _repo()
    state = _make_state(repo)
    state.turn_number = 5
    me = state.players[0]
    me.don_active = 5
    ch = InPlay.of(repo.get("OP01-013"), sickness=False)
    ch.cannot_be_rested_buff = True
    ch.cannot_be_rested_applier_idx = 1
    ch.cannot_be_rested_applied_turn = 4
    me.characters = [ch]

    os.environ["ONEPIECE_AUDIT_INVARIANTS"] = "1"
    try:
        actions = legal_actions(state)
    finally:
        os.environ.pop("ONEPIECE_AUDIT_INVARIANTS", None)

    # 修正後 engine: chara は attackers から 除外 → invariant clean
    cannot_rest_violations = [
        v for v in state.audit_violations if v.get("rule_id") == "INV-cannot-rest-no-attack"
    ]
    assert cannot_rest_violations == [], (
        f"修正後 engine で 違反 検出 (= regression!): {cannot_rest_violations}"
    )
