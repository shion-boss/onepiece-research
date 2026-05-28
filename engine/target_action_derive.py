# -*- coding: utf-8 -*-
"""真 Phase 1.0 (= 2026-05-28): 目指す盤面 (= target entry) から 候補 action を 逆算。

ohtsuki さん ビジョン:
  「各 ターン 開始時: 状況確認 → 実現可能 な entry 中 最大 bonus を 選ぶ →
   その entry の 盤面 に 近づける 候補 action だけ で 探索」

旧 GoalDirectedAI (= [[project_goal_directed_real]] 参照) は ranking-based で、
全 legal action を 展開 した 後 target bonus を 加算 する 中途半端 設計 だった。
真の goal-directed = action 空間 を pre-filter する。 これは plan_search の
分岐爆発 (= 53分 病的 試合 [[project_long_game_pathology]]) を 構造的 に 解消 する。

API:
- is_achievable(state, me_idx, if_cond, plan): 現状から条件達成 可能 か (= heuristic)
- derive_actions_for_goal(state, me_idx, if_cond, plan, legal_actions): 条件 を 満たす に
  寄与 する 候補 action だけ に 絞る
- lookup_best_achievable_entry(state, me_idx, target_spec, ...): bonus 降順 で
  最初 に achievable な entry を 返す

サポート primitive (= cardrush_1392 target_v1.json 集計 で 上位 11 種 = 99%+):
  min_attacks_this_turn_ge, min_leader_attacks_this_turn_ge, self_field_count_ge,
  opp_life_le, self_hand_ge, self_field_power_ge, self_finisher_on_field_ge,
  self_counter_in_hand_ge, self_blocker_count_ge, opp_chara_count_le,
  opp_field_total_power_le
"""
from __future__ import annotations

from typing import Any, Optional, Iterable

# game.py の Action class を type check で 使う (= 循環 import 防止 で lazy import)


# ===========================================================================
# helpers
# ===========================================================================


def _count_attacks_in_plan(plan, leader_only: bool = False) -> int:
    """plan 中 の Attack action 数 を 数える。"""
    if not plan:
        return 0
    from .game import AttackLeader, AttackCharacter
    n = 0
    for act in plan:
        if leader_only:
            if isinstance(act, AttackLeader):
                n += 1
        else:
            if isinstance(act, (AttackLeader, AttackCharacter)):
                n += 1
    return n


def _count_active_attackers(state, me_idx: int) -> int:
    """attack できる (= active + summoning_sickness なし) attacker 数。"""
    me = state.players[me_idx]
    n = 0
    if not me.leader.rested and not me.leader.summoning_sickness:
        n += 1
    for ch in me.characters:
        if not ch.rested and not ch.summoning_sickness:
            n += 1
    return n


def _count_active_leader(state, me_idx: int) -> int:
    me = state.players[me_idx]
    if not me.leader.rested and not me.leader.summoning_sickness:
        return 1
    return 0


def _playable_chara_count(state, me_idx: int) -> int:
    """手札 から play 可能 な chara 数 (= cost ≤ active DON)。 安全側 (rest が必要 等は考慮しない)。"""
    me = state.players[me_idx]
    don_available = me.don_active
    n = 0
    for c in me.hand:
        if getattr(c, "category", None) == "character" and getattr(c, "cost", 0) <= don_available:
            n += 1
    return n


def _playable_blocker_count(state, me_idx: int) -> int:
    """手札 の blocker 持ち chara で play 可能 な もの。"""
    me = state.players[me_idx]
    don_available = me.don_active
    n = 0
    for c in me.hand:
        if getattr(c, "category", None) != "character":
            continue
        if getattr(c, "cost", 0) > don_available:
            continue
        # keywords は カード text に依存、 KEYWORDS field か category 参照
        if "ブロッカー" in (getattr(c, "keywords", []) or []):
            n += 1
    return n


def _is_finisher_card(card) -> bool:
    """finisher = cost ≥ 8 or 効果 で flag 付き chara。 安全な近似。"""
    if getattr(card, "category", None) != "character":
        return False
    return getattr(card, "cost", 0) >= 8


# ===========================================================================
# is_achievable: 各 primitive に対する 到達可能性 heuristic
# ===========================================================================


def is_achievable(state, me_idx: int, if_cond: dict, plan=None) -> bool:
    """if_cond の 全 primitive が 達成可能 (= 残り このターン 中 に 満たせる) か。

    既に 満たされて いる primitive は OK (True 扱い)。 1 つでも 到達不能 で False。
    """
    if not if_cond:
        return True
    me = state.players[me_idx]
    opp = state.players[1 - me_idx]

    for key, target_val in if_cond.items():
        if not _primitive_achievable(state, me_idx, me, opp, key, target_val, plan):
            return False
    return True


