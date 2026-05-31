#!/usr/bin/env python3
"""二重コスト bug 修復 Phase 2: phase1 で 保留した残り (= 公式テキスト個別検証済)。

phase1 (fix_double_optional_cost.py) で 機械的に安全な 85 entry を hoist/drop 済。
本 phase2 は 公式テキストを 1 枚ずつ読んで 確定した 残り を 明示的に修復する。

各 card の 公式テキスト 確認結果:
  OP06-060/064/066/068 (+_p1/_p2/_r1): top {pay_don:1, trash_self} が official-correct
    (= ドン‼-1 + このキャラtrash)、 oct.cost は同義 spelling → HOIST (effect=play_from_hand_or_trash)
  OP12-061/_p1: top {once_per_turn, pay_don:1} official-correct (= ドン‼-1)、
    oct.cost rest_self_don:1 は誤 spelling → HOIST (effect=reduce_play_cost)
  OP11-070/_p1: oct.effect 空 (= 「相手デッキ上1枚を見る」 未実装 primitive)。
    cost 二重のみ修復 = oct DROP。 effect は未実装のまま (別 issue、 _missing_effect 注記)
  OP08-077: oct.effect=return_to_hand_multi は 公式「KOする」 に反する 誤実装、
    かつ do[1] ko は 1 体のみ (公式 2 体)。 → do を ko_multi 2×cost_le_6 に是正
  OP07-059/_p1/_p2: oct.effect=keep_opp_rested と do[1]=stay_rested が 別 target を
    rest 維持 (= 公式 1 枚 を 超過)。 → keep_opp_rested 1 つに是正
  ST26-002: oct.effect=rest(chara_or_don, cost無制限) と do[1]=rest(cost_le_1, donなし)。
    公式「コスト1以下のキャラかドン1枚」 → rest {chara_or_don, cost_le:1} 1 つに是正
  OP04-111: top {rest_self} + oct {ko_self ホーミーズ, rest_self}。 rest_self の冪等重複のみ
    (= ホーミーズ犠牲 cost は oct で 1 回)。 実害なし → 触らない
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EFF_PATH = ROOT / "db" / "card_effects.json"

HOIST = [  # (card_id, effect_idx): do 内 唯一の optional_cost_then を effect で置換
    "OP06-060", "OP06-060_p1", "OP06-060_p2", "OP06-060_r1",
    "OP06-064", "OP06-064_p1", "OP06-064_p2", "OP06-064_r1",
    "OP06-066", "OP06-066_p1", "OP06-066_p2", "OP06-066_r1",
    "OP06-068", "OP06-068_p1", "OP06-068_p2", "OP06-068_r1",
    "OP12-061", "OP12-061_p1",
]
DROP_OCT = ["OP11-070", "OP11-070_p1"]  # cost のみ修復、 effect は未実装のまま


def _find_oct_idx(do):
    for i, d in enumerate(do):
        if isinstance(d, dict) and "optional_cost_then" in d:
            return i
    return -1


def apply(eff: dict) -> list[str]:
    log = []

    # --- HOIST 系 (top cost 正、 oct を effect で置換) ---
    for cid in HOIST:
        for e in eff.get(cid, []):
            if not isinstance(e, dict):
                continue
            do = e.get("do", [])
            i = _find_oct_idx(do)
            if i >= 0:
                effect = do[i]["optional_cost_then"].get("effect", [])
                do[i:i + 1] = effect
                log.append(f"HOIST {cid}: oct→effect({len(effect)})")

    # --- OP11-070: oct DROP (cost 修復のみ) + missing-effect 注記 ---
    for cid in DROP_OCT:
        for e in eff.get(cid, []):
            if not isinstance(e, dict) or e.get("when") != "activate_main":
                continue
            do = e.get("do", [])
            i = _find_oct_idx(do)
            if i >= 0:
                del do[i]
                e["_missing_effect"] = "相手のデッキの上から1枚を見る (= peek_opp_deck_top 未実装。 cost二重のみ修復済)"
                log.append(f"DROP_OCT {cid}: cost二重解消、 effect未実装注記")

    # --- OP08-077: 公式「コスト6以下キャラ2枚までKO」 ---
    for e in eff.get("OP08-077", []):
        if isinstance(e, dict) and e.get("when") == "main":
            e["do"] = [{"ko_multi": ["one_opponent_character_cost_le_6",
                                     "one_opponent_character_cost_le_6"]}]
            log.append("REWORK OP08-077: do=ko_multi 2×cost_le_6")

    # --- OP07-059/_p1/_p2: keep_opp_rested 1 つに ---
    for cid in ["OP07-059", "OP07-059_p1", "OP07-059_p2"]:
        for e in eff.get(cid, []):
            if isinstance(e, dict) and e.get("when") == "on_attack":
                e["do"] = [{"keep_opp_rested_inplay_next_refresh":
                            {"target_rest": "one_opp_chara_or_leader"}}]
                log.append(f"REWORK {cid}: do=keep_opp_rested 単一")

    # --- ST26-002: rest {chara_or_don, cost_le:1} 1 つに ---
    for e in eff.get("ST26-002", []):
        if isinstance(e, dict) and e.get("when") == "on_play":
            e["do"] = [{"rest": {"type": "one_opp_chara_or_don", "cost_le": 1}}]
            log.append("REWORK ST26-002: do=rest chara_or_don(cost_le1) 単一")

    return log


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    eff = json.loads(EFF_PATH.read_text(encoding="utf-8"))
    # dry-run 用に deep copy
    import copy
    log = apply(copy.deepcopy(eff) if not args.apply else eff)
    print(f"=== Phase2 修復: {len(log)} 操作 ===")
    for line in log:
        print(f"  {line}")
    if args.apply:
        EFF_PATH.write_text(json.dumps(eff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"適用完了 → {EFF_PATH.relative_to(ROOT)}")
    else:
        print("(dry-run。 --apply で適用)")


if __name__ == "__main__":
    main()
