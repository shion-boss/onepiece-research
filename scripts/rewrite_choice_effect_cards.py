#!/usr/bin/env python3
"""choice_effect 未実装 19 base cards (+ parallel) を 公式テキスト に 合わせて 書き換え。

各 card は 個別 構造 を 持つ ので 手書き。 parallel (_p1/_p2/_r1) は base と 同 内容
(= _text のみ cid 差し替え)。
"""
from __future__ import annotations
import json
import copy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS = {c["card_id"]: c for c in json.load(open(ROOT / "db" / "cards.json"))}
OV_PATH = ROOT / "db" / "card_effects.json"
ov = json.load(open(OV_PATH, encoding="utf-8"))


def _set(cid: str, entries: list[dict]) -> None:
    """base + 同名 parallel に entries を 適用 (= _text の cid 差し替えのみ)。"""
    if cid not in CARDS:
        print(f"  SKIP {cid}: not in cards.json")
        return
    base_id = cid
    # parallel 検索
    parallels = [k for k in CARDS if k != base_id and k.split("_")[0] == base_id]
    for tgt in [base_id] + parallels:
        new_entries = []
        for e in entries:
            copy_e = copy.deepcopy(e)
            if isinstance(copy_e, dict) and "_text" in copy_e:
                copy_e["_text"] = copy_e["_text"].replace(base_id, tgt)
            new_entries.append(copy_e)
        ov[tgt] = new_entries
    print(f"  OK {base_id} (+{len(parallels)} parallels)")


# ===========================================================
# 19 cards の choice_effect overlay 定義
# ===========================================================

# --- EB02-051 鼻唄三丁矢筈斬り ---
_set("EB02-051", [{
    "_text": "EB02-051 【メイン】以下から1つを選ぶ。・相手のコスト2以下のキャラ1枚までを、KOする。・相手のキャラ1枚までを、このターン中、コスト-4。",
    "when": "main",
    "do": [{
        "choice_effect": {
            "optional": False,
            "options": [
                {"label": "コスト2以下のキャラ KO", "do": [{"ko": "one_opponent_character_cost_le_2cost"}]},
                {"label": "相手キャラ コスト-4 (このターン中)", "do": [{
                    "set_base_cost_timed": {
                        "target": "one_opponent_character_any",
                        "amount": -4,
                        "duration": "turn",
                    }
                }]},
            ],
        }
    }],
}])

# --- OP15-055 使ってけれ ---
_set("OP15-055", [{
    "_text": "OP15-055 【メイン】以下から1つを選ぶ。・カード2枚を引く。・自分の特徴《ドレスローザ》を持つキャラ1枚までは、次の相手のエンドフェイズ終了時まで、【ブロッカー】を得る。",
    "when": "main",
    "do": [{
        "choice_effect": {
            "optional": False,
            "options": [
                {"label": "カード 2 枚 引く", "do": [{"draw": 2}]},
                {"label": "自ドレスローザ キャラ にブロッカー (= 次相手 end まで)", "do": [{
                    "give_keyword": {
                        "target": {"type": "one_self_chara_or_leader_filtered", "filter": {"feature": "ドレスローザ"}},
                        "keyword": "ブロッカー",
                        "duration": "next_opp_turn_end",
                    }
                }]},
            ],
        }
    }],
}])

# --- OP12-060 牛肉バースト ---
_set("OP12-060", [{
    "_text": "OP12-060 【メイン】自分のリーダーが多色の場合、以下から1つを選ぶ。・相手のコスト4以下のキャラ1枚までを、持ち主の手札に戻す。・自分の手札が6枚以下の場合、カード2枚を引く。",
    "when": "main",
    "if": {"leader_color_multi": True},
    "do": [{
        "choice_effect": {
            "optional": False,
            "options": [
                {"label": "コスト4以下 1 枚 手札戻し", "do": [{"return_to_hand": "one_opponent_character_cost_le_4cost"}]},
                {"label": "手札6以下 なら 2 ドロー", "if": {"self_hand_le": 6}, "do": [{"draw": 2}]},
            ],
        }
    }],
}])

# --- OP06-039 退屈凌ぎ ---
_set("OP06-039", [{
    "_text": "OP06-039 【メイン】以下から1つを選ぶ。・相手のコスト6以下のキャラ1枚までを、レストにする。・相手のレストのコスト6以下のキャラ1枚までを、KOする。",
    "when": "main",
    "do": [{
        "choice_effect": {
            "optional": False,
            "options": [
                {"label": "コスト6以下 レスト", "do": [{"rest": "one_opponent_character_cost_le_6cost"}]},
                {"label": "レスト コスト6以下 KO", "do": [{"ko": "one_opponent_rested_character_cost_le_6cost"}]},
            ],
        }
    }],
}])

