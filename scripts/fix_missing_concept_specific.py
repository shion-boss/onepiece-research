#!/usr/bin/env python3
"""missing_*_concept で 個別 card_id 単位 で 補完 (= 一般化 困難な mismatch を 直す)。

対象:
- OP06-035 (+_p1,_p2,_r1): on_play に rest_opp_chara_or_don x2 を 追加
- OP06-112: on_attack に rest opp don を 追加
- OP14-032: empty → on_self_rested 相手コスト4以下キャラレスト
- OP08-119 (+_p1): on_attack に ko_all_others を 追加 (= life_to_hand 1 も)
- OP06-074: on_play に conditional ko (power_le 5000) を 追加
- OP09-098 (+_p1,_r1): main / trigger に conditional ko (cost_le 4) を 追加
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OVERLAY = json.load(open(ROOT / "db" / "card_effects.json"))


def _set_with_variants(cid: str, entries: list) -> int:
    """cid と parallel variants に 同じ entries を 上書き 設定。
    既に non-empty なら variants も 含めて 上書き (= 本 fix で 強制 修正 想定)。
    """
    count = 0
    for c in [cid] + [f"{cid}{s}" for s in ("_p1", "_p2", "_r1", "_r2")]:
        if c not in OVERLAY:
            continue
        OVERLAY[c] = list(entries)
        count += 1
    return count


# OP06-035 全文 (= rest opp chara or don x2 + life_to_hand 1):
op06_035_entries = [
    {
        "_text": "OP06-035 on_play: 相手のキャラかドン 合計2枚 レスト + 自ライフ1手札",
        "when": "on_play",
        "do": [
            {"rest": "one_opp_chara_or_don"},
            {"rest": "one_opp_chara_or_don"},
            {"life_to_hand": 1},
        ],
    }
]

# OP06-112 (= rest opp don 1 を 追加):
op06_112_entries = [
    {
        "_text": "OP06-112 on_attack: 手札1捨て → 相手ドン1レスト",
        "when": "on_attack",
        "cost": {"discard_hand": 1},
        "do": [
            {"trash_self_hand_random": 1},
            {"rest_opp_don": 1},
        ],
    },
    {
        "_text": "OP06-112 trigger: 自ライフ3以下、 このカードを場に出す",
        "when": "trigger",
        "do": [{"play_self": True}],
        "if": {"self_life_le": 3},
    },
]

# OP14-032: 【自分のターン中】 このキャラがレストになった時、 相手のコスト4以下のキャラ1枚 レスト
op14_032_entries = [
    {
        "_text": "[auto] on_self_rested (自ターン中) → 相手 コスト4以下 1枚 レスト",
        "when": "on_self_rested",
        "if": {"self_turn": True},
        "do": [
            {
                "rest": {
                    "type": "one_opponent_character_filtered",
                    "filter": {"cost_le": 4},
                }
            }
        ],
    }
]

# OP08-119: ドン-10 → 他キャラ全KO + デッキ上1ライフ + 相手ライフ1トラッシュ
op08_119_entries = [
    {
        "_text": "OP08-119 on_attack: ドン-10 → 他キャラ全KO + 自デッキ上1ライフ + 相手ライフ1トラッシュ",
        "when": "on_attack",
        "cost": {"pay_don": 10},
        "do": [
            {"ko_all_others": True},
            {"put_top_to_life": 1},
            {"mill_opp_life_to_trash": 1},
        ],
    }
]

# OP06-074: ドン-1 → 相手キャラ1枚 効果無効 + (パワー5000以下なら) KO
op06_074_entries = [
    {
        "_text": "OP06-074 on_play: ドン-1 → 相手1枚 効果無効 + (パワー5000以下なら) KO",
        "when": "on_play",
        "cost": {"return_self_don_to_deck": 1},
        "do": [
            {"negate_effect": "one_opponent_character_any"},
            {
                "ko": {
                    "type": "one_opponent_character_filtered",
                    "filter": {"power_le": 5000},
                }
            },
        ],
    }
]

# OP09-098: main (黒ひげ海賊団) → 相手1枚 効果無効 + (コスト4以下なら) KO
# trigger も same target
op09_098_entries = [
    {
        "_text": "OP09-098 main: 黒ひげ海賊団 → 相手1枚 効果無効 + (コスト4以下なら) KO",
        "when": "main",
        "if": {"leader_feature": "黒ひげ海賊団"},
        "do": [
            {"negate_effect": "one_opponent_character_any"},
            {
                "ko": {
                    "type": "one_opponent_character_filtered",
                    "filter": {"cost_le": 4},
                }
            },
        ],
    },
    {
        "_text": "OP09-098 trigger: 相手リーダーかキャラ1枚 効果無効",
        "when": "trigger",
        "do": [{"negate_effect": "one_opponent_inplay_any"}],
    },
]


SETS: dict[str, list[dict]] = {
    "OP06-035": op06_035_entries,
    "OP06-112": op06_112_entries,
    "OP14-032": op14_032_entries,
    "OP08-119": op08_119_entries,
    "OP06-074": op06_074_entries,
    "OP09-098": op09_098_entries,
}


def main():
    log = []
    total = 0
    for cid, entries in SETS.items():
        n = _set_with_variants(cid, entries)
        log.append(f"  {cid} (+ variants): {n} cards updated")
        total += n
    print(f"Total cards updated: {total}")
    (ROOT / "db" / "card_effects.json").write_text(
        json.dumps(OVERLAY, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "db" / "fix_missing_concept_specific_log.md").write_text(
        "# missing_*_concept 個別 補完ログ\n\n" + "\n".join(log), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
