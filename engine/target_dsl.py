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
    "min_attacks_this_turn_ge",
    "min_leader_attacks_this_turn_ge",
    # action-specific (= 2026-05-29, action 差別 化 用)
    "min_play_chara_this_turn_ge",
    "min_play_event_this_turn_ge",
    "min_play_stage_this_turn_ge",
    "min_activate_main_this_turn_ge",
    "min_attach_don_leader_this_turn_ge",
    "min_attach_don_chara_this_turn_ge",
    "min_attack_chara_this_turn_ge",
    "opp_field_total_power_le",
    "opp_active_chara_count_le",
    "opp_chara_count_le",
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


def _count_attacks_in_plan(plan, leader_only: bool = False) -> int:
    """plan list (= action 列) の attack 数 を カウント。 leader_only=True で AttackLeader のみ。"""
    if not plan:
        return 0
    from .game import AttackLeader, AttackCharacter
    if leader_only:
        return sum(1 for a in plan if isinstance(a, AttackLeader))
    return sum(1 for a in plan if isinstance(a, (AttackLeader, AttackCharacter)))


def _count_action_type_in_plan(plan, action_class_name: str) -> int:
    """plan 内 で 特定 action class が 何 回 取られた か (= 2026-05-29、 action-specific if 条件 用)。"""
    if not plan:
        return 0
    return sum(1 for a in plan if a.__class__.__name__ == action_class_name)


def _extended_eval(cond: dict[str, Any], state: GameState, me, plan=None) -> bool:
    """eval_condition でカバーされない target 固有 primitive を 評価。

    plan: plan_search の 現 plan (= action 列)、 min_attacks_*_ge 系で 使用。
    """
    if not cond:
        return True
    # opp 参照 (= counter-play primitive 用)
    opp = None
    for k in cond:
        if k.startswith("opp_"):
            # state.players の中で me ではない player を opp とする
            for p in state.players:
                if p is not me:
                    opp = p
                    break
            break
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
        elif k == "min_attacks_this_turn_ge":
            if _count_attacks_in_plan(plan, leader_only=False) < int(v):
                return False
        elif k == "min_leader_attacks_this_turn_ge":
            if _count_attacks_in_plan(plan, leader_only=True) < int(v):
                return False
        # === action-specific if 条件 (= 2026-05-29、 bonus が action 差別 化 を 担う ため) ===
        elif k == "min_play_chara_this_turn_ge":
            if _count_action_type_in_plan(plan, "PlayCharacter") < int(v):
                return False
        elif k == "min_play_event_this_turn_ge":
            if _count_action_type_in_plan(plan, "PlayEvent") < int(v):
                return False
        elif k == "min_play_stage_this_turn_ge":
            if _count_action_type_in_plan(plan, "PlayStage") < int(v):
                return False
        elif k == "min_activate_main_this_turn_ge":
            if _count_action_type_in_plan(plan, "ActivateMain") < int(v):
                return False
        elif k == "min_attach_don_leader_this_turn_ge":
            if _count_action_type_in_plan(plan, "AttachDonToLeader") < int(v):
                return False
        elif k == "min_attach_don_chara_this_turn_ge":
            if _count_action_type_in_plan(plan, "AttachDonToCharacter") < int(v):
                return False
        elif k == "min_attack_chara_this_turn_ge":
            if _count_action_type_in_plan(plan, "AttackCharacter") < int(v):
                return False
        elif k == "opp_field_total_power_le":
            if opp is None:
                return False
            total = sum(c.power for c in opp.characters)
            if total > int(v):
                return False
        elif k == "opp_active_chara_count_le":
            if opp is None:
                return False
            count = sum(1 for c in opp.characters if not c.rested)
            if count > int(v):
                return False
        elif k == "opp_chara_count_le":
            if opp is None:
                return False
            if len(opp.characters) > int(v):
                return False
        else:
            # 未知 key (= 拡張テーブル に 漏れ) は False 扱い (暴発防止)
            return False
    return True


# ===========================================================================
# target condition 評価 (= eval_condition + 拡張 を 統合)
# ===========================================================================


