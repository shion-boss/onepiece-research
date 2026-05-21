#!/usr/bin/env python3
"""empty_overlay の replace_ko/replace_leave 系を 手書きエントリで 補完 (v2)。

対象 19 件 のうち、 doable な 16 件 (= OP05-001 系 「victim 自体に power-1000」 の
target=victim サポート が 必要な 3 件 は skip):

- OP05-030 (+_p1,_p2,_r1): 自レストキャラ KO 代替 → holder トラッシュ
- OP13-008 / OP13-047 / OP13-060: 自特徴キャラ 効果KO 代替 → holder トラッシュ
- OP09-012 (+_r1): 自「ボンク・パンチ」効果KO 代替 → holder トラッシュ
- ST29-008 (+_p1): 自《エッグヘッド》効果KO 代替 → ライフ表向き (peek)
- OP14-092: this KO 代替 → トラッシュ3枚をデッキ下
- OP10-034: this バトルKO 代替 → ライフ手札 (optional)
- OP10-074: this 効果KO 代替 → アクティブドン2レスト
- ST20-002: this 効果KO 代替 → ライフ1トラッシュ (optional)
- ST09-010: this KO 代替 → ライフ上下から1トラッシュ (近似: mill_self_life_to_trash 1)
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OVERLAY = json.load(open(ROOT / "db" / "card_effects.json"))


ENTRIES: dict[str, list[dict]] = {
    # OP05-030 ホワイティベイ:
    # 【ブロッカー】【相手のターン中】自分のレストのキャラがKOされる場合、 代わりに このキャラをトラッシュに
    "OP05-030": [
        {
            "_text": "[auto] 自レストキャラ KO 代替 → holder トラッシュ",
            "when": "replace_ko",
            "if": {
                "target": "other_self_chara",
                "target_rested": True,
                "opp_turn": True,
            },
            "do": [{"return_self_to_trash": True}],
        }
    ],
    # OP13-008 / OP13-047 / OP13-060: 特徴キャラ 効果KO 代替 → holder トラッシュ
    "OP13-008": [
        {
            "_text": "[auto] 自《革命軍》キャラ 効果KO 代替 → holder トラッシュ",
            "when": "replace_ko",
            "if": {
                "target": "any_self_chara",
                "target_feature": "革命軍",
                "by_opp_effect": True,
            },
            "do": [{"return_self_to_trash": True}],
        }
    ],
    "OP13-047": [
        {
            "_text": "[auto] 自『白ひげ海賊団』含む特徴 キャラ 効果KO 代替 → holder トラッシュ",
            "when": "replace_ko",
            "if": {
                "target": "any_self_chara",
                "target_feature_contains": "白ひげ海賊団",
                "by_opp_effect": True,
            },
            "do": [{"return_self_to_trash": True}],
        }
    ],
    "OP13-060": [
        {
            "_text": "[auto] 自『ロジャー海賊団』含む特徴 キャラ 効果KO 代替 → holder トラッシュ",
            "when": "replace_ko",
            "if": {
                "target": "any_self_chara",
                "target_feature_contains": "ロジャー海賊団",
                "by_opp_effect": True,
            },
            "do": [{"return_self_to_trash": True}],
        }
    ],
    # OP09-012 ペコムズ:
    # 自分のキャラの「ボンク・パンチ」が効果でKOされる場合、 代わりに このキャラをトラッシュに置いてもよい
    "OP09-012": [
        {
            "_text": "[auto] 自「ボンク・パンチ」 効果KO 代替 → holder トラッシュ (任意)",
            "when": "replace_ko",
            "if": {
                "target": "any_self_chara",
                "target_name": "ボンク・パンチ",
                "by_opp_effect": True,
            },
            "do": [{"return_self_to_trash": True}],
        }
    ],
    # ST29-008 / _p1: 自《エッグヘッド》キャラ 効果KO 代替 → ライフ1枚を表向き
    # 「表向きにする」 は engine 未対応 → peek_self_life_top で 近似
    "ST29-008": [
        {
            "_text": "[auto] 自《エッグヘッド》 効果KO 代替 → ライフ表向き (peek)",
            "when": "replace_ko",
            "if": {
                "target": "any_self_chara",
                "target_feature": "エッグヘッド",
                "by_opp_effect": True,
            },
            "do": [{"peek_self_life_top": 1}],
        }
    ],
    # OP14-092 イム様:
    # 【相手のターン中】【ターン1回】このキャラがKOされる場合、代わりに自分のトラッシュからカード3枚を好きな順番でデッキの下に置くことができる
    "OP14-092": [
        {
            "_text": "[auto] this KO 代替 → 自トラッシュ3枚をデッキ下 (ターン1回)",
            "when": "replace_ko",
            "if": {"target": "self", "opp_turn": True},
            "cost": [{"once_per_turn": True}],
            "do": [
                {
                    "trash_to_deck": {
                        "filter": {},
                        "limit": 3,
                        "to": "bottom",
                    }
                }
            ],
        }
    ],
    # OP10-034 タマ:
    # 【ターン1回】このキャラがバトルでKOされる場合、代わりに自分のライフの上から1枚を手札に加えてもよい
    "OP10-034": [
        {
            "_text": "[auto] this バトル KO 代替 → ライフ1手札 (ターン1回 任意)",
            "when": "replace_ko",
            "if": {"target": "self", "by_battle": True},
            "cost": [{"once_per_turn": True}],
            "do": [{"life_to_hand": 1}],
        }
    ],
    # OP10-074 ナミ:
    # 【ターン1回】このキャラが相手の効果でKOされる場合、代わりに自分のアクティブのドン‼2枚をレストにできる
    "OP10-074": [
        {
            "_text": "[auto] this 効果KO 代替 → アクティブドン2レスト (ターン1回)",
            "when": "replace_ko",
            "if": {"target": "self", "by_opp_effect": True},
            "cost": [{"once_per_turn": True}],
            "do": [{"rest_self_don": 2}],
        }
    ],
    # ST20-002 (ガス・パームス? 確認 必要):
    # 【ターン1回】このキャラが効果でKOされる場合、代わりに自分のライフの上から1枚をトラッシュに置いてもよい
    "ST20-002": [
        {
            "_text": "[auto] this 効果KO 代替 → ライフ1トラッシュ (ターン1回 任意)",
            "when": "replace_ko",
            "if": {"target": "self", "by_opp_effect": True},
            "cost": [{"once_per_turn": True}],
            "do": [{"mill_self_life_to_trash": 1}],
        }
    ],
    # ST09-010:
    # 【ターン1回】このキャラがKOされる場合、代わりに自分のライフの上か下から1枚をトラッシュに置くことができる
    # 「上か下」 → 上のみ で 近似
    "ST09-010": [
        {
            "_text": "[auto] this KO 代替 → ライフ上1トラッシュ (ターン1回、上か下→上)",
            "when": "replace_ko",
            "if": {"target": "self"},
            "cost": [{"once_per_turn": True}],
            "do": [{"mill_self_life_to_trash": 1}],
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
    (ROOT / "db" / "fix_empty_replace_ko_v2_log.md").write_text(
        "# empty_overlay replace_ko v2 補完ログ\n\n" + "\n".join(log),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