def _primitive_achievable(state, me_idx: int, me, opp, key: str, val, plan) -> bool:
    """1 個 の primitive に対する 到達可能 判定。 未知 primitive は 安全側 で True。"""
    # === 攻撃 系 ===
    if key == "min_attacks_this_turn_ge":
        already = _count_attacks_in_plan(plan, leader_only=False)
        possible = _count_active_attackers(state, me_idx)
        return (already + possible) >= int(val)
    if key == "min_leader_attacks_this_turn_ge":
        already = _count_attacks_in_plan(plan, leader_only=True)
        possible = _count_active_leader(state, me_idx)
        return (already + possible) >= int(val)
    # === 自陣 リソース 系 ===
    if key == "self_field_count_ge":
        return (len(me.characters) + _playable_chara_count(state, me_idx)) >= int(val)
    if key == "self_chara_count_ge":
        return (len(me.characters) + _playable_chara_count(state, me_idx)) >= int(val)
    if key == "self_hand_ge":
        # 単純: 手札枯渇 系 action を 抑えれば 維持 可能、 既に N 以上 なら OK
        return len(me.hand) >= int(val) or len(me.hand) + 2 >= int(val)  # 2 は 1 turn 中 の 期待 draw
    if key == "self_field_power_ge":
        cur_power = sum(getattr(ch, "power", 0) for ch in me.characters)
        # DON attach で 1 個 += 1000、 残 don で 増やせる
        max_add = me.don_active * 1000
        return (cur_power + max_add) >= int(val)
    if key == "self_finisher_on_field_ge":
        cur = sum(1 for ch in me.characters if _is_finisher_card(getattr(ch, "card", None)))
        playable_finisher = sum(
            1 for c in me.hand if _is_finisher_card(c) and getattr(c, "cost", 0) <= me.don_active
        )
        return (cur + playable_finisher) >= int(val)
    if key == "self_counter_in_hand_ge":
        from .target_dsl import _card_counter_value
        n = sum(1 for c in me.hand if _card_counter_value(c) > 0)
        return n >= int(val)  # 手札 で 既に 持ってる 数 で 判定 (= 学習中 に 増えない 想定)
    if key == "self_blocker_count_ge":
        from .target_dsl import _has_blocker
        cur = sum(1 for ch in me.characters if _has_blocker(ch))
        possible = _playable_blocker_count(state, me_idx)
        return (cur + possible) >= int(val)
    if key == "self_leader_attached_don_ge":
        cur = me.leader.attached_dons
        possible = me.don_active  # 全部 attach できれば
        return (cur + possible) >= int(val)
    if key == "self_chara_attached_don_ge":
        if not me.characters:
            return False
        max_per_chara = max(ch.attached_dons for ch in me.characters)
        return (max_per_chara + me.don_active) >= int(val)
    if key == "self_trash_count_ge":
        return len(getattr(me, "trash", [])) >= int(val)
    if key == "self_chara_feature_count_ge":
        # 複合: feature 指定 が dict (= {"feature": "X", "count": N}) なら厳密、 int なら 単純
        if isinstance(val, dict):
            target_count = int(val.get("count", 1))
            cur = len(me.characters)  # feature 確認 は cost 重い、 cur 数 で 近似
            return cur >= target_count
        return len(me.characters) >= int(val)
    # === 敵陣 系 ===
    if key == "opp_life_le":
        # 自分の攻撃で削れる: active attacker 数 (= 簡易、 power 考慮なし)
        possible_hits = _count_active_attackers(state, me_idx) - _count_attacks_in_plan(plan)
        return len(opp.life) <= (int(val) + max(0, possible_hits))
    if key == "opp_chara_count_le":
        # KO action 数 を 推定 する のは 重い、 安全側 で 「+2 まで KO 可能」 と 仮定
        return len(opp.characters) <= (int(val) + 2)
    if key == "opp_field_total_power_le":
        cur = sum(getattr(ch, "power", 0) for ch in opp.characters)
        # KO で 5000 程度 削れる と 仮定
        return cur <= (int(val) + 5000)
    # === 未知 primitive: 安全側 True (= 後で支援 追加) ===
    return True


# ===========================================================================
# derive_actions_for_goal: 目指す entry へ 寄与 する 候補 action 集合
# ===========================================================================


