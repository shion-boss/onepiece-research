#!/usr/bin/env python3
"""Plan H snapshot 解析 ツール (= 2026-05-20)。

各 deck × game の snapshot を 読み、 first_player 補正 で GoalDirectedAI / PlanningAI
の 行動 を 正しく 抽出 → 比較。 critical turn (= 大幅 board_eval drop) を 抽出 して
Claude 教師 label 用 に 出力。

# 使い方

```bash
.venv/bin/python scripts/analyze_plan_h_snapshots.py --snapshot-dir /tmp/plan_h_snapshots_v2 --deck tcgportal_hancock
.venv/bin/python scripts/analyze_plan_h_snapshots.py --snapshot-dir /tmp/plan_h_snapshots_v2  # 全 deck summary
```

# 出力

各 deck で:
- GoalDirectedAI / PlanningAI の attack 数 / DON attach 数 / play 数 (= 行動差分)
- 負け試合 の critical turn (= board_eval drop 大、 P0 視点)
- 改善 spec 候補
"""

from __future__ import annotations

import argparse
import glob
import json
from collections import Counter, defaultdict
from pathlib import Path


def parse_meta(meta: dict, game_idx: int) -> dict:
    """meta から first_player + player_0_is_goal を 取得。 旧 snapshot は game_idx % 2 で 推定。"""
    if "first_player" in meta:
        return {
            "first_player": meta["first_player"],
            "player_0_is_goal": meta.get("player_0_is_goal", meta["first_player"] == 0),
        }
    # 旧 snapshot (= patch 前): game_idx % 2 = first_player
    fp = game_idx % 2
    return {"first_player": fp, "player_0_is_goal": (fp == 0)}


def count_actions_per_ai(path: Path) -> dict:
    """snapshot file から GoalDirectedAI / PlanningAI の 行動 を 集計。"""
    with open(path) as f:
        lines = f.readlines()
    meta = json.loads(lines[0])
    game_idx = meta.get("game_idx", int(path.stem.split("_g")[-1]))
    info = parse_meta(meta, game_idx)
    p0_is_goal = info["player_0_is_goal"]

    # idx → ai_name mapping
    def ai_for_idx(idx: int) -> str:
        if idx == 0:
            return "GD" if p0_is_goal else "PA"
        return "PA" if p0_is_goal else "GD"

    actions = {
        "GD": {"leader_attack": 0, "char_attack": 0, "block_attack": 0, "don_attach": 0, "play": 0, "activate": 0},
        "PA": {"leader_attack": 0, "char_attack": 0, "block_attack": 0, "don_attach": 0, "play": 0, "activate": 0},
    }

    for line in lines[1:]:
        s = json.loads(line)
        ai = ai_for_idx(s["turn_player_idx"])
        # event-based attack 集計
        e = s.get("event")
        if isinstance(e, dict) and e.get("type") == "attack":
            tk = e.get("target_kind", "")
            if tk == "leader":
                actions[ai]["leader_attack"] += 1
            elif tk == "character":
                actions[ai]["char_attack"] += 1
            elif tk == "block":
                actions[ai]["block_attack"] += 1
        # log-based play/don/activate 集計
        log = (s.get("log") or "").strip().lower()
        if "play:" in log:
            actions[ai]["play"] += 1
        elif "attach don" in log:
            actions[ai]["don_attach"] += 1
        elif "activate" in log and "main" in log:
            actions[ai]["activate"] += 1

    # winner 判定 (= GD or PA)
    winner_field = meta.get("winner")  # 0=deck1 win=GD win, 1=deck2 win=PA win, -1=draw
    if winner_field == 0:
        winner = "GD"
    elif winner_field == 1:
        winner = "PA"
    else:
        winner = "DRAW"

    return {
        "deck": meta["deck"],
        "game_idx": game_idx,
        "first_player": info["first_player"],
        "winner": winner,
        "turns": meta["turns"],
        "actions": actions,
    }


def analyze_deck(snapshot_dir: Path, deck: str) -> dict:
    """deck 全 game の 行動 集計 → GD vs PA 平均 比較。"""
    paths = sorted(snapshot_dir.glob(f"{deck}_*.jsonl"))
    if not paths:
        return None
    results = [count_actions_per_ai(p) for p in paths]

    summary = {"deck": deck, "n_games": len(results), "games": results}
    summary["wins_gd"] = sum(1 for r in results if r["winner"] == "GD")
    summary["wins_pa"] = sum(1 for r in results if r["winner"] == "PA")

    # action 平均 per game per AI
    avg = {"GD": defaultdict(float), "PA": defaultdict(float)}
    for r in results:
        for ai in ("GD", "PA"):
            for k, v in r["actions"][ai].items():
                avg[ai][k] += v / len(results)
    summary["avg_actions"] = {ai: dict(d) for ai, d in avg.items()}
    return summary


