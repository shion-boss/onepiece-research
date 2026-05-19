#!/usr/bin/env python3
"""Plan H Phase H-1 (= 2026-05-19): 15 deck の mirror target_v1.json を 一括生成。

archetype × speed × defense を 軸に 4 種類 の template を 定義、
各 deck の leader_id を 埋めて 27 entries を 出力。

# template 別 構造

各 deck で turn 2-10 × condition (= even/behind/advantage) = 27 entries
+ turn 1 even = 1 entry (= 計 28 entries)

# 使い方

```bash
.venv/bin/python scripts/generate_mirror_target_specs.py
# → decks/{slug}.target_v1.json を 15 deck 分 出力 (= cardrush_1456 除く)
```

# 設計

mirror entries は 「ターン目標 = deck の 自然な tempo」 に 沿って 書く:
- T1-2: search / tempo 確保
- T3-4: 中盤展開
- T5-7: finisher 段階
- T8-10: lethal 段階

archetype による 違い:
- control 低速 硬い: T1-7 で blocker + counter 厚く、 T8+ で finisher
- midrange 低速 硬い: T3-5 で 中堅展開、 T6+ で finisher
- midrange 中速 硬い: T1-3 早期 tempo、 T4-6 finisher
- midrange 高速 脆い: T1-3 急加速、 T4-5 lethal prep
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DECKS_DIR = REPO_ROOT / "decks"

# 15 deck (= cardrush_1456 除く) の archetype 分類
DECK_INFO = {
    "cardrush_1342": {"leader": "OP14-060", "name": "紫ドフラミンゴ", "template": "control_slow"},
    "cardrush_1385": {"leader": "OP14-079", "name": "黒クロコダイル", "template": "midrange_slow"},
    "cardrush_1392": {"leader": "OP13-079", "name": "黒イム", "template": "control_slow"},
    "cardrush_1399": {"leader": "OP15-002", "name": "赤青ルーシー", "template": "midrange_fast"},
    "cardrush_1439": {"leader": "OP11-041", "name": "青黄ナミ", "template": "control_slow"},
    "cardrush_1453": {"leader": "OP14-020", "name": "緑ミホーク", "template": "midrange_mid"},
    "cardrush_1454": {"leader": "OP15-058", "name": "紫エネル", "template": "midrange_fast"},
    "cardrush_1455": {"leader": "OP15-098", "name": "空島ルフィ", "template": "control_slow"},
    "tcgportal_bonney": {"leader": "EB04-001", "name": "赤黄ボニー", "template": "control_slow"},
    "tcgportal_calgara": {"leader": "OP08-098", "name": "黄カルガラ", "template": "midrange_slow"},
    "tcgportal_coby": {"leader": "OP11-001", "name": "赤黒コビー", "template": "midrange_mid"},
    "tcgportal_corazon": {"leader": "OP12-061", "name": "紫黄ロシナンテ", "template": "midrange_mid"},
    "tcgportal_hancock": {"leader": "OP14-041", "name": "青黄ハンコック", "template": "control_slow"},
    "tcgportal_op11_luffy": {"leader": "OP11-040", "name": "青紫ルフィ", "template": "midrange_slow"},
    "tcgportal_op13_luffy": {"leader": "OP13-001", "name": "赤緑ルフィOP13", "template": "midrange_slow"},
}


# ---------------------------------------------------------------------------
# Template builders (= 1 turn × 1 condition → list[targets])
# ---------------------------------------------------------------------------


def _t(priority: int, cond: dict, bonus: int, desc: str) -> dict:
    """1 target を build。"""
    return {"priority": priority, "if": cond, "bonus": bonus, "description": desc}


def _control_slow_targets(turn: int, condition: str) -> list[dict]:
    """control 低速 硬い (= 白ひげ / イム / ナミ / ドフラミンゴ / ボニー / ハンコック / 空島ルフィ)。

    特徴: 低速 build-up、 T1-5 で 防御層 + 手札、 T6+ で finisher、 T8+ で lethal。
    """
    if turn == 1:
        return [
            _t(1, {"self_chara_count_ge": 1, "self_hand_ge": 4}, 1000, "T1: 1c chara 展開、 手札 4 維持"),
            _t(2, {"self_leader_attached_don_ge": 1}, 500, "fallback: leader don 付与"),
        ]
    if turn == 2:
        if condition == "behind":
            return [
                _t(1, {"self_chara_count_ge": 1, "self_hand_ge": 5, "self_counter_in_hand_ge": 4000}, 1100, "behind T2: 手札 + counter 確保"),
                _t(2, {"self_hand_ge": 5}, 700, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"self_chara_count_ge": 2, "self_leader_attached_don_ge": 1}, 1100, "advantage T2: 場 2 + don 付与"),
                _t(2, {"self_chara_count_ge": 2}, 700, "fallback"),
            ]
        return [
            _t(1, {"self_chara_count_ge": 2, "self_hand_ge": 5}, 1000, "even T2: 場 2 + 手札 5"),
            _t(2, {"self_chara_count_ge": 1, "self_hand_ge": 4}, 600, "fallback"),
        ]
    if turn == 3:
        if condition == "behind":
            return [
                _t(1, {"self_counter_in_hand_ge": 6000, "self_hand_ge": 5}, 1200, "behind T3: counter 6000 + 手札 5"),
                _t(2, {"self_hand_ge": 5}, 700, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"self_chara_count_ge": 2, "self_chara_attached_don_ge": 1}, 1200, "advantage T3: chara don 付与 push"),
                _t(2, {"self_chara_count_ge": 2}, 700, "fallback"),
            ]
        return [
            _t(1, {"self_chara_count_ge": 2, "self_hand_ge": 5}, 1100, "even T3: 中盤準備"),
            _t(2, {"self_chara_count_ge": 1}, 600, "fallback"),
        ]
    if turn == 4:
        if condition == "behind":
            return [
                _t(1, {"self_blocker_count_ge": 1, "self_counter_in_hand_ge": 8000}, 1500, "behind T4: blocker 1 + counter 8000"),
                _t(2, {"self_counter_in_hand_ge": 8000}, 900, "fallback: counter のみ"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"self_field_power_ge": 6000, "self_blocker_count_ge": 1}, 1300, "advantage T4: 場 6000 + blocker"),
                _t(2, {"self_chara_count_ge": 3}, 800, "fallback"),
            ]
        return [
            _t(1, {"self_blocker_count_ge": 1, "self_chara_count_ge": 2, "self_hand_ge": 4}, 1400, "even T4: blocker + 場 2 + 手札"),
            _t(2, {"self_chara_count_ge": 2}, 800, "fallback"),
        ]
    if turn == 5:
        if condition == "behind":
            return [
                _t(1, {"self_blocker_count_ge": 2, "self_counter_in_hand_ge": 8000}, 1600, "behind T5: blocker 2 + counter 8000"),
                _t(2, {"self_blocker_count_ge": 1, "self_counter_in_hand_ge": 8000}, 1000, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"self_field_power_ge": 9000, "self_chara_count_ge": 3}, 1400, "advantage T5: 場 9000 + 3 体"),
                _t(2, {"self_chara_count_ge": 3}, 900, "fallback"),
            ]
        return [
            _t(1, {"self_chara_count_ge": 3, "self_blocker_count_ge": 1, "self_hand_ge": 5}, 1500, "even T5: 場 3 + blocker + 手札"),
            _t(2, {"self_chara_count_ge": 2, "self_blocker_count_ge": 1}, 900, "fallback"),
        ]
    if turn == 6:
        if condition == "behind":
            return [
                _t(1, {"self_finisher_on_field_ge": 1, "self_blocker_count_ge": 2, "self_counter_in_hand_ge": 6000}, 1700, "behind T6: 除去 + blocker 2 + counter"),
                _t(2, {"self_blocker_count_ge": 2, "self_counter_in_hand_ge": 8000}, 1100, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"self_finisher_on_field_ge": 1, "self_field_power_ge": 11000, "opp_life_le": 3}, 1700, "advantage T6: finisher + 場 11000 + ライフ 3"),
                _t(2, {"self_finisher_on_field_ge": 1, "self_field_power_ge": 9000}, 1100, "fallback"),
            ]
        return [
            _t(1, {"self_finisher_on_field_ge": 1, "self_chara_count_ge": 2, "self_blocker_count_ge": 1}, 1600, "even T6: finisher 1 + 場 2 + blocker"),
            _t(2, {"self_field_power_ge": 8000}, 1000, "fallback"),
        ]
    if turn == 7:
        if condition == "behind":
            return [
                _t(1, {"self_finisher_on_field_ge": 1, "self_blocker_count_ge": 2, "self_counter_in_hand_ge": 8000}, 1800, "behind T7: finisher + blocker 2 + counter"),
                _t(2, {"self_blocker_count_ge": 2, "self_finisher_on_field_ge": 1}, 1200, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"self_finisher_on_field_ge": 2, "self_field_power_ge": 13000, "opp_life_le": 2}, 1900, "advantage T7: finisher 2 + ライフ 2"),
                _t(2, {"self_finisher_on_field_ge": 2, "opp_life_le": 3}, 1400, "fallback"),
            ]
        return [
            _t(1, {"self_finisher_on_field_ge": 2, "self_field_power_ge": 12000, "self_blocker_count_ge": 1}, 1800, "even T7: finisher 2 + 場 12000"),
            _t(2, {"self_finisher_on_field_ge": 1, "self_field_power_ge": 10000}, 1200, "fallback"),
        ]
    if turn == 8:
        if condition == "behind":
            return [
                _t(1, {"self_finisher_on_field_ge": 2, "self_blocker_count_ge": 1, "self_counter_in_hand_ge": 8000}, 1900, "behind T8: 一発逆転 finisher 2"),
                _t(2, {"self_blocker_count_ge": 2, "self_counter_in_hand_ge": 10000}, 1200, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"opp_life_le": 1, "self_finisher_on_field_ge": 2, "self_field_power_ge": 14000}, 2000, "advantage T8: ライフ 1 = リーサル直前"),
                _t(2, {"opp_life_le": 2, "self_field_power_ge": 13000}, 1500, "fallback"),
            ]
        return [
            _t(1, {"self_finisher_on_field_ge": 2, "self_field_power_ge": 15000, "opp_life_le": 3}, 1900, "even T8: finisher 2 + 場 15000 + ライフ 3"),
            _t(2, {"self_finisher_on_field_ge": 2, "self_field_power_ge": 13000}, 1300, "fallback"),
        ]
    if turn == 9:
        if condition == "behind":
            return [
                _t(1, {"self_finisher_on_field_ge": 2, "self_counter_in_hand_ge": 10000, "self_blocker_count_ge": 1}, 1900, "behind T9: 反撃 finisher 2"),
                _t(2, {"self_blocker_count_ge": 2, "self_counter_in_hand_ge": 12000}, 1200, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"opp_life_le": 0, "self_finisher_on_field_ge": 2}, 2000, "advantage T9: ライフ 0 = 勝利確定"),
                _t(2, {"opp_life_le": 1, "self_field_power_ge": 13000}, 1500, "fallback"),
            ]
        return [
            _t(1, {"opp_life_le": 1, "self_finisher_on_field_ge": 2, "self_field_power_ge": 13000}, 2000, "even T9: ライフ 1 = リーサル"),
            _t(2, {"opp_life_le": 2, "self_finisher_on_field_ge": 2}, 1500, "fallback"),
        ]
    if turn == 10:
        if condition == "behind":
            return [
                _t(1, {"self_finisher_on_field_ge": 2, "self_field_power_ge": 14000, "self_counter_in_hand_ge": 8000}, 1800, "behind T10: 最終反撃"),
                _t(2, {"self_blocker_count_ge": 2, "self_counter_in_hand_ge": 12000}, 1100, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"opp_life_le": 0, "self_finisher_on_field_ge": 2}, 2000, "advantage T10: 確実 lethal"),
                _t(2, {"opp_life_le": 1, "self_field_power_ge": 14000}, 1500, "fallback"),
            ]
        return [
            _t(1, {"opp_life_le": 0, "self_finisher_on_field_ge": 2}, 2000, "even T10: lethal"),
            _t(2, {"opp_life_le": 1, "self_field_power_ge": 13000}, 1500, "fallback"),
        ]
    return []


def _midrange_slow_targets(turn: int, condition: str) -> list[dict]:
    """midrange 低速 硬い (= クロコ / ミホーク / カルガラ / 青紫ルフィ / 赤緑ルフィ OP13)。

    控えめ tempo + T4-6 で 中堅 + T7+ で finisher。
    """
    if turn == 1:
        return [
            _t(1, {"self_chara_count_ge": 1, "self_hand_ge": 4}, 1000, "T1: 1c chara 展開"),
            _t(2, {"self_leader_attached_don_ge": 1}, 500, "fallback"),
        ]
    if turn == 2:
        if condition == "behind":
            return [
                _t(1, {"self_chara_count_ge": 1, "self_hand_ge": 5, "self_counter_in_hand_ge": 3000}, 1100, "behind T2: counter 確保"),
                _t(2, {"self_hand_ge": 5}, 700, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"self_chara_count_ge": 2, "self_leader_attached_don_ge": 1}, 1100, "advantage T2: 場 2 + push"),
                _t(2, {"self_chara_count_ge": 2}, 700, "fallback"),
            ]
        return [
            _t(1, {"self_chara_count_ge": 2, "self_hand_ge": 5}, 1000, "even T2: 場 2 + 手札"),
            _t(2, {"self_chara_count_ge": 1}, 600, "fallback"),
        ]
    if turn == 3:
        if condition == "behind":
            return [
                _t(1, {"self_chara_count_ge": 2, "self_counter_in_hand_ge": 5000}, 1200, "behind T3: 場 2 + counter"),
                _t(2, {"self_counter_in_hand_ge": 6000}, 700, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"self_chara_count_ge": 3, "self_chara_attached_don_ge": 1}, 1200, "advantage T3: 場 3 + don push"),
                _t(2, {"self_chara_count_ge": 2}, 700, "fallback"),
            ]
        return [
            _t(1, {"self_chara_count_ge": 2, "self_field_power_ge": 4000}, 1100, "even T3: 場 2 + power 4000"),
            _t(2, {"self_chara_count_ge": 2}, 700, "fallback"),
        ]
    if turn == 4:
        if condition == "behind":
            return [
                _t(1, {"self_blocker_count_ge": 1, "self_counter_in_hand_ge": 6000, "self_hand_ge": 4}, 1400, "behind T4: blocker + counter"),
                _t(2, {"self_counter_in_hand_ge": 8000}, 900, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"self_field_power_ge": 7000, "self_chara_count_ge": 3}, 1300, "advantage T4: 場 7000 + 3 体"),
                _t(2, {"self_chara_count_ge": 3}, 800, "fallback"),
            ]
        return [
            _t(1, {"self_chara_count_ge": 2, "self_field_power_ge": 6000, "self_hand_ge": 4}, 1300, "even T4: 場 2 + 6000 power"),
            _t(2, {"self_chara_count_ge": 2}, 800, "fallback"),
        ]
    if turn == 5:
        if condition == "behind":
            return [
                _t(1, {"self_blocker_count_ge": 1, "self_counter_in_hand_ge": 8000, "self_chara_count_ge": 2}, 1500, "behind T5: 受け体勢"),
                _t(2, {"self_blocker_count_ge": 1, "self_counter_in_hand_ge": 6000}, 1000, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"self_field_power_ge": 9000, "self_chara_count_ge": 3}, 1400, "advantage T5: 場 9000 + 3 体"),
                _t(2, {"self_chara_count_ge": 3, "self_field_power_ge": 7000}, 900, "fallback"),
            ]
        return [
            _t(1, {"self_chara_count_ge": 3, "self_field_power_ge": 8000}, 1400, "even T5: 場 3 + 8000 power"),
            _t(2, {"self_chara_count_ge": 2, "self_field_power_ge": 6000}, 900, "fallback"),
        ]
    if turn == 6:
        if condition == "behind":
            return [
                _t(1, {"self_finisher_on_field_ge": 1, "self_blocker_count_ge": 1, "self_counter_in_hand_ge": 6000}, 1600, "behind T6: finisher + 受け"),
                _t(2, {"self_chara_count_ge": 3, "self_counter_in_hand_ge": 8000}, 1100, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"self_finisher_on_field_ge": 1, "self_field_power_ge": 11000, "opp_life_le": 3}, 1700, "advantage T6: finisher + ライフ 3"),
                _t(2, {"self_finisher_on_field_ge": 1, "self_field_power_ge": 9000}, 1100, "fallback"),
            ]
        return [
            _t(1, {"self_finisher_on_field_ge": 1, "self_field_power_ge": 10000, "self_chara_count_ge": 2}, 1500, "even T6: finisher + 場 10000"),
            _t(2, {"self_field_power_ge": 8000}, 1000, "fallback"),
        ]
    if turn == 7:
        if condition == "behind":
            return [
                _t(1, {"self_finisher_on_field_ge": 1, "self_blocker_count_ge": 1, "self_counter_in_hand_ge": 8000}, 1700, "behind T7: finisher + 受け継続"),
                _t(2, {"self_finisher_on_field_ge": 1, "self_blocker_count_ge": 1}, 1100, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"self_finisher_on_field_ge": 2, "self_field_power_ge": 13000, "opp_life_le": 2}, 1900, "advantage T7: finisher 2 + ライフ 2"),
                _t(2, {"self_finisher_on_field_ge": 2, "opp_life_le": 3}, 1400, "fallback"),
            ]
        return [
            _t(1, {"self_finisher_on_field_ge": 2, "self_field_power_ge": 12000}, 1700, "even T7: finisher 2"),
            _t(2, {"self_finisher_on_field_ge": 1, "self_field_power_ge": 10000}, 1100, "fallback"),
        ]
    if turn == 8:
        if condition == "behind":
            return [
                _t(1, {"self_finisher_on_field_ge": 2, "self_blocker_count_ge": 1, "self_counter_in_hand_ge": 8000}, 1800, "behind T8: 反撃"),
                _t(2, {"self_blocker_count_ge": 1, "self_counter_in_hand_ge": 10000}, 1200, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"opp_life_le": 1, "self_finisher_on_field_ge": 2, "self_field_power_ge": 14000}, 2000, "advantage T8: ライフ 1"),
                _t(2, {"opp_life_le": 2, "self_finisher_on_field_ge": 2}, 1500, "fallback"),
            ]
        return [
            _t(1, {"self_finisher_on_field_ge": 2, "self_field_power_ge": 14000, "opp_life_le": 3}, 1800, "even T8: lethal prep"),
            _t(2, {"self_finisher_on_field_ge": 2, "opp_life_le": 4}, 1300, "fallback"),
        ]
    if turn == 9:
        if condition == "behind":
            return [
                _t(1, {"self_finisher_on_field_ge": 2, "self_counter_in_hand_ge": 8000}, 1800, "behind T9: 反撃 finisher 2"),
                _t(2, {"self_blocker_count_ge": 1, "self_counter_in_hand_ge": 10000}, 1100, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"opp_life_le": 0, "self_finisher_on_field_ge": 2}, 2000, "advantage T9: ライフ 0"),
                _t(2, {"opp_life_le": 1, "self_field_power_ge": 13000}, 1500, "fallback"),
            ]
        return [
            _t(1, {"opp_life_le": 1, "self_finisher_on_field_ge": 2, "self_field_power_ge": 13000}, 1900, "even T9: ライフ 1"),
            _t(2, {"opp_life_le": 2, "self_finisher_on_field_ge": 2}, 1400, "fallback"),
        ]
    if turn == 10:
        if condition == "behind":
            return [
                _t(1, {"self_finisher_on_field_ge": 2, "self_field_power_ge": 14000, "self_counter_in_hand_ge": 8000}, 1700, "behind T10: 最終"),
                _t(2, {"self_blocker_count_ge": 1, "self_counter_in_hand_ge": 10000}, 1100, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"opp_life_le": 0, "self_finisher_on_field_ge": 2}, 2000, "advantage T10: 確実 lethal"),
                _t(2, {"opp_life_le": 1, "self_field_power_ge": 14000}, 1500, "fallback"),
            ]
        return [
            _t(1, {"opp_life_le": 0, "self_finisher_on_field_ge": 2}, 2000, "even T10: lethal"),
            _t(2, {"opp_life_le": 1, "self_field_power_ge": 13000}, 1500, "fallback"),
        ]
    return []


def _midrange_mid_targets(turn: int, condition: str) -> list[dict]:
    """midrange 中速 (= coby / corazon)。

    早期 tempo 加速 + T4-6 で 中堅 finisher。
    """
    if turn == 1:
        return [
            _t(1, {"self_chara_count_ge": 1, "self_leader_attached_don_ge": 1}, 1000, "T1: chara + don push"),
            _t(2, {"self_chara_count_ge": 1}, 600, "fallback"),
        ]
    if turn == 2:
        if condition == "behind":
            return [
                _t(1, {"self_chara_count_ge": 1, "self_counter_in_hand_ge": 4000, "self_hand_ge": 5}, 1100, "behind T2: counter"),
                _t(2, {"self_hand_ge": 5}, 700, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"self_chara_count_ge": 2, "self_field_power_ge": 4000}, 1100, "advantage T2"),
                _t(2, {"self_chara_count_ge": 2}, 700, "fallback"),
            ]
        return [
            _t(1, {"self_chara_count_ge": 2, "self_field_power_ge": 4000}, 1000, "even T2"),
            _t(2, {"self_chara_count_ge": 1}, 600, "fallback"),
        ]
    if turn == 3:
        if condition == "behind":
            return [
                _t(1, {"self_chara_count_ge": 2, "self_counter_in_hand_ge": 5000}, 1100, "behind T3"),
                _t(2, {"self_counter_in_hand_ge": 6000}, 700, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"self_chara_count_ge": 3, "self_field_power_ge": 6000, "opp_life_le": 4}, 1300, "advantage T3: push"),
                _t(2, {"self_chara_count_ge": 2}, 700, "fallback"),
            ]
        return [
            _t(1, {"self_chara_count_ge": 2, "self_field_power_ge": 6000}, 1100, "even T3"),
            _t(2, {"self_chara_count_ge": 2}, 700, "fallback"),
        ]
    if turn == 4:
        if condition == "behind":
            return [
                _t(1, {"self_blocker_count_ge": 1, "self_counter_in_hand_ge": 6000}, 1400, "behind T4"),
                _t(2, {"self_counter_in_hand_ge": 8000}, 900, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"self_finisher_on_field_ge": 1, "self_field_power_ge": 8000, "opp_life_le": 3}, 1500, "advantage T4: finisher 早期"),
                _t(2, {"self_field_power_ge": 7000}, 900, "fallback"),
            ]
        return [
            _t(1, {"self_chara_count_ge": 3, "self_field_power_ge": 7000}, 1300, "even T4"),
            _t(2, {"self_chara_count_ge": 2}, 800, "fallback"),
        ]
    if turn == 5:
        if condition == "behind":
            return [
                _t(1, {"self_blocker_count_ge": 1, "self_counter_in_hand_ge": 8000}, 1500, "behind T5"),
                _t(2, {"self_counter_in_hand_ge": 8000}, 1000, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"self_finisher_on_field_ge": 2, "opp_life_le": 2}, 1700, "advantage T5: finisher 2"),
                _t(2, {"self_finisher_on_field_ge": 1, "opp_life_le": 3}, 1100, "fallback"),
            ]
        return [
            _t(1, {"self_finisher_on_field_ge": 1, "self_field_power_ge": 9000}, 1400, "even T5: finisher"),
            _t(2, {"self_field_power_ge": 8000}, 900, "fallback"),
        ]
    if turn == 6:
        if condition == "behind":
            return [
                _t(1, {"self_finisher_on_field_ge": 1, "self_blocker_count_ge": 1, "self_counter_in_hand_ge": 6000}, 1600, "behind T6"),
                _t(2, {"self_blocker_count_ge": 1, "self_counter_in_hand_ge": 8000}, 1100, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"opp_life_le": 1, "self_finisher_on_field_ge": 2, "self_field_power_ge": 12000}, 1900, "advantage T6: lethal"),
                _t(2, {"opp_life_le": 2, "self_finisher_on_field_ge": 2}, 1400, "fallback"),
            ]
        return [
            _t(1, {"self_finisher_on_field_ge": 2, "self_field_power_ge": 11000, "opp_life_le": 3}, 1700, "even T6: finisher 2"),
            _t(2, {"self_finisher_on_field_ge": 1, "opp_life_le": 4}, 1100, "fallback"),
        ]
    if turn == 7:
        if condition == "behind":
            return [
                _t(1, {"self_finisher_on_field_ge": 1, "self_counter_in_hand_ge": 8000}, 1700, "behind T7"),
                _t(2, {"self_blocker_count_ge": 1, "self_counter_in_hand_ge": 8000}, 1100, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"opp_life_le": 0, "self_finisher_on_field_ge": 2}, 2000, "advantage T7: ライフ 0"),
                _t(2, {"opp_life_le": 1, "self_finisher_on_field_ge": 2}, 1500, "fallback"),
            ]
        return [
            _t(1, {"opp_life_le": 1, "self_finisher_on_field_ge": 2, "self_field_power_ge": 12000}, 1900, "even T7: lethal prep"),
            _t(2, {"opp_life_le": 2, "self_finisher_on_field_ge": 2}, 1400, "fallback"),
        ]
    if turn >= 8:
        if condition == "behind":
            return [
                _t(1, {"self_finisher_on_field_ge": 2, "self_counter_in_hand_ge": 8000}, 1800, "behind T8+: 反撃"),
                _t(2, {"self_blocker_count_ge": 1, "self_counter_in_hand_ge": 10000}, 1100, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"opp_life_le": 0, "self_finisher_on_field_ge": 2}, 2000, "advantage T8+: lethal"),
                _t(2, {"opp_life_le": 1, "self_field_power_ge": 13000}, 1500, "fallback"),
            ]
        return [
            _t(1, {"opp_life_le": 0, "self_finisher_on_field_ge": 2}, 2000, "even T8+: lethal"),
            _t(2, {"opp_life_le": 1, "self_finisher_on_field_ge": 2}, 1500, "fallback"),
        ]
    return []


def _midrange_fast_targets(turn: int, condition: str) -> list[dict]:
    """midrange 高速 脆い (= ルーシー / エネル)。

    急加速 早期 lethal、 防御薄 でも 攻撃 優先。
    """
    if turn == 1:
        return [
            _t(1, {"self_chara_count_ge": 1, "self_leader_attached_don_ge": 1}, 1000, "T1: chara + don aggressive"),
            _t(2, {"self_chara_count_ge": 1}, 600, "fallback"),
        ]
    if turn == 2:
        if condition == "behind":
            return [
                _t(1, {"self_chara_count_ge": 2, "self_counter_in_hand_ge": 3000}, 1100, "behind T2"),
                _t(2, {"self_chara_count_ge": 1}, 600, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"self_chara_count_ge": 2, "self_field_power_ge": 5000, "opp_life_le": 4}, 1300, "advantage T2: 早期 push"),
                _t(2, {"self_chara_count_ge": 2}, 800, "fallback"),
            ]
        return [
            _t(1, {"self_chara_count_ge": 2, "self_field_power_ge": 5000}, 1100, "even T2"),
            _t(2, {"self_chara_count_ge": 2}, 700, "fallback"),
        ]
    if turn == 3:
        if condition == "behind":
            return [
                _t(1, {"self_chara_count_ge": 2, "self_counter_in_hand_ge": 4000}, 1100, "behind T3"),
                _t(2, {"self_counter_in_hand_ge": 5000}, 700, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"self_field_power_ge": 7000, "opp_life_le": 3}, 1500, "advantage T3: 早期 lethal 視野"),
                _t(2, {"self_chara_count_ge": 3}, 900, "fallback"),
            ]
        return [
            _t(1, {"self_chara_count_ge": 3, "self_field_power_ge": 6000}, 1200, "even T3"),
            _t(2, {"self_chara_count_ge": 2}, 700, "fallback"),
        ]
    if turn == 4:
        if condition == "behind":
            return [
                _t(1, {"self_counter_in_hand_ge": 5000, "self_chara_count_ge": 2}, 1300, "behind T4: 反撃準備"),
                _t(2, {"self_counter_in_hand_ge": 6000}, 800, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"opp_life_le": 2, "self_field_power_ge": 9000}, 1700, "advantage T4: 早期 lethal"),
                _t(2, {"self_field_power_ge": 8000, "opp_life_le": 3}, 1200, "fallback"),
            ]
        return [
            _t(1, {"self_chara_count_ge": 3, "self_field_power_ge": 8000, "opp_life_le": 3}, 1500, "even T4: push"),
            _t(2, {"self_field_power_ge": 7000}, 900, "fallback"),
        ]
    if turn == 5:
        if condition == "behind":
            return [
                _t(1, {"self_counter_in_hand_ge": 6000, "self_chara_count_ge": 2}, 1400, "behind T5"),
                _t(2, {"self_counter_in_hand_ge": 6000}, 900, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"opp_life_le": 1, "self_field_power_ge": 10000}, 1900, "advantage T5: lethal 直前"),
                _t(2, {"opp_life_le": 2, "self_finisher_on_field_ge": 1}, 1300, "fallback"),
            ]
        return [
            _t(1, {"self_finisher_on_field_ge": 1, "opp_life_le": 2, "self_field_power_ge": 9000}, 1700, "even T5: lethal prep"),
            _t(2, {"self_finisher_on_field_ge": 1, "opp_life_le": 3}, 1100, "fallback"),
        ]
    if turn >= 6:
        if condition == "behind":
            return [
                _t(1, {"self_counter_in_hand_ge": 8000, "self_chara_count_ge": 2}, 1500, "behind T6+: 反撃"),
                _t(2, {"self_counter_in_hand_ge": 8000}, 1000, "fallback"),
            ]
        if condition == "advantage":
            return [
                _t(1, {"opp_life_le": 0, "self_finisher_on_field_ge": 1}, 2000, "advantage T6+: lethal"),
                _t(2, {"opp_life_le": 1, "self_field_power_ge": 11000}, 1500, "fallback"),
            ]
        return [
            _t(1, {"opp_life_le": 1, "self_finisher_on_field_ge": 1, "self_field_power_ge": 11000}, 1900, "even T6+: lethal"),
            _t(2, {"opp_life_le": 2, "self_field_power_ge": 10000}, 1400, "fallback"),
        ]
    return []


TEMPLATES = {
    "control_slow": _control_slow_targets,
    "midrange_slow": _midrange_slow_targets,
    "midrange_mid": _midrange_mid_targets,
    "midrange_fast": _midrange_fast_targets,
}


# ---------------------------------------------------------------------------
# 生成
# ---------------------------------------------------------------------------


def generate_target_spec_for_deck(deck_slug: str, info: dict) -> dict:
    """1 deck の mirror target_v1.json を 生成。"""
    leader_id = info["leader"]
    template_fn = TEMPLATES[info["template"]]
    entries = []

    # T1 even のみ (= mirror で T1 condition は ほぼ even)
    targets = template_fn(1, "even")
    entries.append({
        "turn": 1,
        "opp_leader_id": leader_id,
        "opp_deck_slug": deck_slug,
        "opp_archetype": info["template"].split("_")[0],
        "self_condition": "even",
        "targets": targets,
    })

    # T2-10 × condition (= 9 turn × 3 cond = 27 entry)
    for turn in range(2, 11):
        for cond in ("even", "behind", "advantage"):
            targets = template_fn(turn, cond)
            entries.append({
                "turn": turn,
                "opp_leader_id": leader_id,
                "opp_deck_slug": deck_slug,
                "opp_archetype": info["template"].split("_")[0],
                "self_condition": cond,
                "targets": targets,
            })

    return {
        "deck_slug": deck_slug,
        "leader_id": leader_id,
        "archetype": info["template"].split("_")[0],
        "generated_by": "Plan H generate_mirror_target_specs.py (= template-based, mirror only)",
        "model": "claude-opus-4-7 + generator",
        "entries": entries,
    }


def main() -> None:
    for slug, info in DECK_INFO.items():
        spec = generate_target_spec_for_deck(slug, info)
        out_path = DECKS_DIR / f"{slug}.target_v1.json"
        out_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  {slug:30s} → {len(spec['entries'])} entries (template={info['template']})")
    print(f"\nwrote {len(DECK_INFO)} deck target_v1.json files")


if __name__ == "__main__":
    main()
