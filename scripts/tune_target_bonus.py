#!/usr/bin/env python3
"""bonus 自動最適化 (= 2026-05-26)。

`db/target_fire_log.json` (= scripts/eval_with_entry_firings.py 出力) を 読み込み、
credit assignment で 各 entry の bonus 値 を 更新。

# アルゴリズム

各 entry_id (= "<deck_slug>#<idx>" or "generic#<idx>") で:
  fires_won  = 勝った試合 で その entry が fire した 累計 回数
  fires_lost = 負けた試合 で その entry が fire した 累計 回数
  total      = fires_won + fires_lost
  reward     = (fires_won - fires_lost) / total  ∈ [-1, +1]
  delta      = 1 + α × reward  (= α=0.1 で ±10% 範囲)

  対象 target.bonus に delta 掛けて 更新、 [100, 2000] で clamp。

# 学習 scope

- meta pool current の deck slug を 持つ entry のみ 更新
- 過去 deck (= history 内 slug) の entry は 凍結 (= bonus 触らない)
- generic entries は 常に 更新 (= 全 deck 共通)
- min_fires 未満 (= 信号 弱い) は noise 扱い で skip

# 使い方

```bash
# 既定 α=0.1, min_fires=5
.venv/bin/python scripts/tune_target_bonus.py

# dry-run: 差分 表示 のみ
.venv/bin/python scripts/tune_target_bonus.py --dry-run

# 大胆 学習 α=0.3
.venv/bin/python scripts/tune_target_bonus.py --alpha 0.3
```

# 出力

- 各 decks/<slug>.target_v1.json / db/target_generic.json の bonus を 更新
- db/target_bonus_history.json に iteration 履歴 を 追記 (= rollback 用)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

META_POOL_PATH = REPO_ROOT / "db" / "meta_pool.json"
FIRE_LOG_PATH = REPO_ROOT / "db" / "target_fire_log.json"
GENERIC_PATH = REPO_ROOT / "db" / "target_generic.json"
DECKS_DIR = REPO_ROOT / "decks"
HISTORY_PATH = REPO_ROOT / "db" / "target_bonus_history.json"

# 既存 spec の bonus 範囲 (= 250-3000) を 保護 する 値域。
# Claude 手書き spec は 1500-3000 で 戦略的 重み付け 済 (= 安易に 下げない)。
BONUS_MIN = 100
BONUS_MAX = 3000


def load_json(p: Path) -> Optional[dict]:
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def write_json_indent(p: Path, data: dict) -> None:
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def aggregate_fires(fire_log: dict) -> dict[str, dict[str, int]]:
    """game-by-game fire counts を entry_id 別 win/lost 集計 に 変換。

    Returns:
        {entry_id: {"won": N, "lost": M, "draw": K}}
    """
    agg: dict[str, dict[str, int]] = defaultdict(lambda: {"won": 0, "lost": 0, "draw": 0})
    for g in fire_log.get("games", []):
        winner = g.get("winner_for_deck_a")  # 0 = deck_a, 1 = deck_b, -1 = draw
        # deck_a の fire は winner=0 で 勝者、 winner=1 で 敗者
        for entry_id, cnt in g.get("fire_counts_a", {}).items():
            if winner == 0:
                agg[entry_id]["won"] += cnt
            elif winner == 1:
                agg[entry_id]["lost"] += cnt
            else:
                agg[entry_id]["draw"] += cnt
        for entry_id, cnt in g.get("fire_counts_b", {}).items():
            if winner == 1:
                agg[entry_id]["won"] += cnt
            elif winner == 0:
                agg[entry_id]["lost"] += cnt
            else:
                agg[entry_id]["draw"] += cnt
    return dict(agg)


def compute_bonus_delta(stats: dict, alpha: float) -> float:
    """1 + α × reward を 返す。 reward ∈ [-1, +1]、 delta ∈ [1-α, 1+α]。"""
    total = stats["won"] + stats["lost"]
    if total == 0:
        return 1.0
    reward = (stats["won"] - stats["lost"]) / total
    return 1.0 + alpha * reward


def clamp_bonus(b: float) -> int:
    return int(max(BONUS_MIN, min(BONUS_MAX, b)))


def parse_entry_id(entry_id: str) -> tuple[str, int]:
    """'<source>#<idx>' を (source, idx) に分解。 source = 'generic' or deck slug。"""
    parts = entry_id.rsplit("#", 1)
    if len(parts) != 2:
        raise ValueError(f"invalid entry_id: {entry_id}")
    return parts[0], int(parts[1])


def update_entry_targets(entry: dict, delta_factor: float, dry_run: bool = False) -> list[tuple[int, int, float]]:
    """entry.targets の bonus を 全部 delta 掛けて clamp。 各 (priority, old, new) を 返す。"""
    changes = []
    for tgt in entry.get("targets", []):
        old = int(tgt.get("bonus", 0))
        new = clamp_bonus(old * delta_factor)
        if new != old:
            changes.append((tgt.get("priority", 0), old, new))
            if not dry_run:
                tgt["bonus"] = new
    return changes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--alpha", type=float, default=0.1, help="学習率 α (= delta = 1 + α×reward、 ±α 範囲)")
    ap.add_argument("--min-fires", type=int, default=5, help="この 回数 未満 fire は skip (= noise)")
    ap.add_argument("--dry-run", action="store_true", help="bonus 更新 適用 せず 差分 のみ")
    args = ap.parse_args()

    pool = load_json(META_POOL_PATH)
    if not pool:
        print("ERROR: db/meta_pool.json 不在、 scripts/snapshot_meta_pool.py で 生成 してください", file=sys.stderr)
        sys.exit(1)
    current_slugs = set(pool["current"]["slugs"])

    fire_log = load_json(FIRE_LOG_PATH)
    if not fire_log:
        print("ERROR: db/target_fire_log.json 不在、 scripts/eval_with_entry_firings.py で 生成 してください", file=sys.stderr)
        sys.exit(1)

    if fire_log.get("meta_pool_iteration") != pool["current"].get("iteration"):
        print(
            f"WARN: fire_log iteration={fire_log.get('meta_pool_iteration')} "
            f"!= current pool iteration={pool['current'].get('iteration')}, 古い fire log 使用",
            file=sys.stderr,
        )

    agg = aggregate_fires(fire_log)
    print(f"aggregated {len(agg)} unique entry_ids from {len(fire_log['games'])} games")

    # source 別 entry 集計 (= bonus update を spec file ごと まとめて)
    by_source: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    skipped_low_fire = 0
    skipped_past_deck = 0
    skipped_unknown = 0

    for entry_id, stats in agg.items():
        total = stats["won"] + stats["lost"]
        if total < args.min_fires:
            skipped_low_fire += 1
            continue
        source, idx = parse_entry_id(entry_id)
        # generic は 常時 学習対象、 deck slug は current pool のみ
        if source != "generic" and source not in current_slugs:
            skipped_past_deck += 1
            continue
        by_source[source].append((idx, stats))

    print(f"scope: {len(by_source)} sources, skipped low_fire={skipped_low_fire}, past_deck={skipped_past_deck}")

    # 各 source の spec file を 更新
    total_changes = 0
    summary: list[dict] = []

    for source, items in sorted(by_source.items()):
        if source == "generic":
            spec_path = GENERIC_PATH
        else:
            spec_path = DECKS_DIR / f"{source}.target_v1.json"
        spec = load_json(spec_path)
        if not spec:
            print(f"  WARN: {spec_path} 不在、 skip")
            continue
        entries = spec.get("entries", [])

        source_changes = 0
        for idx, stats in items:
            if idx >= len(entries):
                skipped_unknown += 1
                continue
            entry = entries[idx]
            delta = compute_bonus_delta(stats, args.alpha)
            changes = update_entry_targets(entry, delta, dry_run=args.dry_run)
            if changes:
                source_changes += 1
                for prio, old, new in changes:
                    summary.append({
                        "entry_id": f"{source}#{idx}",
                        "priority": prio,
                        "old_bonus": old,
                        "new_bonus": new,
                        "delta": round(delta, 3),
                        "won": stats["won"],
                        "lost": stats["lost"],
                    })

        total_changes += source_changes
        print(f"  {source}: {len(items)} entries scoped, {source_changes} entries updated")

        if not args.dry_run and source_changes > 0:
            write_json_indent(spec_path, spec)

    print(f"\ntotal: {total_changes} entries updated (skipped_unknown={skipped_unknown})")

    # 履歴 保存
    if not args.dry_run and summary:
        history = load_json(HISTORY_PATH) or {"iterations": []}
        history["iterations"].append({
            "date": str(date.today()),
            "meta_pool_iteration": pool["current"].get("iteration"),
            "alpha": args.alpha,
            "min_fires": args.min_fires,
            "n_games": len(fire_log["games"]),
            "n_entries_updated": total_changes,
            "sample_changes": summary[:20],  # 先頭 20 件 のみ 保存 (= 完全履歴 は 巨大化 防止)
        })
        write_json_indent(HISTORY_PATH, history)
        print(f"history → {HISTORY_PATH}")

    # 差分 top print
    if summary:
        biggest = sorted(summary, key=lambda s: abs(s["new_bonus"] - s["old_bonus"]), reverse=True)[:10]
        print("\n=== 大きな bonus 変動 top 10 ===")
        for s in biggest:
            print(f"  {s['entry_id']:50s}  prio={s['priority']}  {s['old_bonus']:4d} → {s['new_bonus']:4d}  (won={s['won']}, lost={s['lost']})")


if __name__ == "__main__":
    main()