# --- ST12-006 ヨサク＆ジョニー ---
_set("ST12-006", [{
    "_text": "ST12-006 【ドン!!×1】【アタック時】以下から1つを選ぶ。・相手のコスト2以下のキャラ1枚までを、レストにする。・相手のレストのコスト2以下のキャラ1枚までを、KOする。",
    "when": "on_attack",
    "n": 1,
    "do": [{
        "choice_effect": {
            "optional": True,
            "options": [
                {"label": "コスト2以下 レスト", "do": [{"rest": "one_opponent_character_cost_le_2cost"}]},
                {"label": "レスト コスト2以下 KO", "do": [{"ko": "one_opponent_rested_character_cost_le_2cost"}]},
            ],
        }
    }],
}])

# --- ST11-003 逆光 ---
_set("ST11-003", [{
    "_text": "ST11-003 【メイン】自分のリーダーが「ウタ」の場合、以下から1つを選ぶ。・相手のコスト5以下のキャラ1枚までを、レストにする。・相手のレストのコスト5以下のキャラ1枚までを、KOする。",
    "when": "main",
    "if": {"leader_name": "ウタ"},
    "do": [{
        "choice_effect": {
            "optional": False,
            "options": [
                {"label": "コスト5以下 レスト", "do": [{"rest": "one_opponent_character_cost_le_5cost"}]},
                {"label": "レスト コスト5以下 KO", "do": [{"ko": "one_opponent_rested_character_cost_le_5cost"}]},
            ],
        }
    }],
}])

# --- OP06-021 ペローナ ---
_set("OP06-021", [{
    "_text": "OP06-021 【起動メイン】【ターン1回】以下から1つを選ぶ。・相手のコスト4以下のキャラ1枚までを、レストにする。・相手のキャラ1枚までを、このターン中、コスト-1。",
    "when": "activate_main",
    "cost": {"once_per_turn": True},
    "do": [{
        "choice_effect": {
            "optional": False,
            "options": [
                {"label": "コスト4以下 レスト", "do": [{"rest": "one_opponent_character_cost_le_4cost"}]},
                {"label": "相手キャラ コスト-1", "do": [{
                    "set_base_cost_timed": {
                        "target": "one_opponent_character_any", "amount": -1, "duration": "turn",
                    }
                }]},
            ],
        }
    }],
}])

# --- OP08-057 キング ---
_set("OP08-057", [{
    "_text": "OP08-057 【起動メイン】【ターン1回】ドン‼-2：以下から1つを選ぶ。・自分の手札が5枚以下の場合、カード1枚を引く。・相手のキャラ1枚までを、このターン中、コスト-2。",
    "when": "activate_main",
    "cost": {"once_per_turn": True, "pay_don": 2},
    "do": [{
        "choice_effect": {
            "optional": False,
            "options": [
                {"label": "手札5以下 なら 1 ドロー", "if": {"self_hand_le": 5}, "do": [{"draw": 1}]},
                {"label": "相手キャラ コスト-2", "do": [{
                    "set_base_cost_timed": {
                        "target": "one_opponent_character_any", "amount": -2, "duration": "turn",
                    }
                }]},
            ],
        }
    }],
}])

# --- EB02-045 トラファルガー・ロー ---
_set("EB02-045", [{
    "_text": "EB02-045 【ブロッカー】【登場時】自分のトラッシュからカード2枚を好きな順番でデッキの下に置くことができる：以下から1つを選ぶ。・カード1枚を引く。・相手の手札が5枚以上ある場合、相手は自身の手札1枚を捨てる。",
    "when": "on_play",
    "cost": {"trash_to_deck": 2},
    "do": [{
        "choice_effect": {
            "optional": False,
            "options": [
                {"label": "1 ドロー", "do": [{"draw": 1}]},
                {"label": "相手手札5以上 なら 1 枚 捨て", "if": {"opp_hand_ge": 5}, "do": [{"trash_opp_hand_random": 1}]},
            ],
        }
    }],
}])

