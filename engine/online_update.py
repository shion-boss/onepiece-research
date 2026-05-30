"""online self-play RL: per-game spec micro-update (= 2026-05-30、 task #52)。

ohtsuki さん 提案 [[project_corpus_methodology_dead_end]] 後 続:
1 game 終了 後 に loser/winner の trajectory から spec を 微 更新 → 次 game で 強化 された
spec で プレイ → AlphaZero 系譜 の online RL。

## 設計

```
[game] A vs B
   ↓ apply 後
update_spec_from_game(winner_spec, loser_spec, game_meta, trajectory, alpha):
  for action in loser trajectory:
    axes = compute_axes(state_before_action)
    decrease bonus at (axes, action_kind) in loser_spec
  for action in winner trajectory:
    increase bonus at (axes, action_kind) in winner_spec
   ↓
spec が in-memory で 直 接 更新
   ↓
次 game の choose_action で 更新 spec が 使われる
```

## update logic

各 (axes, action_kind) を loser が 取った 場合:
  bonus *= (1 - alpha)  # 微 減

winner が 取った 場合:
  bonus *= (1 + alpha)  # 微 増

bonus は [min_clamp, max_clamp] で clip。 未 存在 entry/target は 自動 生成。

## alpha (= 学習 率) 推奨

- 0.01 = 保守 (= 1000 game で 効果 半 減 / 倍 増)
- 0.05 = 標準 (= 200 game で 半 減)
- 0.10 = aggressive (= 100 game で 半 減)
"""
from __future__ import annotations

from typing import Any, Optional


def _compute_axes_v1(turn: int, opp_leader_id: str, opp_archetype: str,
                      self_condition: str) -> tuple:
    """v1 schema の 4 軸 key を 作 る。 build_spec と 同 logic。"""
    return (turn, opp_leader_id, opp_archetype, self_condition)


def _find_or_create_entry(spec: dict, axes: tuple) -> dict:
    """axes に match する entry を spec.entries から 探 す、 なければ 自動 生 成。"""
    turn, opp_leader_id, opp_archetype, self_condition = axes
    entries = spec.setdefault("entries", [])
    # 既存 entry 検索 (= 完 全 一 致 のみ、 fuzzy 不要)
    for e in entries:
        if (e.get("turn") == turn
                and e.get("opp_leader_id") == opp_leader_id
                and e.get("opp_archetype") == opp_archetype
                and e.get("self_condition") == self_condition):
            return e
    # 新規 entry 作成 (= 後で append)
    new_entry = {
        "turn": turn,
        "opp_leader_id": opp_leader_id,
        "opp_deck_slug": None,
        "opp_archetype": opp_archetype,
        "self_condition": self_condition,
        "targets": [],
    }
    entries.append(new_entry)
    return new_entry


def _find_existing_entry(spec: dict, axes: tuple) -> dict | None:
    """既 存 entry を 厳 密 一致 で 検索、 なければ None (= no_add_entries mode 用)。"""
    turn, opp_leader_id, opp_archetype, self_condition = axes
    for e in spec.get("entries", []):
        if (e.get("turn") == turn
                and e.get("opp_leader_id") == opp_leader_id
                and e.get("opp_archetype") == opp_archetype
                and e.get("self_condition") == self_condition):
            return e
    return None


def _find_existing_target(entry: dict, action_kind: str,
                          action_card_id: str | None = None) -> dict | None:
    """既 存 target を 検 索、 なければ None。"""
    for t in entry.get("targets", []):
        if (t.get("action_kind") == action_kind
                and t.get("action_card_id") == action_card_id):
            return t
    return None


def _find_or_create_target(entry: dict, action_kind: str,
                            action_card_id: str | None = None,
                            init_bonus: int = 1500) -> dict:
    """entry 内 で (action_kind, card_id) に 該当 する target を 探 す、 なければ 作 る。"""
    targets = entry.setdefault("targets", [])
    for t in targets:
        if (t.get("action_kind") == action_kind
                and t.get("action_card_id") == action_card_id):
            return t
    # 新規 target 作成
    from_action_to_if = {
        "PlayCharacter": {"min_play_chara_this_turn_ge": 1},
        "PlayEvent": {"min_play_event_this_turn_ge": 1},
        "PlayStage": {"min_play_stage_this_turn_ge": 1},
        "AttachDonToLeader": {"min_attach_don_leader_this_turn_ge": 1},
        "AttachDonToCharacter": {"min_attach_don_chara_this_turn_ge": 1},
        "ActivateMain": {"min_activate_main_this_turn_ge": 1},
        "AttackLeader": {"min_leader_attacks_this_turn_ge": 1},
        "AttackCharacter": {"min_attack_chara_this_turn_ge": 1},
    }
    new_target = {
        "priority": len(targets) + 1,
        "if": from_action_to_if.get(action_kind, {}),
        "bonus": init_bonus,
        "action_kind": action_kind,
        "action_card_id": action_card_id,
        "description": f"online-learned: {action_kind}",
        "source": "online_self_play",
        "evidence": {"online_updates": 0},
    }
    targets.append(new_target)
    return new_target