def evaluate_target_condition(
    cond: dict[str, Any], state: GameState, me_idx: int, plan=None
) -> bool:
    """target spec の 'if' 節 を 評価。

    既存 `eval_condition` の primitive + Plan H 拡張 primitive を 統合評価。
    すべて True で True (= AND)。 dict が 空 なら True。

    plan: plan_search の 現 plan (= action 列)、 min_attacks_*_ge 系で 使用。
    """
    if not cond:
        return True
    me = state.players[me_idx]

    ext_cond = {k: v for k, v in cond.items() if k in _EXTENDED_KEYS}
    base_cond = {k: v for k, v in cond.items() if k not in _EXTENDED_KEYS}

    if ext_cond and not _extended_eval(ext_cond, state, me, plan):
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


# Tier weight (= leader 厳密 / archetype 一致 / wildcard) — 2026-05-25 ハイブリッド
_TIER_LEADER_EXACT = 1.0   # Tier 1: opp_leader_id 厳密一致
_TIER_ARCHETYPE = 0.7      # Tier 2: opp_archetype 一致 (= leader 不一致 or 未指定 だが archetype 一致)
_TIER_WILDCARD = 0.5       # Tier 3: opp_leader_id=null かつ opp_archetype=null (= 完全 generic)


def find_matching_entries(
    target_spec: dict,
    turn_number: int,
    opp_leader_id: str,
    self_condition: str,
    opp_archetype: Optional[str] = None,
) -> list[tuple[dict, float]]:
    """target_spec の entries から (turn, opp_leader_id, opp_archetype, self_condition) で fuzzy match。

    **排他 logic** (= 2026-05-25): per-deck **内部 wildcard** (= v1 refined "attack 必須" generic、
    +2pt baseline の 一部) は 常時 含める。 **外部 generic.json entries** (= `_external_generic` flag
    付き) のみ、 per-deck Tier 1 match が 1 件 でも あれば drop する。

    これに より:
    - 既知 deck × 既知 leader: per-deck spec が 純粋 適用 (= +2pt baseline 維持)
    - 既知 deck × 未知 leader / 未知 deck: 外部 generic が fallback として 効く

    複数 entry が match する 場合 全部 返す (= (entry, weight) tuple list)。
    weight ∈ [0, 1]、 leader_tier × turn_weight × cond_weight。

    - turn: 厳密一致 → 1.0、 ±1 → 0.6、 else → 0 (skip)
    - leader_tier:
        - opp_leader_id 厳密一致 → 1.0 (Tier 1)
        - opp_leader_id null + opp_archetype 一致 → 0.7 (Tier 2)
        - opp_leader_id null + opp_archetype null → 0.5 (Tier 3 純 wildcard)
        - その他 → skip
    - condition: _CONDITION_COMPAT table で 0.3〜1.0
    - **外部 generic 排他**: per-deck Tier 1 match があれば、 `_external_generic` flag 付き
      entry のみ 結果 から drop (= per-deck 内部 wildcard は 残る)
    """
    if not target_spec:
        return []
    entries = target_spec.get("entries", [])
    if not entries:
        return []

    cond_table = _CONDITION_COMPAT.get(self_condition, {self_condition: 1.0})
    per_deck_matches: list[tuple[dict, float]] = []
    external_matches: list[tuple[dict, float]] = []
    has_per_deck_tier1 = False

    # === 高速化 (= 2026-05-26): entries を opp_leader_id 別 に index 化 ===
    # spec 内 entries 数 が 数百〜数千 規模 で 線形 走査 が plan_search の bottleneck (= 16x slowdown)。
    # leader_id ごと の bucket + null leader bucket (= Tier 2/3) を 事前 build、 lookup を O(K) に 削減。
    # cache key は spec object の id() (= mutate されない 前提、 load_target_spec の cache と 同 寿命)。
    spec_id = id(target_spec)
    leader_index = _LEADER_INDEX_CACHE.get(spec_id)
    if leader_index is None:
        leader_index = {"_by_leader": {}, "_no_leader": []}
        for entry in entries:
            elid = entry.get("opp_leader_id")
            if elid:
                leader_index["_by_leader"].setdefault(elid, []).append(entry)
            else:
                leader_index["_no_leader"].append(entry)
        _LEADER_INDEX_CACHE[spec_id] = leader_index

    # 候補 entry 集合: 厳密 leader 一致 (= Tier 1) + null leader (= Tier 2/3)
    candidate_entries = leader_index["_by_leader"].get(opp_leader_id, []) + leader_index["_no_leader"]

    for entry in candidate_entries:
        e_opp_leader = entry.get("opp_leader_id")
        e_opp_arch = entry.get("opp_archetype")
        is_external = bool(entry.get("_external_generic"))
        is_tier1 = False
        # ハイブリッド 4-tier lookup
        if e_opp_leader and e_opp_leader == opp_leader_id:
            # Tier 1: leader 厳密一致
            leader_w = _TIER_LEADER_EXACT
            is_tier1 = True
        elif e_opp_leader:
            # leader 指定 ある が 不一致 → skip
            continue
        elif e_opp_arch and opp_archetype and e_opp_arch == opp_archetype:
            # Tier 2: leader null + archetype 一致
            leader_w = _TIER_ARCHETYPE
        elif e_opp_arch:
            # archetype 指定 ある が 不一致 → skip
            continue
        else:
            # Tier 3: leader null + archetype null (= 純 wildcard)
            leader_w = _TIER_WILDCARD
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
        weight = leader_w * turn_w * cond_w
        if is_external:
            external_matches.append((entry, weight))
        else:
            per_deck_matches.append((entry, weight))
            if is_tier1:
                has_per_deck_tier1 = True

    # 外部 generic 排他: per-deck Tier 1 match が あれば 外部 generic を drop。
    # per-deck 内部 wildcard (= v1 spec の 一部) は 常時 残す。
    if has_per_deck_tier1:
        return per_deck_matches
    return per_deck_matches + external_matches


