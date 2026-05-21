#!/usr/bin/env python3
"""missing_if_opp_turn の 残 13 件 のうち、 mechanical な ケース を 補完。

対象 (= 個別 card_id 単位):
- OP15-071: ADD opp_turn set_base_power 6000 (self + 「オーム」全)
- ST30-001 (+_p1): ADD opp_turn power_pump (「エース」+「ルフィ」+3000 static)
- P-090: PATCH on_ko entry に if opp_turn 追加
- EB03-033: PATCH entry に if opp_turn + leader_feature + once_per_turn 追加
- OP09-080: ADD replace_leave entry (opp_turn, cost: rest stage, do: add_rested_don 1)
- OP14-053: ADD set_base_power_copy from leader (opp_turn + hand_le 7)
- P-027: ADD opp_turn power_pump filtered (元P3000以下) +1000 static

複雑 ケース は skip:
- OP14-029: replace_leave 追加 が 必要 だが、 do に 「自カード1レスト」 が 必要
- OP05-001 (+_p1,_p2): victim target サポート 必要 (skip)
- OP09-052: KO 後 再登場 の 複雑 ロジック
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

    # OP15-071: ADD opp_turn set_base_power 6000 to self + all 「オーム」
    n = add_to("OP15-071", [
        {
            "_text": "[auto] 【相手のターン中】 self + 「オーム」 set_base_power 6000",
            "when": "on_attached_don",
            "n": 0,
            "if": {"opp_turn": True},
            "do": [
                {
                    "set_base_power_timed": {
                        "target": "self",
                        "amount": 6000,
                        "duration": "static",
                    }
                },
                {
                    "set_base_power_timed": {
                        "target": {
                            "type": "all_self_chara_named",
                            "name": "オーム",
                        },
                        "amount": 6000,
                        "duration": "static",
                    }
                },
            ],
        }
    ])
    log.append(f"  OP15-071: +1 entry × {n}")

    # ST30-001 (+_p1): ADD opp_turn power_pump (「エース」+「ルフィ」+3000)
    n = add_to("ST30-001", [
        {
            "_text": "[auto] 【相手のターン中】 「ポートガス・Ｄ・エース」+「モンキー・Ｄ・ルフィ」 +3000",
            "when": "on_attached_don",
            "n": 0,
            "if": {"opp_turn": True},
            "do": [
                {
                    "power_pump": {
                        "target": {
                            "type": "all_self_chara_filtered",
                            "filter": {
                                "name_in": ["ポートガス・Ｄ・エース", "モンキー・Ｄ・ルフィ"]
                            },
                        },
                        "amount": 3000,
                        "duration": "static",
                    }
                }
            ],
        }
    ])
    log.append(f"  ST30-001 (+_p1): +1 entry × {n}")

    # P-090: PATCH on_ko entry に if opp_turn 追加
    for cid in ["P-090"] + [f"P-090{s}" for s in ("_p1", "_p2", "_r1", "_r2")]:
        if cid not in OVERLAY:
            continue
        for e in OVERLAY[cid]:
            if isinstance(e, dict) and e.get("when") == "on_ko":
                if "if" not in e:
                    e["if"] = {}
                e["if"]["opp_turn"] = True
                log.append(f"  {cid}: + opp_turn to on_ko")

    # EB03-033: PATCH entry に if 追加
    for cid in ["EB03-033"] + [f"EB03-033{s}" for s in ("_p1", "_p2", "_r1", "_r2")]:
        if cid not in OVERLAY:
            continue
        for e in OVERLAY[cid]:
            if isinstance(e, dict) and e.get("when") == "on_self_don_returned_to_deck":
                if "if" not in e:
                    e["if"] = {}
                e["if"]["opp_turn"] = True
                e["if"]["leader_feature"] = "ビッグ・マム海賊団"
                if "cost" not in e:
                    e["cost"] = {"once_per_turn": True}
                else:
                    if isinstance(e["cost"], dict):
                        e["cost"]["once_per_turn"] = True
                log.append(f"  {cid}: + opp_turn + leader_feature + once_per_turn")

    # OP09-080: ADD replace_leave (opp_turn, cost: stage_rest, do: add_rested_don)
    # 公式: 「このステージをレストにできる: ...」 → cost に stage rest 必要
    # engine 簡略: cost を `{"rest_self_stage": true}` で 表現 (= 動作 する か 確認)
    # 実は engine は rest_self_stage cost を 持たないので skip ?
    # → Just add as if{opp_turn} replace_leave + 既存 add_rested_don but in different when
    # OP09-080 は ステージ カード で、 既存 entry は activate_main + add_rested_don。
    # 公式 は 「【相手のターン中】このステージをレストにできる: 自分の特徴《麦わらの一味》を持つキャラが相手の効果で場を離れた時、 ドン!!1枚をレストで追加」
    # → 既存 activate_main は 解釈 違い。 新規 トリガー entry が 必要。
    # → engine の trigger 「自キャラが相手の効果で場を離れた時」 が 必要 (= on_self_chara_left_by_opp_effect)
    # → 現状 そんな trigger は ない、 skip
    log.append(f"  OP09-080: SKIP (新規 trigger 必要)")

    # OP14-053: ADD set_base_power_copy from leader (opp_turn, self_hand_count_le 7)
    # 「【ブロッカー】【相手のターン中】 自手札7以下、 このキャラの元々のパワー = 自リーダー元々のパワー」
    n = add_to("OP14-053", [
        {
            "_text": "[auto] 【相手のターン中】 + 自手札7以下、 self.base_power = leader.base_power (static)",
            "when": "on_attached_don",
            "n": 0,
            "if": {"opp_turn": True, "self_hand_count_le": 7},
            "do": [
                {
                    "set_base_power_copy": {
                        "from_target": "self_leader",
                        "to_target": "self",
                        "duration": "static",
                    }
                }
            ],
        }
    ])
    log.append(f"  OP14-053: +1 entry × {n}")

    # P-027: ADD opp_turn power_pump filtered (元P3000以下) +1000 static
    n = add_to("P-027", [
        {
            "_text": "[auto] 【相手のターン中】 自元P3000以下キャラすべて +1000 (static)",
            "when": "on_attached_don",
            "n": 0,
            "if": {"opp_turn": True},
            "do": [
                {
                    "power_pump": {
                        "target": {
                            "type": "all_self_chara_filtered",
                            "filter": {"power_le": 3000},
                        },
                        "amount": 1000,
                        "duration": "static",
                    }
                }
            ],
        }
    ])
    log.append(f"  P-027: +1 entry × {n}")

    (ROOT / "db" / "card_effects.json").write_text(
        json.dumps(OVERLAY, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "db" / "fix_missing_opp_turn_v2_log.md").write_text(
        "# missing_if_opp_turn v2 補完ログ\n\n" + "\n".join(log), encoding="utf-8"
    )
    print("\n".join(log))


if __name__ == "__main__":
    main()
