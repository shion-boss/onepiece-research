#!/usr/bin/env python3
"""cascade fallback log を 分 析 + 最 適 entry 提 案。

cascade L0-L4 全 miss し た state の 集 計 と、 各 state へ の 提 案 entry を 生 成。

# 使 い 方
```bash
# 1. fallback log を 取 る eval を 走 ら せ る
ONEPIECE_CASCADE_LOG=/tmp/fallback.json .venv/bin/python scripts/eval_goal_directed_mirror.py ...

# 2. 分 析
.venv/bin/python scripts/analyze_cascade_fallback.py /tmp/fallback.json --top 20
```

出 力:
- fallback 頻 度 ranking (= 「何 回 fallback 発 動 し た state」 で sort)
- 各 state へ の 提 案 entry (= universal patterns or 似 た axes の corpus 集 計)
- cascade level hit 率 (= L0 hit % / L1 hit % / ... / miss %)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log_path", help="ONEPIECE_CASCADE_LOG で 出 力 さ れ た JSON")
    ap.add_argument("--top", type=int, default=20, help="表 示 する fallback 上 位 N")
    ap.add_argument("--per-deck", action="store_true",
                    help="deck 毎 に 集 計 表 示")
    args = ap.parse_args()

    log_path = Path(args.log_path)
    if not log_path.exists():
        print(f"ERROR: {log_path} not found", file=sys.stderr)
        sys.exit(1)

    data = json.loads(log_path.read_text(encoding="utf-8"))
    fallbacks = data.get("fallbacks", [])
    hit_levels = data.get("hit_levels", {})

    # 1. hit level 集 計
    print("=" * 70)
    print("CASCADE HIT LEVEL DISTRIBUTION")
    print("=" * 70)
    total_hit = sum(hit_levels.values()) if hit_levels else 0
    total_miss = sum(fb["count"] for fb in fallbacks)
    total_all = total_hit + total_miss
    if total_all == 0:
        print("(no data)")
    else:
        for lvl in sorted(hit_levels.keys(), key=lambda x: int(x)):
            n = hit_levels[lvl]
            print(f"  L{lvl} hit: {n:8,} ({n*100/total_all:5.1f}%)")
        print(f"  MISS  (= GreedyAI fallback): {total_miss:8,} ({total_miss*100/total_all:5.1f}%)")
        print(f"  TOTAL eval calls: {total_all:,}")

    # 2. fallback 頻 度 ranking
    print()
    print("=" * 70)
    print(f"TOP {args.top} FALLBACK STATES (= GreedyAI が プレイ した state)")
    print("=" * 70)
    fallbacks.sort(key=lambda fb: fb["count"], reverse=True)
    for i, fb in enumerate(fallbacks[:args.top]):
        ax = fb["sample_axes"]
        print(f"\n#{i+1}: count={fb['count']:,}  deck={fb.get('deck_slug', '?')}")
        print(f"   turn={ax.get('turn')}, opp_leader={ax.get('opp_leader_id')}")
        print(f"   self life={ax.get('self_life_bucket')}, "
              f"hand={ax.get('self_hand_bucket')}, "
              f"field={ax.get('self_field_bucket')}, "
              f"don={ax.get('self_don_bucket')}")
        print(f"   opp  life={ax.get('opp_life_bucket')}, "
              f"hand={ax.get('opp_hand_bucket')}, "
              f"field={ax.get('opp_field_bucket')}, "
              f"threat={ax.get('opp_threat_bucket')}")
        # 提 案 entry の hint
        suggest = _suggest_action_for_state(ax)
        if suggest:
            print(f"   → 提 案: {suggest}")

    # 3. deck 毎 集 計
    if args.per_deck:
        print()
        print("=" * 70)
        print("PER-DECK FALLBACK COUNT")
        print("=" * 70)
        deck_counter = Counter()
        for fb in fallbacks:
            deck_counter[fb.get("deck_slug", "?")] += fb["count"]
        for deck, c in deck_counter.most_common():
            print(f"  {deck:35}: {c:8,} fallbacks")


def _suggest_action_for_state(axes: dict) -> str:
    """state axes か ら 「universal patterns + 直 感」 で action 提 案 (= hint 程 度)。

    [[feedback_optcg_universal_principles]] の 5 大 原 則 を 軽 量 適 用:
    1. テンポ 押 し (self_life=full + opp_field=empty/some)
    2. 効 果 連 鎖 (T7-9 + self_field=many + opp_field=empty)
    3. chara 強 化 (T5-T10 + self_field=some/many + opp 弱)
    4. 序 盤 カーブ (T2-T5 + self_field=empty + don=tight)
    5. 終 盤 場 制 圧 (T8-T11 + self_field=many + opp 残 chara)
    """
    turn = axes.get("turn") or 0
    self_life = axes.get("self_life_bucket")
    self_field = axes.get("self_field_bucket")
    self_don = axes.get("self_don_bucket")
    opp_life = axes.get("opp_life_bucket")
    opp_field = axes.get("opp_field_bucket")
    opp_threat = axes.get("opp_threat_bucket")

    # 原 則 1: テンポ 押 し
    if self_life in ("full", "mid") and opp_field in ("empty", "some") and opp_threat in ("low", "mid"):
        return "AttackLeader (= テンポ 押 し、 原 則 1)"
    # 原 則 4: 序 盤 カーブ
    if turn <= 5 and self_field == "empty" and self_don == "tight":
        return "AttachDonToLeader (= 序 盤 カーブ、 原 則 4)"
    # 原 則 3: chara 強 化
    if 5 <= turn <= 10 and self_field in ("some", "many"):
        return "AttachDonToCharacter (= chara 強 化、 原 則 3)"
    # 原 則 5: 終 盤 場 制 圧
    if turn >= 8 and self_field == "many" and opp_field in ("some", "many"):
        return "AttackCharacter (= 場 制 圧、 原 則 5)"
    # 原 則 2: 効 果 連 鎖
    if 7 <= turn <= 9 and self_field == "many" and opp_field == "empty":
        return "ActivateMain (= 効 果 連 鎖、 原 則 2)"
    return "(unclear: 状 況 依 存、 PlayCharacter or AttackLeader fallback)"


if __name__ == "__main__":
    main()