def update_target_bonus(target: dict, factor: float, clamp_min: int, clamp_max: int) -> None:
    """target.bonus *= factor、 clamp + evidence 更新。"""
    new_bonus = int(target.get("bonus", 1500) * factor)
    new_bonus = max(clamp_min, min(clamp_max, new_bonus))
    target["bonus"] = new_bonus
    # evidence 更新
    evidence = target.setdefault("evidence", {})
    evidence["online_updates"] = evidence.get("online_updates", 0) + 1


def update_spec_from_trajectory(
    spec: dict,
    trajectory: list[dict],
    won: bool,
    alpha: float = 0.05,
    clamp_min: int = 100,
    clamp_max: int = 5000,
    no_add_entries: bool = False,
    advantage: float | None = None,
) -> dict:
    """spec を 1 game 分 の trajectory で micro-update。

    trajectory = list of action records (= corpus dump 形式) で、 各 item に:
      - state_before の axes 軸 値
      - action 種別

    won = True → 取った action を boost (= bonus *= 1+alpha)
    won = False → 取った action を decay (= bonus *= 1-alpha)

    no_add_entries: True なら 新 entry/target 追加 を skip (= Phase B 用)。
    advantage: None なら 単純 win/loss、 値 指定 で advantage normalization:
       factor = 1 + alpha × advantage (= 「期待 勝率 超過 分 を 強化」)。

    return: 更新 統計 (= {n_targets_touched, n_entries_created, ...})。
    """
    if advantage is not None:
        # advantage normalization (= 2026-05-30 追加、 noise drift 抑制)
        factor = 1.0 + alpha * advantage  # advantage ∈ [-1, +1] 想定
        factor = max(0.5, min(2.0, factor))  # 暴走 防止
    else:
        factor = (1.0 + alpha) if won else (1.0 - alpha)
    stats = {"n_actions": 0, "n_targets_touched": 0,
             "n_entries_created": 0, "n_targets_created": 0}
    pre_n_entries = len(spec.get("entries", []))

    for record in trajectory:
        axes_key = record.get("axes_key")
        action_kind = record.get("action_kind")
        action_card_id = record.get("action_card_id")
        if not axes_key or not action_kind:
            continue
        if action_kind == "EndPhase":
            continue  # end phase は 学習 対象 外

        pre_n_targets = sum(len(e.get("targets", []))
                            for e in spec.get("entries", []))
        if no_add_entries:
            # Phase B mode: 既 存 entries のみ 更新、 新 規 追加 抑 制
            entry = _find_existing_entry(spec, axes_key)
            if entry is None:
                continue  # match なし → skip (= 既 存 entries 軸 と 違う → 学習 対象 外)
            target = _find_existing_target(entry, action_kind, action_card_id)
            if target is None:
                continue
        else:
            entry = _find_or_create_entry(spec, axes_key)
            target = _find_or_create_target(entry, action_kind, action_card_id)
        post_n_targets = sum(len(e.get("targets", []))
                             for e in spec.get("entries", []))
        if post_n_targets > pre_n_targets:
            stats["n_targets_created"] += 1
        update_target_bonus(target, factor, clamp_min, clamp_max)
        stats["n_targets_touched"] += 1
        stats["n_actions"] += 1

    post_n_entries = len(spec.get("entries", []))
    stats["n_entries_created"] = post_n_entries - pre_n_entries
    return stats


def extract_trajectory_from_corpus_game(game_dict: dict, side_idx: int,
                                        leader_to_deck: dict) -> list[dict]:
    """corpus dump (= game_*.json) の actions から 指定 side の trajectory を 抽出。

    各 action record に axes_key を 計算 して 付 与:
      axes_key = (turn, opp_leader_id, opp_archetype, self_condition)
    """
    from scripts.build_spec_from_corpus import (
        _self_condition_from_snapshot, _normalize_archetype, resolve_card_id,
    )
    actions = game_dict.get("actions") or []
    trajectory = []
    for action in actions:
        if action.get("active_player") != side_idx:
            continue
        sb = action.get("state_before") or {}
        players = sb.get("players") or []
        if len(players) != 2:
            continue
        actor_p = players[side_idx]
        opp_p = players[1 - side_idx]
        # axes 計算
        turn = sb.get("turn_number", 0)
        opp_leader = (opp_p.get("leader") or {}).get("card_id")
        if not opp_leader:
            continue
        opp_deck = leader_to_deck.get(opp_leader)
        opp_archetype = "midrange"
        if opp_deck:
            # build_spec の build_leader_maps と 同等 を 使う 想定
            from scripts.build_spec_from_corpus import build_leader_maps
            _, deck_to_arch, _ = build_leader_maps()
            opp_archetype = _normalize_archetype(deck_to_arch.get(opp_deck))
        self_cond = _self_condition_from_snapshot(actor_p, opp_p)
        axes_key = (turn, opp_leader, opp_archetype, self_cond)

        action_dict = action.get("action") or {}
        action_kind = action_dict.get("kind", "?")
        card_id = resolve_card_id(action_dict, actor_p)

        trajectory.append({
            "axes_key": axes_key,
            "action_kind": action_kind,
            "action_card_id": card_id,
            "turn": turn,
        })
    return trajectory


def save_spec(spec: dict, path) -> None:
    """spec を JSON に 保存 (= online update を 永続 化)。"""
    import json
    from pathlib import Path
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
