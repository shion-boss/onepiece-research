"""自分のリーダー効果の「型」と「使い方 prior」を overlay から分類する artifact を作る。

相手デッキ belief モデル (opponent_deck_priors) の対称 = 自分理解 (A 軸 = own concept
piloting)。 配備 AI は「リーダー効果を beam の 1 候補手」としてしか扱わず、 いつ/どう使うと
強いかの明示知識を持たない。 これは overlay (db/card_effects.json) の DSL から機械的に
分類できる (= compute ゼロで作れる self-side prior)。

⚠ 分類が与えるのは「型」と「使い方の粗い prior」まで。 精密な "いつ" は多ターン探索 +
Claude 教師が埋める (= タイミングは play ログにしか無く、 それが無いから Claude 代役)。
この artifact は value の feature / 探索 prior / Claude 教師の context に使う土台。

出力: db/leader_effect_profiles.json   runtime: engine/leader_effect_profile.py
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_OUT_PATH = _REPO_ROOT / "db" / "leader_effect_profiles.json"

# --- when (trigger) → timing バケット (「いつ使うか」の判断があるか) --------------
_TIMING: dict[str, str] = {
    "activate_main": "active",          # プレイヤーが使う時を選ぶ = 判断あり
    "on_attack": "attack",              # アタック時に発火 = 攻撃と紐づく
    "auto_attach_to_leader": "attack",
    "on_attached_don": "attack",        # DON 付与 (=攻撃準備) に紐づく
    "opp_attack": "reactive",           # 相手アタック時 = 防御レバー
    "opp_attack_on_leader": "reactive",
    "replace_ko": "reactive",
    "replace_leave": "reactive",
    "on_life_zero": "reactive",
}
# 上記以外の on_* / end_of_turn / static / setup 系は automatic/passive 扱い
_PASSIVE_WHENS = {"static", "setup_modifier", "don_phase_modifier", "game_start"}


def _timing_of(when: str) -> str:
    if when in _TIMING:
        return _TIMING[when]
    if when in _PASSIVE_WHENS:
        return "passive"
    return "automatic"  # end_of_turn / on_self_* / on_opp_* trigger 群


# --- do primitive → role (効果の正体)。 再帰で wrapper の中身まで拾う ------------
_ROLE_MAP: dict[str, str] = {
    # card advantage / engine
    "draw": "draw_engine", "draw_per_self_hand_discarded": "draw_engine",
    "search": "draw_engine", "search_top_n": "draw_engine",
    "reveal_top_play": "draw_engine", "reveal_life_top_play": "draw_engine",
    "mill_self_top": "draw_engine", "scry_life": "draw_engine",
    "peek_opp_deck_top": "draw_engine",
    # ramp / DON acceleration
    "add_don": "ramp", "add_rested_don": "ramp",
    "attach_don": "ramp", "attach_rested_don": "ramp", "attach_active_don": "ramp",
    "untap_don": "ramp",
    # removal / disruption
    "ko": "removal", "ko_multi": "removal", "ko_all_others": "removal",
    "return_to_hand": "removal", "return_to_deck_bottom": "removal",
    "return_to_deck_bottom_multi": "removal", "rest": "removal",
    "rest_opp_don": "removal", "trash_opp_hand_random": "removal",
    "set_cannot_attack_static": "removal", "set_cannot_attack_target_cost_le": "removal",
    "mill_opp_life_to_hand": "removal", "mill_opp_life_to_trash": "removal",
    "keep_opp_rested_inplay_next_refresh": "removal",
    "keep_opp_rested_don_next_refresh": "removal",
    "disable_opp_on_play_through_opp_turn": "removal",
    "static_swords_attack_chara": "removal",
    # aggression / power / finisher (自分の attacker を強化)
    "power_pump": "aggression", "power_pump_multi": "aggression",
    "power_pump_per_target_attached_don": "aggression",
    "give_keyword": "aggression", "give_rush": "aggression",
    "give_attack_active_chara": "aggression",
    "optional_discard_hand_for_battle_buff": "aggression",
    "rest_self_don_for_battle_buff_per_don": "aggression",
    # enabler (cost 軽減) / develop (踏み倒し展開)
    "cost_minus": "enabler", "set_base_cost": "enabler",
    "set_base_cost_filtered_static": "enabler", "set_base_cost_timed": "enabler",
    "reduce_play_cost": "enabler", "reduce_play_cost_filtered_turn": "enabler",
    "reduce_play_cost_filtered_static": "enabler",
    "play_from_hand": "develop", "play_event_from_hand": "develop",
    "play_from_trash": "develop", "summon_from_deck": "develop",
    "summon_stage_from_deck_with_feature": "develop",
    # life / defense
    "life_to_hand": "life_defense", "put_top_to_life": "life_defense",
    "hand_to_self_life": "life_defense", "prevent_self_life_to_hand_turn": "life_defense",
    "untap_chara": "defense", "untap": "defense", "redirect_attack": "defense",
    # protection (KO 耐性)
    "prevent_ko": "protection", "set_ko_immune": "protection",
    "set_ko_immune_timed": "protection", "set_ko_immune_battle_only": "protection",
    # hand fixing
    "trash_self_hand_random": "hand_fix", "hand_to_deck_bottom": "hand_fix",
    "trash_to_deck": "hand_fix",
}

# role の「効果の identity」優先順 (1 effect に複数 role がある時の primary 選択)
_ROLE_PRIORITY = [
    "removal", "ramp", "draw_engine", "enabler", "develop",
    "aggression", "life_defense", "protection", "defense", "hand_fix",
]


def _deep_keys(node: Any, acc: set[str]) -> None:
    """effect の do ツリーを再帰し、 全 dict キーを集める (wrapper 内も拾う)。"""
    if isinstance(node, dict):
        for k, v in node.items():
            acc.add(k)
            _deep_keys(v, acc)
    elif isinstance(node, list):
        for x in node:
            _deep_keys(x, acc)


def _roles_of(effect: dict[str, Any]) -> list[str]:
    keys: set[str] = set()
    _deep_keys(effect.get("do"), keys)
    roles = {_ROLE_MAP[k] for k in keys if k in _ROLE_MAP}
    return [r for r in _ROLE_PRIORITY if r in roles]


def _gating_of(effect: dict[str, Any]) -> dict[str, Any]:
    cost = effect.get("cost") if isinstance(effect.get("cost"), dict) else {}
    cond = effect.get("if") if isinstance(effect.get("if"), dict) else {}
    life_gated = any("life" in k for k in cond)
    turn_gated = any("turn_number" in k for k in cond)
    hand_gated = any("hand" in k for k in cond)
    return {
        "once_per_turn": bool(cost.get("once_per_turn")),
        "pay_don": int(cost.get("pay_don", 0)) if isinstance(cost.get("pay_don"), int) else 0,
        "rest_self_don": bool(cost.get("rest_self_don")),
        "discard_hand": int(cost.get("discard_hand", 0)) if isinstance(cost.get("discard_hand"), int) else 0,
        "life_gated": life_gated,
        "turn_gated": turn_gated,
        "hand_gated": hand_gated,
    }


def _usage_pattern(timing: str, primary_role: str | None) -> str:
    """timing (主) × role (従) から使い方 prior を導く。"""
    if timing == "reactive":
        return "reactive_defense"
    if timing == "passive":
        return "passive_static"
    if timing == "automatic":
        return "automatic_trigger"
    if timing == "attack":
        return "aggression_when_attacking" if primary_role == "aggression" else "attack_trigger"
    # timing == "active" (activate_main): ここが本当の「いつ使うか」判断
    return {
        "ramp": "engine_use_often",
        "draw_engine": "engine_use_often",
        "hand_fix": "engine_use_often",
        "removal": "hold_for_threat",
        "enabler": "enabler_this_turn",
        "develop": "enabler_this_turn",
        "aggression": "tempo_aggression",
        "life_defense": "defensive_setup",
        "protection": "defensive_setup",
        "defense": "defensive_setup",
    }.get(primary_role or "", "active_other")


def _classify_effect(effect: dict[str, Any]) -> dict[str, Any]:
    when = effect.get("when", "?")
    timing = _timing_of(when)
    roles = _roles_of(effect)
    primary_role = roles[0] if roles else None
    return {
        "when": when,
        "timing": timing,
        "roles": roles,
        "primary_role": primary_role,
        "usage_pattern": _usage_pattern(timing, primary_role),
        "gating": _gating_of(effect),
        "text": effect.get("_text", ""),
    }


# active > attack > automatic > reactive > passive の順で leader-level primary を選ぶ
_TIMING_PRIORITY = {"active": 0, "attack": 1, "automatic": 2, "reactive": 3, "passive": 4}


def build() -> dict[str, Any]:
    cards = json.loads((_REPO_ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
    if isinstance(cards, dict):
        cards = cards.get("cards", [])
    leaders = {c["card_id"]: c for c in cards if c.get("category") == "LEADER"}
    overlay = json.loads((_REPO_ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))

    profiles: dict[str, Any] = {}
    usage_dist: Counter[str] = Counter()
    for lid, card in sorted(leaders.items()):
        effs = overlay.get(lid)
        if not isinstance(effs, list):
            continue
        # setup_modifier 等の純ルール変更は使い方判断に無関係なので除外
        classified = [
            _classify_effect(e)
            for e in effs
            if isinstance(e, dict)
            and e.get("when") not in ("setup_modifier", "don_phase_modifier", "game_start")
        ]
        if not classified:
            continue
        # leader-level primary = timing 優先度が最も高い (=判断が要る) effect
        primary = min(
            classified,
            key=lambda c: (_TIMING_PRIORITY.get(c["timing"], 9), _ROLE_PRIORITY.index(c["primary_role"]) if c["primary_role"] in _ROLE_PRIORITY else 99),
        )
        has_active = any(c["timing"] == "active" for c in classified)
        profiles[lid] = {
            "leader_name": card.get("name", ""),
            "color": card.get("color", ""),
            "n_effects": len(classified),
            "when_decision": has_active,          # プレイヤーが「いつ使うか」を選ぶ効果があるか
            "primary_role": primary["primary_role"],
            "primary_usage": primary["usage_pattern"],
            "effects": classified,
        }
        usage_dist[primary["usage_pattern"]] += 1

    return {
        "meta": {
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "n_leaders": len(profiles),
            "note": "leader 効果の型 + 使い方 prior。runtime=engine/leader_effect_profile.py。"
                    "精密な timing は多ターン探索/Claude 教師が埋める。",
            "usage_distribution": dict(usage_dist.most_common()),
        },
        "leaders": profiles,
    }


def main() -> None:
    data = build()
    _OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    meta = data["meta"]
    print(f"wrote {_OUT_PATH.relative_to(_REPO_ROOT)}")
    print(f"  leaders={meta['n_leaders']}")
    print("  primary_usage distribution:")
    for pat, n in meta["usage_distribution"].items():
        print(f"    {pat:24s} {n}")


if __name__ == "__main__":
    main()