# --- OP06-065 ヴィンスモーク・ニジ ---
_set("OP06-065", [{
    "_text": "OP06-065 【登場時】自分の場のドン !!が相手の場のドン !!の枚数以下の場合、以下から1つを選ぶ。・相手のコスト2以下のキャラ1枚までを、KOする。・相手のコスト4以下のキャラ1枚までを、持ち主の手札に戻す。",
    "when": "on_play",
    "if": {"don_diff_le": 0},
    "do": [{
        "choice_effect": {
            "optional": False,
            "options": [
                {"label": "コスト2以下 KO", "do": [{"ko": "one_opponent_character_cost_le_2cost"}]},
                {"label": "コスト4以下 手札戻し", "do": [{"return_to_hand": "one_opponent_character_cost_le_4cost"}]},
            ],
        }
    }],
}])

# --- OP06-092 ブルック ---
_set("OP06-092", [{
    "_text": "OP06-092 【登場時】以下から1つを選ぶ。・相手のコスト4以下のキャラ1枚までを、トラッシュに置く。・相手は自身のトラッシュのカード3枚を好きな順番でデッキの下に置く。",
    "when": "on_play",
    "do": [{
        "choice_effect": {
            "optional": False,
            "options": [
                {"label": "コスト4以下 KO (= トラッシュへ)", "do": [{"ko": "one_opponent_character_cost_le_4cost"}]},
                {"label": "相手 トラッシュ 3 枚 デッキ下", "do": [{"opp_trash_to_deck_bottom": 3}]},
            ],
        }
    }],
}])

# --- OP06-093 ペローナ ---
_set("OP06-093", [{
    "_text": "OP06-093 【登場時】相手の手札が5枚以上ある場合、以下から1つを選ぶ。・相手は自身の手札1枚を捨てる。・相手のキャラ1枚までを、このターン中、コスト-3。",
    "when": "on_play",
    "if": {"opp_hand_ge": 5},
    "do": [{
        "choice_effect": {
            "optional": False,
            "options": [
                {"label": "相手手札 1 枚 捨て", "do": [{"trash_opp_hand_random": 1}]},
                {"label": "相手キャラ コスト-3", "do": [{
                    "set_base_cost_timed": {
                        "target": "one_opponent_character_any", "amount": -3, "duration": "turn",
                    }
                }]},
            ],
        }
    }],
}])

# --- OP06-116 排撃 ---
_set("OP06-116", [{
    "_text": "OP06-116 【メイン】以下から1つを選ぶ。・相手のコスト5以下のキャラ1枚までを、KOする。・相手のライフが1枚の場合、相手に1ダメージを与える。その後、自分のライフの上から1枚を手札に加える。",
    "when": "main",
    "do": [{
        "choice_effect": {
            "optional": False,
            "options": [
                {"label": "コスト5以下 KO", "do": [{"ko": "one_opponent_character_cost_le_5cost"}]},
                {"label": "相手ライフ1 なら ダメージ + 自ライフ→手札", "if": {"opp_life_le": 1}, "do": [
                    {"mill_opp_life_to_trash": 1},
                    {"life_to_hand": 1},
                ]},
            ],
        }
    }],
}])

# --- OP15-054 形見 ---
_set("OP15-054", [{
    "_text": "OP15-054 【メイン】自分のリーダーが「ルーシー」の場合、以下から1つを選ぶ。・カード2枚を引き、自分の手札1枚を捨てる。その後、自分の手札からコスト4以下の特徴《ドレスローザ》を持つキャラカード1枚までを、登場させる。・ステージ1枚までを、持ち主の手札に戻す。",
    "when": "main",
    "if": {"leader_name": "ルーシー"},
    "do": [{
        "choice_effect": {
            "optional": False,
            "options": [
                {"label": "2 ドロー + 1 捨て + 特徴ドレスローザ コスト4以下 登場", "do": [
                    {"draw": 2},
                    {"trash_self_hand_random": 1},
                    {"play_from_hand": {"filter": {"feature": "ドレスローザ", "cost_le": 4, "category": "CHARACTER"}}},
                ]},
                {"label": "ステージ 1 枚 手札戻し", "do": [{
                    "return_to_hand": {"type": "any_stage_n_1"}
                }]},
            ],
        }
    }],
}])

