#!/usr/bin/env python3
"""fake_power_5000_limit 残 9 件 を 修正。

対象:
- OP04-056 (+_p1,_p2,_p3,_r1): main / trigger の return_to_hand を return_to_deck_bottom に
  + target を le_5000 → opp_inplay (フィルタなし) に修正
- EB01-040 (+_p1,_p2) / ST06-001: ko target le_5000 → cost_eq:0 (= 公式 「コスト0」)
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OVERLAY = json.load(open(ROOT / "db" / "card_effects.json"))


def main():
    log = []

    # OP04-056 (+ variants): main return_to_hand → return_to_deck_bottom (no filter)
    # trigger: return_to_hand cost_le_4 → return_to_deck_bottom + cost_le 4
    for cid in ["OP04-056"] + [f"OP04-056{s}" for s in ("_p1", "_p2", "_p3", "_r1")]:
        if cid not in OVERLAY:
            continue
        for e in OVERLAY[cid]:
            if not isinstance(e, dict):
                continue
            if e.get("when") == "main":
                # 旧 do: [{"return_to_hand": "one_opponent_character_le_5000"}]
                e["do"] = [
                    {
                        "return_to_deck_bottom": {
                            "target": {
                                "type": "one_opponent_inplay_filtered",
                                "filter": {"category_in": ["CHARACTER"]},
                            }
                        }
                    }
                ]
                e["_text"] = "OP04-056 main: キャラ1枚 デッキ下"
                log.append(f"  {cid}: main return_to_deck_bottom (no power filter)")
            elif e.get("when") == "trigger":
                e["do"] = [
                    {
                        "return_to_deck_bottom": {
                            "target": {
                                "type": "one_opponent_character_filtered",
                                "filter": {"cost_le": 4},
                            }
                        }
                    }
                ]
                e["_text"] = "OP04-056 trigger: コスト4以下キャラ1枚 デッキ下"
                log.append(f"  {cid}: trigger return_to_deck_bottom cost_le 4")

    # EB01-040 (+_p1,_p2): ko target le_5000 → cost_eq 0
    for cid in ["EB01-040"] + [f"EB01-040{s}" for s in ("_p1", "_p2", "_r1")]:
        if cid not in OVERLAY:
            continue
        for e in OVERLAY[cid]:
            if not isinstance(e, dict):
                continue
            if e.get("when") == "activate_main":
                e["do"] = [
                    {
                        "ko": {
                            "type": "one_opponent_character_filtered",
                            "filter": {"cost_eq": 0},
                        }
                    }
                ]
                if "コスト0" not in e.get("_text", ""):
                    e["_text"] = (
                        "EB01-040 【起動メイン】【ターン1回】 自ライフ1表向き → "
                        "相手コスト0キャラ1枚 KO"
                    )
                log.append(f"  {cid}: ko target → cost_eq 0")

    # ST06-001: 同様 修正
    for cid in ["ST06-001"] + [f"ST06-001{s}" for s in ("_p1", "_p2", "_r1")]:
        if cid not in OVERLAY:
            continue
        for e in OVERLAY[cid]:
            if not isinstance(e, dict):
                continue
            if e.get("when") == "activate_main":
                e["do"] = [
                    {
                        "ko": {
                            "type": "one_opponent_character_filtered",
                            "filter": {"cost_eq": 0},
                        }
                    }
                ]
                if "コスト0" not in e.get("_text", ""):
                    e["_text"] = (
                        "ST06-001 【起動メイン】【ターン1回】ドン3レスト + 手札1捨て → "
                        "相手コスト0キャラ1枚 KO"
                    )
                log.append(f"  {cid}: ko target → cost_eq 0")

    (ROOT / "db" / "card_effects.json").write_text(
        json.dumps(OVERLAY, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "db" / "fix_fake_power_5000_v3_log.md").write_text(
        "# fake_power_5000_limit v3 補完ログ\n\n" + "\n".join(log), encoding="utf-8"
    )
    print("\n".join(log))


if __name__ == "__main__":
    main()