def find_matching_entries_v2(
    target_spec: dict,
    state_axes: dict,
) -> list[tuple[dict, float]]:
    """v2 rich axes 対応 find_matching_entries (= 2026-05-30 拡張)。

    state_axes は engine.axis_compute.compute_axes_from_state の 出力 dict。
    entry に 書かれた rich axes (= opp_life_bucket 等) と state_axes を 比較、
    全 軸 match で 採用、 weight = leader_tier × turn_weight。

    旧 4 軸 entries (= rich axes なし) との backward compat:
      - entry に rich axes が ない → wildcard で match (= 旧 logic 通り)
      - entry に rich axes あり → 厳 密 一 致 必須
    """
    if not target_spec:
        return []
    entries = target_spec.get("entries", [])
    if not entries:
        return []

    from .axis_compute import axes_match

    matches: list[tuple[dict, float]] = []
    for entry in entries:
        ok, weight = axes_match(entry, state_axes, turn_tolerance=1)
        if ok and weight > 0:
            matches.append((entry, weight))
    return matches


# ===========================================================================
# cascade fallback (= 2026-05-30 追加、 学 習 coverage 不 足 対 応)
# ===========================================================================
#
# 12 軸 strict match で 0 件 だ と GreedyAI fallback = 学 習 効 果 ゼ ロ。
# 段 階 的 に 「優 先 度 低 軸」 を 落 と し て 何 か し ら の entry に hit さ せ る。
# 戦 略 重 要 度 順 (= 残 す べ き 軸):
#   1. turn (= ゲ ー ム 進 行)
#   2. opp_leader_id (= matchup 根 本)
#   3. self_life_bucket / opp_life_bucket (= lethal 圏 判 断)
#   4. self_field_bucket / opp_field_bucket (= 盤 面 状 況)
#   5. opp_threat_bucket (= 脅 威 評 価)
#   6. self_don_bucket / self_hand_bucket / opp_hand_bucket (= リソース)
#   7. opp_active_chara_bucket (= field と overlap)
#   8. opp_archetype / self_condition (= 他 軸 か ら derive 可)
#
# 各 level の drop = state_axes の key を 削 除 (= wildcard 扱 い 化)。

