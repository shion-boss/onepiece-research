# -*- coding: utf-8 -*-
"""Plan H: Goal-directed target spec DSL (2026-05-18 着手)。

Claude が deck × turn × matchup × condition で 「ターン終了時の 目標盤面」 を
書き出す ための DSL。 既存 `engine/effects.py` の `eval_condition` primitive を 流用
+ Plan H 固有の target primitive を 追加。

# target spec format (= Claude が 書く JSON)

```json
{
  "deck_slug": "cardrush_1456",
  "leader_id": "OP13-002",
  "entries": [
    {
      "turn": 4,
      "opp_leader_id": "OP12-001",          // 個別 leader 軸 (= 折りたたまない)
      "opp_deck_slug": "tcgportal_coby",    // 参考 hint
      "self_condition": "behind",            // advantage/even/behind
      "targets": [
        {
          "priority": 1,
          "if": {"self_field_power_ge": 7000, "self_chara_feature_count_ge": {"feature": "白ひげ海賊団", "count": 1}},
          "bonus": 1000,
          "description": "..."
        },
        {
          "priority": 2,
          "if": {"self_field_count_ge": 2},
          "bonus": 500,
          "description": "fallback"
        }
      ]
    }
  ]
}
```

# 思想

- target は **soft bonus** (= 達成 → +bonus、 未達 → 0)、 既存 `compute_score` の 補助
- 「ターン目標 を 持つ」 = plan_search の leaf eval で target に 近い leaf を 優先
- priority chain で fallback (= target 達成不可 でも 設計通り 動く)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .core import GameState
from .effects import eval_condition


# ===========================================================================
# Plan H 拡張 target primitive (= eval_condition に 無い、 target spec 固有)
# ===========================================================================

_EXTENDED_KEYS = {
    "self_field_power_ge",
    "self_blocker_count_ge",
    "self_finisher_in_hand_ge",
    "self_counter_in_hand_ge",
    "self_chara_attached_don_ge",
    "self_active_chara_count_ge",
    "self_hand_ge",
    "self_hand_le",
    "self_leader_attached_don_ge",
    "self_finisher_on_field_ge",
}


def _has_blocker(inplay) -> bool:
    """InPlay (= キャラ) が blocker keyword を 持つか (= 静的 + 動的 keyword 両方 確認)。"""
    card = inplay.card
    static_kws = getattr(card, "keywords", None) or []
    if any("ブロッカー" in str(k) for k in static_kws):
        return True
    # 動的付与 (= give_keyword で 一時付与) を 確認
    dynamic = getattr(inplay, "dynamic_keywords", None) or []
    if any("ブロッカー" in str(k) for k in dynamic):
        return True
    return False


def _card_counter_value(card) -> int:
    """カードの counter 値 (= 0/1000/2000) を 返す。"""
    return int(getattr(card, "counter", 0) or 0)


def _card_is_finisher(card) -> bool:
    """カードが finisher 相当か (= cost ≥ 7、 ヒューリスティック)。"""
    return int(getattr(card, "cost", 0) or 0) >= 7


def _extended_eval(cond: dict[str, Any], state: GameState, me) -> bool:
    """eval_condition でカバーされない target 固有 primitive を 評価。"""
    if not cond:
        return True
    for k, v in cond.items():
        if k == "self_field_power_ge":
            total = sum(c.power for c in me.characters)
            if total < int(v):
                return False
        elif k == "self_blocker_count_ge":
            count = sum(1 for c in me.characters if _has_blocker(c))
            if count < int(v):
                return False
        elif k == "self_finisher_in_hand_ge":
            count = sum(1 for c in me.hand if _card_is_finisher(c))
            if count < int(v):
                return False
        elif k == "self_finisher_on_field_ge":
            count = sum(1 for c in me.characters if _card_is_finisher(c.card))
            if count < int(v):
                return False
        elif k == "self_counter_in_hand_ge":
            total = sum(_card_counter_value(c) for c in me.hand)
            if total < int(v):
                return False
        elif k == "self_chara_attached_don_ge":
            total = sum(c.attached_dons for c in me.characters)
            if total < int(v):
                return False
        elif k == "self_leader_attached_don_ge":
            if me.leader.attached_dons < int(v):
                return False
        elif k == "self_active_chara_count_ge":
            count = sum(1 for c in me.characters if not c.rested)
            if count < int(v):
                return False
        elif k == "self_hand_ge":
            if len(me.hand) < int(v):
                return False
        elif k == "self_hand_le":
            if len(me.hand) > int(v):
                return False
        else:
            # 未知 key (= 拡張テーブル に 漏れ) は False 扱い (暴発防止)
            return False
    return True


# ===========================================================================
# target condition 評価 (= eval_condition + 拡張 を 統合)
# ===========================================================================


def evaluate_target_condition(
    cond: dict[str, Any], state: GameState, me_idx: int
) -> bool:
    """target spec の 'if' 節 を 評価。

    既存 `eval_condition` の primitive + Plan H 拡張 primitive を 統合評価。
    すべて True で True (= AND)。 dict が 空 なら True。
    """
    if not cond:
        return True
    me = state.players[me_idx]

    ext_cond = {k: v for k, v in cond.items() if k in _EXTENDED_KEYS}
    base_cond = {k: v for k, v in cond.items() if k not in _EXTENDED_KEYS}

    if ext_cond and not _extended_eval(ext_cond, state, me):
        return False
    if base_cond and not eval_condition(base_cond, state, me, None):
        return False
    return True


# ===========================================================================
# self_condition 判定 (= advantage / even / behind)
# ===========================================================================


def compute_self_condition(state: GameState, me_idx: int) -> str:
    """現状の 自陣状況 を 'advantage' / 'even' / 'behind' で 判定。

    ライフ差 (= weight 2) + field 数 差 + hand 差 (= 3 枚以上 で ±1) の 合計 で 分類。
    threshold ±3 (= 「明らかに 優勢/劣勢」 のみ tagging、 中間 は even)。
    """
    me = state.players[me_idx]
    opp = state.players[1 - me_idx]

    score = 0
    score += (len(me.life) - len(opp.life)) * 2
    score += len(me.characters) - len(opp.characters)
    hand_diff = len(me.hand) - len(opp.hand)
    if hand_diff >= 3:
        score += 1
    elif hand_diff <= -3:
        score -= 1

    if score >= 3:
        return "advantage"
    if score <= -3:
        return "behind"
    return "even"


# ===========================================================================
# entry 選択 (= turn × opp_leader × self_condition で fuzzy lookup)
# ===========================================================================


# condition の 隣接度 (= state condition → entry condition の 重み table)
# 例: state が "even" の 時、 "even" entry は 1.0、 "advantage"/"behind" entry は 0.5
_CONDITION_COMPAT = {
    "even": {"even": 1.0, "advantage": 0.5, "behind": 0.5},
    "advantage": {"advantage": 1.0, "even": 0.5, "behind": 0.3},
    "behind": {"behind": 1.0, "even": 0.5, "advantage": 0.3},
}


def find_matching_entries(
    target_spec: dict,
    turn_number: int,
    opp_leader_id: str,
    self_condition: str,
) -> list[tuple[dict, float]]:
    """target_spec の entries から (turn, opp_leader_id, self_condition) で fuzzy match。

    複数 entry が match する 場合 全部 返す (= (entry, weight) tuple list)。
    weight ∈ [0, 1]、 turn_weight × cond_weight。

    - turn: 厳密一致 → 1.0、 ±1 → 0.6、 else → 0 (skip)
    - opp_leader_id: 厳密 一致 のみ (= 違う leader の entry は 無関係)
    - condition: _CONDITION_COMPAT table で 0.3〜1.0
    """
    if not target_spec:
        return []
    entries = target_spec.get("entries", [])
    if not entries:
        return []

    cond_table = _CONDITION_COMPAT.get(self_condition, {self_condition: 1.0})
    matches: list[tuple[dict, float]] = []

    for entry in entries:
        if entry.get("opp_leader_id") != opp_leader_id:
            continue
        e_turn = entry.get("turn", 0)
        turn_diff = abs(e_turn - turn_number)
        if turn_diff == 0:
            turn_w = 1.0
        elif turn_diff == 1:
            turn_w = 0.6
        else:
            continue  # turn ±1 のみ
        e_cond = entry.get("self_condition", "even")
        cond_w = cond_table.get(e_cond, 0.0)
        if cond_w <= 0:
            continue
        weight = turn_w * cond_w
        matches.append((entry, weight))

    return matches


def find_target_entry(
    target_spec: dict,
    turn_number: int,
    opp_leader_id: str,
    self_condition: str,
) -> Optional[dict]:
    """後方互換 shim: find_matching_entries の 最高 weight entry を 返す。"""
    matches = find_matching_entries(target_spec, turn_number, opp_leader_id, self_condition)
    if not matches:
        return None
    return max(matches, key=lambda em: em[1])[0]


# ===========================================================================
# bonus 計算 (= plan_search の leaf eval で 呼ばれる)
# ===========================================================================


def compute_target_match_bonus(
    state: GameState,
    me_idx: int,
    target_spec: dict,
    turn_number: int,
    cap: int = 3000,
) -> int:
    """plan_search の leaf eval で 呼ばれる bonus 計算 (= 集約 版、 2026-05-19 更新)。

    現 state の (turn, opp_leader_id, self_condition) で **match する 全 entries** を 探し、
    各 entry で priority 順 に targets を 評価 → 最初 match の bonus を 取得 →
    `weight × importance × bonus` で 重み付き加算。 合計 を cap で 抑える。

    weight = turn_weight × cond_weight (= find_matching_entries 由来、 [0, 1])
    importance = entry.get("importance", 1.0) (= 戦略的重要度、 default 1.0)
    cap = 暴走防止 (= default 3000、 既存 W_TURN_PLAN と 同 scale)

    全 entry miss / no priority match → 0。
    """
    if not target_spec:
        return 0

    opp = state.players[1 - me_idx]
    opp_leader_id = getattr(opp.leader.card, "card_id", None)
    if not opp_leader_id:
        return 0

    self_cond = compute_self_condition(state, me_idx)
    matches = find_matching_entries(target_spec, turn_number, opp_leader_id, self_cond)
    if not matches:
        return 0

    total_bonus = 0.0
    for entry, weight in matches:
        importance = float(entry.get("importance", 1.0))
        targets = entry.get("targets", [])
        if not targets:
            continue
        sorted_targets = sorted(targets, key=lambda t: t.get("priority", 999))
        for tgt in sorted_targets:
            if_cond = tgt.get("if", {})
            if evaluate_target_condition(if_cond, state, me_idx):
                target_bonus = int(tgt.get("bonus", 0))
                total_bonus += weight * importance * target_bonus
                break  # priority chain で 1 つ 採用、 次 entry へ
    return int(min(total_bonus, cap))


# ===========================================================================
# load / cache
# ===========================================================================

_TARGET_SPEC_CACHE: dict[str, dict] = {}


def load_target_spec(
    deck_slug: str, base_dir: Optional[Path] = None
) -> Optional[dict]:
    """decks/<slug>.target_v1.json を 読み込む (= memo cache)。 なければ None。"""
    if deck_slug in _TARGET_SPEC_CACHE:
        return _TARGET_SPEC_CACHE[deck_slug]

    if base_dir is None:
        base_dir = Path(__file__).resolve().parent.parent / "decks"
    path = base_dir / f"{deck_slug}.target_v1.json"
    if not path.exists():
        _TARGET_SPEC_CACHE[deck_slug] = None  # type: ignore[assignment]
        return None
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
        _TARGET_SPEC_CACHE[deck_slug] = spec
        return spec
    except Exception:
        _TARGET_SPEC_CACHE[deck_slug] = None  # type: ignore[assignment]
        return None


def clear_target_spec_cache() -> None:
    """テスト 用 cache clear。"""
    _TARGET_SPEC_CACHE.clear()


# ===========================================================================
# DSL spec (= Claude prompt 用 仕様書、 generate_target_spec.py で 同梱)
# ===========================================================================

DSL_SPEC = """\
# Target Spec DSL (= Plan H、 Claude が 書く 形式)