# --- OP08-030 ペドロ ---
_set("OP08-030", [{
    "_text": "OP08-030 【ブロッカー】【KO時】以下から1つを選ぶ。・相手のドン‼1枚までを、レストにする。・相手のレストのコスト6以下のキャラ1枚までを、KOする。",
    "when": "on_ko",
    "do": [{
        "choice_effect": {
            "optional": False,
            "options": [
                {"label": "相手ドン 1 枚 レスト", "do": [{"rest_opp_don": 1}]},
                {"label": "レスト コスト6以下 KO", "do": [{"ko": "one_opponent_rested_character_cost_le_6cost"}]},
            ],
        }
    }],
}])

# --- OP03-028 ジャンゴ ---
_set("OP03-028", [{
    "_text": "OP03-028 【登場時】以下から1つを選ぶ。・自分の特徴《東の海》を持つ、リーダーかコスト6以下のキャラ1枚までを、アクティブにする。・このキャラと相手のキャラ1枚までを、レストにする。",
    "when": "on_play",
    "do": [{
        "choice_effect": {
            "optional": False,
            "options": [
                {"label": "自東の海 リーダーかコスト6以下 1 枚 untap", "do": [{
                    "untap_chara": {"type": "one_self_chara_or_leader_filtered", "filter": {"feature": "東の海", "cost_le": 6}}
                }]},
                {"label": "このキャラ + 相手キャラ レスト", "do": [
                    {"rest": "self"},
                    {"rest": "one_opponent_character_any"},
                ]},
            ],
        }
    }],
}])

# --- EB01-052 ヴィオラ ---
# 「自ライフ 裏向き」 は 公式 で 「ライフ を 公開できなくする」 = mark_self_life_face_down 等。
# 既存 primitive で 不対応 → option 2 を 「marker」 で 一旦 簡略 (= 効果 概ね 防御寄り)。
_set("EB01-052", [{
    "_text": "EB01-052 【ブロッカー】【登場時】以下から1つを選ぶ。・相手のライフすべてを見て、好きな順番で置く。・自分のライフすべてを裏向きにする。",
    "when": "on_play",
    "do": [{
        "choice_effect": {
            "optional": False,
            "options": [
                {"label": "相手ライフ 並び替え (peek)", "do": [{"scry_all_life_reorder": {"owner": "opp"}}]},
                {"label": "自ライフ 裏向き化 (= 効果防止 marker、 engine 簡略)", "do": []},
            ],
        }
    }],
}])

# --- ST20-005 シャーロット・リンリン (相手 actor) ---
_set("ST20-005", [{
    "_text": "ST20-005 【登場時】自分の手札1枚を捨てることができる：相手は以下から1つを選ぶ。・相手は自身の手札2枚を捨てる。・相手のライフの上から1枚をトラッシュに置く。",
    "when": "on_play",
    "cost": {"discard_hand": 1},
    "do": [{
        "choice_effect": {
            "optional": False,
            "actor": "opp",
            "options": [
                {"label": "相手手札 2 枚 捨て", "do": [{"trash_opp_hand_random": 2}]},
                {"label": "相手ライフ→トラッシュ 1 枚", "do": [{"mill_opp_life_to_trash": 1}]},
            ],
        }
    }],
}])

# --- ST07-010 シャーロット・リンリン (相手 actor) ---
_set("ST07-010", [{
    "_text": "ST07-010 【登場時】相手は以下から1つを選ぶ。・相手のライフの上から1枚をトラッシュに置く。・自分のデッキの上から1枚をライフの上に加える。",
    "when": "on_play",
    "do": [{
        "choice_effect": {
            "optional": False,
            "actor": "opp",
            "options": [
                {"label": "相手ライフ→トラッシュ 1 枚", "do": [{"mill_opp_life_to_trash": 1}]},
                {"label": "自デッキトップ→ライフ", "do": [{"put_top_to_life": 1}]},
            ],
        }
    }],
}])

# --- ST07-015 ソウル・ポーカス (相手 actor) ---
_set("ST07-015", [{
    "_text": "ST07-015 【メイン】相手は以下から1つを選ぶ。・相手のライフの上から1枚をトラッシュに置く。・自分のデッキの上から1枚をライフの上に加える。",
    "when": "main",
    "do": [{
        "choice_effect": {
            "optional": False,
            "actor": "opp",
            "options": [
                {"label": "相手ライフ→トラッシュ 1 枚", "do": [{"mill_opp_life_to_trash": 1}]},
                {"label": "自デッキトップ→ライフ", "do": [{"put_top_to_life": 1}]},
            ],
        }
    }],
}])

# ===========================================================
# 書き出し
# ===========================================================
OV_PATH.write_text(json.dumps(ov, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nwrote: {OV_PATH}")
