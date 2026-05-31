# -*- coding: utf-8 -*-
"""二重コスト bug の regression guard。

[[project_card_effect_100_plan_kickoff]] 順2 prototype で発見・runtime 実証した
「top-level `cost` と do 内 `optional_cost_then` の cost が 2 重請求される」 bug の
再発防止。 109 entry を 修復済 (= fix_double_optional_cost*.py)。
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    TriggerEvent,
    _execute_event,
    fire_activate_main,
    load_effect_overlay,
    resolve_triggers,
)

ROOT = Path(__file__).resolve().parent.parent

# 実リソースを伴う cost キー (= once_per_turn 等の非リソースは除く)
REAL_COST_KEYS = {
    "rest_self_don", "discard_hand", "rest_self", "rest", "trash_self_hand_random",
    "pay_don", "return_self_don_to_deck", "return_self_don", "trash_self",
    # 2026-05-31 追加: inline 監査で trash_self + return_self_to_trash 系の二重 (16 entry) が
    # 旧 REAL set から漏れていた (OP14-083 / ST22-002 等)。 同義 self-cost spelling を網羅。
    "return_self_to_trash", "return_self_to_hand",
}
# 意図的に残す例外: rest_self の冪等重複のみで実害なし (ホーミーズ犠牲 cost は oct で 1 回)
ALLOWLIST = {"OP04-111"}


def _has_real_cost(cost) -> bool:
    if isinstance(cost, dict):
        return any(k in REAL_COST_KEYS for k in cost)
    if isinstance(cost, list):
        return any(_has_real_cost(c) for c in cost)
    return False


def test_no_entry_double_charges_cost():
    """全 overlay entry で top-level real cost と do 内 optional_cost_then real cost の
    二重持ちが ない こと (= 二重請求 0)。"""
    eff = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    offenders = []
    for cid, v in eff.items():
        if cid == "_meta" or not isinstance(v, list) or cid in ALLOWLIST:
            continue
        for ei, e in enumerate(v):
            if not isinstance(e, dict):
                continue
            if not _has_real_cost(e.get("cost")):
                continue
            for d in e.get("do", []):
                if isinstance(d, dict) and "optional_cost_then" in d:
                    if _has_real_cost(d["optional_cost_then"].get("cost", [])):
                        offenders.append(f"{cid} eff#{ei}")
    assert not offenders, f"二重コスト entry が残存: {offenders}"


def _state(repo, overlay, leader="OP01-001"):
    p1 = Player(name="P0", leader=InPlay.of(repo.get(leader), sickness=False))
    p2 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1.deck = [repo.get("OP01-013")] * 30
    p2.deck = [repo.get("OP01-013")] * 30
    p2.characters = [InPlay.of(repo.get("OP01-016"), sickness=False)]
    st = GameState(players=[p1, p2], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    p1.don_active = 10
    p1.don_rested = 0
    return st, p1, p2


def test_op14_096_main_rests_exactly_2_don():
    """OP14-096 浸食輪廻: 公式 ドン‼2枚レスト → 正確に 2 枚 (旧 bug: 4 枚)。"""
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p1, p2 = _state(repo, overlay, leader="OP13-079")
    _execute_event(st, TriggerEvent(when="main", owner_idx=0, source_card_id="OP14-096"))
    assert p1.don_rested == 2, f"expected 2, got {p1.don_rested}"


def test_op13_026_activate_main_rests_exactly_1_don():
    """OP13-026 サニーくん: 公式 ドン‼1枚レスト → 正確に 1 枚 (旧 bug: 2 枚)。"""
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    src = InPlay.of(repo.get("OP13-026"), sickness=False)
    st, p1, p2 = _state(repo, overlay)
    p1.characters = [src, InPlay.of(repo.get("OP01-016"), sickness=False)]
    p1.hand = [repo.get("OP01-013")] * 3
    am = [e for e in overlay["OP13-026"].effects if e.get("when") == "activate_main"][0]
    fire_activate_main(st, p1, p2, src, am)
    resolve_triggers(st)
    assert p1.don_rested == 1, f"expected 1, got {p1.don_rested}"
