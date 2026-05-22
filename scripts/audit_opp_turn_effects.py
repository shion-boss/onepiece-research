"""相手ターン中に発動できる効果のカバレッジ監査。

検出パターン:
  A. when="opp_attack" / "opp_attack_on_leader" / "opp_attack_on_chara"
     → defender の active 効果 (= 紫ドフラ OP14-060 等)
  B. when="counter" + category="EVENT"
     → defender が 手札 から 発動 する カウンターイベント
  C. when="opp_turn_start" / "opp_turn_end"
     → 相手ターン 開始/終了 時
  D. when="on_opp_chara_played" / "on_opp_chara_ko" / "on_opp_blocker_use"
     → 相手 行動 reactive
  E. 効果spec の `if: opp_turn` (= 相手ターン中 条件付き 常在)

各パターンで:
  - cost 持ち → human defender 用 に click activation 用 (= my recent fix) で 適用 確認
  - 無コスト + reactive → 自動発動
  - 公式テキスト 「【相手のターン中】」 を 含む 効果 が overlay で 抜けてない か
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS_PATH = ROOT / "db" / "cards.json"
OVERLAY_PATH = ROOT / "db" / "card_effects.json"


def main():
    cards = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
    overlay = json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))
    card_map = {c["card_id"]: c for c in cards}

    by_when: dict[str, list] = defaultdict(list)
    counter_events: list = []
    opp_turn_conditional: list = []  # if: opp_turn

    for cid, eff_list in overlay.items():
        if not isinstance(eff_list, list):
            continue
        cat = card_map.get(cid, {}).get("category", "")
        for i, eff in enumerate(eff_list):
            if not isinstance(eff, dict):
                continue
            when = eff.get("when", "")
            if when in {"opp_attack", "opp_attack_on_leader", "opp_attack_on_chara",
                       "opp_turn_start", "opp_turn_end",
                       "on_opp_chara_played", "on_opp_chara_ko",
                       "on_opp_blocker_use", "on_opp_life_taken",
                       "on_opp_chara_rested", "on_opp_event_played"}:
                cost = eff.get("cost") or {}
                has_cost = bool(cost) and (
                    int(cost.get("pay_don", 0)) > 0
                    or int(cost.get("rest_self_don", 0)) > 0
                    or int(cost.get("discard_hand", 0)) > 0
                )
                by_when[when].append({
                    "card_id": cid,
                    "name": card_map.get(cid, {}).get("name", "?"),
                    "eff_idx": i,
                    "has_cost": has_cost,
                    "cost": cost,
                    "_text": eff.get("_text", "")[:80],
                })
            if when == "counter" and cat == "EVENT":
                counter_events.append({
                    "card_id": cid,
                    "name": card_map.get(cid, {}).get("name", "?"),
                    "cost": eff.get("cost"),
                    "_text": eff.get("_text", "")[:80],
                })
            if_block = eff.get("if") or {}
            if isinstance(if_block, dict) and if_block.get("opp_turn"):
                opp_turn_conditional.append({
                    "card_id": cid,
                    "name": card_map.get(cid, {}).get("name", "?"),
                    "when": when,
                    "eff_idx": i,
                    "_text": eff.get("_text", "")[:80],
                })

    print("=" * 70)
    print("相手ターン中 発動 効果 監査")
    print("=" * 70)
    for when, entries in by_when.items():
        with_cost = [e for e in entries if e["has_cost"]]
        no_cost = [e for e in entries if not e["has_cost"]]
        print(f"\n[{when}] 合計 {len(entries)} 件 (cost持ち={len(with_cost)}, 無コスト={len(no_cost)})")
        if with_cost:
            print(f"  cost持ち (= human click activation 対象):")
            for e in with_cost[:10]:
                cost_str = ", ".join(f"{k}={v}" for k, v in e["cost"].items())
                print(f"    {e['card_id']} {e['name'][:18]} [{cost_str}]")
            if len(with_cost) > 10:
                print(f"    ... 他 {len(with_cost)-10} 件")

    print(f"\n[counter event] 合計 {len(counter_events)} 件")
    print(f"  (= 防御モーダルで 手札ドラッグ で 発動、 my recent fix で 対応済)")

    print(f"\n[if: opp_turn 条件] 合計 {len(opp_turn_conditional)} 件")
    print(f"  (= 相手ターン中 のみ 有効 な 条件付き 効果。 passive / 静的)")
    for e in opp_turn_conditional[:10]:
        print(f"    {e['card_id']} {e['name'][:18]} when={e['when']} | {e['_text']}")
    if len(opp_turn_conditional) > 10:
        print(f"    ... 他 {len(opp_turn_conditional)-10} 件")

    # 公式 「【相手のターン中】」 検出 vs overlay 反映 monitoring
    print()
    print("=" * 70)
    print("公式テキスト 「【相手のターン中】」 含む カード の overlay カバレッジ")
    print("=" * 70)
    pattern = re.compile(r"【相手のターン中】")
    missing: list[str] = []
    covered: list[str] = []
    for c in cards:
        cid = c["card_id"]
        if not pattern.search(c.get("text", "") or ""):
            continue
        eff_list = overlay.get(cid)
        # has_relevant: 何らかの opp_turn / opp_attack 系 effect or if:opp_turn or
        # conditions:[{opp_turn:true}] を 持つ
        has_relevant = False
        if isinstance(eff_list, list):
            for eff in eff_list:
                if not isinstance(eff, dict):
                    continue
                when = eff.get("when", "")
                if when.startswith("opp_") or when.startswith("on_opp_"):
                    has_relevant = True
                    break
                if_block = eff.get("if") or {}
                if isinstance(if_block, dict) and if_block.get("opp_turn"):
                    has_relevant = True
                    break
                conds = eff.get("conditions") or []
                if isinstance(conds, list):
                    for c in conds:
                        if isinstance(c, dict) and c.get("opp_turn"):
                            has_relevant = True
                            break
                if has_relevant:
                    break
        if has_relevant:
            covered.append(cid)
        else:
            missing.append(cid)
    print(f"  公式テキストに 「【相手のターン中】」 を含む カード: {len(covered) + len(missing)}")
    print(f"  overlay でも opp_turn 系 を 実装: {len(covered)} ✓")
    print(f"  実装漏れ candidate: {len(missing)}")
    if missing[:15]:
        for cid in missing[:15]:
            c = card_map[cid]
            text_snip = (c.get("text", "") or "")[:80]
            print(f"    {cid} {c['name'][:18]} | {text_snip}")
        if len(missing) > 15:
            print(f"    ... 他 {len(missing)-15} 件")


if __name__ == "__main__":
    main()
