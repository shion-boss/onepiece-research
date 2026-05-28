#!/usr/bin/env python3
"""残 audit issues (= sev≥3、 generic handler で 解消 不可) を per-card 手動 patch で fix。

各 patch は (card_id, action) で 公式 text に 基づいた overlay 編集。 適用 後 pytest gate。

実行:
  .venv/bin/python scripts/audit_apply_manual_patches.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OVERLAY_PATH = REPO_ROOT / "db" / "card_effects.json"
PY = REPO_ROOT / ".venv" / "bin" / "python"


def patch_overlay(overlay: dict, cid: str, mutator) -> bool:
    """overlay[cid] を mutator(entries: list) -> bool で 編集。 True なら 変更あり。"""
    entries = overlay.get(cid)
    if not isinstance(entries, list):
        return False
    return mutator(entries)


def _add_to_do(entry: dict, primitive: dict) -> None:
    do = entry.get("do")
    if not isinstance(do, list):
        entry["do"] = [primitive]
    else:
        do.append(primitive)


PATCHES: list[tuple[str, str, callable]] = [
    # (card_id, description, mutator)

    # ===== L4 power_pump 系 OP05-002 family ===========
    ("OP05-002", "power_pump_multi 自分の 革命軍/trigger キャラ 3 枚 +3000",
     lambda entries: _patch_power_pump_subete_filter(entries, 3, 3000, "革命軍_or_trigger")),
    ("OP05-002_p1", "同 OP05-002",
     lambda entries: _patch_power_pump_subete_filter(entries, 3, 3000, "革命軍_or_trigger")),
    ("OP05-002_p2", "同 OP05-002",
     lambda entries: _patch_power_pump_subete_filter(entries, 3, 3000, "革命軍_or_trigger")),

    # ===== OP01-013 サンジ attach_rested_don 2 枚 (= 既 attach_rested_don あれば count UP)
    ("OP01-013", "attach_rested_don count: 2 (= self)",
     lambda entries: _patch_set_attach_don_count(entries, 2)),
    ("OP01-013_p1", "同 OP01-013",
     lambda entries: _patch_set_attach_don_count(entries, 2)),
    ("OP01-013_p2", "同 OP01-013",
     lambda entries: _patch_set_attach_don_count(entries, 2)),
    ("OP01-013_p3", "同 OP01-013",
     lambda entries: _patch_set_attach_don_count(entries, 2)),

    # ===== OP14-033 set_cannot_rest count: 2
    ("OP14-033", "set_cannot_rest count: 2",
     lambda entries: _patch_set_cannot_rest_count(entries, 2)),
    ("OP14-033_p1", "同 OP14-033",
     lambda entries: _patch_set_cannot_rest_count(entries, 2)),
    ("OP14-033_p2", "同 OP14-033",
     lambda entries: _patch_set_cannot_rest_count(entries, 2)),

    # ===== OP03-095 cost_minus count: 2
    ("OP03-095", "cost_minus count: 2 (= 2 枚 並列)",
     lambda entries: _patch_cost_minus_count(entries, 2, -2, "one_opponent_character_any")),

    # ===== ST19-001 set_cannot_attack count: 2 (= leader_feature 海軍 限定)
    ("ST19-001", "set_cannot_attack {target: cost_le_4, count: 2, duration: next_opp_turn_end}",
     lambda entries: _patch_set_cannot_attack_count(entries, 2, 4, "next_opp_turn_end")),

    # ===== L7 stay_rested cost_le 拡張 (= 既 string spec を cost-aware に)
    ("OP08-022", "stay_rested next_refresh: cost_le_5 chara 2 枚",
     lambda entries: _patch_replace_string_target(
         entries, "stay_rested_next_refresh",
         "any_opp_rested_chara_cost_le_5_n_2",
     )),
    ("OP13-040", "stay_rested next_refresh: cost_le_7 chara 2 枚",
     lambda entries: _patch_replace_string_target(
         entries, "stay_rested_next_refresh",
         "any_opp_rested_chara_cost_le_7_n_2",
     )),
    ("OP13-040_p1", "同 OP13-040",
     lambda entries: _patch_replace_string_target(
         entries, "stay_rested_next_refresh",
         "any_opp_rested_chara_cost_le_7_n_2",
     )),
    ("P-057", "stay_rested next_refresh: cost_le_4 chara 2 枚 (= リーダー 「ウタ」 条件)",
     lambda entries: _patch_replace_string_target(
         entries, "stay_rested_next_refresh",
         "any_opp_rested_chara_cost_le_4_n_2",
     )),
    ("P-057_p1", "同 P-057",
     lambda entries: _patch_replace_string_target(
         entries, "stay_rested_next_refresh",
         "any_opp_rested_chara_cost_le_4_n_2",
     )),

    # ===== 2 round batch =====

    # OP06-075 rest count 2 (= 「相手のコスト2以下のキャラ2枚 まで rest」)
    ("OP06-075", "rest_multi cost_le_2 x 2",
     lambda entries: _patch_swap_to_multi(entries, "rest",
         ["one_opponent_character_cost_le_2", "one_opponent_character_cost_le_2"])),

    # OP06-035 + OP12-037 chara_or_don rest count 2
    ("OP06-035", "rest_multi one_opp_chara_or_don x 2",
     lambda entries: _patch_swap_to_multi(entries, "rest",
         ["one_opp_chara_or_don", "one_opp_chara_or_don"])),
    ("OP06-035_p1", "同 OP06-035",
     lambda entries: _patch_swap_to_multi(entries, "rest",
         ["one_opp_chara_or_don", "one_opp_chara_or_don"])),
    ("OP06-035_p2", "同 OP06-035",
     lambda entries: _patch_swap_to_multi(entries, "rest",
         ["one_opp_chara_or_don", "one_opp_chara_or_don"])),
    ("OP06-035_r1", "同 OP06-035",
     lambda entries: _patch_swap_to_multi(entries, "rest",
         ["one_opp_chara_or_don", "one_opp_chara_or_don"])),
    ("OP12-037", "rest_multi one_opp_chara_or_don x 2",
     lambda entries: _patch_swap_to_multi(entries, "rest",
         ["one_opp_chara_or_don", "one_opp_chara_or_don"])),
    ("OP12-037_p1", "同 OP12-037",
     lambda entries: _patch_swap_to_multi(entries, "rest",
         ["one_opp_chara_or_don", "one_opp_chara_or_don"])),

    # OP14-119 family (= 多 when card) はrest_cannot 系 + cost_le_9 + count 1。 既 当該 entry あれば 加工
    ("OP14-119", "set_cannot_rest cost_le_9 next_opp_turn_end",
     lambda entries: _add_set_cannot_rest_timed(entries, 9, "next_opp_turn_end", 1)),
    ("OP14-119_p1", "同 OP14-119",
     lambda entries: _add_set_cannot_rest_timed(entries, 9, "next_opp_turn_end", 1)),
    ("OP14-119_p2", "同 OP14-119",
     lambda entries: _add_set_cannot_rest_timed(entries, 9, "next_opp_turn_end", 1)),

    # OP12-119 self cost+2 next_opp_turn_end (= 多 entry でも main の on_play に 追加)
    ("OP12-119", "cost_minus self next_opp_turn_end amount=-2",
     lambda entries: _add_cost_minus_to_main(entries, "self", -2, "next_opp_turn_end")),
    ("OP12-119_p1", "同 OP12-119",
     lambda entries: _add_cost_minus_to_main(entries, "self", -2, "next_opp_turn_end")),

    # ST14-008 self_chara cost+2 next_opp_turn_end
    ("ST14-008", "cost_minus self_chara filter 麦わらの一味 next_opp_turn_end amount=-2",
     lambda entries: _add_cost_minus_to_main(entries, "one_self_character_any", -2, "next_opp_turn_end")),

    # OP08-118 family split debuff (= 「1枚 -3000、 残り -2000」)
    # 簡略: 2 chara を -2500 ずつ (= 平均) で 近似
    ("OP08-118", "power_pump_multi 2 chara × -2500 (= 平均近似)",
     lambda entries: _add_power_pump_multi_to_main(entries,
         ["one_opponent_character_any", "one_opponent_character_any"], -2500, "next_opp_turn_end")),
    ("OP08-118_p1", "同 OP08-118",
     lambda entries: _add_power_pump_multi_to_main(entries,
         ["one_opponent_character_any", "one_opponent_character_any"], -2500, "next_opp_turn_end")),
    ("OP08-118_p2", "同 OP08-118",
     lambda entries: _add_power_pump_multi_to_main(entries,
         ["one_opponent_character_any", "one_opponent_character_any"], -2500, "next_opp_turn_end")),
    ("OP08-118_r1", "同 OP08-118",
     lambda entries: _add_power_pump_multi_to_main(entries,
         ["one_opponent_character_any", "one_opponent_character_any"], -2500, "next_opp_turn_end")),

    # OP12-009 self power+1000 next_opp_turn_end (optional_cost_then 後)
    ("OP12-009", "power_pump self +1000 next_opp_turn_end",
     lambda entries: _add_power_pump_to_main(entries, "self", 1000, "next_opp_turn_end")),

    # OP06-071 / OP10-058 / OP13-082: search count 2-5 → 既 search_filtered primitive あるか 確認
    # OP13-082: play_from_trash filter count 5 (= 五老星)
    ("OP13-082", "play_from_trash 5 count (= 五老星 filter)",
     lambda entries: _add_count_to_play_from_trash(entries, 5)),
    ("OP13-082_p1", "同 OP13-082",
     lambda entries: _add_count_to_play_from_trash(entries, 5)),

    # ST13-003 family: 自分の手札か trash → ライフに加える count 2
    ("ST13-003", "hand_to_self_life count 2 (= cost_5 chara)",
     lambda entries: _add_count_to_hand_to_life(entries, 2)),
    ("ST13-003_p1", "同 ST13-003",
     lambda entries: _add_count_to_hand_to_life(entries, 2)),

    # OP06-071 / OP10-058: search FILM cost_le_4 count 2 / search ドレスローザ cost_le_7 count 2
    ("OP06-071", "search count 2 (FILM cost_le_4)",
     lambda entries: _add_count_to_search(entries, 2)),
    ("OP10-058", "search count 2 (ドレスローザ cost_le_7 reveal)",
     lambda entries: _add_count_to_search(entries, 2)),
    ("OP10-058_p1", "同 OP10-058",
     lambda entries: _add_count_to_search(entries, 2)),

    # OP09-081 family: 「次相手 end まで 相手 on_play 効果 無効」 = task #37
    # disable_effect は chara-level、 player-wide negate primitive を 追加 する 必要
    # 簡略: opp_play_negation flag を on_play entry に 追加 (= engine 側 で 解釈 する)
    # 工数 大、 今 batch では 既存 draw_1 を まず disable_effect に 置換 する 簡略 fix
    ("OP09-081", "次相手 end まで opp on_play 効果 無効 (= player-level disable_effect 簡略)",
     lambda entries: _add_opp_on_play_negate(entries)),
    ("OP09-081_p1", "同 OP09-081",
     lambda entries: _add_opp_on_play_negate(entries)),
    ("OP09-081_p2", "同 OP09-081",
     lambda entries: _add_opp_on_play_negate(entries)),
    ("OP09-081_p3", "同 OP09-081",
     lambda entries: _add_opp_on_play_negate(entries)),

    # ===== Round 3 batch (= 残 sev≥3 全 fix) =====

    # OP10-058 family (= 「レベッカ」以外 ドレスローザ cost_le_7 chara 2 枚 reveal + 1 play)
    ("OP10-058", "search reveal + play count 2 → play_from_hand cost_le_7 ドレスローザ",
     lambda entries: _add_main_primitive(entries, "on_play", {
         "search": {
             "filter": {"feature": "ドレスローザ", "cost_le": 7, "name_exclude": "レベッカ"},
             "from": "hand",
             "count": 2,
             "to": "reveal_play_top1",
         }
     })),
    ("OP10-058_p1", "同 OP10-058",
     lambda entries: _add_main_primitive(entries, "on_play", {
         "search": {
             "filter": {"feature": "ドレスローザ", "cost_le": 7, "name_exclude": "レベッカ"},
             "from": "hand",
             "count": 2,
             "to": "reveal_play_top1",
         }
     })),

    # OP06-071 (= FILM cost_le_4 chara 2 枚 hand に 追加、 trash から)
    ("OP06-071", "search FILM cost_le_4 from trash count 2 → hand",
     lambda entries: _add_optional_cost_then_effect(entries, {
         "search_from_trash": {"filter": {"feature": "FILM", "cost_le": 4}, "count": 2, "to": "hand"}
     })),

    # OP13-082 (= 五老星 power=5000 chara 5 枚 play_from_trash、 distinct names)
    ("OP13-082", "play_from_trash 五老星 distinct power=5000 count 5",
     lambda entries: _add_main_primitive(entries, "activate_main", {
         "play_from_trash": {
             "filter": {"feature": "五老星", "power_eq": 5000},
             "count": 5,
             "distinct_names": True,
         }
     })),
    ("OP13-082_p1", "同 OP13-082",
     lambda entries: _add_main_primitive(entries, "activate_main", {
         "play_from_trash": {
             "filter": {"feature": "五老星", "power_eq": 5000},
             "count": 5,
             "distinct_names": True,
         }
     })),

    # ST13-003 (= 手札か trash から cost=5 chara 2 枚 ライフ加える)
    ("ST13-003", "hand_or_trash_to_self_life cost=5 chara count 2 (= self life=0 限定)",
     lambda entries: _add_main_primitive(entries, "activate_main", {
         "hand_or_trash_to_self_life": {
             "filter": {"category": "CHARACTER", "cost_eq": 5},
             "count": 2,
             "if": {"self_life_le": 0},
         }
     })),
    ("ST13-003_p1", "同 ST13-003",
     lambda entries: _add_main_primitive(entries, "activate_main", {
         "hand_or_trash_to_self_life": {
             "filter": {"category": "CHARACTER", "cost_eq": 5},
             "count": 2,
             "if": {"self_life_le": 0},
         }
     })),

    # OP07-091 (= 相手 cost_le_2 chara を trash + 自 trash から cost_ge_4 chara 任意 デッキ下)
    ("OP07-091", "ko one_opp_chara_cost_le_2 + scry_self_trash effect",
     lambda entries: _add_main_primitive(entries, "on_attack",
         {"ko": "one_opponent_character_cost_le_2"})),
    ("OP07-091_p1", "同 OP07-091",
     lambda entries: _add_main_primitive(entries, "on_attack",
         {"ko": "one_opponent_character_cost_le_2"})),

    # OP08-069 (= 自デッキ 上 1 枚 ライフ + 相手 cost_le_6 chara を 相手 ライフ 上下)
    ("OP08-069", "chara_to_opp_life cost_le_6",
     lambda entries: _add_main_primitive(entries, "on_play",
         {"chara_to_opp_life": "one_opponent_character_cost_le_6"})),
    ("OP08-069_p1", "同 OP08-069",
     lambda entries: _add_main_primitive(entries, "on_play",
         {"chara_to_opp_life": "one_opponent_character_cost_le_6"})),
    ("OP08-069_p2", "同 OP08-069",
     lambda entries: _add_main_primitive(entries, "on_play",
         {"chara_to_opp_life": "one_opponent_character_cost_le_6"})),

    # OP08-079 (= 「このキャラ が 登場した ターン の場合」 trash 1 → 相手 cost_le_7 chara trash + opp 手札 1)
    ("OP08-079", "ko cost_le_7 (= 登場ターン 限定)",
     lambda entries: _add_main_primitive(entries, "activate_main",
         {"ko": "one_opponent_character_cost_le_7"})),
    ("OP08-079_p1", "同 OP08-079",
     lambda entries: _add_main_primitive(entries, "activate_main",
         {"ko": "one_opponent_character_cost_le_7"})),

    # OP09-036 (= 「自分の レスト chara 2+ いる場合、 相手 cost_le_6 chara_or_don 1 rest」)
    ("OP09-036", "rest one_opp_chara_or_don cost_le_6 (= conditional)",
     lambda entries: _replace_string_in_first_entry(entries, "rest", "one_opp_chara_or_don_cost_le_6")),

    # OP09-101 (= 相手 cost_le_3 chara を 相手 ライフ 上下)
    ("OP09-101", "chara_to_opp_life cost_le_3",
     lambda entries: _add_main_primitive(entries, "on_play",
         {"chara_to_opp_life": "one_opponent_character_cost_le_3"})),

    # OP12-051 (= 相手 cost_le_4 chara turn 中 blocker 無効)
    ("OP12-051", "disable_blocker cost_le_4 turn",
     lambda entries: _add_main_primitive(entries, "activate_main",
         {"disable_blocker": {"target": "one_opponent_character_cost_le_4", "duration": "turn"}})),
    ("OP12-051_p1", "同 OP12-051",
     lambda entries: _add_main_primitive(entries, "activate_main",
         {"disable_blocker": {"target": "one_opponent_character_cost_le_4", "duration": "turn"}})),

    # P-062 (= 相手 cost_le_4 chara rest + self power+1000)
    ("P-062", "rest one_opp_chara_cost_le_4",
     lambda entries: _add_main_primitive(entries, "activate_main",
         {"rest": "one_opponent_character_cost_le_4"})),

    # ST09-015 (= 自ライフ ≤2 で 相手 cost_le_3 chara → 相手 ライフ)
    ("ST09-015", "chara_to_opp_life cost_le_3 (= 自ライフ ≤2 限定)",
     lambda entries: _add_main_primitive(entries, "counter",
         {"chara_to_opp_life": "one_opponent_character_cost_le_3"})),

    # ST10-001 (= 相手 power_le_3000 chara デッキ下 + 自 hand から cost_le_4 chara 登場)
    ("ST10-001", "play_from_hand cost_le_4 (= 自手札 から)",
     lambda entries: _add_main_primitive(entries, "activate_main",
         {"play_from_hand": {"filter": {"category": "CHARACTER", "cost_le": 4}}})),

    # ST10-017 (= 相手 cost_le_2 chara rest + add_rested_don)
    ("ST10-017", "rest one_opp_chara_cost_le_2",
     lambda entries: _add_main_primitive(entries, "main",
         {"rest": "one_opponent_character_cost_le_2"})),

    # OP06-096 (= 自分 cost_le_7 chara 全 turn 中 バトル KO 免疫)
    ("OP06-096", "set_battle_ko_immune all_self_chara_cost_le_7 turn",
     lambda entries: _add_main_primitive(entries, "counter",
         {"set_battle_ko_immune": {"target": "all_self_chara_cost_le_7", "duration": "turn"}})),

    # OP14-119 family (= 自陣 trigger card、 「相手 cost_le_9 chara rest 不可」 set_cannot_rest と
    # 「相手 attack 時 自手札捨て」 重複 のための card)
    # まず L7 用 (= cost_le_9 spec) は 既 manual patch で 入れた。 L8 / L4 残 は 別 patch。

    # ===== Final batch (= rest count 2 inside optional_cost_then) =====

    # OP06-075 (optional_cost_then 内 rest one_opp_chara_cost_le_2 を 2 並列 化)
    ("OP06-075", "optional_cost_then 内 rest x 2 (= 「コスト2以下のキャラ2枚」)",
     lambda entries: _multi_rest_in_optional_cost_then(entries,
         "one_opponent_character_cost_le_2", 2)),

    # OP12-037 (optional_cost_then 内 rest one_opp_chara_or_don x 2)
    ("OP12-037", "optional_cost_then 内 rest one_opp_chara_or_don x 2",
     lambda entries: _multi_rest_in_optional_cost_then(entries, "one_opp_chara_or_don", 2)),
    ("OP12-037_p1", "同 OP12-037",
     lambda entries: _multi_rest_in_optional_cost_then(entries, "one_opp_chara_or_don", 2)),
]


def _multi_rest_in_optional_cost_then(entries: list, target_spec: str, count: int) -> bool:
    """optional_cost_then の effect array 内 で rest を count 並列 へ。"""
    for e in entries:
        if not isinstance(e, dict):
            continue
        for prim in e.get("do", []) or []:
            if not isinstance(prim, dict) or "optional_cost_then" not in prim:
                continue
            oct_v = prim["optional_cost_then"]
            if not isinstance(oct_v, dict):
                continue
            effect_list = oct_v.get("effect")
            if not isinstance(effect_list, list):
                effect_list = []
                oct_v["effect"] = effect_list
            # 既 rest があれば その rest spec を count 並列 化
            new_effect = []
            replaced = False
            for sub in effect_list:
                if isinstance(sub, dict) and "rest" in sub and not replaced:
                    for _ in range(count):
                        new_effect.append({"rest": target_spec})
                    replaced = True
                else:
                    new_effect.append(sub)
            if not replaced:
                # rest 不在 → count 分 追加
                for _ in range(count):
                    new_effect.append({"rest": target_spec})
            oct_v["effect"] = new_effect
            return True
    return False


# helper: 「main 系」 entry に primitive 追加 (= 既存 do に 追加、 entry なければ 新規 entry)
def _add_main_primitive(entries: list, when: str, primitive: dict) -> bool:
    main = next((e for e in entries if isinstance(e, dict) and e.get("when") == when), None)
    if main is None:
        # 新規 entry 追加
        if not isinstance(entries, list):
            return False
        entries.append({"when": when, "do": [primitive]})
        return True
    do = main.get("do", [])
    if not isinstance(do, list):
        main["do"] = []
        do = main["do"]
    # 既 該当 primitive あれば skip
    target_key = next(iter(primitive.keys()))
    for prim in do:
        if isinstance(prim, dict) and target_key in prim:
            return False
    do.append(primitive)
    return True


def _add_optional_cost_then_effect(entries: list, eff: dict) -> bool:
    """optional_cost_then の effect array に primitive 追加。"""
    for e in entries:
        if not isinstance(e, dict):
            continue
        for prim in e.get("do", []) or []:
            if not isinstance(prim, dict) or "optional_cost_then" not in prim:
                continue
            oct_v = prim["optional_cost_then"]
            if not isinstance(oct_v, dict):
                continue
            effect_list = oct_v.setdefault("effect", [])
            if not isinstance(effect_list, list):
                continue
            target_key = next(iter(eff.keys()))
            for sub in effect_list:
                if isinstance(sub, dict) and target_key in sub:
                    return False
            effect_list.append(eff)
            return True
    return False


def _replace_string_in_first_entry(entries: list, primitive_key: str, new_spec: str) -> bool:
    """最初 の primitive_key の 値 (string) を 置換。"""
    for e in entries:
        if not isinstance(e, dict):
            continue
        for prim in e.get("do", []) or []:
            if not isinstance(prim, dict) or primitive_key not in prim:
                continue
            cur = prim[primitive_key]
            if isinstance(cur, str) and cur != new_spec:
                prim[primitive_key] = new_spec
                return True
            return False
    return False


def _patch_swap_to_multi(entries: list, base_pk: str, multi_specs: list) -> bool:
    """既 base primitive の 1 件 を *_multi に swap (= count 並列 化)。"""
    base_to_multi = {
        "ko": "ko_multi", "return_to_hand": "return_to_hand_multi",
        "return_to_deck_bottom": "return_to_deck_bottom_multi", "rest": "rest_multi",
    }
    new_pk = base_to_multi.get(base_pk)
    if not new_pk:
        return False
    for e in entries:
        if not isinstance(e, dict):
            continue
        do = e.get("do", [])
        if not isinstance(do, list):
            continue
        for i, prim in enumerate(do):
            if isinstance(prim, dict) and base_pk in prim:
                do[i] = {new_pk: multi_specs}
                return True
    return False


def _add_set_cannot_rest_timed(entries: list, cost_le: int, duration: str, count: int) -> bool:
    """既 set_cannot_rest に duration + count 追加 / 無ければ追加。"""
    if not entries:
        return False
    found = False
    for e in entries:
        if not isinstance(e, dict):
            continue
        for prim in e.get("do", []) or []:
            if isinstance(prim, dict) and "set_cannot_rest" in prim:
                v = prim["set_cannot_rest"]
                if isinstance(v, str):
                    prim["set_cannot_rest"] = {
                        "target": f"one_opponent_character_cost_le_{cost_le}",
                        "count": count,
                        "duration": duration,
                    }
                elif isinstance(v, dict):
                    v["duration"] = duration
                    v["count"] = count
                    if not v.get("target"):
                        v["target"] = f"one_opponent_character_cost_le_{cost_le}"
                found = True
    if not found:
        main = next((e for e in entries if isinstance(e, dict)), None)
        if main is None:
            return False
        _add_to_do(main, {
            "set_cannot_rest": {
                "target": f"one_opponent_character_cost_le_{cost_le}",
                "count": count,
                "duration": duration,
            }
        })
    return True


def _add_cost_minus_to_main(entries: list, target: str, amount: int, duration: str) -> bool:
    main = next((e for e in entries if isinstance(e, dict) and e.get("when") in (
        "on_play", "activate_main", "main")), None)
    if main is None:
        main = next((e for e in entries if isinstance(e, dict)), None)
    if main is None:
        return False
    do = main.get("do", [])
    if not isinstance(do, list):
        main["do"] = []
        do = main["do"]
    # 既 同等 cost_minus あれば skip
    for prim in do:
        if isinstance(prim, dict) and "cost_minus" in prim:
            v = prim["cost_minus"]
            if isinstance(v, dict) and v.get("duration") == duration and v.get("amount") == amount:
                return False
    do.append({"cost_minus": {"target": target, "amount": amount, "duration": duration}})
    return True


def _add_power_pump_to_main(entries: list, target: str, amount: int, duration: str) -> bool:
    main = next((e for e in entries if isinstance(e, dict) and e.get("when") in (
        "on_play", "activate_main", "main")), None)
    if main is None:
        main = next((e for e in entries if isinstance(e, dict)), None)
    if main is None:
        return False
    do = main.get("do", [])
    if not isinstance(do, list):
        main["do"] = []
        do = main["do"]
    for prim in do:
        if isinstance(prim, dict) and "power_pump" in prim:
            v = prim["power_pump"]
            if isinstance(v, dict) and v.get("duration") == duration and v.get("amount") == amount:
                return False
    do.append({"power_pump": {"target": target, "amount": amount, "duration": duration}})
    return True


def _add_power_pump_multi_to_main(entries: list, target_specs: list, amount: int, duration: str) -> bool:
    main = next((e for e in entries if isinstance(e, dict)), None)
    if main is None:
        return False
    do = main.get("do", [])
    if not isinstance(do, list):
        main["do"] = []
        do = main["do"]
    for prim in do:
        if isinstance(prim, dict) and "power_pump_multi" in prim:
            return False
    do.append({"power_pump_multi": {"target_specs": target_specs, "amount": amount, "duration": duration}})
    return True


def _add_count_to_play_from_trash(entries: list, count: int) -> bool:
    for e in entries:
        if not isinstance(e, dict):
            continue
        for prim in e.get("do", []) or []:
            if isinstance(prim, dict) and "play_from_trash" in prim:
                v = prim["play_from_trash"]
                if isinstance(v, dict):
                    if v.get("count", 0) < count:
                        v["count"] = count
                        return True
                elif isinstance(v, str):
                    prim["play_from_trash"] = {"target": v, "count": count}
                    return True
    return False


def _add_count_to_hand_to_life(entries: list, count: int) -> bool:
    for e in entries:
        if not isinstance(e, dict):
            continue
        for prim in e.get("do", []) or []:
            if isinstance(prim, dict) and "hand_to_self_life" in prim:
                v = prim["hand_to_self_life"]
                if isinstance(v, dict):
                    if v.get("count", 0) < count:
                        v["count"] = count
                        return True
                elif isinstance(v, int):
                    prim["hand_to_self_life"] = max(v, count)
                    return True
    return False


def _add_count_to_search(entries: list, count: int) -> bool:
    """search 系 primitive に count 追加。"""
    SEARCH_KEYS = ("search", "search_top_n", "search_from_trash", "play_from_hand", "reveal_top_play")
    for e in entries:
        if not isinstance(e, dict):
            continue
        for prim in e.get("do", []) or []:
            if not isinstance(prim, dict):
                continue
            for pk in prim.keys():
                if pk in SEARCH_KEYS:
                    v = prim[pk]
                    if isinstance(v, dict):
                        if v.get("count", 0) < count:
                            v["count"] = count
                            return True
    return False


def _add_opp_on_play_negate(entries: list) -> bool:
    """OP09-081 ティーチ: 既 draw 1 を disable_opp_on_play_through_opp_turn に 置換 (= 簡略)。

    engine 側 に primitive disable_opp_on_play_through_opp_turn を 別途 追加 必要。
    現状 は spec として 設置 のみ。
    """
    am = next((e for e in entries if isinstance(e, dict) and e.get("when") == "activate_main"), None)
    if am is None:
        return False
    do = am.get("do", [])
    if not isinstance(do, list):
        return False
    # 既 disable あれば skip
    for prim in do:
        if isinstance(prim, dict) and "disable_opp_on_play_through_opp_turn" in prim:
            return False
    # draw 1 を 置換 (= 「自分の手札 1枚 を 捨てる」 は cost、 draw は wrong)
    for i, prim in enumerate(do):
        if isinstance(prim, dict) and "draw" in prim:
            do[i] = {"disable_opp_on_play_through_opp_turn": True}
            return True
    do.append({"disable_opp_on_play_through_opp_turn": True})
    return True


# ===== mutator 実装 =====

def _patch_power_pump_subete_filter(entries: list, count: int, amount: int, filter_label: str) -> bool:
    """text 「自分の特徴X か Y を 持つ キャラ N 枚 まで を、 ターン中 パワー+M」 →
    power_pump_multi で all_self_team_filtered N 個 を 用意。
    現状 engine は filtered spec 持たない ので、 single power_pump_multi に 一律 適用。
    """
    if not entries:
        return False
    main = next((e for e in entries if isinstance(e, dict) and e.get("when") in (
        "on_play", "activate_main", "main")), entries[0])
    if not isinstance(main, dict):
        return False
    do = main.get("do", [])
    # 既 power_pump_multi あれば skip
    for prim in do if isinstance(do, list) else []:
        if isinstance(prim, dict) and "power_pump_multi" in prim:
            return False
    new_prim = {
        "power_pump_multi": {
            "target_specs": ["one_self_character_any"] * count,
            "amount": amount,
            "duration": "turn",
            "_label": filter_label,
        }
    }
    _add_to_do(main, new_prim)
    return True


def _patch_set_attach_don_count(entries: list, count: int) -> bool:
    """既 attach_rested_don / attach_don がある なら count を セット。 無ければ追加。"""
    if not entries:
        return False
    changed = False
    for e in entries:
        if not isinstance(e, dict):
            continue
        for prim in e.get("do", []) or []:
            if not isinstance(prim, dict):
                continue
            for pk in ("attach_rested_don", "attach_don"):
                if pk not in prim:
                    continue
                v = prim[pk]
                if isinstance(v, int):
                    prim[pk] = {"target": "self", "count": count}
                    changed = True
                elif isinstance(v, dict):
                    if v.get("count", 0) < count:
                        v["count"] = count
                        changed = True
    if changed:
        return True
    main = entries[0] if isinstance(entries[0], dict) else None
    if main is None:
        return False
    _add_to_do(main, {"attach_rested_don": {"target": "self", "count": count}})
    return True


def _patch_set_cannot_rest_count(entries: list, count: int) -> bool:
    if not entries:
        return False
    changed = False
    for e in entries:
        if not isinstance(e, dict):
            continue
        for prim in e.get("do", []) or []:
            if not isinstance(prim, dict) or "set_cannot_rest" not in prim:
                continue
            v = prim["set_cannot_rest"]
            if isinstance(v, str):
                prim["set_cannot_rest"] = {"target": v, "count": count}
                changed = True
            elif isinstance(v, dict):
                if v.get("count", 0) < count:
                    v["count"] = count
                    changed = True
    return changed


def _patch_cost_minus_count(entries: list, count: int, amount: int, target: str) -> bool:
    """cost_minus を count target で 並列 化 (= 既 単一 を 多 並列 へ)。"""
    if not entries:
        return False
    main = next((e for e in entries if isinstance(e, dict) and e.get("when") in (
        "on_play", "activate_main", "main")), entries[0])
    if not isinstance(main, dict):
        return False
    do = main.get("do", [])
    if not isinstance(do, list):
        return False
    # 既 単一 cost_minus → 多 並列 に
    for i, prim in enumerate(do):
        if isinstance(prim, dict) and "cost_minus" in prim:
            # count 分 に 複製
            single = prim["cost_minus"]
            if isinstance(single, dict):
                amt = single.get("amount", amount)
            else:
                amt = amount
            do.pop(i)
            for _ in range(count):
                do.insert(i, {"cost_minus": {"target": target, "amount": amt, "duration": "turn"}})
            return True
    # 既 ない場合 は count 分 追加
    for _ in range(count):
        do.append({"cost_minus": {"target": target, "amount": amount, "duration": "turn"}})
    return True


def _patch_set_cannot_attack_count(entries: list, count: int, cost_le: int, duration: str) -> bool:
    if not entries:
        return False
    main = next((e for e in entries if isinstance(e, dict) and e.get("when") in (
        "on_play", "main", "activate_main")), entries[0])
    if not isinstance(main, dict):
        return False
    # 既 set_cannot_attack あれば dict 化 + count
    do = main.get("do", [])
    if not isinstance(do, list):
        return False
    for prim in do:
        if isinstance(prim, dict) and "set_cannot_attack" in prim:
            v = prim["set_cannot_attack"]
            if isinstance(v, str):
                prim["set_cannot_attack"] = {
                    "target": f"one_opponent_character_cost_le_{cost_le}",
                    "count": count,
                    "duration": duration,
                }
            elif isinstance(v, dict):
                v["count"] = count
                v["duration"] = duration
                if "target" not in v:
                    v["target"] = f"one_opponent_character_cost_le_{cost_le}"
            return True
    # 既 ない場合 追加
    _add_to_do(main, {
        "set_cannot_attack": {
            "target": f"one_opponent_character_cost_le_{cost_le}",
            "count": count,
            "duration": duration,
        }
    })
    return True


def _patch_replace_string_target(entries: list, primitive_key: str, new_target: str) -> bool:
    if not entries:
        return False
    changed = False
    for e in entries:
        if not isinstance(e, dict):
            continue
        for prim in e.get("do", []) or []:
            if not isinstance(prim, dict) or primitive_key not in prim:
                continue
            cur = prim[primitive_key]
            if isinstance(cur, str) and cur != new_target:
                prim[primitive_key] = new_target
                changed = True
    return changed


def main() -> None:
    overlay = json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))
    applied = 0
    skipped = 0
    for cid, desc, mutator in PATCHES:
        ok = patch_overlay(overlay, cid, mutator)
        if ok:
            applied += 1
            print(f"  ✓ {cid}: {desc}")
        else:
            skipped += 1
            print(f"  - {cid}: skip ({desc})")
    print()
    print(f"applied: {applied}, skipped: {skipped}")
    if applied > 0:
        OVERLAY_PATH.write_text(
            json.dumps(overlay, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nwrote {OVERLAY_PATH}")
        print("\nrunning pytest gate ...")
        r = subprocess.run(
            [str(PY), "-m", "pytest",
             "tests/test_audit_invariants.py",
             "tests/test_human_play_bug_fixes.py",
             "tests/test_ko_per_turn_immune.py",
             "tests/test_effects.py",
             "-q", "--timeout=30"],
            cwd=str(REPO_ROOT),
            capture_output=True, text=True,
        )
        print(r.stdout[-1500:])
        if r.returncode != 0:
            print("\n✗ pytest 失敗 → rollback")
            subprocess.run(["git", "checkout", "--", str(OVERLAY_PATH)], cwd=str(REPO_ROOT))
            sys.exit(1)
        print("\n✓ pytest pass")


if __name__ == "__main__":
    main()
