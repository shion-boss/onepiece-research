#!/usr/bin/env python3
"""corpus → target_v1.json spec 生成 (= 2026-05-29、 task #49 続)。

mining (= adversarial entries) + bonus learning (= 勝率 → bonus) の 結果 を
**統合 して GoalDirectedAI が 読める v1 schema** に 変換、 decks/<slug>.target_v1.json を 上書き。

[[feedback_corpus_methodology]]: corpus は raw、 ここ は derived/。
[[feedback_adversarial_entry_mining]]: opp 勝利 行動 を 入れる。

## アルゴリズム

1. corpus 内 の 全 行動 から (axes, action, won) tuple を 抽出
2. side A (= 自分 視点) + side B (= 対戦 相手 視点) 両方 集計
3. 各 actor_leader_id ごとに entries 構築:
   - axes key = (turn, opp_leader_id, self_condition) (= v1 互換)
   - 同 key 内 で action 別 集計 (= win_rate × n_total)
   - 上位 action を target 化 (priority 順)
4. bonus = baseline × (win_rate / 0.5) ^ scale、 clamp [250, 3000]
5. 出力 = decks/<slug>.target_v1.json (= 既存 上書き)

## 使い方

```bash
.venv/bin/python -u scripts/build_spec_from_corpus.py \\
    --corpus-dir db/game_corpus/round_1_quick \\
    --output-dir decks/ \\
    --min-count 5 --baseline 1500 --scale 2.0
```
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


# ===========================================================================
# leader → deck_slug + archetype mapping (= 起動 時 1 回 build)
# ===========================================================================


def build_leader_maps() -> tuple[dict, dict, dict]:
    """戻り値: (leader_id → deck_slug, deck_slug → archetype_EN, deck_slug → leader_id)。

    archetype は analysis.json の JP を EN 正規 化 (= 'コントロール' → 'control' 等)、
    既存 target_v1 spec の EN 表記 と 整合 を 取る。
    """
    leader_to_deck = {}
    deck_to_leader = {}
    deck_to_archetype = {}
    decks_dir = REPO_ROOT / "decks"
    for p in sorted(decks_dir.glob("*.json")):
        name = p.name
        if ".target" in name or ".analysis" in name or "_archive" in str(p):
            continue
        slug = p.stem
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        leader = d.get("leader") or d.get("leader_id")
        if isinstance(leader, dict):
            leader = leader.get("id") or leader.get("card_id")
        if leader:
            leader_to_deck[leader] = slug
            deck_to_leader[slug] = leader
        # archetype from .analysis.json (= JP) → EN 正規 化
        ana_path = decks_dir / f"{slug}.analysis.json"
        raw_arch = "midrange"
        if ana_path.exists():
            try:
                ana = json.loads(ana_path.read_text(encoding="utf-8"))
                raw_arch = ana.get("archetype", "midrange")
            except Exception:
                pass
        deck_to_archetype[slug] = _normalize_archetype(raw_arch)
    return leader_to_deck, deck_to_archetype, deck_to_leader


# ===========================================================================
# 軸 抽出 (= mining script と 共有 ロジック)
# ===========================================================================


def _life_bucket(n: int) -> str:
    if n <= 0:
        return "dead"
    if n == 1:
        return "lethal"
    if n <= 2:
        return "low"
    if n <= 3:
        return "mid"
    return "full"


def _field_bucket(n: int) -> str:
    if n == 0:
        return "empty"
    if n <= 2:
        return "mid"
    return "full"


def _self_condition_from_snapshot(actor: dict, target: dict) -> str:
    """engine/target_dsl.py:compute_self_condition と **完全 同 logic** で 計算。

    score = (me_life - opp_life) * 2 + (me_field - opp_field) + hand_diff_sign
    threshold: ±3 (= 公式 engine 仕様)

    snapshot 値 を 使う が、 出力 は engine と 同じ {"advantage","even","behind"}。
    """
    me_life = actor.get("life_count", 0)
    opp_life = target.get("life_count", 0)
    me_field = actor.get("field_count", 0)
    opp_field = target.get("field_count", 0)
    me_hand = actor.get("hand_count", 0)
    opp_hand = target.get("hand_count", 0)

    score = (me_life - opp_life) * 2 + (me_field - opp_field)
    hand_diff = me_hand - opp_hand
    if hand_diff >= 3:
        score += 1
    elif hand_diff <= -3:
        score -= 1

    if score >= 3:
        return "advantage"
    if score <= -3:
        return "behind"
    return "even"


# archetype: JP → EN mapping (= 既存 spec が 'midrange'/'control'/'aggro' を 使う ので 整合)
_ARCHETYPE_JP_TO_EN = {
    "コントロール": "control",
    "アグロ": "aggro",
    "ミッドレンジ": "midrange",
    "ランプ": "ramp",
    "control": "control",
    "aggro": "aggro",
    "midrange": "midrange",
    "ramp": "ramp",
}


def _normalize_archetype(arch: str | None) -> str:
    """analysis.json の JP → EN 正規 化。 未知 値 は 'midrange' fallback。"""
    if not arch:
        return "midrange"
    return _ARCHETYPE_JP_TO_EN.get(arch, "midrange")


# ===========================================================================
# action → if 条件 (= 雑 だが 「最低 限 実行 可能」 を 保証)
# ===========================================================================


def resolve_card_id(action_dict: dict, actor_p: dict) -> str | None:
    """action.hand_idx + actor.hand_card_ids → card_id 解決。

    PlayCharacter / PlayEvent / PlayStage が hand_idx を 持つ。 corpus dump で
    hand_idx は ある が card_id は ない 場合 (= 旧 round_1_quick) は ここで 解決。
    新 round_2_full は snapshot_action 側 で 既に card_id が 入って る ので fallback として 動く。
    """
    if action_dict.get("card_id"):
        return action_dict["card_id"]
    hand_idx = action_dict.get("hand_idx")
    if hand_idx is None:
        return None
    hand = actor_p.get("hand_card_ids", [])
    if 0 <= hand_idx < len(hand):
        return hand[hand_idx]
    return None


def derive_if_condition(action_kind: str, card_id: str | None) -> dict:
    """action-specific if 条件 を 生成 (= 2026-05-29 修正、 plan history を 見る)。

    plan 内 で **その action を 取った 後** だけ 真 に なる 条件 → bonus が 特定 action
    の leaf でしか 加算 されない → AI 行動 差別 化 が 機能 する。

    旧 雑 if (= self_hand_ge:1 等) は ほぼ 常 真 で 全 action leaf に bonus 加算 →
    定数 化 → bonus 効果 ゼロ という bug を 修正。
    """
    if action_kind == "PlayCharacter":
        return {"min_play_chara_this_turn_ge": 1}
    if action_kind == "PlayEvent":
        return {"min_play_event_this_turn_ge": 1}
    if action_kind == "PlayStage":
        return {"min_play_stage_this_turn_ge": 1}
    if action_kind == "AttachDonToLeader":
        return {"min_attach_don_leader_this_turn_ge": 1}
    if action_kind == "AttachDonToCharacter":
        return {"min_attach_don_chara_this_turn_ge": 1}
    if action_kind == "ActivateMain":
        return {"min_activate_main_this_turn_ge": 1}
    if action_kind == "AttackLeader":
        return {"min_leader_attacks_this_turn_ge": 1}
    if action_kind == "AttackCharacter":
        return {"min_attack_chara_this_turn_ge": 1}
    return {}


def make_description(action_kind: str, card_id: str | None, win_rate: float, n: int) -> str:
    cid = f" {card_id}" if card_id else ""
    return f"{action_kind}{cid} (= n={n}, wr={win_rate:.0%}, from corpus)"


# ===========================================================================
# corpus → クラス タリング
# ===========================================================================


def _resolve_side_idx(game: dict) -> tuple[int, int]:
    fp = game.get("first_player", 0)
    return (0, 1) if fp == 0 else (1, 0)


def scan_corpus(corpus_dir: Path) -> dict:
    """全 game scan、 (actor_deck_slug, v1_axes_key, action_key) → {n_total, n_won}。

    actor_deck_slug = 「この spec を 適用 する 視点 deck」 (= 我々 が AI に なる 側)。
    両 side を 抽出 (= side A win → side A 行動 が +、 side B win → side B 行動 が +)。
    """
    leader_to_deck, deck_to_archetype, _ = build_leader_maps()
    stats: dict[tuple, dict] = defaultdict(lambda: {"n_total": 0, "n_won": 0})
    n_games = 0
    n_actions_total = 0

    for game_path in sorted(corpus_dir.rglob("game_*.json")):
        try:
            game = json.loads(game_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        n_games += 1
        winner_for_a = (game.get("result") or {}).get("winner_for_deck_a", -1)
        if winner_for_a == -1:
            continue
        side_a_idx, side_b_idx = _resolve_side_idx(game)

        for action in game.get("actions", []):
            actor_idx = action.get("active_player")
            if actor_idx not in (0, 1):
                continue
            opp_idx = 1 - actor_idx
            sb = action.get("state_before") or {}
            players = sb.get("players")
            if not players or len(players) != 2:
                continue
            actor_p = players[actor_idx]
            opp_p = players[opp_idx]

            actor_leader = actor_p.get("leader", {}).get("card_id")
            opp_leader = opp_p.get("leader", {}).get("card_id")
            if not actor_leader or not opp_leader:
                continue

            actor_deck = leader_to_deck.get(actor_leader)
            if not actor_deck:
                continue  # 我々 が 管理 しない deck

            # v1 axes (= side actor 視点、 engine と 完全 同 logic で 計算)
            turn = sb.get("turn_number", 0)
            self_cond = _self_condition_from_snapshot(actor_p, opp_p)
            opp_deck = leader_to_deck.get(opp_leader)
            opp_archetype = _normalize_archetype(
                deck_to_archetype.get(opp_deck) if opp_deck else None
            )

            # === rich axes (= 2026-05-30 拡 張、 [[project_corpus_methodology_dead_end]] 後) ===
            from engine.axis_compute import compute_axes_from_snapshot
            rich_axes = compute_axes_from_snapshot(sb, side_b_idx, side_a_idx, opp_archetype) \
                if action.get("active_player") == side_b_idx else \
                compute_axes_from_snapshot(sb, side_a_idx, side_b_idx, opp_archetype)
            # 注: 上 は side B 視 点 と side A 視 点 で 軸 が opp_/self_ 逆 転 する
            # actor_idx と target_idx の 関 係 で 計 算 必 要
            from engine.axis_compute import compute_axes_from_snapshot as _ax
            # actor の view (= 我々 spec 主)、 opp は target
            actor_idx_for_axes = action.get("active_player", 0)
            target_idx_for_axes = 1 - actor_idx_for_axes
            rich_axes = _ax(sb, actor_idx_for_axes, target_idx_for_axes, opp_archetype)

            # === v2 axes (= 2026-05-30 拡 張): rich 12 軸 で entry 細 分 化 ===
            # 旧 v1 = (turn, opp_leader, opp_archetype, self_cond) の 4 軸
            # 新 v2 = + opp_life/hand/field/threat + self_life/hand/field/don の 12 軸
            # rich_axes は 既 上 で 計 算 済 み
            v2_key = (
                turn, opp_leader, opp_archetype, self_cond,
                rich_axes.get("opp_life_bucket", "full"),
                rich_axes.get("opp_hand_bucket", "mid"),
                rich_axes.get("opp_field_bucket", "empty"),
                rich_axes.get("opp_threat_bucket", "low"),
                rich_axes.get("self_life_bucket", "full"),
                rich_axes.get("self_hand_bucket", "mid"),
                rich_axes.get("self_field_bucket", "empty"),
                rich_axes.get("self_don_bucket", "tight"),
            )
            v1_key = v2_key  # build_specs 後 段 と 整 合
            action_dict = action.get("action", {})
            action_kind = action_dict.get("kind", "?")
            # card_id 解決 (= hand_idx → actor の hand_card_ids、 旧 corpus 互換)
            card_id = resolve_card_id(action_dict, actor_p)
            action_key = (action_kind, card_id)
            if action_kind == "EndPhase":
                continue  # 「何 も しない」 は target に しない

            full_key = (actor_deck, v1_key, action_key)
            stats[full_key]["n_total"] += 1
            # 勝敗: actor が 勝った か
            actor_won = (actor_idx == side_a_idx and winner_for_a == 0) or \
                        (actor_idx == side_b_idx and winner_for_a == 1)
            if actor_won:
                stats[full_key]["n_won"] += 1
            n_actions_total += 1

    return {
        "stats": stats,
        "n_games": n_games,
        "n_actions": n_actions_total,
        "leader_to_deck": leader_to_deck,
        "deck_to_archetype": deck_to_archetype,
    }


# ===========================================================================
# 集計 → spec 構築
# ===========================================================================


def build_specs(
    scan_result: dict,
    min_count: int,
    baseline: float,
    scale: float,
    max_targets_per_entry: int,
    bonus_clamp_min: int,
    bonus_clamp_max: int,
    tier3_min_opp_count: int = 8,
    tier3_min_winrate: float = 0.5,
    tier3_baseline_factor: float = 0.5,
    min_winrate: float = 0.0,
) -> dict[str, list[dict]]:
    """deck_slug → entries list (= Tier 1 + Tier 3)。

    Tier 1: (deck_slug, turn, opp_leader, opp_archetype, self_cond) per cell。
    Tier 3: (deck_slug, turn, self_cond) per cell、 cross-opp consistency 高 action のみ。

    Tier 3 condition: action が **≥ tier3_min_opp_count 個 の 異 opp_leader** で
                       win_rate ≥ tier3_min_winrate (= 50%) を 達成 (= 「自 deck 強み」 sign)。
                       bonus は tier3_baseline_factor (= 0.5) で 下げる (= Tier 1 より 弱)。
    """
    stats = scan_result["stats"]
    # 集約: (deck_slug, v1_key) → list of {action_key, win_rate, n_total, bonus}
    by_entry: dict[tuple, list[dict]] = defaultdict(list)
    for (deck_slug, v1_key, action_key), s in stats.items():
        if s["n_total"] < min_count:
            continue
        win_rate = s["n_won"] / s["n_total"]
        if win_rate < min_winrate:
            continue  # 敗 北 action の spec 化 を 防 ぐ (= 2026-05-30)
        ratio = max(win_rate, 0.05) / 0.5
        bonus = round(baseline * (ratio ** scale))
        bonus = max(bonus_clamp_min, min(bonus_clamp_max, bonus))
        by_entry[(deck_slug, v1_key)].append({
            "action_kind": action_key[0],
            "action_card_id": action_key[1],
            "n_total": s["n_total"],
            "n_won": s["n_won"],
            "win_rate": round(win_rate, 3),
            "bonus": bonus,
        })

    # spec 構築
    deck_to_entries: dict[str, list[dict]] = defaultdict(list)
    for (deck_slug, v1_key), actions in by_entry.items():
        # bonus desc 順 で sort
        actions.sort(key=lambda x: -x["bonus"])
        targets = []
        for i, a in enumerate(actions[:max_targets_per_entry]):
            targets.append({
                "priority": i + 1,
                "if": derive_if_condition(a["action_kind"], a["action_card_id"]),
                "bonus": a["bonus"],
                "description": make_description(
                    a["action_kind"], a["action_card_id"], a["win_rate"], a["n_total"],
                ),
                "source": "corpus_off_policy_v1",
                "evidence": {"n_total": a["n_total"], "win_rate": a["win_rate"]},
            })
        # v2_key 形 式: (turn, opp_leader, opp_archetype, self_cond,
        #               opp_life_b, opp_hand_b, opp_field_b, opp_threat_b,
        #               self_life_b, self_hand_b, self_field_b, self_don_b)
        (turn, opp_leader, opp_archetype, self_cond,
         opp_life_b, opp_hand_b, opp_field_b, opp_threat_b,
         self_life_b, self_hand_b, self_field_b, self_don_b) = v1_key
        # opp_deck_slug from leader_to_deck
        opp_deck = scan_result["leader_to_deck"].get(opp_leader)
        deck_to_entries[deck_slug].append({
            "turn": turn,
            # === v2 rich axes ===
            "opp_life_bucket": opp_life_b,
            "opp_hand_bucket": opp_hand_b,
            "opp_field_bucket": opp_field_b,
            "opp_threat_bucket": opp_threat_b,
            "self_life_bucket": self_life_b,
            "self_hand_bucket": self_hand_b,
            "self_field_bucket": self_field_b,
            "self_don_bucket": self_don_b,
            # === v1 互 換 軸 ===
            "opp_leader_id": opp_leader,
            "opp_deck_slug": opp_deck,
            "opp_archetype": opp_archetype,
            "self_condition": self_cond,
            "targets": targets,
        })

    # === Tier 3 entries (= 自 deck 強み fallback、 [[feedback_tier_strategy]]) ===
    # 各 (deck_slug, turn, self_cond) で、 異 opp_leader 間 を 横断 集計 して
    # consistency 高い action のみ 採用。
    # tier1_stats[(deck, turn, self_cond, action_key)][opp_leader] = (n_total, n_won)
    tier1_by_action: dict[tuple, dict] = defaultdict(lambda: {"per_opp": {}})
    for (deck_slug, v1_key, action_key), s in stats.items():
        if s["n_total"] < min_count:
            continue
        # v1_key は 今 v2 形 式 (= 12 要 素)、 turn と self_cond だけ 抽 出
        turn = v1_key[0]
        opp_leader = v1_key[1]
        self_cond = v1_key[3]
        key3 = (deck_slug, turn, self_cond, action_key)
        wr = s["n_won"] / s["n_total"]
        tier1_by_action[key3]["per_opp"][opp_leader] = (s["n_total"], s["n_won"], wr)

    tier3_entries_by_deck: dict[str, dict[tuple, list[dict]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for (deck_slug, turn, self_cond, action_key), info in tier1_by_action.items():
        per_opp = info["per_opp"]
        # consistency: win_rate >= tier3_min_winrate を 達成 した opp_leader 数
        consistent_opps = [
            (opp, n, w, wr) for opp, (n, w, wr) in per_opp.items()
            if wr >= tier3_min_winrate
        ]
        if len(consistent_opps) < tier3_min_opp_count:
            continue  # consistency 不足 → 「deck 強み」 と は 言えない
        # cross-opp 集計
        total_n = sum(n for _, n, _, _ in consistent_opps)
        total_w = sum(w for _, _, w, _ in consistent_opps)
        if total_n < min_count:
            continue
        cross_wr = total_w / total_n
        ratio = max(cross_wr, 0.05) / 0.5
        bonus = round(baseline * tier3_baseline_factor * (ratio ** scale))
        bonus = max(bonus_clamp_min, min(bonus_clamp_max, bonus))
        tier3_entries_by_deck[deck_slug][(turn, self_cond)].append({
            "action_kind": action_key[0],
            "action_card_id": action_key[1],
            "n_total": total_n,
            "n_won": total_w,
            "win_rate": round(cross_wr, 3),
            "bonus": bonus,
            "consistency_opp_count": len(consistent_opps),
        })

    # Tier 3 entries を deck_to_entries に append
    for deck_slug, by_t3_key in tier3_entries_by_deck.items():
        for (turn, self_cond), actions in by_t3_key.items():
            actions.sort(key=lambda x: -x["bonus"])
            targets = []
            for i, a in enumerate(actions[:max_targets_per_entry]):
                targets.append({
                    "priority": i + 1,
                    "if": derive_if_condition(a["action_kind"], a["action_card_id"]),
                    "bonus": a["bonus"],
                    "description": (
                        f"{a['action_kind']}"
                        f"{(' ' + a['action_card_id']) if a['action_card_id'] else ''} "
                        f"(= 自 deck 強み: {a['consistency_opp_count']}/16 opp で win_rate "
                        f"≥{tier3_min_winrate:.0%}、 cross-opp wr={a['win_rate']:.0%}, "
                        f"n={a['n_total']})"
                    ),
                    "source": "corpus_off_policy_v1_tier3",
                    "evidence": {
                        "n_total": a["n_total"],
                        "win_rate": a["win_rate"],
                        "consistency_opp_count": a["consistency_opp_count"],
                    },
                })
            deck_to_entries[deck_slug].append({
                "turn": turn,
                "opp_leader_id": None,         # Tier 3: opp 不問
                "opp_deck_slug": None,
                "opp_archetype": None,
                "self_condition": self_cond,
                "targets": targets,
            })

    # entry を turn → opp_leader → self_cond 順 で sort (= None は 末尾)
    for slug in deck_to_entries:
        deck_to_entries[slug].sort(key=lambda e: (
            e["turn"], e["opp_leader_id"] or "ZZZ", e["self_condition"],
        ))
    return deck_to_entries


def write_specs(deck_to_entries: dict[str, list[dict]], output_dir: Path,
                scan_result: dict, args_summary: dict) -> int:
    """各 deck の spec を 上書き。 戻り値: 書いた deck 数。"""
    leader_to_deck = scan_result["leader_to_deck"]
    deck_to_archetype = scan_result["deck_to_archetype"]
    # deck_to_leader 逆引き
    deck_to_leader = {v: k for k, v in leader_to_deck.items()}

    output_dir.mkdir(parents=True, exist_ok=True)
    n_written = 0
    for slug, entries in deck_to_entries.items():
        if not entries:
            continue
        leader_id = deck_to_leader.get(slug, "")
        archetype = deck_to_archetype.get(slug, "midrange")
        spec = {
            "deck_slug": slug,
            "leader_id": leader_id,
            "archetype": archetype,
            "synergy_feature": None,
            "finisher_cost": None,
            "blocker_scarce": False,
            "generated_by": "build_spec_from_corpus.py",
            "model": "off-policy corpus learning (= [[feedback_corpus_methodology]])",
            "notes": (
                f"corpus={args_summary.get('corpus_dir')}, "
                f"min_count={args_summary.get('min_count')}, "
                f"baseline={args_summary.get('baseline')}, "
                f"scale={args_summary.get('scale')}"
            ),
            "entries": entries,
        }
        out_path = output_dir / f"{slug}.target_v1.json"
        out_path.write_text(
            json.dumps(spec, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        n_written += 1
    return n_written


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus-dir", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, default=REPO_ROOT / "decks")
    ap.add_argument("--min-count", type=int, default=5)
    ap.add_argument("--baseline", type=float, default=1500.0)
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--max-targets-per-entry", type=int, default=4)
    ap.add_argument("--bonus-clamp-min", type=int, default=250)
    ap.add_argument("--bonus-clamp-max", type=int, default=3000)
    ap.add_argument("--min-winrate", type=float, default=0.0,
                    help="(state, action) の win_rate が この 値 未満 なら entry に 入れない (= 敗 北 行 動 除外)")
    ap.add_argument("--tier3-min-opp-count", type=int, default=8,
                    help="Tier 3 採用 閾値: action が 何 個 の opp_leader で 過半勝率 を 達成 した か")
    ap.add_argument("--tier3-min-winrate", type=float, default=0.5,
                    help="Tier 3 採用 閾値: 各 opp_leader での 最低 win_rate")
    ap.add_argument("--tier3-baseline-factor", type=float, default=0.5,
                    help="Tier 3 bonus baseline 倍率 (= Tier 1 の 何 % で 弱める か)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.corpus_dir.is_dir():
        print(f"ERROR: corpus dir not found: {args.corpus_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"[build_spec] scanning {args.corpus_dir} ...", flush=True)
    scan = scan_corpus(args.corpus_dir)
    print(f"[build_spec] games={scan['n_games']:,} actions={scan['n_actions']:,} clusters={len(scan['stats']):,}",
          flush=True)

    print(f"[build_spec] building specs (min_count={args.min_count}, baseline={args.baseline}, "
          f"scale={args.scale}, clamp=[{args.bonus_clamp_min},{args.bonus_clamp_max}]) ...",
          flush=True)
    deck_to_entries = build_specs(
        scan,
        min_count=args.min_count,
        baseline=args.baseline,
        scale=args.scale,
        max_targets_per_entry=args.max_targets_per_entry,
        bonus_clamp_min=args.bonus_clamp_min,
        bonus_clamp_max=args.bonus_clamp_max,
        tier3_min_opp_count=args.tier3_min_opp_count,
        tier3_min_winrate=args.tier3_min_winrate,
        tier3_baseline_factor=args.tier3_baseline_factor,
        min_winrate=args.min_winrate,
    )
    print(f"[build_spec] decks with entries: {len(deck_to_entries)}", flush=True)
    for slug, entries in sorted(deck_to_entries.items()):
        n_targets = sum(len(e["targets"]) for e in entries)
        print(f"  {slug:30s}: {len(entries):4d} entries / {n_targets:5d} targets", flush=True)

    if args.dry_run:
        print(f"[build_spec] DRY RUN (= no file written)", flush=True)
        return

    try:
        corpus_str = str(args.corpus_dir.resolve().relative_to(REPO_ROOT))
    except ValueError:
        corpus_str = str(args.corpus_dir)
    args_summary = {
        "corpus_dir": corpus_str,
        "min_count": args.min_count,
        "baseline": args.baseline,
        "scale": args.scale,
    }
    n_written = write_specs(deck_to_entries, args.output_dir, scan, args_summary)
    print(f"[build_spec] wrote {n_written} target_v1.json files to {args.output_dir}",
          flush=True)


if __name__ == "__main__":
    main()