def extract_critical_turns(path: Path, drop_threshold: int = 5000) -> list:
    """負け試合 で GD 視点 の board_eval が 大幅 落ちた turn を 抽出。"""
    with open(path) as f:
        lines = f.readlines()
    meta = json.loads(lines[0])
    game_idx = meta.get("game_idx", int(path.stem.split("_g")[-1]))
    info = parse_meta(meta, game_idx)
    p0_is_goal = info["player_0_is_goal"]
    sign = 1 if p0_is_goal else -1  # GD 視点 で board_eval 符号 補正

    if (meta.get("winner") == 0 and p0_is_goal) or (meta.get("winner") == 1 and not p0_is_goal):
        return []  # GD win game は 解析 不要

    critical = []
    prev_be = 0
    for line in lines[1:]:
        s = json.loads(line)
        be = s.get("board_eval", 0)
        gd_be = sign * be  # GD 視点 で 正規化
        if prev_be:
            delta = gd_be - prev_be
            if delta < -drop_threshold:
                # GD ターン or PA ターン?
                ai_turn = "GD" if (s["turn_player_idx"] == 0) == p0_is_goal else "PA"
                critical.append({
                    "turn": s["turn"],
                    "ai_turn": ai_turn,
                    "phase": s["phase"],
                    "delta": delta,
                    "log": (s.get("log") or "").strip()[:120],
                    "p0_life": s["players"][0]["life_count"],
                    "p1_life": s["players"][1]["life_count"],
                })
        prev_be = gd_be
    return critical


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot-dir", required=True)
    ap.add_argument("--deck", default=None, help="deck slug (= 単一 deck 解析)。 省略で 全 deck summary。")
    ap.add_argument("--critical-threshold", type=int, default=10000)
    args = ap.parse_args()

    snapshot_dir = Path(args.snapshot_dir)
    if args.deck:
        # 単一 deck 詳細解析
        summary = analyze_deck(snapshot_dir, args.deck)
        if not summary:
            print(f"no snapshot for {args.deck}")
            return
        print(f"=== {summary['deck']} ({summary['n_games']} games、 GD wins={summary['wins_gd']}/{summary['wins_pa']}) ===\n")
        print("avg actions per game per AI:")
        for ai in ("GD", "PA"):
            row = summary["avg_actions"][ai]
            print(f"  {ai}: leader_atk={row['leader_attack']:.1f} char_atk={row['char_attack']:.1f} block_atk={row['block_attack']:.1f} don_attach={row['don_attach']:.1f} play={row['play']:.1f} activate={row['activate']:.1f}")
        print()
        # critical turn 抽出 (= 負け試合 only)
        for p in sorted(snapshot_dir.glob(f"{args.deck}_*.jsonl")):
            critical = extract_critical_turns(p, args.critical_threshold)
            if critical:
                meta = json.loads(p.read_text(encoding="utf-8").split("\n")[0])
                print(f"--- {p.name} (winner={'GD' if meta['winner']==0 else 'PA'}, turns={meta['turns']}) ---")
                for c in critical[:5]:
                    print(f"  T{c['turn']} {c['ai_turn']}-turn Δ{c['delta']:+.0f} P0life={c['p0_life']}/P1life={c['p1_life']}: {c['log']}")
                print()
    else:
        # 全 deck summary
        decks = sorted({p.stem.split("_seed")[0] for p in snapshot_dir.glob("*.jsonl")})
        print(f"{'deck':28s} | n  | gd-pa | leader_atk GD/PA | don_attach GD/PA | play GD/PA")
        print("-" * 110)
        for deck in decks:
            s = analyze_deck(snapshot_dir, deck)
            if not s:
                continue
            gd = s["avg_actions"]["GD"]
            pa = s["avg_actions"]["PA"]
            print(f"{deck:28s} | {s['n_games']:2d} | {s['wins_gd']:2d}-{s['wins_pa']:2d} | {gd['leader_attack']:4.1f}/{pa['leader_attack']:4.1f}      | {gd['don_attach']:4.1f}/{pa['don_attach']:4.1f}      | {gd['play']:4.1f}/{pa['play']:4.1f}")


if __name__ == "__main__":
    main()