def derive_actions_for_goal(state, me_idx: int, if_cond: dict, plan, legal_actions):
    """legal_actions から 「if_cond の 達成 に 寄与 する」 action だけ に 絞る。

    全 if 条件 の OR (= どれか の 条件 達成 に 寄与 する action を 採用)。
    safety net: EndPhase (= turn 終了) は 常に 含める (= AI が end_turn を 選べない と デッドロック)。

    候補 が 空 (= どの action も 寄与しない) なら 元の legal_actions を 返す (= fallback)。
    """
    if not if_cond:
        return legal_actions
    from .game import (
        PlayCharacter, PlayEvent, PlayStage,
        AttachDonToLeader, AttachDonToCharacter,
        AttackLeader, AttackCharacter,
        ActivateMain, EndPhase,
    )

    # 既に 満たされた 条件 は skip (= 寄与不要)、 未達成 条件 のみ で 候補 action を 集める
    me = state.players[me_idx]
    opp = state.players[1 - me_idx]
    unsatisfied: list[tuple[str, Any]] = []
    for key, target_val in if_cond.items():
        if not _primitive_currently_satisfied(state, me_idx, me, opp, key, target_val, plan):
            unsatisfied.append((key, target_val))

    if not unsatisfied:
        # 全 条件 達成 済 → 全 action 残し (= 維持 のみ で 良い、 plan_search に 委ねる)
        return legal_actions

    # OR で候補 action 集合 構築
    keep = [False] * len(legal_actions)
    for idx, action in enumerate(legal_actions):
        # safety net
        if isinstance(action, EndPhase):
            keep[idx] = True
            continue
        for key, target_val in unsatisfied:
            if _action_contributes(action, key, target_val, state, me_idx, me, opp):
                keep[idx] = True
                break

    filtered = [a for i, a in enumerate(legal_actions) if keep[i]]
    if not filtered:
        return legal_actions  # fallback: 何も 寄与しない なら 全 legal を 返す
    return filtered


def _primitive_currently_satisfied(state, me_idx, me, opp, key, val, plan) -> bool:
    """primitive が 現 state で 既に 満たされて いる か (= 寄与不要 判定 用)。"""
    if key == "min_attacks_this_turn_ge":
        return _count_attacks_in_plan(plan, leader_only=False) >= int(val)
    if key == "min_leader_attacks_this_turn_ge":
        return _count_attacks_in_plan(plan, leader_only=True) >= int(val)
    if key in ("self_field_count_ge", "self_chara_count_ge"):
        return len(me.characters) >= int(val)
    if key == "self_hand_ge":
        return len(me.hand) >= int(val)
    if key == "self_field_power_ge":
        return sum(getattr(ch, "power", 0) for ch in me.characters) >= int(val)
    if key == "self_finisher_on_field_ge":
        return sum(1 for ch in me.characters if _is_finisher_card(getattr(ch, "card", None))) >= int(val)
    if key == "self_counter_in_hand_ge":
        from .target_dsl import _card_counter_value
        return sum(1 for c in me.hand if _card_counter_value(c) > 0) >= int(val)
    if key == "self_blocker_count_ge":
        from .target_dsl import _has_blocker
        return sum(1 for ch in me.characters if _has_blocker(ch)) >= int(val)
    if key == "self_leader_attached_don_ge":
        return me.leader.attached_dons >= int(val)
    if key == "self_chara_attached_don_ge":
        if not me.characters:
            return False
        return max(ch.attached_dons for ch in me.characters) >= int(val)
    if key == "self_trash_count_ge":
        return len(getattr(me, "trash", [])) >= int(val)
    if key == "opp_life_le":
        return len(opp.life) <= int(val)
    if key == "opp_chara_count_le":
        return len(opp.characters) <= int(val)
    if key == "opp_field_total_power_le":
        return sum(getattr(ch, "power", 0) for ch in opp.characters) <= int(val)
    return False  # 未知 primitive は 「満たされていない」 (= 寄与 action を 試行 する 余地)


