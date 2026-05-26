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
    """plan_search の leaf eval で 呼ばれる bonus 計算 (= MAX 版、 2026-05-26 更新)。

    現 state の (turn, opp_leader_id, opp_archetype, self_condition) で **match する 全 entries** を
    探し、 各 entry で priority 順 に targets を 評価 → 最初 match の bonus を 取得 →
    `weight × importance × bonus` の **最大値** を 返す (= leaf 選択 を 駆動 する のは 最良 target 1 件)。

    旧 SUM 版 では 7200 cross-leader entries 投入 後 cap=3000 飽和 で leaf 差別化 が
    消失していた (= どの leaf も 同じ bonus に 潰れる)。 MAX 化 で 「ターン目標 = 1 つ の 明確 ゴール」
    という 本来 設計 に 寄せる。

    weight = leader_tier × turn_weight × cond_weight (= find_matching_entries 由来、 [0, 1])
    importance = entry.get("importance", 1.0) (= 戦略的重要度、 default 1.0)
    cap = 暴走防止 (= default 3000、 単一 entry の bonus は 500-2000 範囲 なので 通常 cap 未満)

    全 entry miss / no priority match → 0。
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

    self_cond = compute_self_condition(state, me_idx)
    matches = find_matching_entries(
        target_spec, turn_number, opp_leader_id, self_cond, opp_archetype
    )
    if not matches:
        return 0

    best_bonus = 0.0
    best_entry_id: Optional[str] = None
    for entry, weight in matches:
        importance = float(entry.get("importance", 1.0))
        targets = entry.get("targets", [])
        if not targets:
            continue
        sorted_targets = sorted(targets, key=lambda t: t.get("priority", 999))
        for tgt in sorted_targets:
            if_cond = tgt.get("if", {})
            if evaluate_target_condition(if_cond, state, me_idx, plan):
                target_bonus = int(tgt.get("bonus", 0))
                contribution = weight * importance * target_bonus
                if contribution > best_bonus:
                    best_bonus = contribution
                    best_entry_id = entry.get("_entry_id")
                break  # priority chain で 1 つ 採用、 次 entry へ
    # fire logging hook (= state._fired_target_counts[me_idx] が dict なら 集計)
    # bonus 学習 で 「どの entry が 何回 driving した か」 を per-player track する。
    # default off (= 通常 plan_search では 無効)、 eval_with_entry_firings.py が opt-in。
    if best_entry_id and best_bonus > 0:
        counts = getattr(state, "_fired_target_counts", None)
        if counts is not None and me_idx < len(counts):
            counts[me_idx][best_entry_id] = counts[me_idx].get(best_entry_id, 0) + 1
    return int(min(best_bonus, cap))


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

    # per-deck spec を 読む (= 既存 path)
    path = base_dir / f"{deck_slug}.target_{version}.json"
    per_deck_spec: Optional[dict] = None
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
