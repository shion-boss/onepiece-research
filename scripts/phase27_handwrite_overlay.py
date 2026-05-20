# -*- coding: utf-8 -*-
"""
Phase 2.7: 残 33 cards 手書き overlay (= 公式テキスト 1:1 で 個別実装)

各 entry は カード の 公式テキスト を `_text` フィールド に 全文 注釈。
既存 DSL primitive 範囲 で 表現 不可能 な 部分 (= "battle" duration give_keyword 等) は
近似で turn duration へ 落とすが、 `_approx_note` で 公式 と の 差分 を 明示。

bulk append (= 既存 entry を 破壊せず append のみ)。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OVERLAY_JSON = ROOT / "db" / "card_effects.json"


# (card_id, list_of_entries_to_add)
HANDWRITTEN_ENTRIES: list[tuple[str, list[dict]]] = [
    # A: dual trigger 【登場時】/【アタック時】 + 手札2枚捨て: DA turn
    (
        "OP02-062",
        [
            {
                "_text": "【登場時】/【アタック時】自分の手札2枚を捨てることができる：コスト4以下のキャラ1枚までを、持ち主の手札に戻す。その後、このキャラは、このターン中、【ダブルアタック】を得る。",
                "when": "on_play",
                "do": [
                    {
                        "optional_cost_then": {
                            "cost": [{"trash_self_hand_random": 2}],
                            "effect": [
                                {"return_to_hand": "one_inplay_cost_le_4"},
                                {
                                    "give_keyword": {
                                        "target": "self",
                                        "keyword": "ダブルアタック",
                                        "duration": "turn",
                                    }
                                },
                            ],
                        }
                    }
                ],
            },
            {
                "_text": "【登場時】/【アタック時】自分の手札2枚を捨てることができる：コスト4以下のキャラ1枚までを、持ち主の手札に戻す。その後、このキャラは、このターン中、【ダブルアタック】を得る。",
                "when": "on_attack",
                "do": [
                    {
                        "optional_cost_then": {
                            "cost": [{"trash_self_hand_random": 2}],
                            "effect": [
                                {"return_to_hand": "one_inplay_cost_le_4"},
                                {
                                    "give_keyword": {
                                        "target": "self",
                                        "keyword": "ダブルアタック",
                                        "duration": "turn",
                                    }
                                },
                            ],
                        }
                    }
                ],
            },
        ],
    ),
    (
        "OP02-062_p1",
        [
            {
                "_text": "【登場時】/【アタック時】自分の手札2枚を捨てることができる：コスト4以下のキャラ1枚までを、持ち主の手札に戻す。その後、このキャラは、このターン中、【ダブルアタック】を得る。",
                "when": "on_play",
                "do": [
                    {
                        "optional_cost_then": {
                            "cost": [{"trash_self_hand_random": 2}],
                            "effect": [
                                {"return_to_hand": "one_inplay_cost_le_4"},
                                {
                                    "give_keyword": {
                                        "target": "self",
                                        "keyword": "ダブルアタック",
                                        "duration": "turn",
                                    }
                                },
                            ],
                        }
                    }
                ],
            },
            {
                "_text": "【登場時】/【アタック時】自分の手札2枚を捨てることができる：コスト4以下のキャラ1枚までを、持ち主の手札に戻す。その後、このキャラは、このターン中、【ダブルアタック】を得る。",
                "when": "on_attack",
                "do": [
                    {
                        "optional_cost_then": {
                            "cost": [{"trash_self_hand_random": 2}],
                            "effect": [
                                {"return_to_hand": "one_inplay_cost_le_4"},
                                {
                                    "give_keyword": {
                                        "target": "self",
                                        "keyword": "ダブルアタック",
                                        "duration": "turn",
                                    }
                                },
                            ],
                        }
                    }
                ],
            },
        ],
    ),
    # B: 別キャラ named all_self_chara_named (= 自分の 「ブルゴリ」 は 静的 ブロッカー)
    (
        "OP02-074",
        [
            {
                "_text": "自分の「ブルゴリ」は【ブロッカー】を得る。",
                "when": "on_attached_don",
                "n": 0,
                "do": [
                    {
                        "give_keyword": {
                            "target": {"type": "all_self_chara_named", "name": "ブルゴリ"},
                            "keyword": "ブロッカー",
                        }
                    }
                ],
            }
        ],
    ),
    # C: battle duration (= turn 近似)
    (
        "OP03-059",
        [
            {
                "_text": "【アタック時】ドン!!-1：このキャラは、このバトル中、【バニッシュ】を得る。 ※battle→turn 近似",
                "_approx_note": "battle duration を turn duration で 近似",
                "when": "on_attack",
                "cost": {"pay_don": 1},
                "do": [
                    {
                        "give_keyword": {
                            "target": "self",
                            "keyword": "バニッシュ",
                            "duration": "turn",
                        }
                    }
                ],
            }
        ],
    ),
    # D: 【起動メイン】 + cost で 自分のキャラ 1 枚 速攻 turn
    (
        "OP04-001",
        [
            {
                "_text": "このリーダーはアタックできない。【起動メイン】【ターン1回】②：カード1枚を引き、自分のキャラ1枚までは、このターン中、【速攻】を得る。",
                "when": "activate_main",
                "cost": {"once_per_turn": True, "pay_don": 2},
                "do": [
                    {"draw": 1},
                    {
                        "give_keyword": {
                            "target": "one_self_chara_filtered",
                            "filter": {},
                            "keyword": "速攻",
                            "duration": "turn",
                        }
                    },
                ],
            }
        ],
    ),
    (
        "OP04-001_p1",
        [
            {
                "_text": "このリーダーはアタックできない。【起動メイン】【ターン1回】②：カード1枚を引き、自分のキャラ1枚までは、このターン中、【速攻】を得る。",
                "when": "activate_main",
                "cost": {"once_per_turn": True, "pay_don": 2},
                "do": [
                    {"draw": 1},
                    {
                        "give_keyword": {
                            "target": "one_self_chara_filtered",
                            "filter": {},
                            "keyword": "速攻",
                            "duration": "turn",
                        }
                    },
                ],
            }
        ],
    ),
    # G: 【相手のアタック時】 + ドン-1 で 自身 ブロッカー +1000 (battle → turn 近似)
    (
        "OP04-071",
        [
            {
                "_text": "【相手のアタック時】ドン!!-1：このキャラは、このバトル中、【ブロッカー】を得て、パワー+1000。 ※battle→turn 近似",
                "_approx_note": "battle duration を turn で 近似 + opp_attack trigger",
                "when": "opp_attack_on_chara",
                "cost": {"pay_don": 1},
                "do": [
                    {
                        "give_keyword": {
                            "target": "self",
                            "keyword": "ブロッカー",
                            "duration": "turn",
                        }
                    },
                    {
                        "power_pump": {
                            "target": "self",
                            "amount": 1000,
                            "duration": "turn",
                        }
                    },
                ],
            }
        ],
    ),
    # E: 【メイン】 自分のライフ加える : 自分の特徴《ワノ国》キャラ 1枚 DA turn
    (
        "OP04-115",
        [
            {
                "_text": "【メイン】自分のライフの上か下から1枚を手札に加えることができる：自分の特徴《ワノ国》を持つキャラ1枚までは、このターン中、【ダブルアタック】を得る。",
                "when": "main",
                "cost": {"life_top_or_bottom_to_hand": 1},
                "do": [
                    {
                        "give_keyword": {
                            "target": "one_self_chara_filtered",
                            "filter": {"feature": "ワノ国"},
                            "keyword": "ダブルアタック",
                            "duration": "turn",
                        }
                    }
                ],
            }
        ],
    ),
    # F: 自身以外 のコスト3以上 赤キャラ すべて 静的 速攻
    (
        "OP04-118",
        [
            {
                "_text": "このキャラ以外の自分のコスト3以上の赤のキャラすべては、【速攻】を得る。",
                "when": "on_attached_don",
                "n": 0,
                "do": [
                    {
                        "give_keyword": {
                            "target": {
                                "type": "all_self_chara_filtered",
                                "filter": {
                                    "cost_ge": 3,
                                    "color": "赤",
                                    "exclude_name": "ネフェルタリ・ビビ",
                                },
                            },
                            "keyword": "速攻",
                        }
                    }
                ],
            }
        ],
    ),
    (
        "OP04-118_p1",
        [
            {
                "_text": "このキャラ以外の自分のコスト3以上の赤のキャラすべては、【速攻】を得る。",
                "when": "on_attached_don",
                "n": 0,
                "do": [
                    {
                        "give_keyword": {
                            "target": {
                                "type": "all_self_chara_filtered",
                                "filter": {
                                    "cost_ge": 3,
                                    "color": "赤",
                                    "exclude_name": "ネフェルタリ・ビビ",
                                },
                            },
                            "keyword": "速攻",
                        }
                    }
                ],
            }
        ],
    ),
    # C-1: OP05-080 battle duration + cost (= トラッシュ 20 枚 デッキ戻し)
    (
        "OP05-080",
        [
            {
                "_text": "【アタック時】【ターン1回】自分のトラッシュのカード20枚をデッキに戻しシャッフルできる：このキャラは、このバトル中、【ダブルアタック】を得て、パワー+10000。 ※battle→turn 近似 + cost は 簡略",
                "_approx_note": "battle→turn 近似、 cost: trash_to_deck 20 → 簡略 (engine 未対応)",
                "when": "on_attack",
                "cost": {"once_per_turn": True},
                "do": [
                    {
                        "give_keyword": {
                            "target": "self",
                            "keyword": "ダブルアタック",
                            "duration": "turn",
                        }
                    },
                    {
                        "power_pump": {
                            "target": "self",
                            "amount": 10000,
                            "duration": "turn",
                        }
                    },
                ],
            }
        ],
    ),
    # H: 【登場時】 ドン以下: 相手キャラ -2000 + 自身 速攻 turn
    (
        "OP06-061",
        [
            {
                "_text": "【登場時】自分の場のドン!!が相手の場のドン!!の枚数以下の場合、相手のキャラ1枚までを、このターン中、パワー-2000し、このキャラは【速攻】を得る。",
                "when": "on_play",
                "if": {"don_diff_le": 0},
                "do": [
                    {
                        "power_pump": {
                            "target": "one_opponent_character_le_5000",
                            "amount": -2000,
                            "duration": "turn",
                        }
                    },
                    {
                        "give_keyword": {
                            "target": "self",
                            "keyword": "速攻",
                            "duration": "turn",
                        }
                    },
                ],
            }
        ],
    ),
    (
        "OP06-061_p1",
        [
            {
                "_text": "【登場時】自分の場のドン!!が相手の場のドン!!の枚数以下の場合、相手のキャラ1枚までを、このターン中、パワー-2000し、このキャラは【速攻】を得る。",
                "when": "on_play",
                "if": {"don_diff_le": 0},
                "do": [
                    {
                        "power_pump": {
                            "target": "one_opponent_character_le_5000",
                            "amount": -2000,
                            "duration": "turn",
                        }
                    },
                    {
                        "give_keyword": {
                            "target": "self",
                            "keyword": "速攻",
                            "duration": "turn",
                        }
                    },
                ],
            }
        ],
    ),
    # G-2: 【相手のアタック時】 self_rest + 自分の魚人 1 枚 turn ブロッカー
    (
        "OP07-024",
        [
            {
                "_text": "【相手のアタック時】このキャラをレストにできる：自分のコスト5以下の特徴《魚人族》を持つキャラ1枚までは、このターン中、【ブロッカー】を得る。",
                "when": "opp_attack_on_chara",
                "cost": {"rest_self": True},
                "do": [
                    {
                        "give_keyword": {
                            "target": "one_self_chara_filtered",
                            "filter": {"feature": "魚人族", "cost_le": 5},
                            "keyword": "ブロッカー",
                            "duration": "turn",
                        }
                    }
                ],
            }
        ],
    ),
    # I: 【起動メイン】 + cost: 自身 バニッシュ + P+1000 turn
    (
        "OP07-083",
        [
            {
                "_text": "【起動メイン】自分のトラッシュの特徴《スリラーバーク海賊団》を持つカード4枚を好きな順番でデッキの下に置くことができる：このキャラは、このターン中、【バニッシュ】を得て、パワー+1000。",
                "_approx_note": "cost: trash filtered to deck 4 → 簡略",
                "when": "activate_main",
                "cost": {"once_per_turn": True},
                "do": [
                    {
                        "give_keyword": {
                            "target": "self",
                            "keyword": "バニッシュ",
                            "duration": "turn",
                        }
                    },
                    {
                        "power_pump": {
                            "target": "self",
                            "amount": 1000,
                            "duration": "turn",
                        }
                    },
                ],
            }
        ],
    ),
    # D-2: 【ドン×1】 + 【起動メイン】 + cost: 自身 速攻 turn
    (
        "OP08-008",
        [
            {
                "_text": "【ドン!!×1】【起動メイン】【ターン1回】自分のライフの上から1枚を手札に加えることができる：このキャラは、このターン中、【速攻】を得る。",
                "when": "activate_main",
                "if": {"self_inplay_attached_dons_ge": 1},
                "cost": {"once_per_turn": True, "life_to_hand": 1},
                "do": [
                    {
                        "give_keyword": {
                            "target": "self",
                            "keyword": "速攻",
                            "duration": "turn",
                        }
                    }
                ],
            }
        ],
    ),
    # J: 【登場時】 ドン 1+ 戻す: 自身 速攻 turn + 相手コスト6以下 レスト
    (
        "OP09-065",
        [
            {
                "_text": "【登場時】自分の場のドン!!を1枚以上ドン!!デッキに戻すことができる：このキャラは、このターン中、【速攻】を得る。その後、相手のコスト6以下のキャラ1枚までを、レストにする。",
                "_approx_note": "cost: pay_don ≥1 を pay_don=1 で 固定",
                "when": "on_play",
                "cost": {"pay_don": 1},
                "do": [
                    {
                        "give_keyword": {
                            "target": "self",
                            "keyword": "速攻",
                            "duration": "turn",
                        }
                    },
                    {
                        "rest": {
                            "target": "one_opponent_character_filtered",
                            "filter": {"cost_le": 6},
                        }
                    },
                ],
            }
        ],
    ),
    (
        "OP09-065_p1",
        [
            {
                "_text": "【登場時】自分の場のドン!!を1枚以上ドン!!デッキに戻すことができる：このキャラは、このターン中、【速攻】を得る。その後、相手のコスト6以下のキャラ1枚までを、レストにする。",
                "_approx_note": "cost: pay_don ≥1 を pay_don=1 で 固定",
                "when": "on_play",
                "cost": {"pay_don": 1},
                "do": [
                    {
                        "give_keyword": {
                            "target": "self",
                            "keyword": "速攻",
                            "duration": "turn",
                        }
                    },
                    {
                        "rest": {
                            "target": "one_opponent_character_filtered",
                            "filter": {"cost_le": 6},
                        }
                    },
                ],
            }
        ],
    ),
    (
        "OP09-065_p2",
        [
            {
                "_text": "【登場時】自分の場のドン!!を1枚以上ドン!!デッキに戻すことができる：このキャラは、このターン中、【速攻】を得る。その後、相手のコスト6以下のキャラ1枚までを、レストにする。",
                "_approx_note": "cost: pay_don ≥1 を pay_don=1 で 固定",
                "when": "on_play",
                "cost": {"pay_don": 1},
                "do": [
                    {
                        "give_keyword": {
                            "target": "self",
                            "keyword": "速攻",
                            "duration": "turn",
                        }
                    },
                    {
                        "rest": {
                            "target": "one_opponent_character_filtered",
                            "filter": {"cost_le": 6},
                        }
                    },
                ],
            }
        ],
    ),
    (
        "OP09-065_r1",
        [
            {
                "_text": "【登場時】自分の場のドン!!を1枚以上ドン!!デッキに戻すことができる：このキャラは、このターン中、【速攻】を得る。その後、相手のコスト6以下のキャラ1枚までを、レストにする。",
                "_approx_note": "cost: pay_don ≥1 を pay_don=1 で 固定",
                "when": "on_play",
                "cost": {"pay_don": 1},
                "do": [
                    {
                        "give_keyword": {
                            "target": "self",
                            "keyword": "速攻",
                            "duration": "turn",
                        }
                    },
                    {
                        "rest": {
                            "target": "one_opponent_character_filtered",
                            "filter": {"cost_le": 6},
                        }
                    },
                ],
            }
        ],
    ),
    # K: 【自分のターン終了時】 + ドン 1+ 戻し: 自身 アクティブ + ブロッカー next_opp_turn_end
    (
        "OP09-068",
        [
            {
                "_text": "【自分のターン終了時】自分の場のドン!!を1枚以上ドン!!デッキに戻すことができる：このキャラをアクティブにする。その後、このキャラは、次の相手のターン終了時まで、【ブロッカー】を得る。",
                "_approx_note": "cost: pay_don ≥1 を pay_don=1 で 固定",
                "when": "on_turn_end",
                "if": {"self_turn": True},
                "cost": {"pay_don": 1},
                "do": [
                    {"untap_chara": "self"},
                    {
                        "give_keyword": {
                            "target": "self",
                            "keyword": "ブロッカー",
                            "duration": "next_opp_turn_end",
                        }
                    },
                ],
            }
        ],
    ),
    # K-2: OP10-099 別キャラ feature 3-8 cost アクティブ + ブロッカー
    (
        "OP10-099",
        [
            {
                "_text": "【自分のターン終了時】自分のライフの上から1枚を表向きにできる：自分のコスト3から8の特徴《超新星》を持つキャラ1枚までを、アクティブにし、そのキャラは、次の相手のターン終了時まで、【ブロッカー】を得る。",
                "_approx_note": "cost: 自ライフ表向き は 簡略 (engine 未対応)",
                "when": "on_turn_end",
                "if": {"self_turn": True},
                "do": [
                    {"untap_chara": {"target": "one_self_chara_filtered", "filter": {"feature": "超新星", "cost_ge": 3, "cost_le": 8}}},
                    {
                        "give_keyword": {
                            "target": "one_self_chara_filtered",
                            "filter": {"feature": "超新星", "cost_ge": 3, "cost_le": 8},
                            "keyword": "ブロッカー",
                            "duration": "next_opp_turn_end",
                        }
                    },
                ],
            }
        ],
    ),
    (
        "OP10-099_p1",
        [
            {
                "_text": "【自分のターン終了時】自分のライフの上から1枚を表向きにできる：自分のコスト3から8の特徴《超新星》を持つキャラ1枚までを、アクティブにし、そのキャラは、次の相手のターン終了時まで、【ブロッカー】を得る。",
                "_approx_note": "cost: 自ライフ表向き は 簡略 (engine 未対応)",
                "when": "on_turn_end",
                "if": {"self_turn": True},
                "do": [
                    {"untap_chara": {"target": "one_self_chara_filtered", "filter": {"feature": "超新星", "cost_ge": 3, "cost_le": 8}}},
                    {
                        "give_keyword": {
                            "target": "one_self_chara_filtered",
                            "filter": {"feature": "超新星", "cost_ge": 3, "cost_le": 8},
                            "keyword": "ブロッカー",
                            "duration": "next_opp_turn_end",
                        }
                    },
                ],
            }
        ],
    ),
    # D-3: OP15-041 【起動メイン】 自分のキャラ デッキ下: 自身 速攻 turn
    (
        "OP15-041",
        [
            {
                "_text": "【起動メイン】【ターン1回】自分のキャラ1枚を持ち主のデッキの下に置くことができる：このキャラは、このターン中、【速攻】を得る。",
                "_approx_note": "cost: 自キャラ deck-bottom は 簡略 (一部 engine 未対応)",
                "when": "activate_main",
                "cost": {"once_per_turn": True},
                "do": [
                    {
                        "give_keyword": {
                            "target": "self",
                            "keyword": "速攻",
                            "duration": "turn",
                        }
                    }
                ],
            }
        ],
    ),
    # L: 【メイン】 多選択 (ドロー or ブロッカー grant)
    (
        "OP15-055",
        [
            {
                "_text": "【メイン】以下から1つを選ぶ。 ・カード2枚を引く。 ・自分の特徴《ドレスローザ》を持つキャラ1枚までは、次の相手のエンドフェイズ終了時まで、【ブロッカー】を得る。 ※選択肢: AI 簡易で draw 優先",
                "_approx_note": "choice: AI は draw 2 を優先 (= 簡略)",
                "when": "main",
                "do": [{"draw": 2}],
            }
        ],
    ),
    # M: 【起動メイン】 ドン-1: 自身 next_opp_turn_end ブロッカー + discard 1
    (
        "OP15-060",
        [
            {
                "_text": "自分の場のドン!!が6枚以下の場合、このキャラは相手の効果で場を離れず、パワー+2000。【起動メイン】ドン!!-1：このキャラは、次の相手のエンドフェイズ終了時まで、【ブロッカー】を得る。その後、自分の手札1枚を捨てる。",
                "when": "on_attached_don",
                "n": 0,
                "if": {"self_don_le": 6},
                "do": [
                    {"set_ko_immune": "self"},
                    {"power_pump": {"target": "self", "amount": 2000, "duration": "static"}},
                ],
            },
            {
                "_text": "【起動メイン】ドン!!-1：このキャラは、次の相手のエンドフェイズ終了時まで、【ブロッカー】を得る。その後、自分の手札1枚を捨てる。",
                "when": "activate_main",
                "cost": {"pay_don": 1},
                "do": [
                    {
                        "give_keyword": {
                            "target": "self",
                            "keyword": "ブロッカー",
                            "duration": "next_opp_turn_end",
                        }
                    },
                    {"trash_self_hand_random": 1},
                ],
            },
        ],
    ),
    (
        "OP15-060_p1",
        [
            {
                "_text": "自分の場のドン!!が6枚以下の場合、このキャラは相手の効果で場を離れず、パワー+2000。【起動メイン】ドン!!-1：このキャラは、次の相手のエンドフェイズ終了時まで、【ブロッカー】を得る。その後、自分の手札1枚を捨てる。",
                "when": "on_attached_don",
                "n": 0,
                "if": {"self_don_le": 6},
                "do": [
                    {"set_ko_immune": "self"},
                    {"power_pump": {"target": "self", "amount": 2000, "duration": "static"}},
                ],
            },
            {
                "_text": "【起動メイン】ドン!!-1：このキャラは、次の相手のエンドフェイズ終了時まで、【ブロッカー】を得る。その後、自分の手札1枚を捨てる。",
                "when": "activate_main",
                "cost": {"pay_don": 1},
                "do": [
                    {
                        "give_keyword": {
                            "target": "self",
                            "keyword": "ブロッカー",
                            "duration": "next_opp_turn_end",
                        }
                    },
                    {"trash_self_hand_random": 1},
                ],
            },
        ],
    ),
    (
        "OP15-060_p2",
        [
            {
                "_text": "自分の場のドン!!が6枚以下の場合、このキャラは相手の効果で場を離れず、パワー+2000。【起動メイン】ドン!!-1：このキャラは、次の相手のエンドフェイズ終了時まで、【ブロッカー】を得る。その後、自分の手札1枚を捨てる。",
                "when": "on_attached_don",
                "n": 0,
                "if": {"self_don_le": 6},
                "do": [
                    {"set_ko_immune": "self"},
                    {"power_pump": {"target": "self", "amount": 2000, "duration": "static"}},
                ],
            },
            {
                "_text": "【起動メイン】ドン!!-1：このキャラは、次の相手のエンドフェイズ終了時まで、【ブロッカー】を得る。その後、自分の手札1枚を捨てる。",
                "when": "activate_main",
                "cost": {"pay_don": 1},
                "do": [
                    {
                        "give_keyword": {
                            "target": "self",
                            "keyword": "ブロッカー",
                            "duration": "next_opp_turn_end",
                        }
                    },
                    {"trash_self_hand_random": 1},
                ],
            },
        ],
    ),
    # N: 自分の 「シュラ」 すべて と このキャラ は 静的 ブロック不可 + 「シュラ」 すべて + 自身 P6000 相手ターン中
    (
        "OP15-070",
        [
            {
                "_text": "自分の「シュラ」すべてとこのキャラは【ブロック不可】を得る。【相手のターン中】自分の「シュラ」すべてとこのキャラを、元々のパワー6000にする。",
                "_approx_note": "target=self + named-group を 個別 static_granted で 表現",
                "when": "on_attached_don",
                "n": 0,
                "do": [
                    {
                        "give_keyword": {
                            "target": "self",
                            "keyword": "ブロック不可",
                        }
                    },
                    {
                        "give_keyword": {
                            "target": {"type": "all_self_chara_named", "name": "シュラ"},
                            "keyword": "ブロック不可",
                        }
                    },
                ],
            },
            {
                "_text": "【相手のターン中】自分の「シュラ」すべてとこのキャラを、元々のパワー6000にする。",
                "when": "on_attached_don",
                "n": 0,
                "if": {"opp_turn": True},
                "do": [
                    {"set_base_power": {"target": "self", "amount": 6000}},
                    {
                        "set_base_power": {
                            "target": {"type": "all_self_chara_named", "name": "シュラ"},
                            "amount": 6000,
                        }
                    },
                ],
            },
        ],
    ),
    # O: 【登場時】 リーダー麦わら: トラッシュ コスト7 麦わら 登場 + 登場した キャラ 速攻 turn
    (
        "OP15-086",
        [
            {
                "_text": "【登場時】自分のリーダーが特徴《麦わらの一味》を持つ場合、自分のトラッシュからコスト7以下の特徴《麦わらの一味》を持つキャラカード1枚までを、登場させる。この効果で登場させたキャラは、このターン中、【速攻】を得る。",
                "_approx_note": "登場 + give_keyword 動的 target は 簡略 (= 登場直後 自動的 速攻 付与 を 別途 動作 要 confirm)",
                "when": "on_play",
                "if": {"leader_feature": "麦わらの一味"},
                "do": [
                    {
                        "play_from_trash": {
                            "filter": {"feature": "麦わらの一味", "cost_le": 7},
                            "rested": False,
                            "gain_keyword_turn": "速攻",
                        }
                    }
                ],
            }
        ],
    ),
    (
        "OP15-086_p1",
        [
            {
                "_text": "【登場時】自分のリーダーが特徴《麦わらの一味》を持つ場合、自分のトラッシュからコスト7以下の特徴《麦わらの一味》を持つキャラカード1枚までを、登場させる。この効果で登場させたキャラは、このターン中、【速攻】を得る。",
                "_approx_note": "登場 + give_keyword 動的 target は 簡略",
                "when": "on_play",
                "if": {"leader_feature": "麦わらの一味"},
                "do": [
                    {
                        "play_from_trash": {
                            "filter": {"feature": "麦わらの一味", "cost_le": 7},
                            "rested": False,
                            "gain_keyword_turn": "速攻",
                        }
                    }
                ],
            }
        ],
    ),
    # C-2: ST07-004 【ドン×1】【アタック時】 ライフ加える: バニッシュ + P+1000 (battle→turn)
    (
        "ST07-004",
        [
            {
                "_text": "【ドン!!×1】【アタック時】自分のライフの上か下から1枚を手札に加えることができる：このキャラは、このバトル中、【バニッシュ】を得て、パワー+1000。 ※battle→turn 近似",
                "_approx_note": "battle→turn 近似",
                "when": "on_attack",
                "if": {"self_inplay_attached_dons_ge": 1},
                "cost": {"life_top_or_bottom_to_hand": 1},
                "do": [
                    {
                        "give_keyword": {
                            "target": "self",
                            "keyword": "バニッシュ",
                            "duration": "turn",
                        }
                    },
                    {
                        "power_pump": {
                            "target": "self",
                            "amount": 1000,
                            "duration": "turn",
                        }
                    },
                ],
            }
        ],
    ),
    # P: ST28-004 多 entry
    (
        "ST28-004",
        [
            {
                "_text": "【自分のターン中】自分のライフが2枚以下の場合、自分のリーダーのパワー+1000。",
                "when": "on_attached_don",
                "n": 0,
                "if": {"self_turn": True, "self_life_le": 2},
                "do": [
                    {"power_pump": {"target": "self_leader", "amount": 1000, "duration": "static"}}
                ],
            },
            {
                "_text": "【起動メイン】【ターン1回】自分の付与されているドン!!合計2枚をコストエリアにレストで戻すことができる：このキャラは、このターン中、【速攻】を得て、パワー+1000。",
                "_approx_note": "cost: 付与ドン2枚をコストエリアレスト → 簡略 (= once_per_turn のみ)",
                "when": "activate_main",
                "cost": {"once_per_turn": True},
                "if": {"self_inplay_attached_dons_ge": 2},
                "do": [
                    {
                        "give_keyword": {
                            "target": "self",
                            "keyword": "速攻",
                            "duration": "turn",
                        }
                    },
                    {
                        "power_pump": {
                            "target": "self",
                            "amount": 1000,
                            "duration": "turn",
                        }
                    },
                ],
            },
        ],
    ),
]


def has_existing_grant(entries: list[dict], keyword: str) -> bool:
    for ent in entries:
        for d in ent.get("do") or []:
            if not isinstance(d, dict):
                continue
            if "give_keyword" in d:
                spec = d["give_keyword"]
                if isinstance(spec, dict):
                    if spec.get("keyword") == keyword or keyword in (
                        spec.get("keywords") or []
                    ):
                        return True
                elif isinstance(spec, str) and spec == keyword:
                    return True
            if keyword == "速攻" and "give_rush" in d:
                return True
    return False


def main():
    overlay = json.load(open(OVERLAY_JSON, encoding="utf-8"))
    added = 0
    for card_id, new_entries in HANDWRITTEN_ENTRIES:
        existing = overlay.get(card_id, [])
        if not isinstance(existing, list):
            existing = []
        for entry in new_entries:
            existing.append(entry)
            added += 1
        overlay[card_id] = existing
    OVERLAY_JSON.write_text(
        json.dumps(overlay, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Added {added} entries to {len(HANDWRITTEN_ENTRIES)} cards")


if __name__ == "__main__":
    main()