CASCADE_DROP_LEVELS: tuple[set[str], ...] = (
    set(),  # L0: drop なし (= 12 軸 strict)
    # L1: derivable / overlap (= 他 軸 か ら 復 元 可 + 冗 長)
    {"self_condition", "opp_archetype", "opp_active_chara_bucket"},
    # L2: + リソース 軸 (= hand / don、 戦 略 重 要 度 中)
    {"self_condition", "opp_archetype", "opp_active_chara_bucket",
     "self_hand_bucket", "opp_hand_bucket", "self_don_bucket"},
    # L3: + 盤 面 軸 (= field / threat、 残 る は life + matchup core)
    {"self_condition", "opp_archetype", "opp_active_chara_bucket",
     "self_hand_bucket", "opp_hand_bucket", "self_don_bucket",
     "opp_threat_bucket", "opp_field_bucket", "self_field_bucket"},
    # L4: + life 軸 (= turn + opp_leader_id の 2 軸 のみ、 旧 4 軸 相 当)
    {"self_condition", "opp_archetype", "opp_active_chara_bucket",
     "self_hand_bucket", "opp_hand_bucket", "self_don_bucket",
     "opp_threat_bucket", "opp_field_bucket", "self_field_bucket",
     "opp_life_bucket", "self_life_bucket"},
)

# cascade level に 応 じ た weight 減 衰 (= 深 い ほ ど 信 頼 度 落 ち る)
CASCADE_LEVEL_DECAY: tuple[float, ...] = (1.0, 0.85, 0.70, 0.55, 0.40)


def find_matching_entries_cascade(
    target_spec: dict,
    state_axes: dict,
) -> tuple[list[tuple[dict, float]], int]:
    """cascade fallback で match を 探 す。 strict (L0) → 段 階 的 緩 和 → L4。

    Returns:
      (matches, level_used): 最 初 に hit し た level の matches + その level 番 号。
      全 miss なら ([], -1)。 weight は level decay 適 用 済。
    """
    if not target_spec:
        return [], -1

    for level, drop_keys in enumerate(CASCADE_DROP_LEVELS):
        if drop_keys:
            relaxed_axes = {k: v for k, v in state_axes.items() if k not in drop_keys}
        else:
            relaxed_axes = state_axes
        matches = find_matching_entries_v2(target_spec, relaxed_axes)
        if matches:
            decay = CASCADE_LEVEL_DECAY[level] if level < len(CASCADE_LEVEL_DECAY) else 0.3
            decayed = [(e, w * decay) for e, w in matches]
            return decayed, level

    return [], -1


def find_target_entry(
    target_spec: dict,
    turn_number: int,
    opp_leader_id: str,
    self_condition: str,
    opp_archetype: Optional[str] = None,
) -> Optional[dict]:
    """後方互換 shim: find_matching_entries の 最高 weight entry を 返す。"""
    matches = find_matching_entries(
        target_spec, turn_number, opp_leader_id, self_condition, opp_archetype
    )
    if not matches:
        return None
    return max(matches, key=lambda em: em[1])[0]


# ===========================================================================
# opp archetype 取得 (= ハイブリッド Tier 2 用、 db/deck_archetypes.json lookup)
# ===========================================================================

# deck slug → archetype (= "アグロ" / "ミッドレンジ" / "コントロール" / "ランプ") の memo cache。
# scripts/build_deck_archetypes.py で 事前 build した db/deck_archetypes.json を 読む。
# 未知 deck (= map に 無い) は None → Tier 2 skip → Tier 3 (純 wildcard) のみ 効く。
_ARCHETYPE_MAP: Optional[dict[str, str]] = None
_ARCHETYPE_MAP_LOADED: bool = False


def _load_archetype_map() -> dict[str, str]:
    """db/deck_archetypes.json (= 事前 build slug → archetype map) を 読む (= 1 回 のみ)。

    無ければ 空 dict。 build script が 走って いない 場合 は 全 deck が None 扱い。
    """
    global _ARCHETYPE_MAP, _ARCHETYPE_MAP_LOADED
    if _ARCHETYPE_MAP_LOADED:
        return _ARCHETYPE_MAP or {}
    _ARCHETYPE_MAP_LOADED = True
    map_path = Path(__file__).resolve().parent.parent / "db" / "deck_archetypes.json"
    if not map_path.exists():
        _ARCHETYPE_MAP = {}
        return {}
    try:
        data = json.loads(map_path.read_text(encoding="utf-8"))
        # format: {"cardrush_1456": "コントロール", ...} or {"map": {...}, "meta": {...}}
        if isinstance(data, dict) and "map" in data:
            _ARCHETYPE_MAP = data["map"]
        else:
            _ARCHETYPE_MAP = data
        return _ARCHETYPE_MAP or {}
    except Exception:
        _ARCHETYPE_MAP = {}
        return {}


