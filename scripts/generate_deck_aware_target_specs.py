#!/usr/bin/env python3
"""Plan H Phase H-1 v2 (= 2026-05-19): deck-aware target_v1.json 一括生成。

template-based (= generate_mirror_target_specs.py) は 16-deck eval で
平均 -1.9pt FAIL。 原因: 各 deck の 実際 cards / 戦略 を 反映 してない。

これは analysis.json から:
- synergy_feature_priority (= 主特徴 軸)
- blocker_scarce signal (= blocker 要求 しない)
- finisher cost (= deck 固有 の 大型 cost)
- have_search_loop / have_burst_finisher 等

を 抽出 → 各 deck の 実態 に 合わせた entries を 構築。

# 使い方

```bash
.venv/bin/python scripts/generate_deck_aware_target_specs.py
# → 全 15 deck (= cardrush_1456 除く) の target_v1.json を 上書き
```
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DECKS_DIR = REPO_ROOT / "decks"


def _t(priority: int, cond: dict, bonus: int, desc: str) -> dict:
    return {"priority": priority, "if": cond, "bonus": bonus, "description": desc}


def _extract_deck_props(slug: str) -> dict:
    """analysis.json から deck-specific 情報 を 抽出。"""
    deck = json.loads((DECKS_DIR / f"{slug}.json").read_text(encoding="utf-8"))
    a = json.loads((DECKS_DIR / f"{slug}.analysis.json").read_text(encoding="utf-8"))
    sig = {s["type"]: s["value"] for s in a.get("ai_hint_signals", [])}
    key_cards = a.get("key_cards", [])
    finishers = [c for c in key_cards if c.get("role") == "finisher"]
    finisher_cost = min((c["cost"] for c in finishers), default=None)
    return {
        "leader_id": deck["leader"],
        "leader_name": deck.get("leader_name", ""),
        "archetype": a.get("archetype", ""),
        "speed": a.get("speed", ""),
        "defense": a.get("defense", ""),
        "synergy_feature": sig.get("synergy_feature_priority", "") or "",
        "blocker_scarce": bool(sig.get("blocker_scarce", False)),
        "have_search_loop": bool(sig.get("have_search_loop", False)),
        "have_removal_arsenal": bool(sig.get("have_removal_arsenal", False)),
        "have_burst_finisher": bool(sig.get("have_burst_finisher", False)),
        "have_ramp": bool(sig.get("have_ramp", False)),
        "preserve_counter_for_lethal": bool(sig.get("preserve_counter_for_lethal", False)),
        "tank_lifeup_ok": bool(sig.get("tank_lifeup_ok", False)),
        "finisher_cost": finisher_cost,  # None なら deck に finisher role なし
        "key_card_costs": sorted(set(c.get("cost", 0) for c in key_cards if c.get("cost"))),
    }


def _expected_field_count(turn: int, archetype: str) -> int:
    """turn N で 期待 する 場 chara 数。"""
    if archetype.startswith("ミッドレンジ") or archetype.startswith("midrange"):
        return min(max(1, turn - 1), 4)
    if archetype.startswith("コントロール") or archetype.startswith("control"):
        # control は ゆっくり、 序盤 場 薄い
        return min(max(1, (turn - 1) // 2 + 1), 3)
    return min(max(1, turn - 1), 4)


def _expected_field_power(turn: int) -> int:
    """turn N で 期待 する 場 power 合計。"""
    return min(turn * 1500, 12000)


def _expected_hand(turn: int) -> int:
    """turn N で 維持 したい 手札 数。"""
    return max(3, 6 - (turn - 1) // 3)


def _expected_synergy_count(turn: int) -> int:
    """turn N で synergy feature キャラ 数 期待値。"""
    return min(max(1, (turn - 1) // 2 + 1), 3)


def build_targets(turn: int, cond: str, props: dict) -> list[dict]:
    """deck-aware に turn × cond の targets を 構築。"""
    archetype = props["archetype"]
    feature = props["synergy_feature"]
    blocker_scarce = props["blocker_scarce"]
    finisher_cost = props["finisher_cost"]
    has_finisher_role = finisher_cost is not None
    preserve_counter = props["preserve_counter_for_lethal"]

    # turn が finisher cost 以上 で finisher の plan 入る
    can_play_finisher = has_finisher_role and turn >= (finisher_cost or 99)

    targets: list[dict] = []

    if turn == 1:
        # T1: search/draw start
        if feature:
            targets.append(_t(1, {
                "self_chara_feature_count_ge": {"feature": feature, "count": 1},
                "self_hand_ge": 4,
            }, 1000, f"T1: {feature} chara 展開 + 手札 4"))
        else:
            targets.append(_t(1, {"self_chara_count_ge": 1, "self_hand_ge": 4}, 900, "T1: chara 展開"))
        targets.append(_t(2, {"self_chara_count_ge": 1}, 500, "fallback: chara 1 体"))
        return targets

    # behind 全 turn 共通: counter 確保 + (blocker 持つ deck だけ) blocker
    if cond == "behind":
        # 序盤 (T2-4): hand + counter
        if turn <= 4:
            cond_dict = {
                "self_hand_ge": max(4, 6 - (turn - 1) // 2),
                "self_counter_in_hand_ge": min(4000 + (turn - 1) * 1000, 8000),
            }
            if not blocker_scarce and turn >= 3:
                cond_dict["self_blocker_count_ge"] = 1
            targets.append(_t(1, cond_dict, 1200 + turn * 100, f"behind T{turn}: 手札 + counter"))
            targets.append(_t(2, {"self_counter_in_hand_ge": 5000}, 700, "fallback: counter のみ"))
            return targets
        # 中盤 (T5-7): blocker (= ある場合) or 強い chara
        if turn <= 7:
            cond_dict = {"self_counter_in_hand_ge": 8000}
            if not blocker_scarce:
                cond_dict["self_blocker_count_ge"] = 1
            else:
                cond_dict["self_field_power_ge"] = _expected_field_power(turn)
            if can_play_finisher:
                cond_dict["self_finisher_on_field_ge"] = 1
            targets.append(_t(1, cond_dict, 1400 + turn * 80, f"behind T{turn}: 受け継続"))
            # fallback: counter のみ
            targets.append(_t(2, {"self_counter_in_hand_ge": 8000}, 900, "fallback: counter のみ"))
            return targets
        # 終盤 (T8-10): 反撃
        cond_dict = {
            "self_counter_in_hand_ge": 8000,
            "self_field_power_ge": _expected_field_power(turn),
        }
        if can_play_finisher:
            cond_dict["self_finisher_on_field_ge"] = 1
        targets.append(_t(1, cond_dict, 1700, f"behind T{turn}: 反撃"))
        targets.append(_t(2, {"self_counter_in_hand_ge": 10000}, 1000, "fallback"))
        return targets

    # advantage 全 turn 共通: push + lethal 視野
    if cond == "advantage":
        if turn <= 3:
            cond_dict = {"self_chara_count_ge": _expected_field_count(turn, archetype)}
            if feature:
                cond_dict["self_chara_feature_count_ge"] = {"feature": feature, "count": min(_expected_synergy_count(turn), 2)}
            cond_dict["self_leader_attached_don_ge"] = 1
            targets.append(_t(1, cond_dict, 1100, f"advantage T{turn}: push 維持"))
            targets.append(_t(2, {"self_chara_count_ge": _expected_field_count(turn, archetype)}, 700, "fallback"))
            return targets
        if turn <= 6:
            cond_dict = {"self_field_power_ge": _expected_field_power(turn)}
            if feature:
                cond_dict["self_chara_feature_count_ge"] = {"feature": feature, "count": _expected_synergy_count(turn)}
            if turn >= 4 and can_play_finisher and turn >= finisher_cost - 1:
                cond_dict["opp_life_le"] = 3
            targets.append(_t(1, cond_dict, 1300 + turn * 50, f"advantage T{turn}: 中盤 pressure"))
            targets.append(_t(2, {"self_field_power_ge": _expected_field_power(turn) - 2000}, 800, "fallback"))
            return targets
        # T7+: lethal 視野
        cond_dict = {
            "self_field_power_ge": _expected_field_power(turn),
            "opp_life_le": max(0, 10 - turn),  # T8 で ライフ 2、 T10 で 0
        }
        if can_play_finisher:
            cond_dict["self_finisher_on_field_ge"] = 1 if turn < 9 else 2
        targets.append(_t(1, cond_dict, 1700 + min(turn * 30, 300), f"advantage T{turn}: lethal 視野"))
        targets.append(_t(2, {"opp_life_le": max(0, 11 - turn)}, 1200, "fallback"))
        return targets

    # even (= default、 通常 tempo)
    if turn <= 3:
        cond_dict = {
            "self_chara_count_ge": _expected_field_count(turn, archetype),
            "self_hand_ge": _expected_hand(turn),
        }
        if feature:
            cond_dict["self_chara_feature_count_ge"] = {
                "feature": feature, "count": min(_expected_synergy_count(turn), 2)
            }
        targets.append(_t(1, cond_dict, 1000 + turn * 50, f"even T{turn}: {feature or 'chara'} 展開"))
        targets.append(_t(2, {"self_chara_count_ge": _expected_field_count(turn, archetype)}, 600, "fallback"))
        return targets
    if turn <= 6:
        cond_dict = {
            "self_field_power_ge": _expected_field_power(turn),
            "self_hand_ge": _expected_hand(turn),
        }
        if feature:
            cond_dict["self_chara_feature_count_ge"] = {
                "feature": feature, "count": _expected_synergy_count(turn)
            }
        if not blocker_scarce and turn >= 4:
            cond_dict["self_blocker_count_ge"] = 1
        if can_play_finisher and turn >= finisher_cost:
            cond_dict["self_finisher_on_field_ge"] = 1
        targets.append(_t(1, cond_dict, 1200 + turn * 80, f"even T{turn}: 中盤 安定"))
        # fallback (= 厳密 条件 緩く)
        fallback_cond = {"self_field_power_ge": _expected_field_power(turn) - 2000}
        if feature:
            fallback_cond["self_chara_feature_count_ge"] = {"feature": feature, "count": 1}
        targets.append(_t(2, fallback_cond, 800, "fallback"))
        return targets
    # even T7-10: lethal prep / lethal
    cond_dict = {
        "self_field_power_ge": _expected_field_power(turn),
        "opp_life_le": max(1, 11 - turn),
    }
    if can_play_finisher:
        cond_dict["self_finisher_on_field_ge"] = min(2, turn - 6)
    targets.append(_t(1, cond_dict, 1500 + turn * 50, f"even T{turn}: lethal prep"))
    targets.append(_t(2, {"self_field_power_ge": _expected_field_power(turn) - 2000}, 1000, "fallback"))
    return targets


def _entry_importance(turn: int, cond: str) -> float:
    """戦略的重要度 (= turn 7-10 lethal 段階 が 最重要)。"""
    if turn >= 8:
        return 1.3
    if turn >= 6:
        return 1.1
    if turn >= 3:
        return 1.0
    return 0.8  # T1-2 は 序盤、 重要度 低


def generate_target_spec_for_deck(slug: str) -> dict:
    """1 deck の deck-aware target_v1.json を 生成。"""
    props = _extract_deck_props(slug)
    leader_id = props["leader_id"]
    entries = []

    # T1 は even のみ
    entries.append({
        "turn": 1,
        "opp_leader_id": leader_id,
        "opp_deck_slug": slug,
        "opp_archetype": props["archetype"][:8],
        "self_condition": "even",
        "importance": _entry_importance(1, "even"),
        "targets": build_targets(1, "even", props),
    })

    # T2-10 × 3 conditions = 27 entries
    for turn in range(2, 11):
        for cond in ("even", "behind", "advantage"):
            entries.append({
                "turn": turn,
                "opp_leader_id": leader_id,
                "opp_deck_slug": slug,
                "opp_archetype": props["archetype"][:8],
                "self_condition": cond,
                "importance": _entry_importance(turn, cond),
                "targets": build_targets(turn, cond, props),
            })

    return {
        "deck_slug": slug,
        "leader_id": leader_id,
        "archetype": props["archetype"],
        "synergy_feature": props["synergy_feature"],
        "finisher_cost": props["finisher_cost"],
        "blocker_scarce": props["blocker_scarce"],
        "generated_by": "Plan H generate_deck_aware_target_specs.py v2 (= analysis-driven)",
        "model": "claude-opus-4-7 + deck-aware generator",
        "entries": entries,
    }


def main() -> None:
    slugs = [
        "cardrush_1342", "cardrush_1385", "cardrush_1392", "cardrush_1399",
        "cardrush_1439", "cardrush_1453", "cardrush_1454", "cardrush_1455",
        "tcgportal_bonney", "tcgportal_calgara", "tcgportal_coby",
        "tcgportal_corazon", "tcgportal_hancock",
        "tcgportal_op11_luffy", "tcgportal_op13_luffy",
    ]
    for slug in slugs:
        spec = generate_target_spec_for_deck(slug)
        out_path = DECKS_DIR / f"{slug}.target_v1.json"
        out_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        props = _extract_deck_props(slug)
        feat = props["synergy_feature"]
        fc = props["finisher_cost"]
        print(f"  {slug:30s} feat={feat:<20s} fin_cost={fc} entries={len(spec['entries'])}")
    print(f"\nwrote {len(slugs)} deck-aware target_v1.json files")


if __name__ == "__main__":
    main()
