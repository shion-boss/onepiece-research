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
    """戻り値: (leader_id → deck_slug, deck_slug → archetype, deck_slug → leader_id)。"""
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
        # archetype from .analysis.json
        ana_path = decks_dir / f"{slug}.analysis.json"
        if ana_path.exists():
            try:
                ana = json.loads(ana_path.read_text(encoding="utf-8"))
                deck_to_archetype[slug] = ana.get("archetype", "midrange")
            except Exception:
                deck_to_archetype[slug] = "midrange"
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


def _self_condition(actor_life_bucket: str, target_life_bucket: str,
                    actor_field_bucket: str, target_field_bucket: str) -> str:
    """corpus 軸 → v1 schema の self_condition (= advantage/even/behind) に 写像。"""
    life_order = {"dead": 0, "lethal": 1, "low": 2, "mid": 3, "full": 4}
    al = life_order.get(actor_life_bucket, 3)
    tl = life_order.get(target_life_bucket, 3)
    field_order = {"empty": 0, "mid": 1, "full": 2}
    af = field_order.get(actor_field_bucket, 1)
    tf = field_order.get(target_field_bucket, 1)
    score = (al - tl) + (af - tf)
    if score >= 2:
        return "advantage"
    if score <= -2:
        return "behind"
    return "even"


# ===========================================================================
# action → if 条件 (= 雑 だが 「最低 限 実行 可能」 を 保証)
# ===========================================================================


def derive_if_condition(action_kind: str, card_id: str | None) -> dict:
    """action 種別 から 雑 if 条件 を 生成。 V1 は シンプル。"""
    if action_kind == "PlayCharacter":
        return {"self_hand_ge": 1}
    if action_kind == "PlayEvent":
        return {"self_hand_ge": 1}
    if action_kind == "PlayStage":
        return {"self_hand_ge": 1}
    if action_kind == "AttachDonToLeader":
        return {}  # always feasible if don active >= 1 (= 自動 filter)
    if action_kind == "AttachDonToCharacter":
        return {"self_chara_count_ge": 1}
    if action_kind == "ActivateMain":
        return {"self_chara_count_ge": 1}
    if action_kind == "AttackLeader":
        return {}  # leader attack も 可
    if action_kind == "AttackCharacter":
        return {}
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

            # v1 axes (= side actor 視点)
            turn = sb.get("turn_number", 0)
            actor_life_b = _life_bucket(actor_p.get("life_count", 0))
            target_life_b = _life_bucket(opp_p.get("life_count", 0))
            actor_field_b = _field_bucket(actor_p.get("field_count", 0))
            target_field_b = _field_bucket(opp_p.get("field_count", 0))
            self_cond = _self_condition(actor_life_b, target_life_b,
                                         actor_field_b, target_field_b)
            opp_archetype = "midrange"
            opp_deck = leader_to_deck.get(opp_leader)
            if opp_deck:
                opp_archetype = deck_to_archetype.get(opp_deck, "midrange")

            v1_key = (turn, opp_leader, opp_archetype, self_cond)
            action_dict = action.get("action", {})
            action_key = (action_dict.get("kind", "?"), action_dict.get("card_id"))
            if action_key[0] == "EndPhase":
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
) -> dict[str, list[dict]]:
    """deck_slug → entries list。"""
    stats = scan_result["stats"]
    # 集約: (deck_slug, v1_key) → list of {action_key, win_rate, n_total, bonus}
    by_entry: dict[tuple, list[dict]] = defaultdict(list)
    for (deck_slug, v1_key, action_key), s in stats.items():
        if s["n_total"] < min_count:
            continue
        win_rate = s["n_won"] / s["n_total"]
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
        turn, opp_leader, opp_archetype, self_cond = v1_key
        # opp_deck_slug from leader_to_deck
        opp_deck = scan_result["leader_to_deck"].get(opp_leader)
        deck_to_entries[deck_slug].append({
            "turn": turn,
            "opp_leader_id": opp_leader,
            "opp_deck_slug": opp_deck,
            "opp_archetype": opp_archetype,
            "self_condition": self_cond,
            "targets": targets,
        })

    # entry を turn → opp_leader → self_cond 順 で sort
    for slug in deck_to_entries:
        deck_to_entries[slug].sort(key=lambda e: (
            e["turn"], e["opp_leader_id"], e["self_condition"],
        ))
    return deck_to_entries


def write_specs(deck_to_entries: dict[str, list[dict]], output_dir: Path,
                scan_result: dict, args_summary: dict) -> int:
    """各 deck の spec を 上書き。 戻り値: 書いた deck 数。"""
    leader_to_deck = scan_result["leader_to_deck"]
    deck_to_archetype = scan_result["deck_to_archetype"]
    # deck_to_leader 逆引き
    deck_to_leader = {v: k for k, v in leader_to_deck.items()}

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
