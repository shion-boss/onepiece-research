"""Phase 2 runtime invariant checker (= 2026-05-28、 docs/AUTO_AUDIT_SYSTEM.md Layer 2)。

公式 ルール + カード text 由来 の **観測 可能 invariant** を 宣言 + runtime 検証。
engine 実装 の 思考 漏れ を 機械的 に 検出 (= Bug 1 系 を 取りこぼさない)。

## 使い方

### A. 単体 check (= test 用)

```python
from engine.audit_invariants import check_state_invariants, check_legal_actions_invariants

for violation in check_state_invariants(state):
    print(violation)

actions = legal_actions(state)
for violation in check_legal_actions_invariants(state, actions):
    print(violation)
```

### B. runtime hook (= 学習 中 / AI vs AI 中 全自動 監査)

```bash
# env var で 有効化 (= off だと 完全 zero-overhead)
ONEPIECE_AUDIT_INVARIANTS=1 .venv/bin/python scripts/eval_with_entry_firings.py ...
```

`engine/game.py:legal_actions` が module 末尾 で env 確認 → 自動 check。 違反 検出 で
`state.audit_violations.append(...)` + log push。

## invariant 一覧

### 状態 invariant (= state ごと 確認)

- INV-life-range            : 0 ≤ len(P.life) ≤ 5
- INV-hand-nonneg           : len(P.hand) ≥ 0
- INV-don-total             : P.don_active + P.don_rested ≤ 10
- INV-deck-nonneg           : len(P.deck) ≥ 0
- INV-leader-exists         : P.leader is not None

### 行動 invariant (= legal_actions 出力 ごと 確認)

- INV-cannot-rest-no-attack : cannot_be_rested_buff の chara は attacker に 含まれない
  (= Bug 1 を catch)
- INV-rested-no-attack      : rested=True の chara は attacker に 含まれない
- INV-summoning-no-attack   : summoning_sickness の chara は (rush 持ち以外) attacker に
  含まれない

### 効果 invariant (= effect_event ごと 確認、 Phase 2.5 で 追加 予定)

- INV-ko-removed-from-field
- INV-power-pump-delta
- INV-cost-paid
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterator


@dataclass
class AuditViolation:
    """invariant 違反 1 件。"""
    rule_id: str
    severity: int  # 5=critical, 4=high, 3=medium, 2=low, 1=info
    message: str
    evidence: dict
    turn: int | None = None
    phase: str | None = None

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "message": self.message,
            "evidence": self.evidence,
            "turn": self.turn,
            "phase": self.phase,
        }


def check_state_invariants(state: Any) -> Iterator[AuditViolation]:
    """state 全体 の 静的 invariant を 検証。"""
    turn = getattr(state, "turn_number", None)
    phase = getattr(state.phase, "name", None) if getattr(state, "phase", None) else None

    for p_idx, p in enumerate(state.players):
        # life nonneg (= 公式 OPTCG では effect で 5 超 可、 例: 「自分のライフ追加」 系)
        life_len = len(p.life)
        if life_len < 0:
            yield AuditViolation(
                rule_id="INV-life-nonneg",
                severity=5,
                message=f"P{p_idx} life length {life_len} negative",
                evidence={"player_idx": p_idx, "life_len": life_len},
                turn=turn, phase=phase,
            )

        # hand nonneg
        if len(p.hand) < 0:
            yield AuditViolation(
                rule_id="INV-hand-nonneg",
                severity=5,
                message=f"P{p_idx} hand size negative",
                evidence={"player_idx": p_idx, "hand": len(p.hand)},
                turn=turn, phase=phase,
            )

        # don total
        don_total = p.don_active + p.don_rested
        if don_total < 0 or don_total > 10:
            yield AuditViolation(
                rule_id="INV-don-total",
                severity=5,
                message=f"P{p_idx} don total {don_total} out of [0, 10]",
                evidence={
                    "player_idx": p_idx,
                    "don_active": p.don_active,
                    "don_rested": p.don_rested,
                },
                turn=turn, phase=phase,
            )

        # deck nonneg
        if len(p.deck) < 0:
            yield AuditViolation(
                rule_id="INV-deck-nonneg",
                severity=5,
                message=f"P{p_idx} deck size negative",
                evidence={"player_idx": p_idx, "deck": len(p.deck)},
                turn=turn, phase=phase,
            )

        # leader exists
        if p.leader is None:
            yield AuditViolation(
                rule_id="INV-leader-exists",
                severity=5,
                message=f"P{p_idx} leader is None",
                evidence={"player_idx": p_idx},
                turn=turn, phase=phase,
            )


def check_legal_actions_invariants(state: Any, actions: list) -> Iterator[AuditViolation]:
    """legal_actions の 出力 list に 対する invariant を 検証。"""
    turn = getattr(state, "turn_number", None)
    phase = getattr(state.phase, "name", None) if getattr(state, "phase", None) else None
    me = state.players[state.turn_player_idx]

    # attacker iid set
    attacker_iids = set()
    for a in actions:
        iid = getattr(a, "attacker_iid", None)
        if iid is not None:
            attacker_iids.add(iid)

    if not attacker_iids:
        return

    # 全 自陣 chara (= leader + characters) を 走査 → 違反 確認
    for ch in [me.leader] + list(me.characters):
        if ch.instance_id not in attacker_iids:
            continue

        # INV-cannot-rest-no-attack (= Bug 1 catch)
        if getattr(ch, "cannot_be_rested_buff", False):
            yield AuditViolation(
                rule_id="INV-cannot-rest-no-attack",
                severity=5,
                message=f"{ch.card.name} has cannot_be_rested_buff=True but appears as attacker "
                        f"(= 公式: 攻撃 は REST 化、 cannot_be_rested と 矛盾)",
                evidence={
                    "card_id": ch.card.card_id,
                    "card_name": ch.card.name,
                    "instance_id": ch.instance_id,
                    "applier_idx": getattr(ch, "cannot_be_rested_applier_idx", -1),
                    "applied_turn": getattr(ch, "cannot_be_rested_applied_turn", 0),
                },
                turn=turn, phase=phase,
            )

        # INV-rested-no-attack
        if getattr(ch, "rested", False):
            yield AuditViolation(
                rule_id="INV-rested-no-attack",
                severity=5,
                message=f"{ch.card.name} is rested but appears as attacker",
                evidence={
                    "card_id": ch.card.card_id,
                    "instance_id": ch.instance_id,
                },
                turn=turn, phase=phase,
            )

        # INV-summoning-no-attack (= rush 持ち / 速攻:キャラ は 例外)
        if (getattr(ch, "summoning_sickness", False)
            and not getattr(ch, "is_rush_now", False)
            and not getattr(ch, "is_rush_chara_only_now", False)):
            yield AuditViolation(
                rule_id="INV-summoning-no-attack",
                severity=5,
                message=f"{ch.card.name} has summoning_sickness without rush but is attacker",
                evidence={
                    "card_id": ch.card.card_id,
                    "instance_id": ch.instance_id,
                },
                turn=turn, phase=phase,
            )


def is_audit_enabled() -> bool:
    """env var で runtime audit を 有効化 する か。 default off (= zero overhead)。"""
    return os.environ.get("ONEPIECE_AUDIT_INVARIANTS", "0") in ("1", "true", "True")


def run_all_checks(state: Any, actions: list | None = None) -> list[AuditViolation]:
    """全 invariant を 走らせて list で 返す。"""
    out = list(check_state_invariants(state))
    if actions is not None:
        out += list(check_legal_actions_invariants(state, actions))
    return out
