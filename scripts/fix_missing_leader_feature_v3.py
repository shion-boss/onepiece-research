#!/usr/bin/env python3
"""missing_if_leader_feature 残 10 件 のうち、 mechanical な ケース を 補完。

対象:
- OP04-096 (+_p1,_p2,_r1): leader_feature ドレスローザ + 自《ドレスローザ》 キャラ 速攻 static
- OP07-071 (+_p1): leader_feature フォクシー海賊団 + 相手キャラ全 power-1000 (opp_turn static)
- PRB02-001_p1: 親 PRB02-001 と sync (= 静的 buff entry 不足)
- EB04-035: 既存 entry に if leader_feature + 必要 modifications

複雑 skip:
- OP09-025: 「リーダーとのバトルでKOされない」 (= 細粒度 ko_immune 要件)
- OP06-048: 「相手が【ブロッカー】 か イベントを発動した時」 reactive trigger
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OVERLAY = json.load(open(ROOT / "db" / "card_effects.json"))


def add_to(cid: str, new_entries: list[dict]) -> int:
    count = 0
    for c in [cid] + [f"{cid}{s}" for s in ("_p1", "_p2", "_r1", "_r2")]:
        if c not in OVERLAY:
            continue
        if not isinstance(OVERLAY[c], list):
            continue
        OVERLAY[c].extend(new_entries)
        count += 1
    return count


def main():
    log = []

    # OP04-096: leader_feature ドレスローザ + 自《ドレスローザ》 キャラ 速攻 static
    n = add_to("OP04-096", [
        {
            "_text": "[auto] leader_feature ドレスローザ → 自《ドレスローザ》 キャラ 速攻 (static)",
            "when": "on_attached_don",
            "n": 0,
            "if": {"leader_feature": "ドレスローザ"},
            "do": [
                {
                    "give_keyword": {
                        "target": {
                            "type": "all_self_chara_filtered",
                            "filter": {"feature": "ドレスローザ"},
                        },
                        "keyword": "速攻",
                    }
                }
            ],
        }
    ])
    log.append(f"  OP04-096 (+ variants): +1 entry × {n}")

    # OP07-071: 【相手のターン中】 leader_feature フォクシー海賊団 → 相手キャラ全 power-1000 (static)
    n = add_to("OP07-071", [
        {
            "_text": "[auto] 【相手のターン中】 leader フォクシー海賊団 → 相手キャラ全 -1000 (static)",
            "when": "on_attached_don",
            "n": 0,
            "if": {"opp_turn": True, "leader_feature": "フォクシー海賊団"},
            "do": [
                {
                    "power_pump": {
                        "target": {
                            "type": "all_opponent_chara_filtered",
                            "filter": {},
                        },
                        "amount": -1000,
                        "duration": "static",
                    }
                }
            ],
        }
    ])
    log.append(f"  OP07-071 (+_p1): +1 entry × {n}")

    # PRB02-001_p1: sync 静的 buff entry (= 親 PRB02-001 と同じ structure)
    if "PRB02-001_p1" in OVERLAY:
        # 親と同じ静的 buff entry を 追加 (= 既存に重複しないように)
        parent = OVERLAY.get("PRB02-001", [])
        target_entry = None
        for e in parent:
            if isinstance(e, dict) and e.get("when") == "on_attached_don":
                target_entry = e
                break
        if target_entry:
            # 既存 PRB02-001_p1 に append (= 既に sync 済み なら skip)
            existing_flat = json.dumps(OVERLAY["PRB02-001_p1"], ensure_ascii=False)
            if "on_attached_don" not in existing_flat:
                OVERLAY["PRB02-001_p1"].append(target_entry)
                log.append(f"  PRB02-001_p1: + on_attached_don entry (sync from parent)")

    # EB04-035: 既存 entry に if leader_feature + once_per_turn を patch
    for cid in ["EB04-035"] + [f"EB04-035{s}" for s in ("_p1", "_p2", "_r1", "_r2")]:
        if cid not in OVERLAY:
            continue
        for e in OVERLAY[cid]:
            if isinstance(e, dict) and e.get("when") == "on_self_don_returned_to_deck":
                if "if" not in e:
                    e["if"] = {}
                e["if"]["leader_feature"] = "キッド海賊団"
                if "cost" not in e:
                    e["cost"] = {"once_per_turn": True}
                elif isinstance(e["cost"], dict):
                    e["cost"]["once_per_turn"] = True
                log.append(f"  {cid}: + if leader_feature キッド海賊団 + once_per_turn")

    (ROOT / "db" / "card_effects.json").write_text(
        json.dumps(OVERLAY, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "db" / "fix_missing_leader_feature_v3_log.md").write_text(
        "# missing_if_leader_feature v3 補完ログ\n\n" + "\n".join(log), encoding="utf-8"
    )
    print("\n".join(log))


if __name__ == "__main__":
    main()
