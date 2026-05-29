#!/usr/bin/env python3
"""adversarial entry mining (= 2026-05-29、 task #47)。

corpus から **対戦 相手 が 勝った 試合 の 行動 パターン** を 抽出 → 新 entry 候補 を 提案。

[[feedback_adversarial_entry_mining]]: 自分 だけ で なく opp の 勝ち から も 学ぶ、 学習 効率 2x。
[[feedback_corpus_methodology]]: corpus は raw、 ここ は derived/。

## アルゴリズム

1. corpus 全 試合 を scan
2. side B (= opp) が 勝った 試合 を 抽出
3. 各 opp 行動 から (state_axes, action) tuple 抽出
   - state_axes = (turn, actor_leader, target_leader, life buckets, field buckets, did_mulligan)
4. 軸 tuple ごと に 行動 を 集計 + AI 種別 重み (= PlanningAI 3, mirror 2, Greedy 1, Random 0.5)
5. min_count 以上 の cluster を 候補 entry として output

出力 = db/derived/adversarial_entries/<round>/candidates.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# AI 品質 重み (= [[feedback_adversarial_entry_mining]])
AI_QUALITY_WEIGHTS = {
    "PlanningAI": 3.0,
    "MCTSAI": 3.0,
    "GoalDirectedAI": 2.0,  # mirror
    "GreedyAI": 1.0,
    "RandomAI": 0.3,
}


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


def _threat_bucket(player_state: dict) -> str:
    """active chara の 攻撃 圧 を 3 段 で 評価。"""
    active = player_state.get("field_active_count", 0)
    don_a = player_state.get("don_active", 0)
    score = active * 2 + don_a
    if score <= 1:
        return "low"
    if score <= 5:
        return "mid"
    return "high"


def extract_axes(state_features: dict, actor_idx: int, target_idx: int) -> tuple:
    """actor (= 行動 する 側) の 視点 で 軸 値 を 抽出。 hash 化 用 に tuple で 返す。"""
    actor = state_features["players"][actor_idx]
    target = state_features["players"][target_idx]
    return (
        state_features["turn_number"],
        actor["leader"]["card_id"],         # = actor の leader (= 我々 が 学ぶ 視点)
        target["leader"]["card_id"],        # = target の leader (= 対戦 相手)
        _life_bucket(actor["life_count"]),
        _life_bucket(target["life_count"]),
        _field_bucket(actor.get("field_count", 0)),
        _field_bucket(target.get("field_count", 0)),
        _threat_bucket(actor),
        _threat_bucket(target),
        actor.get("did_mulligan", False),
        target.get("did_mulligan", False),
    )


def axes_to_dict(axes_tuple: tuple) -> dict:
    """tuple → 読みやすい dict 化 (= 候補 JSON 用)。"""
    return {
        "turn": axes_tuple[0],
        "actor_leader_id": axes_tuple[1],
        "target_leader_id": axes_tuple[2],
        "actor_life_bucket": axes_tuple[3],
        "target_life_bucket": axes_tuple[4],
        "actor_field_bucket": axes_tuple[5],
        "target_field_bucket": axes_tuple[6],
        "actor_threat_bucket": axes_tuple[7],
        "target_threat_bucket": axes_tuple[8],
        "actor_did_mulligan": axes_tuple[9],
        "target_did_mulligan": axes_tuple[10],
    }


def resolve_card_id(action_dict: dict, actor_p: dict) -> str | None:
    """hand_idx → card_id 解決 (= 新 corpus は dump 済、 旧 round_1_quick 互換 fallback)。"""
    if action_dict.get("card_id"):
        return action_dict["card_id"]
    hand_idx = action_dict.get("hand_idx")
    if hand_idx is None:
        return None
    hand = actor_p.get("hand_card_ids", [])
    if 0 <= hand_idx < len(hand):
        return hand[hand_idx]
    return None


def action_to_key(action_dict: dict, actor_p: dict | None = None) -> tuple:
    """action JSON → hashable key (= 集計 用、 card_id 解決 込み)。"""
    card_id = action_dict.get("card_id")
    if not card_id and actor_p is not None:
        card_id = resolve_card_id(action_dict, actor_p)
    return (
        action_dict.get("kind", "?"),
        card_id,
        action_dict.get("hand_idx"),  # = 旧 from_idx よりも 一般 的、 PlayCharacter/Event/Stage 共通
    )


def _resolve_side_idx(game: dict) -> tuple[int, int]:
    """game.first_player から (side_a_idx, side_b_idx) を 返す。
    first_player=0 → players[0]=deck_a (side A)、 first_player=1 → players[0]=deck_b。
    """
    fp = game.get("first_player", 0)
    if fp == 0:
        return 0, 1  # side_a=0, side_b=1
    else:
        return 1, 0


def mine_corpus(corpus_dir: Path, min_count: int = 5) -> list[dict]:
    """corpus 全 試合 → adversarial 軸 候補 cluster の list。"""
    # state_axes → list of (action_key, weight, opp_ai_class)
    clusters: dict[tuple, list] = defaultdict(list)
    # 集計 meta
    n_games = 0
    n_opp_wins = 0
    n_opp_actions = 0

    for game_path in sorted(corpus_dir.rglob("game_*.json")):
        try:
            game = json.loads(game_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        n_games += 1
        winner = (game.get("result") or {}).get("winner_for_deck_a", -1)
        if winner != 1:  # side B が 勝った 試合 のみ
            continue
        n_opp_wins += 1

        side_a_idx, side_b_idx = _resolve_side_idx(game)
        opp_ai_class = (game.get("ai_versions", {}).get("b") or {}).get("class", "Unknown")
        weight = AI_QUALITY_WEIGHTS.get(opp_ai_class, 1.0)

        for action in game.get("actions", []):
            if action.get("active_player") != side_b_idx:
                continue  # side B (= opp) の 行動 のみ
            # EndPhase は 学習 対象 外 (= "何 も しない" は 既存 fallback で OK)
            if action.get("action", {}).get("kind") == "EndPhase":
                continue
            sb = action.get("state_before") or {}
            try:
                axes = extract_axes(sb, side_b_idx, side_a_idx)
            except Exception:
                continue
            # actor (= side B) の 視点 で card_id 解決
            actor_p = (sb.get("players") or [{}, {}])[side_b_idx]
            action_key = action_to_key(action.get("action", {}), actor_p)
            clusters[axes].append((action_key, weight, opp_ai_class))
            n_opp_actions += 1

    # min_count 以上 の cluster を 候補 化
    candidates = []
    for axes, action_list in clusters.items():
        if len(action_list) < min_count:
            continue
        # action 集計 (= 重み 込み)
        action_weights: Counter = Counter()
        action_counts: Counter = Counter()
        ai_breakdown: Counter = Counter()
        for action_key, weight, ai_class in action_list:
            action_weights[action_key] += weight
            action_counts[action_key] += 1
            ai_breakdown[ai_class] += 1
        # top 3 actions
        top_actions = []
        for action_key, w in action_weights.most_common(3):
            top_actions.append({
                "action_kind": action_key[0],
                "card_id": action_key[1],
                "from_idx": action_key[2],
                "weighted_count": round(w, 2),
                "raw_count": action_counts[action_key],
            })
        candidates.append({
            "axes": axes_to_dict(axes),
            "sample_count": len(action_list),
            "ai_breakdown": dict(ai_breakdown),
            "top_actions": top_actions,
        })

    # weighted_count 大 順 sort
    candidates.sort(key=lambda c: -c["top_actions"][0]["weighted_count"] if c["top_actions"] else 0)

    meta = {
        "n_games_scanned": n_games,
        "n_opp_wins": n_opp_wins,
        "n_opp_actions": n_opp_actions,
        "n_clusters_total": len(clusters),
        "n_candidates_above_threshold": len(candidates),
        "min_count_threshold": min_count,
    }
    return meta, candidates


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus-dir", type=Path, required=True,
                    help="db/game_corpus/<round_name>/")
    ap.add_argument("--min-count", type=int, default=5,
                    help="cluster の 最小 sample 数 (= 統計 信頼 閾値)")
    ap.add_argument("--output", type=Path, default=None,
                    help="出力 path (= default: db/derived/adversarial_entries/<round>/candidates.json)")
    ap.add_argument("--top", type=int, default=50,
                    help="表示 する 候補 上位 数")
    args = ap.parse_args()

    if not args.corpus_dir.is_dir():
        print(f"ERROR: corpus dir not found: {args.corpus_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"[mine] scanning corpus: {args.corpus_dir}")
    meta, candidates = mine_corpus(args.corpus_dir, min_count=args.min_count)
    print(f"[mine] games scanned: {meta['n_games_scanned']:,}")
    print(f"[mine] opp wins: {meta['n_opp_wins']:,}")
    print(f"[mine] opp actions extracted: {meta['n_opp_actions']:,}")
    print(f"[mine] clusters total: {meta['n_clusters_total']:,}")
    print(f"[mine] candidates >= {args.min_count} samples: {meta['n_candidates_above_threshold']:,}")
    print()

    if args.output is None:
        round_name = args.corpus_dir.name
        args.output = REPO_ROOT / "db" / "derived" / "adversarial_entries" / round_name / "candidates.json"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"meta": meta, "candidates": candidates}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[mine] output: {args.output.relative_to(REPO_ROOT)}")
    print()
    print(f"=== top {min(args.top, len(candidates))} candidates ===")
    for i, c in enumerate(candidates[:args.top]):
        ax = c["axes"]
        a0 = c["top_actions"][0] if c["top_actions"] else {}
        print(f"  [{i+1:3d}] T{ax['turn']:2d} {ax['actor_leader_id']:9s} vs {ax['target_leader_id']:9s} "
              f"actorL={ax['actor_life_bucket']:5s} targL={ax['target_life_bucket']:5s} "
              f"actorF={ax['actor_field_bucket']:5s} targF={ax['target_field_bucket']:5s}  "
              f"→ {a0.get('action_kind','?'):16s} {a0.get('card_id') or '':10s} "
              f"(n={c['sample_count']}, w={a0.get('weighted_count', 0):.1f})")


if __name__ == "__main__":
    main()
