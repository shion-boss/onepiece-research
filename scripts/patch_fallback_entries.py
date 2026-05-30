#!/usr/bin/env python3
"""cascade fallback log + 提 案 entries (JSON) を 該 当 deck spec へ append。

# 使 い 方
```bash
# 1. 提 案 entries を JSON で 用 意 (= claude が 作 成):
#    [
#      {
#        "deck_slug": "tcgportal_op11_luffy",
#        "axes": {"turn": 8, "opp_leader_id": null, ...},
#        "action_kind": "AttackLeader",
#        "action_card_id": null,
#        "bonus": 2500,
#        "description": "終 盤 場 制 圧 (= 原 則 5)"
#      },
#      ...
#    ]
.venv/bin/python scripts/patch_fallback_entries.py /tmp/suggestions.json
```

deck spec の entries に push、 axes 全 wildcard なら catch-all として 機 能。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("suggestions_path", help="提 案 entries JSON")
    ap.add_argument("--dry-run", action="store_true", help="変 更 内 容 表 示 のみ")
    ap.add_argument("--decks-dir", default="decks", help="deck spec 保 存 dir")
    args = ap.parse_args()

    sugg_path = Path(args.suggestions_path)
    suggestions = json.loads(sugg_path.read_text(encoding="utf-8"))
    if not isinstance(suggestions, list):
        print("ERROR: suggestions JSON must be a list", file=sys.stderr)
        sys.exit(1)

    decks_dir = Path(args.decks_dir)
    by_deck: dict[str, list] = {}
    for sg in suggestions:
        slug = sg.get("deck_slug")
        if not slug:
            print(f"WARN: missing deck_slug in {sg}", file=sys.stderr)
            continue
        by_deck.setdefault(slug, []).append(sg)

    for slug, sgs in by_deck.items():
        spec_path = decks_dir / f"{slug}.target_v1.json"
        if not spec_path.exists():
            print(f"WARN: {spec_path} not found, skip", file=sys.stderr)
            continue
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        entries = spec.setdefault("entries", [])
        added = 0
        for sg in sgs:
            ax = sg.get("axes", {})
            new_entry = {
                "turn": ax.get("turn"),
                "opp_leader_id": ax.get("opp_leader_id"),
                "opp_archetype": ax.get("opp_archetype"),
                "self_condition": ax.get("self_condition"),
                "opp_life_bucket": ax.get("opp_life_bucket"),
                "opp_hand_bucket": ax.get("opp_hand_bucket"),
                "opp_field_bucket": ax.get("opp_field_bucket"),
                "opp_threat_bucket": ax.get("opp_threat_bucket"),
                "self_life_bucket": ax.get("self_life_bucket"),
                "self_hand_bucket": ax.get("self_hand_bucket"),
                "self_field_bucket": ax.get("self_field_bucket"),
                "self_don_bucket": ax.get("self_don_bucket"),
                "importance": sg.get("importance", 1.0),
                "targets": [{
                    "priority": 1,
                    "if": _action_to_if(sg["action_kind"]),
                    "bonus": int(sg.get("bonus", 1500)),
                    "action_kind": sg["action_kind"],
                    "action_card_id": sg.get("action_card_id"),
                    "description": sg.get("description", "claude-suggested fallback entry"),
                    "source": "claude_fallback_patch",
                }],
            }
            entries.append(new_entry)
            added += 1

        if args.dry_run:
            print(f"[dry-run] {slug}: would add {added} entries (total → {len(entries)})")
        else:
            spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"{slug}: added {added} entries (total → {len(entries)})")


def _action_to_if(action_kind: str) -> dict:
    """action_kind か ら if 条 件 を 自 動 生 成 (= online_update.py と 同 等)。"""
    mapping = {
        "PlayCharacter": {"min_play_chara_this_turn_ge": 1},
        "PlayEvent": {"min_play_event_this_turn_ge": 1},
        "PlayStage": {"min_play_stage_this_turn_ge": 1},
        "AttachDonToLeader": {"min_attach_don_leader_this_turn_ge": 1},
        "AttachDonToCharacter": {"min_attach_don_chara_this_turn_ge": 1},
        "ActivateMain": {"min_activate_main_this_turn_ge": 1},
        "AttackLeader": {"min_leader_attacks_this_turn_ge": 1},
        "AttackCharacter": {"min_attack_chara_this_turn_ge": 1},
    }
    return mapping.get(action_kind, {})


if __name__ == "__main__":
    main()