## 軸

leader 個別 軸 (= 16 × 16 = 256 matchup) × turn (= 1-10) × self_condition (= advantage/even/behind)
→ 全 7,680 entry / 全 16 self_deck (= 480 entry / deck)

## entry 構造

```json
{
  "turn": 4,
  "opp_leader_id": "OP12-001",
  "opp_deck_slug": "tcgportal_coby",
  "opp_archetype": "aggro",
  "self_condition": "behind",
  "targets": [
    {
      "priority": 1,
      "if": { ... primitive 合成 ... },
      "bonus": 1000,
      "description": "日本語 戦略意図"
    },
    {
      "priority": 2,
      "if": { ... fallback condition ... },
      "bonus": 500,
      "description": "..."
    }
  ]
}
```

## 'if' 節 primitive 全 list

### resource
- self_life_ge / self_life_le: int — 自ライフ
- self_hand_ge / self_hand_le: int — 自手札
- self_don_ge: int — 自場ドン (active+rested+attached) 合計
- self_don_active_ge / self_don_active_le: int — アクティブ ドン のみ
- self_trash_count_ge: int — 自トラッシュ枚数

### field
- self_field_count_ge / self_field_count_le: int — 自場キャラ数
- self_field_power_ge: int — 自場 power 合計
- self_chara_feature_count_ge: {feature: str, count: int} — 特徴 X の キャラ 数
- self_chara_power_ge: int — 自場に power N 以上 の キャラ あり
- self_blocker_count_ge: int — 自場 blocker キャラ 数
- self_active_chara_count_ge: int — 自場 active キャラ 数
- self_chara_attached_don_ge: int — 自場 chara 付与 don 合計
- self_leader_attached_don_ge: int — 自リーダー 付与 don

