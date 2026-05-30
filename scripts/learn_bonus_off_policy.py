#!/usr/bin/env python3
"""off-policy bonus 学習 (= 2026-05-29、 task #48)。

corpus から **side A (= GoalDirectedAI) の (state, action) tuple** を 抽出 →
勝率 集計 → bonus テーブル 出力。

[[feedback_corpus_methodology]]: corpus は raw、 ここ は derived/。
ohtsuki さん 提案 (= 2026-05-29 sess): 学習 時 behavior policy ≠ target policy。
これ で argmax 不変 trap を 構造 的 に 解消。

## アルゴリズム

1. corpus 全 試合 を scan
2. side A の 各 action (= 我々 が 学ぶ 視点) を 抽出
3. (state_axes, action_key) cluster → 勝率 集計
4. bonus = baseline × (win_rate / 0.5) ^ scale で 一括 算出
5. 出力 = db/derived/bonus_learning/<round>/value_table.json

V1 は **生 統計 のみ 出力** (= spec への 自動 マージ は しない、 手動 レビュー)。
V2 で spec に append する logic 追加 予定。

## 使い方

```bash
.venv/bin/python -u scripts/learn_bonus_off_policy.py \\
    --corpus-dir db/game_corpus/round_1_quick \\
    --min-count 5 \\
    --baseline 1500 \\
    --scale 2.0
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
# 軸 抽出 (= mining script と 共有 logic、 重複 だが V1 シンプル 化 優先)
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


def _threat_bucket(player_state: dict) -> str:
    active = player_state.get("field_active_count", 0)
    don_a = player_state.get("don_active", 0)
    score = active * 2 + don_a
    if score <= 1:
        return "low"
    if score <= 5:
        return "mid"
    return "high"


def extract_axes(state_features: dict, actor_idx: int, target_idx: int) -> tuple:
    actor = state_features["players"][actor_idx]
    target = state_features["players"][target_idx]
    return (
        state_features["turn_number"],
        actor["leader"]["card_id"],
        target["leader"]["card_id"],
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


def action_to_key(action_dict: dict) -> tuple:
    return (
        action_dict.get("kind", "?"),
        action_dict.get("card_id"),
    )


def _resolve_side_idx(game: dict) -> tuple[int, int]:
    fp = game.get("first_player", 0)
    return (0, 1) if fp == 0 else (1, 0)


# ===========================================================================
# core: corpus → (axes, action) 別 勝率 + bonus テーブル
# ===========================================================================


def learn_bonus(
    corpus_dir: Path,
    min_count: int = 5,
    baseline: float = 1500.0,
    scale: float = 2.0,
    target_side: str = "a",
) -> tuple[dict, list[dict]]:
    """target_side = 'a' (= side A = GoalDirectedAI 視点)。
    'b' で opp 視点 (= adversarial mining と 重複 部分 あり)。 default 'a'。
    """
    # (axes, action_key) → {n_total, n_won_for_target_side}
    stats: dict[tuple, dict[str, int]] = defaultdict(lambda: {"n_total": 0, "n_won": 0})
    n_games = 0
    n_actions = 0

    for game_path in sorted(corpus_dir.rglob("game_*.json")):
        try:
            game = json.loads(game_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        n_games += 1
        winner_for_a = (game.get("result") or {}).get("winner_for_deck_a", -1)
        if winner_for_a == -1:
            continue  # draw / unknown は 集計 から 除外

        side_a_idx, side_b_idx = _resolve_side_idx(game)
        if target_side == "a":
            actor_idx = side_a_idx
            opp_idx = side_b_idx
            actor_won = (winner_for_a == 0)
        else:
            actor_idx = side_b_idx
            opp_idx = side_a_idx
            actor_won = (winner_for_a == 1)

        for action in game.get("actions", []):
            if action.get("active_player") != actor_idx:
                continue
            sb = action.get("state_before") or {}
            try:
                axes = extract_axes(sb, actor_idx, opp_idx)
            except Exception:
                continue
            action_key = action_to_key(action.get("action", {}))
            key = (axes, action_key)
            stats[key]["n_total"] += 1
            if actor_won:
                stats[key]["n_won"] += 1
            n_actions += 1

    # min_count で 足切り + bonus 計算
    entries = []
    for (axes, action_key), s in stats.items():
        if s["n_total"] < min_count:
            continue
        win_rate = s["n_won"] / s["n_total"]
        # bonus = baseline × (win_rate / 0.5) ^ scale
        ratio = max(win_rate, 0.05) / 0.5  # 下限 5% で 0 を 避ける
        bonus = round(baseline * (ratio ** scale))
        entries.append({
            "axes": axes_to_dict(axes),
            "action_kind": action_key[0],
            "action_card_id": action_key[1],
            "n_total": s["n_total"],
            "n_won": s["n_won"],
            "win_rate": round(win_rate, 3),
            "bonus": bonus,
        })

    # win_rate × n_total で sort (= 効果 大 + 信頼 度 高 の 順)
    entries.sort(key=lambda e: -(e["win_rate"] - 0.5) * (e["n_total"] ** 0.5))

    meta = {
        "n_games_scanned": n_games,
        "n_actions_extracted": n_actions,
        "n_unique_clusters": len(stats),
        "n_above_threshold": len(entries),
        "min_count_threshold": min_count,
        "baseline_bonus": baseline,
        "scale": scale,
        "target_side": target_side,
    }
    return meta, entries


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus-dir", type=Path, required=True)
    ap.add_argument("--min-count", type=int, default=5,
                    help="cluster 最小 sample 数 (= 統計 信頼 閾値)")
    ap.add_argument("--baseline", type=float, default=1500.0,
                    help="bonus baseline 値 (= win_rate=0.5 で この 値)")
    ap.add_argument("--scale", type=float, default=2.0,
                    help="win_rate^scale で bonus 計算 (= 大 で 強調)")
    ap.add_argument("--target-side", choices=["a", "b"], default="a",
                    help="どちら の side の 視点 で 集計 する か (= a = GoalDirectedAI 視点)")
    ap.add_argument("--output", type=Path, default=None)
    ap.add_argument("--top", type=int, default=30,
                    help="表示 する 上位 / 下位 件数")
    args = ap.parse_args()

    if not args.corpus_dir.is_dir():
        print(f"ERROR: corpus dir not found: {args.corpus_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"[bonus] scanning corpus: {args.corpus_dir}", flush=True)
    meta, entries = learn_bonus(
        args.corpus_dir,
        min_count=args.min_count,
        baseline=args.baseline,
        scale=args.scale,
        target_side=args.target_side,
    )
    print(f"[bonus] games scanned: {meta['n_games_scanned']:,}")
    print(f"[bonus] {args.target_side}-side actions extracted: {meta['n_actions_extracted']:,}")
    print(f"[bonus] unique clusters: {meta['n_unique_clusters']:,}")
    print(f"[bonus] above threshold (n>={args.min_count}): {meta['n_above_threshold']:,}")
    print()

    if args.output is None:
        round_name = args.corpus_dir.name
        args.output = REPO_ROOT / "db" / "derived" / "bonus_learning" / round_name / "value_table.json"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"meta": meta, "entries": entries}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[bonus] output: {args.output.relative_to(REPO_ROOT)}")
    print()

    if entries:
        print(f"=== top {min(args.top, len(entries))} (= 高 win_rate × 高 信頼 度) ===")
        for i, e in enumerate(entries[:args.top]):
            ax = e["axes"]
            print(f"  [{i+1:3d}] T{ax['turn']:2d} {ax['actor_leader_id']:9s} vs {ax['target_leader_id']:9s} "
                  f"L{ax['actor_life_bucket']:5s}/{ax['target_life_bucket']:5s} "
                  f"F{ax['actor_field_bucket']:5s}/{ax['target_field_bucket']:5s}  "
                  f"→ {e['action_kind']:16s} {e['action_card_id'] or '':10s} "
                  f"n={e['n_total']} wr={e['win_rate']:.0%} bonus={e['bonus']:5d}")

        # 下位 (= 負け 行動) も 確認
        print()
        print(f"=== bottom {min(args.top, len(entries))} (= 負け 多い 行動) ===")
        for i, e in enumerate(entries[-args.top:][::-1]):
            ax = e["axes"]
            print(f"  [{i+1:3d}] T{ax['turn']:2d} {ax['actor_leader_id']:9s} vs {ax['target_leader_id']:9s} "
                  f"L{ax['actor_life_bucket']:5s}/{ax['target_life_bucket']:5s} "
                  f"F{ax['actor_field_bucket']:5s}/{ax['target_field_bucket']:5s}  "
                  f"→ {e['action_kind']:16s} {e['action_card_id'] or '':10s} "
                  f"n={e['n_total']} wr={e['win_rate']:.0%} bonus={e['bonus']:5d}")


if __name__ == "__main__":
    main()