def get_archetype_by_slug(slug: Optional[str]) -> Optional[str]:
    """deck slug から archetype を 引く (= db/deck_archetypes.json lookup)。

    map に 無い slug は None (= 未知 deck、 Tier 2 skip)。
    """
    if not slug:
        return None
    return _load_archetype_map().get(slug)


def clear_archetype_cache() -> None:
    """テスト 用 cache clear。"""
    global _ARCHETYPE_MAP, _ARCHETYPE_MAP_LOADED
    _ARCHETYPE_MAP = None
    _ARCHETYPE_MAP_LOADED = False


# ===========================================================================
# bonus 計算 (= plan_search の leaf eval で 呼ばれる)
# ===========================================================================


def compute_target_match_bonus(
    state: GameState,
    me_idx: int,
    target_spec: dict,
    turn_number: int,
    cap: int = 3000,
    plan=None,
) -> int:
    """plan_search の leaf eval で 呼ばれる bonus 計算 (= argmax 版、 2026-05-30 更新)。

    現 state の (turn, opp_leader_id, opp_archetype, self_condition) で **match する 全 entries** を
    探し、 各 entry で **全 if-satisfying targets** を 評価 → `weight × importance × bonus` の
    **最大値** を 返す (= argmax(Q-value) policy、 priority chain 廃止)。

    旧 設計 では priority 順 で 「最初 if 満たす target」 で break して い た が、 bonus 最適化
    路 線 で は priority が 嘘 を つ く 問題 (= 学習 後 priority 1 の bonus が priority 2 より
    下 が る ケース で 動 作 が dead lock) が 発生。 argmax 化 で 価値 関数 と し て の 整 合 性 を 確 保。

    旧 SUM 版 (= 7200 cross-leader entries で cap 飽和) → MAX 版 (= 2026-05-26 旧)
    → argmax 版 (= 2026-05-30 現)。

    weight = leader_tier × turn_weight × cond_weight (= find_matching_entries 由来、 [0, 1])
    importance = entry.get("importance", 1.0) (= 戦略的重要度、 default 1.0)
    cap = 暴走防止 (= default 3000、 単一 entry の bonus は 500-2000 範囲 なので 通常 cap 未満)

    全 entry miss / if 満たす target 0 → 0。
    """
    if not target_spec:
        return 0

    opp = state.players[1 - me_idx]
    opp_leader_id = getattr(opp.leader.card, "card_id", None)
    if not opp_leader_id:
        return 0

    # opp archetype 取得 (= state.deck_slugs[opp_idx] → db/deck_archetypes.json lookup)
    # 失敗時 (= 未知 deck) None で Tier 2 skip、 Tier 3 (純 wildcard) のみ 効く
    opp_idx = 1 - me_idx
    opp_slug: Optional[str] = None
    try:
        deck_slugs = getattr(state, "deck_slugs", None)
        if deck_slugs and len(deck_slugs) > opp_idx:
            opp_slug = deck_slugs[opp_idx] or None
    except Exception:
        opp_slug = None
    opp_archetype = get_archetype_by_slug(opp_slug)

    # 2026-05-30 v2 化 + cascade fallback:
    # L0 (= 12 軸 strict) で hit すれば weight 1.0、 miss なら L1-L4 で 段 階 緩 和。
    # 全 miss なら 0 を 返 す (= caller が GreedyAI fallback)。
    # 学 習 coverage 不 足 deck (= op11_luffy 系) で の miss を 救 済、
    # cardrush_1456 系 (= coverage 十 分) で は L0 hit で 高 bonus 維 持。
    from .axis_compute import compute_axes_from_state
    state_axes = compute_axes_from_state(state, me_idx, opp_archetype or "midrange")
    state_axes["turn"] = turn_number  # 明 示 反 映
    matches, cascade_level = find_matching_entries_cascade(target_spec, state_axes)
    if not matches:
        # cascade L0-L4 全 miss = spec ゼ ロ 寄 与 = AI が GreedyAI 同 等 で プレイ。
        # ENV 変 数 で 設 定 さ れ た log path に state_axes + deck_slug を 記 録 (= 後 で
        # entry 提 案 + spec 補 強 用)。
        _log_cascade_fallback(state_axes, opp_slug, me_idx)
        return 0
    # cascade level も per-state 記 録 (= L0 hit 率 / L4 救 済 率 を 集 計 用)
    _log_cascade_hit(cascade_level)

    best_bonus = 0.0
    best_entry_id: Optional[str] = None
    for entry, weight in matches:
        importance = float(entry.get("importance", 1.0))
        targets = entry.get("targets", [])
        if not targets:
            continue
        # 2026-05-30 argmax 化: priority sort + break 廃止、 全 if-satisfying targets を 評価
        # して MAX bonus を 採用。 bonus 最適化 と の 整 合 性 (= 学 習 後 priority が 嘘 を つ く
        # 問題 を 根本 解消)、 Q(s,a) 価値 関数 path と 整合。
        for tgt in targets:
            if_cond = tgt.get("if", {})
            if evaluate_target_condition(if_cond, state, me_idx, plan):
                target_bonus = int(tgt.get("bonus", 0))
                contribution = weight * importance * target_bonus
                if contribution > best_bonus:
                    best_bonus = contribution
                    best_entry_id = entry.get("_entry_id")
    # fire logging hook (= state._fired_target_counts[me_idx] が dict なら 集計)
    # bonus 学習 で 「どの entry が 何回 driving した か」 を per-player track する。
    # default off (= 通常 plan_search では 無効)、 eval_with_entry_firings.py が opt-in。
    if best_entry_id and best_bonus > 0:
        counts = getattr(state, "_fired_target_counts", None)
        if counts is not None and me_idx < len(counts):
            counts[me_idx][best_entry_id] = counts[me_idx].get(best_entry_id, 0) + 1
    return int(min(best_bonus, cap))


