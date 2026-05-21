#!/usr/bin/env python3
"""empty_overlay の 「【自分のターン中】 [条件] <target> パワー/コスト ±N」 静的 buff を 補完。

audit `empty_overlay_with_text` の 'own_turn_static' カテゴリ (= 約 24 件) のうち、
mechanical に 解釈できる ケース を 手書きエントリで 補完。

trigger 系 (= レストになった時、 DON returned 等) は 別タスク (= 新規 trigger 追加 必要)。
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OVERLAY = json.load(open(ROOT / "db" / "card_effects.json"))


# card_id → list of entries to set (overwrite). parallel variants are added.
ENTRIES: dict[str, list[dict]] = {
    # OP04-012 ネフェルタリ・コブラ (ステージ、 赤):
    # 【自分のターン中】このキャラ以外の自分の特徴《アラバスタ王国》を持つキャラすべてを、 パワー+1000
    # → ステージ自身は characters に 入らないため filter feature:アラバスタ王国 で 自然に 除外可。
    "OP04-012": [
        {
            "_text": "[auto] 自ターン中、 自特徴《アラバスタ王国》キャラすべて パワー+1000",
            "when": "on_attached_don",
            "n": 0,
            "if": {"self_turn": True},
            "do": [
                {
                    "power_pump": {
                        "target": {
                            "type": "all_self_chara_filtered",
                            "filter": {"feature": "アラバスタ王国"},
                        },
                        "amount": 1000,
                        "duration": "static",
                    }
                }
            ],
        }
    ],
    # OP14-034 モンキー・D・ルフィ (緑):
    # 第1節: 【自分のターン中】 自元コスト4以上の緑特徴《麦わらの一味》 キャラすべて、 パワー+1000
    # 第2節: 【ターン1回】 自特徴《麦わらの一味》 キャラが 相手の効果でKO される場合、 代わりに自分のキャラ1枚をレスト できる
    # 第2節は replace_ko 系で 複雑 → 第1節のみ 補完
    "OP14-034": [
        {
            "_text": "[auto] 自ターン中、 自緑特徴《麦わらの一味》コスト4以上 キャラすべて パワー+1000",
            "when": "on_attached_don",
            "n": 0,
            "if": {"self_turn": True},
            "do": [
                {
                    "power_pump": {
                        "target": {
                            "type": "all_self_chara_filtered",
                            "filter": {
                                "cost_ge": 4,
                                "color": "緑",
                                "feature": "麦わらの一味",
                            },
                        },
                        "amount": 1000,
                        "duration": "static",
                    }
                }
            ],
        }
    ],
    # ST30-003 エドワード・ニューゲート:
    # 【自分のターン中】 自元パワー6000のキャラすべて、 パワー+1000
    "ST30-003": [
        {
            "_text": "[auto] 自ターン中、 自元パワー6000キャラすべて パワー+1000",
            "when": "on_attached_don",
            "n": 0,
            "if": {"self_turn": True},
            "do": [
                {
                    "power_pump": {
                        "target": {
                            "type": "all_self_chara_filtered",
                            "filter": {"power_eq": 6000},
                        },
                        "amount": 1000,
                        "duration": "static",
                    }
                }
            ],
        }
    ],
    # P-066 ボア・ハンコック:
    # 【自分のターン中】 自手札5以下の場合、 自特徴《九蛇海賊団》 キャラすべて、 パワー+1000
    "P-066": [
        {
            "_text": "[auto] 自ターン中 + 自手札5以下、 自特徴《九蛇海賊団》キャラすべて パワー+1000",
            "when": "on_attached_don",
            "n": 0,
            "if": {"self_turn": True, "self_hand_count_le": 5},
            "do": [
                {
                    "power_pump": {
                        "target": {
                            "type": "all_self_chara_filtered",
                            "filter": {"feature": "九蛇海賊団"},
                        },
                        "amount": 1000,
                        "duration": "static",
                    }
                }
            ],
        }
    ],
    # OP07-087 バスカビル:
    # 【自分のターン中】 相手のコスト0のキャラがいる場合、 このキャラはパワー+3000
    "OP07-087": [
        {
            "_text": "[auto] 自ターン中 + 相手コスト0キャラあり、 このキャラ パワー+3000",
            "when": "on_attached_don",
            "n": 0,
            "if": {
                "self_turn": True,
                "opp_chara_filtered_count_ge": {
                    "filter": {"cost_eq": 0},
                    "count": 1,
                },
            },
            "do": [
                {
                    "power_pump": {
                        "target": "self",
                        "amount": 3000,
                        "duration": "static",
                    }
                }
            ],
        }
    ],
    # OP08-006 チェスマーリモ:
    # 【自分のターン中】 自トラッシュに「クロマーリモ」 と 「チェス」 がある場合、 このキャラ パワー+2000
    "OP08-006": [
        {
            "_text": "[auto] 自ターン中 + 自トラッシュに「クロマーリモ」「チェス」、 このキャラ パワー+2000",
            "when": "on_attached_don",
            "n": 0,
            "if": {
                "self_turn": True,
                "self_trash_has_named_all": ["クロマーリモ", "チェス"],
            },
            "do": [
                {
                    "power_pump": {
                        "target": "self",
                        "amount": 2000,
                        "duration": "static",
                    }
                }
            ],
        }
    ],
    # OP02-024 モビー・ディック号 (ステージ、 赤):
    # 【自分のターン中】 自ライフ1以下、 自分の「エドワード・ニューゲート」と『白ひげ海賊団』を含む特徴を持つキャラ
    # すべてを、 パワー+2000
    "OP02-024": [
        {
            "_text": "[auto] 自ターン中 + 自ライフ1以下、 名「エドワード・ニューゲート」or特徴『白ひげ海賊団』含むキャラ パワー+2000",
            "when": "on_attached_don",
            "n": 0,
            "if": {"self_turn": True, "self_life_le": 1},
            "do": [
                {
                    "power_pump": {
                        "target": {
                            "type": "all_self_chara_filtered",
                            "filter": {
                                "or": [
                                    {"name": "エドワード・ニューゲート"},
                                    {"feature_contains": "白ひげ海賊団"},
                                ]
                            },
                        },
                        "amount": 2000,
                        "duration": "static",
                    }
                }
            ],
        }
    ],
    # OP05-084 チャルロス聖:
    # 【自分のターン中】 自場のキャラが、 特徴《天竜人》のみの場合、 相手のキャラすべてをコスト-4
    "OP05-084": [
        {
            "_text": "[auto] 自ターン中 + 自場《天竜人》のみ、 相手キャラすべてをコスト-4",
            "when": "on_attached_don",
            "n": 0,
            "if": {"self_turn": True, "self_chara_only_feature": "天竜人"},
            "do": [
                {
                    "set_base_cost_filtered_static": {
                        "filter": {},
                        "delta": -4,
                        "scope": "opp",
                    }
                }
            ],
        }
    ],
    # OP05-092 ロズワード聖 (同上、 amount -6):
    "OP05-092": [
        {
            "_text": "[auto] 自ターン中 + 自場《天竜人》のみ、 相手キャラすべてをコスト-6",
            "when": "on_attached_don",
            "n": 0,
            "if": {"self_turn": True, "self_chara_only_feature": "天竜人"},
            "do": [
                {
                    "set_base_cost_filtered_static": {
                        "filter": {},
                        "delta": -6,
                        "scope": "opp",
                    }
                }
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
        # parallel variants
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
    (ROOT / "db" / "fix_empty_own_turn_static_log.md").write_text(
        "# empty_overlay own_turn_static 補完ログ\n\n" + "\n".join(log),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
