#!/usr/bin/env python3
"""human play log → spec entry 化 (= 模 倣 学 習)。

各 human action を spec entry の target に 変 換:
  - axes (= 12 軸): action 直 前 の MAIN phase snapshot か ら 計 算
  - target: action_kind を if 条 件 で 表 現、 bonus は 信 頼 度 高 め (= 2700)
  - 同 axes + 同 action_kind は 重 複 排 除 (= 既 存 entry に target 追 加)

# 使 い 方
```bash
.venv/bin/python scripts/import_human_play_to_spec.py \\
    --log-dir db/human_play_log \\
    --decks-dir decks \\
    --bonus 2700
```

# 効 果
- target_missing 20% → 大 幅 削 減 (= 学 習 観 測 ゼロ の action_kind を 注 入)
- rank 2-3 → top1 化 (= 人 間 信 頼 度 で 上 書 き)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from engine.axis_compute import (
    life_bucket, hand_bucket, field_bucket, threat_bucket,
    don_bucket, active_chara_bucket,
)


# action_kind → if 条 件 マッピング (= build_spec_from_corpus と 同 形 式)
ACTION_TO_IF = {
    "PlayCharacter": {"min_play_chara_this_turn_ge": 1},
    "PlayEvent": {"min_play_event_this_turn_ge": 1},
    "PlayStage": {"min_play_stage_this_turn_ge": 1},
    "AttachDonToLeader": {"min_attach_don_leader_this_turn_ge": 1},
    "AttachDonToCharacter": {"min_attach_don_chara_this_turn_ge": 1},
    "ActivateMain": {"min_activate_main_this_turn_ge": 1},
    "AttackLeader": {"min_leader_attacks_this_turn_ge": 1},
    "AttackCharacter": {"min_attack_chara_this_turn_ge": 1},
}


def compute_axes_from_snapshot(s, me_idx, opp_archetype="midrange"):
    """snapshot dict か ら 12 軸 state_axes 計 算。"""
    me = s["players"][me_idx]
    opp = s["players"][1 - me_idx]
    target_active_power = sum(
        c.get("power", 0) for c in opp.get("characters", [])
        if not c.get("rested", False)
    )
    me_life = me.get("life_count", 0)
    opp_life = opp.get("life_count", 0)
    if me_life > opp_life:
        self_cond = "advantage"
    elif me_life < opp_life:
        self_cond = "behind"
    else:
        self_cond = "even"
    return {
        "turn": s["turn"],
        "opp_leader_id": opp["leader"]["card_id"],
        "opp_archetype": opp_archetype,
        "self_condition": self_cond,
        "opp_life_bucket": life_bucket(opp_life),
        "opp_hand_bucket": hand_bucket(opp.get("hand_count", 0)),
        "opp_field_bucket": field_bucket(len(opp.get("characters", []))),
        "opp_active_chara_bucket": active_chara_bucket(
            sum(1 for c in opp.get("characters", []) if not c.get("rested", False))
        ),
        "opp_threat_bucket": threat_bucket(target_active_power, opp.get("don_active", 0)),
        "self_life_bucket": life_bucket(me_life),
        "self_hand_bucket": hand_bucket(me.get("hand_count", 0)),
        "self_field_bucket": field_bucket(len(me.get("characters", []))),
        "self_don_bucket": don_bucket(me.get("don_active", 0)),
    }


def find_snapshot_for_action(snapshots, turn, human_idx):
    """同 turn の human_idx MAIN phase snapshot を 1 件 返 す。"""
    for s in snapshots:
        if (s.get("turn") == turn
                and s.get("turn_player_idx") == human_idx
                and s.get("phase") == "MAIN"):
            return s
    return None


def axes_to_key(axes):
    """axes dict → hashable tuple。"""
    keys = sorted(axes.keys())
    return tuple((k, axes[k]) for k in keys)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log-dir", default="db/human_play_log")
    ap.add_argument("--decks-dir", default="decks")
    ap.add_argument("--bonus", type=int, default=2700,
                    help="human-derived target bonus (= 信 頼 度 高 め、 default 2700)")
    ap.add_argument("--win-only", action="store_true",
                    help="人 間 が 勝 っ た log だ け 採 用 (= ノイズ 削 減)")
    ap.add_argument("--dry-run", action="store_true",
                    help="変 更 量 のみ 表 示、 書 込 ま な い")
    args = ap.parse_args()

    log_dir = REPO_ROOT / args.log_dir
    decks_dir = REPO_ROOT / args.decks_dir

    # 集 計: deck_slug → axes_key → action_kind → samples
    by_deck: dict[str, dict] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    deck_card_samples: dict[str, dict] = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))

    n_logs = 0
    n_actions = 0
    n_skipped_loss = 0
    for log_path in sorted(log_dir.glob("*.json")):
        log = json.loads(log_path.read_text(encoding="utf-8"))
        meta = log.get("metadata", {})
        human_idx = meta.get("human_idx")
        deck_slug = meta.get("deck_human_slug")
        if not deck_slug or human_idx is None:
            continue
        result = log.get("result", {})
        human_won = result.get("winner_for_human") == 1
        if args.win_only and not human_won:
            n_skipped_loss += 1
            continue
        n_logs += 1
        snapshots = log.get("snapshots", [])
        action_evals = log.get("action_evals", [])
        for ae in action_evals:
            if ae.get("player_idx") != human_idx:
                continue
            action_kind = ae.get("action")
            if action_kind not in ACTION_TO_IF:
                continue
            snap = find_snapshot_for_action(snapshots, ae.get("turn"), human_idx)
            if not snap:
                continue
            axes = compute_axes_from_snapshot(snap, human_idx)
            axes_key = axes_to_key(axes)
            by_deck[deck_slug][axes_key][action_kind] += 1
            ctx = ae.get("context") or {}
            cid = ctx.get("card_id")
            if cid:
                deck_card_samples[deck_slug][axes_key][action_kind].add(cid)
            n_actions += 1

    print(f"=== human play → spec import ===")
    print(f"  logs processed: {n_logs} (skipped {n_skipped_loss} loss-only)")
    print(f"  total human actions: {n_actions}")
    print(f"  decks affected: {len(by_deck)}")

    # 各 deck で entries 追 加
    for deck_slug, axes_map in by_deck.items():
        spec_path = decks_dir / f"{deck_slug}.target_v1.json"
        if not spec_path.exists():
            print(f"  WARN: {spec_path} not found, skip")
            continue
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        existing_entries = spec.setdefault("entries", [])

        # 既 entry を axes_key で index
        existing_idx: dict = {}
        for e in existing_entries:
            k = axes_to_key({
                "turn": e.get("turn"),
                "opp_leader_id": e.get("opp_leader_id"),
                "opp_archetype": e.get("opp_archetype"),
                "self_condition": e.get("self_condition"),
                "opp_life_bucket": e.get("opp_life_bucket"),
                "opp_hand_bucket": e.get("opp_hand_bucket"),
                "opp_field_bucket": e.get("opp_field_bucket"),
                "opp_active_chara_bucket": e.get("opp_active_chara_bucket"),
                "opp_threat_bucket": e.get("opp_threat_bucket"),
                "self_life_bucket": e.get("self_life_bucket"),
                "self_hand_bucket": e.get("self_hand_bucket"),
                "self_field_bucket": e.get("self_field_bucket"),
                "self_don_bucket": e.get("self_don_bucket"),
            })
            existing_idx[k] = e

        n_new_entries = 0
        n_new_targets = 0
        n_upgraded_targets = 0
        for axes_key, action_counts in axes_map.items():
            axes = dict(axes_key)
            entry = existing_idx.get(axes_key)
            if entry is None:
                # 新 規 entry 作 成
                entry = dict(axes)
                entry["importance"] = 1.0
                entry["targets"] = []
                existing_entries.append(entry)
                existing_idx[axes_key] = entry
                n_new_entries += 1
            targets = entry.setdefault("targets", [])
            for action_kind, count in action_counts.items():
                if_cond = ACTION_TO_IF[action_kind]
                if_key = next(iter(if_cond.keys()))
                # 既 target で 同 if 条 件 が あ る か
                existing_target = None
                for t in targets:
                    if if_key in (t.get("if") or {}):
                        existing_target = t
                        break
                card_ids = deck_card_samples[deck_slug][axes_key][action_kind]
                card_id_str = next(iter(card_ids)) if card_ids else None
                description = (
                    f"{action_kind} (= human play n={count}"
                    + (f", card={card_id_str}" if card_id_str else "")
                    + ")"
                )
                if existing_target is None:
                    # 新 規 target 追 加
                    targets.append({
                        "priority": len(targets) + 1,
                        "if": dict(if_cond),
                        "bonus": args.bonus,
                        "description": description,
                        "source": "human_play_import",
                        "evidence": {"n_total": count, "win_rate": 1.0},
                    })
                    n_new_targets += 1
                else:
                    # 既 存 target、 bonus が 低 い な ら 上 書 き (= 人 間 信 頼 度 を 反 映)
                    existing_bonus = int(existing_target.get("bonus", 0))
                    if existing_bonus < args.bonus:
                        existing_target["bonus"] = args.bonus
                        existing_target["description"] = (
                            existing_target.get("description", "") + f" + {description}"
                        )[:300]
                        existing_target.setdefault("evidence", {})
                        existing_target["evidence"]["human_play_boost"] = count
                        n_upgraded_targets += 1

        if args.dry_run:
            print(f"  [dry-run] {deck_slug}: +{n_new_entries} entries, "
                  f"+{n_new_targets} targets, +{n_upgraded_targets} upgraded")
        else:
            spec_path.write_text(
                json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"  {deck_slug}: +{n_new_entries} entries, "
                  f"+{n_new_targets} targets, +{n_upgraded_targets} upgraded "
                  f"→ {len(existing_entries)} total")

    return 0


if __name__ == "__main__":
    sys.exit(main())