# ===========================================================================
# cascade fallback logger (= 2026-05-30 追加、 spec 補 強 用)
# ===========================================================================
#
# cascade L0-L4 全 miss を 記 録 (= AI が GreedyAI 同 等 で プレイ せ ざ る を 得 な い state)。
# 後 で analyze script (scripts/analyze_cascade_fallback.py) で 頻 出 patterns を 抽 出
# し て、 該 当 state へ 最 適 entry を 追 加 する 用。
#
# ENV var で 有 効 化:
#   ONEPIECE_CASCADE_LOG=/path/to/fallback.json  (= JSON 出 力 path)
# atexit hook で プロセス 終 了 時 に dump (= per-game 等 で 重 複 集 計)。

import atexit as _atexit
import os as _os

_CASCADE_FALLBACK_LOG_PATH: Optional[str] = _os.environ.get("ONEPIECE_CASCADE_LOG", "") or None
# state_axes hash → count + 代 表 axes sample
_CASCADE_FALLBACK_COUNTER: dict[tuple, dict] = {}
# cascade level hit 数 集 計 (= L0 hit / L1 hit / ... / miss)
_CASCADE_HIT_LEVEL_COUNTER: dict[int, int] = {}


def _log_cascade_fallback(state_axes: dict, deck_slug: Optional[str],
                          me_idx: int) -> None:
    """cascade 全 miss を 記 録。 ENV var 未 設 定 なら no-op。"""
    if not _CASCADE_FALLBACK_LOG_PATH:
        return
    key = (
        state_axes.get("turn"),
        state_axes.get("opp_leader_id"),
        state_axes.get("self_life_bucket"),
        state_axes.get("opp_life_bucket"),
        state_axes.get("self_field_bucket"),
        state_axes.get("opp_field_bucket"),
        state_axes.get("opp_threat_bucket"),
        deck_slug,
    )
    entry = _CASCADE_FALLBACK_COUNTER.get(key)
    if entry is None:
        # 初 回 = sample axes 保 存 (= full 12 軸)
        _CASCADE_FALLBACK_COUNTER[key] = {
            "count": 1,
            "sample_axes": dict(state_axes),
            "deck_slug": deck_slug,
        }
    else:
        entry["count"] += 1


def _log_cascade_hit(level: int) -> None:
    """cascade hit level を 集 計。 ENV var 未 設 定 なら no-op。"""
    if not _CASCADE_FALLBACK_LOG_PATH:
        return
    _CASCADE_HIT_LEVEL_COUNTER[level] = _CASCADE_HIT_LEVEL_COUNTER.get(level, 0) + 1


