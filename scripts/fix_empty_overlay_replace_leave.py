#!/usr/bin/env python3
"""empty_overlay の replace_leave 系 11 件 を 手書きエントリで 補完。

OP07-042 (= chara-to-deck-bottom を do で 実行 する 必要、 engine 拡張未対応) は skip。
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OVERLAY = json.load(open(ROOT / "db" / "card_effects.json"))


ENTRIES: dict[str, list[dict]] = {
    # OP15-009 (リーダー、 黄):
    # 自分の元々のパワー7000以下のキャラが相手の効果で場を離れる場合、
    # 代わりに自分のリーダーを、 このターン中、 パワー-2000できる
    "OP15-009": [
        {
            "_text": "[auto] 自元P7000以下 効果離脱 → 自リーダー パワー-2000 (turn)",
            "when": "replace_leave",
            "if": {
                "target": "any_self_chara",
                "target_power_le": 7000,
                "by_opp_effect": True,
            },
            "do": [
                {
                    "power_pump": {
                        "target": "self_leader",
                        "amount": -2000,
                        "duration": "turn",
                    }
                }
            ],
        }
    ],
    # OP15-094:
    # このキャラ以外の自分の特徴《麦わらの一味》を持つキャラが相手の効果で場を離れる場合、
    # 代わりにこのキャラをトラッシュに置く ことができる
    "OP15-094": [
        {
            "_text": "[auto] 自他《麦わらの一味》 効果離脱 → holder トラッシュ",
            "when": "replace_leave",
            "if": {
                "target": "other_self_chara",
                "target_feature": "麦わらの一味",
                "by_opp_effect": True,
            },
            "do": [{"return_self_to_trash": True}],
        }
    ],
    # OP15-105:
    # 自分の元々のパワー7000以下のキャラが相手の効果で場を離れる場合、
    # 代わりに自分のライフの上から1枚を手札に加える ことができる
    "OP15-105": [
        {
            "_text": "[auto] 自元P7000以下 効果離脱 → 自ライフ1手札",
            "when": "replace_leave",
            "if": {
                "target": "any_self_chara",
                "target_power_le": 7000,
                "by_opp_effect": True,
            },
            "do": [{"life_to_hand": 1}],
        }
    ],
    # OP13-017:
    # 【ターン1回】自分の特徴《革命軍》を持つキャラが相手の効果で場を離れる場合、
    # 代わりにこのキャラ (= holder) を、 このターン中、 パワー-2000できる
    "OP13-017": [
        {
            "_text": "[auto] 自《革命軍》 効果離脱 → holder パワー-2000 (turn、 1回)",
            "when": "replace_leave",
            "if": {
                "target": "any_self_chara",
                "target_feature": "革命軍",
                "by_opp_effect": True,
            },
            "cost": [{"once_per_turn": True}],
            "do": [
                {
                    "power_pump": {
                        "target": "self",
                        "amount": -2000,
                        "duration": "turn",
                    }
                }
            ],
        }
    ],
    # OP13-109:
    # このキャラが相手の効果で場を離れる場合、 代わりに自分のライフの上から1枚を表向きにできる
    "OP13-109": [
        {
            "_text": "[auto] this 効果離脱 → 自ライフ1表向き (peek)",
            "when": "replace_leave",
            "if": {"target": "self", "by_opp_effect": True},
            "do": [{"peek_self_life_top": 1}],
        }
    ],
    # OP12-048:
    # 【相手のターン中】自分の青の特徴《海軍》を持つキャラが相手の効果で場を離れる場合、
    # 代わりにこのキャラ (= holder) をレストにし、 自分の手札1枚を捨てる ことができる
    "OP12-048": [
        {
            "_text": "[auto] 自青《海軍》 効果離脱 (相手ターン) → holder レスト + 手札1捨て",
            "when": "replace_leave",
            "if": {
                "target": "any_self_chara",
                "target_feature": "海軍",
                "target_color": "青",
                "by_opp_effect": True,
                "opp_turn": True,
            },
            "cost": [{"trash_self_hand_random": 1}],
            "do": [{"rest": "self"}],
        }
    ],
    # OP11-101 (+_p1):
    # 【ブロッカー】【ターン1回】「カポネ・ベッジ」以外の自分の特徴《超新星》を持つキャラが
    # 相手の効果で場を離れる場合、 代わりに自分のライフの上に裏向きで加える ことができる
    # 「裏向きで加える」 = デッキ上1枚をライフに (= put_top_to_life)。 公式 ライフのトリガー無効化の挙動
    "OP11-101": [
        {
            "_text": "[auto] 自《超新星》他 効果離脱 → デッキ上1ライフ (裏向き、 ターン1回)",
            "when": "replace_leave",
            "if": {
                "target": "any_self_chara",
                "target_feature": "超新星",
                "target_name_exclude": "カポネ・ベッジ",
                "by_opp_effect": True,
            },
            "cost": [{"once_per_turn": True}],
            "do": [{"put_top_to_life": 1}],
        }
    ],
    # ST30-011 (+_p1):
    # 自分の元々のパワー6000のキャラが相手の効果で場を離れる場合、 代わりに このキャラ (= holder) を
    # レストにできる
    "ST30-011": [
        {
            "_text": "[auto] 自元P6000 効果離脱 → holder レスト",
            "when": "replace_leave",
            "if": {
                "target": "any_self_chara",
                "target_power_le": 6000,
                "target_power_ge": 6000,
                "by_opp_effect": True,
            },
            "do": [{"rest": "self"}],
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
    (ROOT / "db" / "fix_empty_replace_leave_log.md").write_text(
        "# empty_overlay replace_leave 補完ログ\n\n" + "\n".join(log),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