### opp
- opp_life_le / opp_life_ge: int — 相手ライフ
- opp_hand_count_ge: int — 相手手札

### hand quality
- self_finisher_in_hand_ge: int — 手札 finisher (cost ≥ 7) の 数
- self_finisher_on_field_ge: int — 場 finisher の 数
- self_counter_in_hand_ge: int — 手札 counter 値 合計

### context
- self_turn / opp_turn: bool
- self_turn_number_ge: int — 自分の N ターン目以降

## ルール

1. 'if' 節 は **AND** (= 全 primitive 満たす 必要)
2. priority 1 から 順次 評価、 最初に match した bonus を 採用
3. priority 1-3 まで 推奨 (= fallback chain)
4. bonus は 500-2000 範囲 (= 既存 W_TURN_PLAN=3000 と バランス、 ±50% 余裕)
5. description で 日本語 戦略意図 を 記述 (= 後の review 用)
6. self_condition は **start-of-turn の 状況** を 想定 (= 「behind なら 守備寄り 目標、 advantage なら 攻撃寄り 目標」 の 出し分け)

## 推奨 entry 例 (= cardrush_1456 赤青エース)

```json
{
  "turn": 4,
  "opp_leader_id": "OP12-001",
  "opp_deck_slug": "tcgportal_coby",
  "self_condition": "behind",
  "targets": [
    {
      "priority": 1,
      "if": {
        "self_field_power_ge": 7000,
        "self_chara_feature_count_ge": {"feature": "白ひげ海賊団", "count": 1},
        "self_hand_ge": 4
      },
      "bonus": 1000,
      "description": "vs 黒コビー: 白ひげ軸 power 7000 / マルコ ドロー で hand 維持、 高速 アグロ に カウンター 構え"
    },
    {
      "priority": 2,
      "if": {"self_field_count_ge": 2, "self_blocker_count_ge": 1},
      "bonus": 500,
      "description": "fallback: 場 2 体 + blocker 1 で 受け"
    }
  ]
}
```
"""