def _save_cascade_fallback_log() -> None:
    """atexit で 呼 ば れ、 fallback log を JSON dump。"""
    if not _CASCADE_FALLBACK_LOG_PATH:
        return
    if not _CASCADE_FALLBACK_COUNTER and not _CASCADE_HIT_LEVEL_COUNTER:
        return
    # 既 存 file あれ ば merge (= per-process append 想 定)
    existing: dict = {"fallbacks": [], "hit_levels": {}}
    p = Path(_CASCADE_FALLBACK_LOG_PATH)
    if p.exists():
        try:
            existing = json.loads(p.read_text(encoding="utf-8"))
            if "fallbacks" not in existing:
                existing["fallbacks"] = []
            if "hit_levels" not in existing:
                existing["hit_levels"] = {}
        except Exception:
            existing = {"fallbacks": [], "hit_levels": {}}
    # 既 存 と 同 key を 統 合 (= count 加 算)
    existing_by_key: dict = {}
    for fb in existing["fallbacks"]:
        ax = fb["sample_axes"]
        k = (ax.get("turn"), ax.get("opp_leader_id"),
             ax.get("self_life_bucket"), ax.get("opp_life_bucket"),
             ax.get("self_field_bucket"), ax.get("opp_field_bucket"),
             ax.get("opp_threat_bucket"), fb.get("deck_slug"))
        existing_by_key[k] = fb
    for k, v in _CASCADE_FALLBACK_COUNTER.items():
        if k in existing_by_key:
            existing_by_key[k]["count"] += v["count"]
        else:
            existing["fallbacks"].append(v)
    for lvl, c in _CASCADE_HIT_LEVEL_COUNTER.items():
        existing["hit_levels"][str(lvl)] = existing["hit_levels"].get(str(lvl), 0) + c
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


if _CASCADE_FALLBACK_LOG_PATH:
    _atexit.register(_save_cascade_fallback_log)


# ===========================================================================
# load / cache
# ===========================================================================

_TARGET_SPEC_CACHE: dict[str, dict] = {}
_GENERIC_SPEC_CACHE: Optional[dict] = None
_GENERIC_SPEC_LOADED: bool = False
# spec id() → {_by_leader: {leader_id: [entries]}, _no_leader: [entries]} (= find_matching_entries 高速化)
_LEADER_INDEX_CACHE: dict[int, dict] = {}


def _load_generic_spec(base_dir: Path) -> Optional[dict]:
    """db/target_generic.json を 読み込む (= プロセス 中 1 回 のみ)。

    全 deck 共通 の fallback entries (= archetype + wildcard 軸)。
    1 度 load したら _GENERIC_SPEC_CACHE に 保持、 file 無し なら None で 確定。
    """
    global _GENERIC_SPEC_CACHE, _GENERIC_SPEC_LOADED
    if _GENERIC_SPEC_LOADED:
        return _GENERIC_SPEC_CACHE
    _GENERIC_SPEC_LOADED = True
    # base_dir は decks/、 generic は db/ に置く
    generic_path = base_dir.parent / "db" / "target_generic.json"
    if not generic_path.exists():
        _GENERIC_SPEC_CACHE = None
        return None
    try:
        _GENERIC_SPEC_CACHE = json.loads(generic_path.read_text(encoding="utf-8"))
        return _GENERIC_SPEC_CACHE
    except Exception:
        _GENERIC_SPEC_CACHE = None
        return None


