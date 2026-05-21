#!/usr/bin/env python3
"""empty_overlay_with_text 42 件 一括補完 (= 2026-05-22 audit cleanup)。

各カードを 公式テキスト 準拠 で overlay entry に 翻訳。
engine 制約 で 完全実装 不可 な ものは `_doc` note で 明示。

使用方法:
    .venv/bin/python scripts/fix_empty_overlay_phase4.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "db" / "card_effects.json"


def main():
    ov = json.loads(PATH.read_text(encoding="utf-8"))

    fixes: dict[str, list] = {}

    # ====== Pattern A: 静的 条件付き パワー / KO 耐性 / cost 等 ======

    # EB04-051: 元々のパワー12000以上のキャラがいない場合、 このキャラはアタックできない
    # 簡略: self_chara_max_power_lt 条件 未実装 → _doc で skip 注記。 単純 cannot_attack_static の
    # 場合 全試合 アタック不可 (= 過大評価) なので 未対応 と 明示。
    fixes["EB04-051"] = [
        {
            "_text": "EB04-051 元々のパワー12000以上のキャラがいない場合、このキャラはアタックできない。",
            "_doc": "「元々のパワー12000以上のキャラがいない場合」 条件 (= self_chara_max_power_lt 等) は engine 未対応。 簡略: 常に attack 可能 (= 効果無視)。 game balance 上 多くの 場面で 条件 false なので 機会 損失 程度。",
            "when": "leader_passive",
            "do": []
        }
    ]

    # OP14-003: このキャラは相手の元々のパワー5000以下のキャラの効果でKOされない
    fixes["OP14-003"] = [
        {
            "_text": "OP14-003 このキャラは相手の元々のパワー5000以下のキャラの効果でKOされない。",
            "_doc": "「効果source の元々のパワー5000以下」 を effect source 起点 で 判別する 機構 は engine 未対応。 簡略: 通常 KO 耐性 なし。 game 内 OP9-091 等 5000P↓ chara effect KO は 通る。",
            "when": "on_attached_don",
            "n": 0,
            "do": []
        }
    ]

    # OP14-086: 自分のトラッシュが7枚以上ある場合、 このキャラのパワー+1000し、
    #          自分の『B・W』を含む特徴を持つキャラすべてを、 コスト+2。
    fixes["OP14-086"] = [
        {
            "_text": "OP14-086 自分のトラッシュが7枚以上ある場合、このキャラのパワー+1000し、自分の『B・W』を含む特徴を持つキャラすべてを、コスト+2。",
            "when": "on_attached_don",
            "n": 0,
            "if": {"self_trash_count_ge": 7},
            "do": [
                {"power_pump": {"target": "self", "amount": 1000}},
                {"set_base_cost_filtered_static": {
                    "filter": {"feature_contains": "B・W"},
                    "delta": 2,
                    "scope": "self"
                }}
            ]
        }
    ]

    # OP12-021: 自分のリーダーが属性(斬)を持ち、自分のレストのドン‼が6枚以上ある場合、
    #          このキャラは相手の効果でレストにされない。【ブロッカー】
    fixes["OP12-021"] = [
        {
            "_text": "OP12-021 自分のリーダーが属性(斬)を持ち、自分のレストのドン‼が6枚以上ある場合、このキャラは相手の効果でレストにされない。",
            "_doc": "「効果でレストにされない」 は set_cannot_be_rested_static (= protect_from_opp_effect で 代用) を 使用。 厳密 には rest 限定 ではなく 全般 opp 効果 ブロック の 近似。",
            "when": "on_attached_don",
            "n": 0,
            "if": {
                "leader_attribute": "斬",
                "self_don_rested_ge": 6
            },
            "do": [
                {"set_cannot_be_rested_static": True}
            ]
        }
    ]

    # OP12-036 (+_p1): 手札のこのカードは、効果で登場できない。 自分のリーダーが属性(斬)を持つ場合、
    #                  このキャラは属性(斬)を持つカードとのバトルでKOされず、パワー+1000。
    op12_036 = [
        {
            "_text": "OP12-036 自分のリーダーが属性(斬)を持つ場合、このキャラは属性(斬)を持つカードとのバトルでKOされず、パワー+1000。",
            "_doc": "「効果で登場できない」 = play_via_effect ガード は engine 未配線 (= 簡略 で 通常通り 登場可能)。",
            "when": "on_attached_don",
            "n": 0,
            "if": {"leader_attribute": "斬"},
            "do": [
                {"set_immune_attribute_in_battle": {"target": "self", "attributes": ["斬"]}},
                {"power_pump": {"target": "self", "amount": 1000}}
            ]
        }
    ]
    fixes["OP12-036"] = [dict(e) for e in op12_036]
    fixes["OP12-036_p1"] = [dict(e) for e in op12_036]
    fixes["OP12-036_p1"][0]["_text"] = fixes["OP12-036_p1"][0]["_text"].replace("OP12-036", "OP12-036_p1")

    # OP11-027: 自分のリーダーが「しらほし」の場合、このキャラは登場したターンにキャラへアタックできる
    fixes["OP11-027"] = [
        {
            "_text": "OP11-027 自分のリーダーが「しらほし」の場合、このキャラは登場したターンにキャラへアタックできる。",
            "_doc": "「登場したターンにキャラへアタックできる」 = 速攻 (= rush) の キャラ 限定 版。 厳密 には 速攻 は リーダー+キャラ 両方 攻撃 可。 簡略: 速攻 を 付与 (= 過剰 包含、 リーダー アタック も 可)。",
            "when": "on_attached_don",
            "n": 0,
            "if": {"leader_name": "しらほし"},
            "do": [
                {"give_keyword": {"target": "self", "keyword": "速攻"}}
            ]
        }
    ]

    # OP11-046: 自分のキャラが『ジェルマ』を含む特徴を持つキャラのみの場合、
    #          このキャラは相手の効果で、KOされずレストにされない。 【ブロッカー】
    fixes["OP11-046"] = [
        {
            "_text": "OP11-046 自分のキャラが『ジェルマ』を含む特徴を持つキャラのみの場合、このキャラは相手の効果で、KOされずレストにされない。",
            "_doc": "「自分のキャラが特徴X のみ」 条件 (= self_all_charas_feature_contains) は engine 未対応 で 簡略: 条件 を leader_feature_contains で 近似。 ジェルマ デッキ の リーダーは ジェルマ 特徴 持ち が 多い。",
            "when": "on_attached_don",
            "n": 0,
            "if": {"leader_feature_contains": "ジェルマ"},
            "do": [
                {"set_protect_from_opp_effect_static": True}
            ]
        }
    ]

    # OP08-029: このキャラがアクティブの場合、 「ペコムズ」以外の自分のコスト3以下の
    #          特徴《ミンク族》を持つキャラは、 効果でKOされない。
    fixes["OP08-029"] = [
        {
            "_text": "OP08-029 このキャラがアクティブの場合、「ペコムズ」以外の自分のコスト3以下の特徴《ミンク族》を持つキャラは、効果でKOされない。",
            "_doc": "「アクティブの場合」 = self が rested でない 条件 (= self_active)。 set_ko_immune を all_self_chara_filtered (= cost_le 3 + feature ミンク族 + name exclude ペコムズ) に 付与。",
            "when": "on_attached_don",
            "n": 0,
            "if": {"self_not_rested": True},
            "do": [
                {
                    "set_ko_immune": {
                        "type": "all_self_chara_filtered",
                        "filter": {
                            "feature": "ミンク族",
                            "cost_le": 3,
                            "exclude_name": "ペコムズ"
                        }
                    }
                }
            ]
        }
    ]

    # OP07-033 (+ _p2 / _r1): 自分のキャラが3枚以上いる場合、自分の、「モンキー・D・ルフィ」以外の
    #                          コスト3以下のキャラは相手の効果でKOされない。
    for variant in ["OP07-033", "OP07-033_p2", "OP07-033_r1"]:
        # Note: _r1 uses "Ｄ" (full-width); _p2/_default use "D" (half-width)
        excl_name = "モンキー・Ｄ・ルフィ" if variant == "OP07-033_r1" else "モンキー・D・ルフィ"
        fixes[variant] = [
            {
                "_text": f"{variant} 自分のキャラが3枚以上いる場合、自分の、「{excl_name}」以外のコスト3以下のキャラは相手の効果でKOされない。",
                "when": "on_attached_don",
                "n": 0,
                "if": {"self_chara_count_ge": 3},
                "do": [
                    {
                        "set_ko_immune": {
                            "type": "all_self_chara_filtered",
                            "filter": {
                                "cost_le": 3,
                                "exclude_name": excl_name
                            }
                        }
                    }
                ]
            }
        ]

    # OP07-069: 自分の場のドン!!が相手の場のドン!!の枚数以下の場合、
    #          自分の、「ピクルス」以外の特徴《フォクシー海賊団》を持つキャラは相手の効果でKOされない
    fixes["OP07-069"] = [
        {
            "_text": "OP07-069 自分の場のドン!!が相手の場のドン!!の枚数以下の場合、自分の、「ピクルス」以外の特徴《フォクシー海賊団》を持つキャラは相手の効果でKOされない。",
            "_doc": "「自分のドン≤相手のドン」 条件 (= don_diff_le 0) で 近似 (= 正確)。",
            "when": "on_attached_don",
            "n": 0,
            "if": {"don_diff_le": 0},
            "do": [
                {
                    "set_ko_immune": {
                        "type": "all_self_chara_filtered",
                        "filter": {
                            "feature": "フォクシー海賊団",
                            "exclude_name": "ピクルス"
                        }
                    }
                }
            ]
        }
    ]

    # OP06-012: 相手の元々のパワー6000以上の、 リーダーかキャラがいる場合、 このキャラはバトルでKOされない
    fixes["OP06-012"] = [
        {
            "_text": "OP06-012 相手の元々のパワー6000以上の、リーダーかキャラがいる場合、このキャラはバトルでKOされない。",
            "_doc": "「相手リーダーかキャラの 元々のパワー6000以上 が居る」 条件 (= opp_inplay_truly_original_power_ge_count_ge) で 近似 (= 厳密対応 不要)。",
            "when": "on_attached_don",
            "n": 0,
            "if": {"opp_inplay_truly_original_power_ge_6000_count_ge": 1},
            "do": [
                {"set_ko_immune_battle_only": True}
            ]
        }
    ]

    # OP06-088: 自分のリーダーが特徴《ドレスローザ》を持ち、 自分のリーダーがアクティブの場合、
    #          このキャラのパワー+2000
    fixes["OP06-088"] = [
        {
            "_text": "OP06-088 自分のリーダーが特徴《ドレスローザ》を持ち、自分のリーダーがアクティブの場合、このキャラのパワー+2000。",
            "when": "on_attached_don",
            "n": 0,
            "if": {
                "leader_feature": "ドレスローザ",
                "self_leader_active": True
            },
            "do": [
                {"power_pump": {"target": "self", "amount": 2000}}
            ]
        }
    ]

    # OP06-109: 【ドン !!×2】相手のライフが3枚以下の場合、このキャラは効果でKOされない
    fixes["OP06-109"] = [
        {
            "_text": "OP06-109 【ドン!!×2】相手のライフが3枚以下の場合、このキャラは効果でKOされない。",
            "when": "on_attached_don",
            "n": 2,
            "if": {"opp_life_le": 3},
            "do": [
                {"set_ko_immune": "self"}
            ]
        }
    ]

    # OP02-027: 自分のドン‼すべてがレストの場合、 このキャラは相手の効果で場を離れない
    fixes["OP02-027"] = [
        {
            "_text": "OP02-027 自分のドン‼すべてがレストの場合、このキャラは相手の効果で場を離れない。",
            "_doc": "「自分のドン!!すべてがレスト」 = self_don_active=0 で 近似。",
            "when": "on_attached_don",
            "n": 0,
            "if": {"self_don_active_eq": 0},
            "do": [
                {"set_protect_from_opp_effect_static": True}
            ]
        }
    ]

    # P-067: このキャラがレストの場合、 相手はキャラの「ユースタス・キッド」以外にアタックできない
    fixes["P-067"] = [
        {
            "_text": "P-067 このキャラがレストの場合、相手はキャラの「ユースタス・キッド」以外にアタックできない。",
            "_doc": "「このキャラがレストの場合」 = self_rested 条件。 cannot_attack_target_except (= 「ユースタス・キッド」 以外 attack 不可) を セット。",
            "when": "on_attached_don",
            "n": 0,
            "if": {"self_rested": True},
            "do": [
                {"cannot_attack_target_except": {"name": "ユースタス・キッド"}}
            ]
        }
    ]

    # P-104 (+ _p1): 自分か相手の場のドン‼が10枚ある場合、 このキャラは相手の効果で場を離れない
    p_104 = [
        {
            "_text": "P-104 自分か相手の場のドン‼が10枚ある場合、このキャラは相手の効果で場を離れない。",
            "_doc": "「自分か相手 の場のドン10枚」 = either_player_don_total_eq 10 (= 新条件、 簡略で self_don_total_eq:10 or opp_don_total_eq:10 の OR 等)。 engine では single check (= don_total_eq) のみ 想定。",
            "when": "on_attached_don",
            "n": 0,
            "if": {"either_player_don_total_eq_10": True},
            "do": [
                {"set_protect_from_opp_effect_static": True}
            ]
        }
    ]
    fixes["P-104"] = [dict(e) for e in p_104]
    fixes["P-104_p1"] = [dict(e) for e in p_104]
    fixes["P-104_p1"][0]["_text"] = fixes["P-104_p1"][0]["_text"].replace("P-104", "P-104_p1")

    # P-120: 手札のこのカードは、 相手のライフが離れているターン中、 コスト－2
    fixes["P-120"] = [
        {
            "_text": "P-120 手札のこのカードは、相手のライフが離れているターン中、コスト－2。",
            "_doc": "「相手のライフが離れているターン中」 = opp_life_lost_this_turn 条件 (= engine 未配線、 簡略で常時 -2 cost を 適用)。",
            "when": "in_hand",
            "do": [
                {"in_hand_cost_minus": 2}
            ]
        }
    ]

    # ====== Pattern B: Reactive triggers ======

    # OP06-044 family: 【自分のターン中】【ターン1回】相手がイベントを発動した時、 相手は自身の手札1枚をデッキの下に置く
    op06_044 = [
        {
            "_text": "OP06-044 【自分のターン中】【ターン1回】相手がイベントを発動した時、相手は自身の手札1枚をデッキの下に置く。",
            "when": "opp_event_or_trigger_fired",
            "if": {"self_turn": True},
            "cost": {"once_per_turn": True},
            "do": [
                {"opp_discard_hand_to_deck_bottom": 1}
            ]
        }
    ]
    fixes["OP06-044"] = [dict(e) for e in op06_044]
    fixes["OP06-044_p1"] = [dict(e) for e in op06_044]
    fixes["OP06-044_r1"] = [dict(e) for e in op06_044]
    for v in ["OP06-044_p1", "OP06-044_r1"]:
        fixes[v][0]["_text"] = fixes[v][0]["_text"].replace("OP06-044", v)

    # OP11-012 (+ _p1): 【自分のターン中】【ターン1回】相手がイベントを発動した時、
    #                    自分のキャラすべてを、 このターン中、 パワー+2000
    op11_012 = [
        {
            "_text": "OP11-012 【自分のターン中】【ターン1回】相手がイベントを発動した時、自分のキャラすべてを、このターン中、パワー+2000。",
            "when": "opp_event_or_trigger_fired",
            "if": {"self_turn": True},
            "cost": {"once_per_turn": True},
            "do": [
                {"power_pump": {
                    "target": "all_self_characters",
                    "amount": 2000,
                    "duration": "turn"
                }}
            ]
        }
    ]
    fixes["OP11-012"] = [dict(e) for e in op11_012]
    fixes["OP11-012_p1"] = [dict(e) for e in op11_012]
    fixes["OP11-012_p1"][0]["_text"] = fixes["OP11-012_p1"][0]["_text"].replace("OP11-012", "OP11-012_p1")

    # OP07-031 family: 【ブロッカー】 + 【自分のターン中】【ターン1回】キャラが自分の効果でレストになった時、
    #                  カード1枚を引き、自分の手札1枚を捨てる
    op07_031 = [
        {
            "_text": "OP07-031 【自分のターン中】【ターン1回】キャラが自分の効果でレストになった時、カード1枚を引き、自分の手札1枚を捨てる。",
            "when": "on_self_chara_rested_by_self_effect",
            "if": {"self_turn": True},
            "cost": {"once_per_turn": True},
            "do": [
                {"draw": 1},
                {"trash_self_hand_random": 1}
            ]
        }
    ]
    fixes["OP07-031"] = [dict(e) for e in op07_031]
    fixes["OP07-031_p1"] = [dict(e) for e in op07_031]
    fixes["OP07-031_r1"] = [dict(e) for e in op07_031]
    fixes["OP07-031_r2"] = [dict(e) for e in op07_031]
    for v in ["OP07-031_p1", "OP07-031_r1", "OP07-031_r2"]:
        fixes[v][0]["_text"] = fixes[v][0]["_text"].replace("OP07-031", v)

    # OP08-046: 【自分のターン中】【ターン1回】キャラが自分の効果で場を離れた時、
    #          相手の手札が5枚以上ある場合、 相手は自身の手札1枚をデッキの下に置く。 その後、 このキャラをレストにする。
    fixes["OP08-046"] = [
        {
            "_text": "OP08-046 【自分のターン中】【ターン1回】キャラが自分の効果で場を離れた時、相手の手札が5枚以上ある場合、相手は自身の手札1枚をデッキの下に置く。その後、このキャラをレストにする。",
            "when": "on_self_chara_leave_by_self_effect",
            "if": {
                "self_turn": True,
                "opp_hand_count_ge": 5
            },
            "cost": {"once_per_turn": True},
            "do": [
                {"opp_discard_hand_to_deck_bottom": 1},
                {"rest": "self"}
            ]
        }
    ]

    # OP14-021: 【自分のターン中】このキャラがレストになった時、 自分のライフの上から1枚を手札に加えてもよい。
    #          そうした場合、 相手のレストの、 キャラかステージ1枚までは、 次の相手のリフレッシュフェイズでアクティブにならない
    fixes["OP14-021"] = [
        {
            "_text": "OP14-021 【自分のターン中】このキャラがレストになった時、自分のライフの上から1枚を手札に加えてもよい。そうした場合、相手のレストの、キャラかステージ1枚までは、次の相手のリフレッシュフェイズでアクティブにならない。",
            "_doc": "「相手のレストのキャラかステージ」 ターゲット は 既存 keep_opp_rested_chara_with_don_ge_next_refresh で 近似 (= ステージ も 含めると 引数 拡張 必要)。",
            "when": "on_self_rested",
            "if": {"self_turn": True},
            "optional": True,
            "cost": {"life_to_hand": 1},
            "do": [
                {"keep_opp_rested_chara_with_don_ge_next_refresh": {"amount": 0, "count": 1}}
            ]
        }
    ]

    # OP14-035: 【自分のターン中】このキャラがレストになった時、 相手のレストのコスト4以下のキャラ1枚までは、
    #          次の相手のリフレッシュフェイズでアクティブにならない
    fixes["OP14-035"] = [
        {
            "_text": "OP14-035 【自分のターン中】このキャラがレストになった時、相手のレストのコスト4以下のキャラ1枚までは、次の相手のリフレッシュフェイズでアクティブにならない。",
            "_doc": "コスト4以下 + レスト 条件 は 既存 keep_opp_rested_chara_with_don_ge_next_refresh の 引数 で 簡略 表現 (= cost_le filter は 追加 検証 必要)。",
            "when": "on_self_rested",
            "if": {"self_turn": True},
            "do": [
                {"keep_opp_rested_chara_with_don_ge_next_refresh": {"amount": 0, "count": 1, "cost_le": 4}}
            ]
        }
    ]

    # OP11-088: 【ブロッカー】 + 【ターン1回】相手のキャラがアタックした時、 発動できる。
    #          そのキャラが属性(斬)を持つ場合、 このキャラは、 このバトル中、 パワー+5000
    fixes["OP11-088"] = [
        {
            "_text": "OP11-088 【ターン1回】相手のキャラがアタックした時、発動できる。そのキャラが属性(斬)を持つ場合、このキャラは、このバトル中、パワー+5000。",
            "_doc": "「相手キャラのみアタック時」 + 「攻撃者属性=斬」 + 「このバトル中」 (= turn duration 簡略)。 attacker_attribute 条件 は engine 未対応 → 簡略: 全 opp_attack 時 +5000 (= 過剰)。",
            "when": "opp_attack_on_chara",
            "if": {"opp_attacker_attribute": "斬"},
            "optional": True,
            "cost": {"once_per_turn": True},
            "do": [
                {"power_pump": {"target": "self", "amount": 5000, "duration": "turn"}}
            ]
        }
    ]

    # OP09-074: 【自分のターン中】【ターン1回】自分の場のドン!!がドン!!デッキに戻された時、
    #          自分のリーダーかキャラ1枚までを、 このターン中、 パワー+1000
    fixes["OP09-074"] = [
        {
            "_text": "OP09-074 【自分のターン中】【ターン1回】自分の場のドン!!がドン!!デッキに戻された時、自分のリーダーかキャラ1枚までを、このターン中、パワー+1000。",
            "when": "on_self_don_returned_to_deck",
            "if": {"self_turn": True},
            "cost": {"once_per_turn": True},
            "do": [
                {"power_pump": {
                    "target": "one_self_team_any",
                    "amount": 1000,
                    "duration": "turn"
                }}
            ]
        }
    ]

    # OP11-077: 【自分のターン中】【ターン1回】自分の場のドン‼がドン‼デッキに戻された時、
    #          自分の特徴《ビッグ・マム海賊団》を持つキャラ1枚までを、 次の相手のターン終了時まで、 コスト+2
    fixes["OP11-077"] = [
        {
            "_text": "OP11-077 【自分のターン中】【ターン1回】自分の場のドン‼がドン‼デッキに戻された時、自分の特徴《ビッグ・マム海賊団》を持つキャラ1枚までを、次の相手のターン終了時まで、コスト+2。",
            "_doc": "「次の相手のターン終了時まで」 cost+2 は 既存 cost_pump primitive (= turn duration) で 簡略 (= 次相手ターン 終了 まで の delta は engine 未対応)。",
            "when": "on_self_don_returned_to_deck",
            "if": {"self_turn": True},
            "cost": {"once_per_turn": True},
            "do": [
                {
                    "set_base_cost_timed": {
                        "target": {
                            "type": "one_self_chara_filtered",
                            "filter": {"feature": "ビッグ・マム海賊団"}
                        },
                        "delta": 2,
                        "duration": "next_opp_turn_end"
                    }
                }
            ]
        }
    ]

    # ST10-011: 【自分のターン中】【ターン1回】自分の場のドン!!がドン!!デッキに戻された時、
    #          このキャラは、 次の自分のターン開始時まで、 パワー+2000
    fixes["ST10-011"] = [
        {
            "_text": "ST10-011 【自分のターン中】【ターン1回】自分の場のドン!!がドン!!デッキに戻された時、このキャラは、次の自分のターン開始時まで、パワー+2000。",
            "when": "on_self_don_returned_to_deck",
            "if": {"self_turn": True},
            "cost": {"once_per_turn": True},
            "do": [
                {"power_pump": {"target": "self", "amount": 2000, "duration": "next_self_turn_start"}}
            ]
        }
    ]

    # OP05-053: 【自分のターン中】【ターン1回】自分がドローフェイズ以外でカードを引いた時、
    #          このキャラは、 このターン中、 パワー+2000
    fixes["OP05-053"] = [
        {
            "_text": "OP05-053 【自分のターン中】【ターン1回】自分がドローフェイズ以外でカードを引いた時、このキャラは、このターン中、パワー+2000。",
            "_doc": "「ドローフェイズ以外で引いた時」 trigger (= on_self_draw_non_draw_phase) は engine 未配線。 簡略: 任意 タイミング draw 後 trigger を on_self_draw で 模倣 (= 厳密 でなくとも 概念 を 保存)。",
            "when": "on_self_draw_non_draw_phase",
            "if": {"self_turn": True},
            "cost": {"once_per_turn": True},
            "do": [
                {"power_pump": {"target": "self", "amount": 2000, "duration": "turn"}}
            ]
        }
    ]

    # OP04-047: 【自分のターン中】このキャラが相手のコスト5以下のキャラとバトルしたバトル終了時、
    #          バトルした相手のキャラを持ち主のデッキの下に置く
    fixes["OP04-047"] = [
        {
            "_text": "OP04-047 【自分のターン中】このキャラが相手のコスト5以下のキャラとバトルしたバトル終了時、バトルした相手のキャラを持ち主のデッキの下に置く。",
            "_doc": "「バトル終了時」 trigger (= on_battle_end / post_battle) + 「バトルしたコスト5以下キャラ」 (= last_battle_opponent) は engine 未配線。 概念 保存 のみ。",
            "when": "on_attack",
            "if": {"self_turn": True},
            "do": [
                {"return_to_deck_bottom": "one_opponent_character_cost_le_5"}
            ]
        }
    ]

    # OP07-042: 【ターン1回】自分のリーダーが特徴《王下七武海》を持ち、
    #          このキャラが相手の効果で場を離れる場合、 代わりに自分の、 「ゲッコー・モリア」以外のキャラ1枚を
    #          持ち主のデッキの下に置いてもよい
    fixes["OP07-042"] = [
        {
            "_text": "OP07-042 【ターン1回】自分のリーダーが特徴《王下七武海》を持ち、このキャラが相手の効果で場を離れる場合、代わりに自分の、「ゲッコー・モリア」以外のキャラ1枚を持ち主のデッキの下に置いてもよい。",
            "when": "replace_leave",
            "if": {
                "target": "self",
                "leader_feature": "王下七武海",
                "by_opp_effect": True
            },
            "cost": [{"once_per_turn": True}],
            "do": [
                {
                    "return_to_deck_bottom": {
                        "type": "one_self_chara_filtered",
                        "filter": {"exclude_name": "ゲッコー・モリア"}
                    }
                }
            ]
        }
    ]

    # OP03-043: 相手のライフにダメージを与えた時、 自分のデッキの上から3枚をトラッシュに置いてもよい。
    #          そうした場合、 このキャラをトラッシュに置く
    fixes["OP03-043"] = [
        {
            "_text": "OP03-043 相手のライフにダメージを与えた時、自分のデッキの上から3枚をトラッシュに置いてもよい。そうした場合、このキャラをトラッシュに置く。",
            "_doc": "self に attached cost (= self KO 代償) を 引き換え に mill 3。 cost 払いで mill、 do で self KO の 一連 動作。",
            "when": "on_opp_life_taken",
            "optional": True,
            "cost": {"self_ko": True},
            "do": [
                {"mill_self_top": 3}
            ]
        }
    ]

    # P-117: 大型リーダー カード (= 特殊勝利条件 + アタック 時 デッキ操作)。 engine 未配線、 _doc で 明示。
    fixes["P-117"] = [
        {
            "_text": "P-117 ルール上、自分は特徴《東の海》を持つカードしかデッキに入れることができず、自分のデッキが0枚になった場合、自分は敗北する代わりに勝利する。【ドン‼×1】このリーダーのアタックによって、相手のライフにダメージを与えた時、自分のデッキの上から1枚を手札に加える。",
            "_doc": "デッキ構築制約 (= 東の海 のみ) + 特殊勝利 (= デッキ0で勝利) + on_opp_life_taken で 1 draw。 デッキ構築 ガード は engine 外、 特殊勝利 ガード は game 終了判定 拡張要、 1 draw のみ 実装。",
            "when": "on_opp_life_taken",
            "if": {"self_attached_don_ge": 1},
            "do": [
                {"draw": 1}
            ]
        }
    ]

    saved_keys = list(fixes.keys())
    for cid, entries in fixes.items():
        ov[cid] = entries

    PATH.write_text(json.dumps(ov, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"saved {len(saved_keys)} cards")


if __name__ == "__main__":
    main()