def _action_contributes(action, key, val, state, me_idx, me, opp) -> bool:
    """この action が この primitive の 達成 に 寄与する か。"""
    from .game import (
        PlayCharacter, PlayEvent, PlayStage,
        AttachDonToLeader, AttachDonToCharacter,
        AttackLeader, AttackCharacter,
        ActivateMain, EndPhase,
    )
    # === 攻撃 系 ===
    if key == "min_attacks_this_turn_ge":
        return isinstance(action, (AttackLeader, AttackCharacter))
    if key == "min_leader_attacks_this_turn_ge":
        return isinstance(action, AttackLeader)
    # === 自陣 リソース 系 ===
    if key in ("self_field_count_ge", "self_chara_count_ge"):
        return isinstance(action, PlayCharacter)
    if key == "self_hand_ge":
        # ドロー effect 持ちカード play は 寄与、 手札捨て系 ActivateMain は 寄与しない
        if isinstance(action, PlayCharacter):
            card = getattr(action, "card", None)
            text = getattr(card, "text", "") or ""
            return "ドロー" in text or "引く" in text or "+1枚" in text
        if isinstance(action, PlayEvent):
            card = getattr(action, "card", None)
            text = getattr(card, "text", "") or ""
            return "ドロー" in text or "引く" in text
        return False
    if key == "self_field_power_ge":
        # AttachDon は power +1000、 PlayCharacter も 寄与
        return isinstance(action, (AttachDonToLeader, AttachDonToCharacter, PlayCharacter))
    if key == "self_finisher_on_field_ge":
        if isinstance(action, PlayCharacter):
            return _is_finisher_card(getattr(action, "card", None))
        return False
    if key == "self_counter_in_hand_ge":
        # 手札 counter 持ち は 「捨てない」 が 寄与 = action の 「寄与」 は 「他の手で時間つぶす」
        # → ここでは 「counter を消費しない」 = PlayCharacter で counter なし、 攻撃、 等
        if isinstance(action, PlayCharacter):
            card = getattr(action, "card", None)
            from .target_dsl import _card_counter_value
            return _card_counter_value(card) == 0  # counter ない カード を 場 に
        return True  # その他 (= 攻撃 / DON 等) は 影響 少
    if key == "self_blocker_count_ge":
        if isinstance(action, PlayCharacter):
            card = getattr(action, "card", None)
            return "ブロッカー" in (getattr(card, "keywords", []) or [])
        return False
    if key == "self_leader_attached_don_ge":
        return isinstance(action, AttachDonToLeader)
    if key == "self_chara_attached_don_ge":
        return isinstance(action, AttachDonToCharacter)
    if key == "self_trash_count_ge":
        # trash を 増やす = カード を 場 から 失う action、 PlayEvent (= trash 行き) も
        return isinstance(action, (PlayEvent, ActivateMain))
    # === 敵陣 系 ===
    if key == "opp_life_le":
        return isinstance(action, AttackLeader)
    if key in ("opp_chara_count_le", "opp_field_total_power_le"):
        # KO 系 effect は ActivateMain / PlayEvent / PlayCharacter (on_play KO) 全部 候補
        return isinstance(action, (PlayCharacter, PlayEvent, ActivateMain))
    # 未知 primitive は 「寄与不明 = 含める」 (= 安全側)
    return True


# ===========================================================================
# lookup_best_achievable_entry: 状況 match + bonus 降順 + achievable filter
# ===========================================================================


def derive_disrupt_actions(
    state, me_idx: int, opp_if_cond: dict, plan, legal_actions,
) -> list:
    """敵 best_entry の if 条件 から、 我々 が それを 阻止 する に 寄与 する action を集める。

    ohtsuki さん ビジョン: 「相手 が 良い盤面 に なりそう なら 妨害」。 自陣 candidate と union
    して plan_search に渡すため。

    opp 視点の primitive を 我々 視点 に 翻訳:
    - opp `min_attacks_this_turn_ge: N`: 敵 attacker を 我々 turn 中 に KO する (= 敵 chara KO)
    - opp `self_*_ge` (= 敵が増やしたい): 我々 KO で 減らす
    - opp `opp_life_le: N` (= 我々 life を 削りたい): 我々 が blocker を 場 に / counter 温存
    - opp `self_finisher_on_field_ge: N`: 敵 finisher を KO / 手札送り

    候補 が 空 なら 空 list を返す (= union 側 で 自陣 candidate のみ で 走る)。
    """
    if not opp_if_cond:
        return []
    from .game import (
        PlayCharacter, PlayEvent, PlayStage,
        AttachDonToLeader, AttachDonToCharacter,
        AttackLeader, AttackCharacter,
        ActivateMain, EndPhase,
    )
    me = state.players[me_idx]
    opp = state.players[1 - me_idx]

    keep = [False] * len(legal_actions)
    for idx, action in enumerate(legal_actions):
        for key, val in opp_if_cond.items():
            if _action_disrupts(action, key, val, state, me_idx, me, opp):
                keep[idx] = True
                break
    return [a for i, a in enumerate(legal_actions) if keep[i]]


