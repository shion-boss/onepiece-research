#!/usr/bin/env python3
"""empty_overlay の 「このキャラがKOされた時」 on_ko reactive を 補完。

対象:
- EB01-057 (+_p1,_p2,_r1): on_ko (相手効果) → デッキ上1ライフ
- OP03-015: on_ko (相手ターン中) → 相手1枚 パワー-2000 (turn)
- ST15-003: on_ko (相手ターン中) → 自リーダー パワー+2000 (turn)
- ST10-014: on_self_don_returned_to_deck → draw 1 + discard 1

EB01-057 の 「相手の効果で」 を opp_turn で 近似 (= 完全 一致 では ない、 効果KOは opp turn が ほとんど)。
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OVERLAY = json.load(open(ROOT / "db" / "card_effects.json"))


ENTRIES: dict[str, list[dict]] = {
    # EB01-057 シャクヤク: このキャラが相手の効果でKOされた時、 自デッキ上1ライフ
    # by_opp_effect は engine 未対応 → opp_turn で 近似 (= 相手ターン中効果KO が ほぼ全て)
    "EB01-057": [
        {
            "_text": "[auto] on_ko (相手ターン中) → デッキ上1ライフ",
            "when": "on_ko",
            "if": {"opp_turn": True},
            "do": [{"put_top_to_life": 1}],
        }
    ],
    # OP03-015 ホーキンス: 【相手のターン中】このキャラがKOされた時、 相手1枚 パワー-2000 (turn)
    "OP03-015": [
        {
            "_text": "[auto] on_ko (相手ターン中) → 相手 1 枚 パワー-2000 (turn)",
            "when": "on_ko",
            "if": {"opp_turn": True},
            "do": [
                {
                    "power_pump": {
                        "target": "one_opponent_inplay_any",
                        "amount": -2000,
                        "duration": "turn",
                    }
                }
            ],
        }
    ],
    # ST15-003: 【相手のターン中】このキャラが効果でKOされた時、 自リーダー パワー+2000 (turn)
    "ST15-003": [
        {
            "_text": "[auto] on_ko (相手ターン中) → 自リーダー パワー+2000 (turn)",
            "when": "on_ko",
            "if": {"opp_turn": True},
            "do": [
                {
                    "power_pump": {
                        "target": "self_leader",
                        "amount": 2000,
                        "duration": "turn",
                    }
                }
            ],
        }
    ],
    # ST10-014: 【ターン1回】自分の場のドン!!がドン!!デッキに戻された時、 カード1枚を引き、 手札1枚を捨てる
    "ST10-014": [
        {
            "_text": "[auto] on_self_don_returned_to_deck → draw 1 + 手札ランダム1捨て (1回)",
            "when": "on_self_don_returned_to_deck",
            "cost": {"once_per_turn": True},
            "do": [
                {"draw": 1},
                {"trash_self_hand_random": 1},
            ],
        }
    ],
}


def main():
    fixed = 0
    log = []
    for cid, entries in ENTRIES.items():
        if cid not in OVERLAY:
            log.append(f"  {cid}: SKIP (not in overlay)")
            continue
        current = OVERLAY[cid]
        if current and len(current) > 0:
            log.append(f"  {cid}: SKIP (already has {len(current)} entries)")
            continue
        OVERLAY[cid] = list(entries)
        log.append(f"  {cid}: + {len(entries)} entries")
        fixed += 1
        for suffix in ("_p1", "_p2", "_r1", "_r2"):
            variant = f"{cid}{suffix}"
            if variant in OVERLAY:
                v_current = OVERLAY[variant]
                if v_current and len(v_current) > 0:
                    log.append(f"    {variant}: SKIP (has entries)")
                    continue
                OVERLAY[variant] = list(entries)
                log.append(f"    {variant}: + {len(entries)} entries (variant)")
                fixed += 1

    print(f"Fixed {fixed} cards")
    (ROOT / "db" / "card_effects.json").write_text(
        json.dumps(OVERLAY, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "db" / "fix_empty_on_ko_reactive_log.md").write_text(
        "# empty_overlay on_ko reactive 補完ログ\n\n" + "\n".join(log),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