def load_target_spec(
    deck_slug: str, base_dir: Optional[Path] = None, version: str = "v1"
) -> Optional[dict]:
    """decks/<slug>.target_<version>.json を 読み込む (= memo cache)。

    2026-05-25 ハイブリッド: per-deck spec が あれば 生 spec + generic を merge。
    per-deck spec が 無くて も generic が あれば generic だけ で spec 返す
    (= 未知 deck でも Tier 2/3 fallback が 効く)。

    version: "v1" (= default、 既存) or "v2" (= cross-trained、 2026-05-20)
    """
    cache_key = f"{deck_slug}:{version}"
    if cache_key in _TARGET_SPEC_CACHE:
        return _TARGET_SPEC_CACHE[cache_key]

    if base_dir is None:
        base_dir = Path(__file__).resolve().parent.parent / "decks"

    # runtime 上書き path 確認 (= 2026-05-30 追加、 Vercel Blob か ら fetched spec を /tmp/specs に
    # sync する pattern。 ONEPIECE_SPEC_RUNTIME_DIR env で 場 所 override 可、 default /tmp/specs)。
    # runtime path に file が あ れ ば そ ち ら 優 先 (= Blob 永 続 化 さ れ た 最 新)、 な け れ ば
    # bundle (= base_dir) 読 込 で 既 動 作 維 持。
    import os as _os_for_spec
    runtime_dir = Path(_os_for_spec.environ.get("ONEPIECE_SPEC_RUNTIME_DIR", "/tmp/specs"))
    runtime_path = runtime_dir / f"{deck_slug}.target_{version}.json"
    per_deck_spec: Optional[dict] = None
    if runtime_path.exists() and runtime_path.stat().st_size > 0:
        try:
            per_deck_spec = json.loads(runtime_path.read_text(encoding="utf-8"))
        except Exception:
            per_deck_spec = None

    # per-deck spec を 読む (= 既存 bundle path、 runtime に な か っ た 場 合 の fallback)
    if per_deck_spec is None:
        path = base_dir / f"{deck_slug}.target_{version}.json"
        if path.exists():
            try:
                per_deck_spec = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                per_deck_spec = None

    # generic spec を 読む (= 全 deck 共通 fallback)
    generic_spec = _load_generic_spec(base_dir)

    # merge: per-deck entries + generic entries を 1 つ の spec に 統合
    if per_deck_spec is None and generic_spec is None:
        _TARGET_SPEC_CACHE[cache_key] = None  # type: ignore[assignment]
        return None

    merged_entries: list[dict] = []
    base: dict = {}
    if per_deck_spec is not None:
        # per-deck entries に entry_id = "<deck_slug>#<idx>" を 付与 (= bonus 学習 fire log の key)
        for idx, e in enumerate(per_deck_spec.get("entries", [])):
            tagged = dict(e)
            tagged.setdefault("_entry_id", f"{deck_slug}#{idx}")
            merged_entries.append(tagged)
        base = {k: v for k, v in per_deck_spec.items() if k != "entries"}
    if generic_spec is not None:
        # 外部 generic entries に _external_generic=True flag を 付与 (= find_matching_entries で
        # per-deck 内部 wildcard と 区別 して 排他 判定 に 使う)。 元 file は 触らない。
        # entry_id = "generic#<idx>" (= 全 deck 共通、 fire log で global 集計)
        for idx, ge in enumerate(generic_spec.get("entries", [])):
            tagged = dict(ge)
            tagged["_external_generic"] = True
            tagged.setdefault("_entry_id", f"generic#{idx}")
            merged_entries.append(tagged)
    merged = dict(base)
    merged["entries"] = merged_entries
    merged.setdefault("deck_slug", deck_slug)
    _TARGET_SPEC_CACHE[cache_key] = merged
    return merged


def clear_target_spec_cache() -> None:
    """テスト 用 cache clear。"""
    global _GENERIC_SPEC_CACHE, _GENERIC_SPEC_LOADED
    _TARGET_SPEC_CACHE.clear()
    _LEADER_INDEX_CACHE.clear()
    _GENERIC_SPEC_CACHE = None
    _GENERIC_SPEC_LOADED = False


# ===========================================================================
# DSL spec (= Claude prompt 用 仕様書、 generate_target_spec.py で 同梱)
# ===========================================================================

DSL_SPEC = """\
# Target Spec DSL (= Plan H、 Claude が 書く 形式)

## 軸 (= 2026-05-25 ハイブリッド 4-tier)

per-deck file (= `decks/<slug>.target_v1.json`):
  Tier 1: opp_leader_id 厳密一致 entry (weight 1.0) — 16×16=256 matchup × turn × condition

shared file (= `db/target_generic.json`):
  Tier 2: opp_leader_id=null + opp_archetype 一致 entry (weight 0.7) — archetype × turn × condition
  Tier 3: opp_leader_id=null + opp_archetype=null entry (weight 0.5) — 純 wildcard × turn × condition

未指定 self_deck (= spec 不在) でも Tier 2/3 fallback で 動く = デッキ研究 ツール 汎用化。

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