def _action_disrupts(action, key, val, state, me_idx, me, opp) -> bool:
    """この action が opp_if_cond の 達成 を 阻止 する 方向 に 寄与 する か。"""
    from .game import (
        PlayCharacter, PlayEvent, PlayStage,
        AttachDonToLeader, AttachDonToCharacter,
        AttackLeader, AttackCharacter,
        ActivateMain, EndPhase,
    )
    # 敵が attack 数 を 稼ぎたい / 自陣 field を 増やしたい → 敵 chara を KO する 系
    if key in ("min_attacks_this_turn_ge", "self_field_count_ge", "self_chara_count_ge",
               "self_field_power_ge", "self_finisher_on_field_ge", "self_blocker_count_ge"):
        # KO系 effect は PlayEvent / ActivateMain / 一部 PlayCharacter (= on_play KO) 候補
        # 攻撃で 敵 chara を KO する のも 候補
        return isinstance(action, (PlayEvent, ActivateMain, AttackCharacter))
    # 敵 が leader 攻撃 を 稼ぎたい → 我々が ブロッカー を 置く / counter 温存 (= 「攻撃しない」 は 妨害だが negative action)
    if key == "min_leader_attacks_this_turn_ge":
        # 我々ターン 中 に できる 妨害 は ブロッカー play
        if isinstance(action, PlayCharacter):
            card = getattr(action, "card", None)
            return "ブロッカー" in (getattr(card, "keywords", []) or [])
        return False
    # 敵 が 我々 life を 削りたい (opp_life_le from opp's pov = our life) → blocker play、 counter 温存 (= 何もしない方向)
    if key == "opp_life_le":
        if isinstance(action, PlayCharacter):
            card = getattr(action, "card", None)
            return "ブロッカー" in (getattr(card, "keywords", []) or [])
        return False
    # 敵 が 手札 を 増やしたい (= self_hand_ge from opp's pov) → 我々 は trash_opp_hand 効果カード
    if key == "self_hand_ge":
        # 効果 で 敵手札 を 落とす カード play = PlayEvent / PlayCharacter (on_play で trash_opp_hand)
        return isinstance(action, (PlayEvent, ActivateMain))
    # 敵 が DON leader 付与 を 増やしたい → 直接妨害 困難 (= rest_opp_don 効果 はある)
    if key in ("self_leader_attached_don_ge", "self_chara_attached_don_ge"):
        return isinstance(action, (PlayEvent, ActivateMain))
    # 敵 が trash 蓄積 を したい → 直接妨害 困難 (= 自然 進行 を 待つ しか ない)
    if key == "self_trash_count_ge":
        return False
    # 未知 primitive: 妨害方法 不明 = False
    return False


def lookup_best_achievable_entry(
    state, me_idx: int, target_spec: dict, plan=None,
) -> Optional[dict]:
    """この turn の 「目指す盤面」 を 1 つ 決める。

    1. find_matching_entries で 状況 (= turn × leader × cond) match 候補 を 取得
    2. 各 entry の 各 target を bonus × weight × importance 降順 に 並べる
    3. 最初 の achievable な target を 採用 (= if 条件 が 現状から到達可能)

    返り値: {"if": {...}, "bonus": int, "description": str} or None
    """
    if not target_spec:
        return None
    from .target_dsl import (
        find_matching_entries, compute_self_condition, get_archetype_by_slug,
    )

    opp = state.players[1 - me_idx]
    opp_leader_id = getattr(opp.leader.card, "card_id", None)
    if not opp_leader_id:
        return None
    opp_idx = 1 - me_idx
    opp_slug = None
    try:
        deck_slugs = getattr(state, "deck_slugs", None)
        if deck_slugs and len(deck_slugs) > opp_idx:
            opp_slug = deck_slugs[opp_idx] or None
    except Exception:
        opp_slug = None
    opp_archetype = get_archetype_by_slug(opp_slug)
    self_cond = compute_self_condition(state, me_idx)
    matches = find_matching_entries(
        target_spec, state.turn_number, opp_leader_id, self_cond, opp_archetype,
    )
    if not matches:
        return None

    # 全 entry × 全 target を score=weight*importance*bonus 降順 で 並べる
    candidates: list[tuple[float, dict]] = []
    for entry, weight in matches:
        importance = float(entry.get("importance", 1.0))
        for tgt in entry.get("targets", []):
            bonus = int(tgt.get("bonus", 0))
            score = weight * importance * bonus
            if score > 0:
                candidates.append((score, tgt))
    candidates.sort(key=lambda x: -x[0])

    # 上位 から achievable check
    for score, tgt in candidates:
        if_cond = tgt.get("if", {})
        if is_achievable(state, me_idx, if_cond, plan):
            return {
                "if": if_cond,
                "bonus": int(tgt.get("bonus", 0)),
                "score": score,
                "description": tgt.get("description", ""),
            }
    return None
