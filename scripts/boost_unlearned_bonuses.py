#!/usr/bin/env python3
"""未学習 _diversified entries の bonus を boost (= optimistic initialization、 2026-05-28)。

ohtsuki さん指摘: 「新しく追加する entries は bonus 高めに設定して、 使ってみて、 よくなかったら
下がっていく設計に」 = 古典 RL の optimistic initialization。

判定:
- `_diversified=True` flag 付き (= 私の diversify_target_entries.py 生成分) のみ対象
- かつ 未学習 (= round 1 snapshot と 現在 で bonus 変化なし) のものを boost
- 既校正済 (= round 1/3 で touched 30,318) は そのまま (= 信頼できる学習信号を持つ)
- Claude 手書き original (= _diversified flag なし) は そのまま

boost 量:
- bonus += BOOST (default 800)
- cap=3000 を超えないよう min(bonus + BOOST, 3000) で 押さえ
- 既に bonus >= 2200 なら boost effect 限定的、 cap で打ち止め

実行:
  .venv/bin/python scripts/boost_unlearned_bonuses.py --dry-run         # 試算
  .venv/bin/python scripts/boost_unlearned_bonuses.py                   # 適用
  .venv/bin/python scripts/boost_unlearned_bonuses.py --boost 1000      # boost 量変更
  .venv/bin/python scripts/boost_unlearned_bonuses.py --baseline db/bonus_rounds/round_1
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DECKS_DIR = REPO_ROOT / "decks"


def _load_bonus_map(dir_path: Path) -> dict:
    """(slug, entry_idx, target_idx) → bonus map を構築。"""
    out = {}
    for spec_path in sorted(dir_path.glob("*.target_v1.json")):
        slug = spec_path.name.replace(".target_v1.json", "")
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        for ei, entry in enumerate(spec.get("entries", [])):
            for ti, tgt in enumerate(entry.get("targets", [])):
                out[(slug, ei, ti)] = int(tgt.get("bonus", 0))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="変更を書き戻さず 試算のみ")
    ap.add_argument("--boost", type=int, default=800, help="boost 量 (default 800)")
    ap.add_argument("--cap", type=int, default=3000, help="bonus cap (default 3000)")
    ap.add_argument("--baseline", default="db/bonus_rounds/round_1",
                    help="未学習判定 用 baseline dir (= ここの spec と現状の bonus が一致 = 未学習)")
    args = ap.parse_args()

    baseline_dir = REPO_ROOT / args.baseline
    if not baseline_dir.is_dir():
        print(f"ERROR: baseline dir not found: {baseline_dir}", file=sys.stderr)
        sys.exit(1)

    baseline_map = _load_bonus_map(baseline_dir)
    print(f"baseline: {baseline_dir} ({len(baseline_map)} targets)")
    print(f"boost: +{args.boost}, cap: {args.cap}")
    print(f"mode: {'dry-run' if args.dry_run else 'apply'}")
    print("-" * 60)

    total_targets = 0
    diversified = 0
    untouched_diversified = 0
    already_high = 0
    boosted = 0
    boost_distribution = {"+0-200": 0, "+200-400": 0, "+400-600": 0, "+600-800": 0}

    for spec_path in sorted(DECKS_DIR.glob("*.target_v1.json")):
        slug = spec_path.name.replace(".target_v1.json", "")
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        changed = False
        for ei, entry in enumerate(spec.get("entries", [])):
            for ti, tgt in enumerate(entry.get("targets", [])):
                total_targets += 1
                if not tgt.get("_diversified"):
                    continue
                diversified += 1
                # 未学習判定: baseline と現在 bonus が同じ = まだ学習で動いてない
                key = (slug, ei, ti)
                baseline_bonus = baseline_map.get(key)
                current_bonus = int(tgt.get("bonus", 0))
                if baseline_bonus is None or baseline_bonus != current_bonus:
                    # 既に学習で動いてる
                    continue
                untouched_diversified += 1
                if current_bonus >= args.cap - 50:
                    already_high += 1
                    continue
                # boost
                new_bonus = min(current_bonus + args.boost, args.cap)
                actual_boost = new_bonus - current_bonus
                if actual_boost > 0:
                    tgt["bonus"] = new_bonus
                    tgt["_optimistic_boosted"] = True
                    boosted += 1
                    changed = True
                    # 分布 集計
                    if actual_boost < 200:
                        boost_distribution["+0-200"] += 1
                    elif actual_boost < 400:
                        boost_distribution["+200-400"] += 1
                    elif actual_boost < 600:
                        boost_distribution["+400-600"] += 1
                    else:
                        boost_distribution["+600-800"] += 1

        if changed and not args.dry_run:
            spec_path.write_text(
                json.dumps(spec, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    print(f"total targets             : {total_targets}")
    print(f"_diversified              : {diversified}")
    print(f"  既に学習で動いた          : {diversified - untouched_diversified}")
    print(f"  未学習 (boost 対象候補)   : {untouched_diversified}")
    print(f"    既に高 bonus (skip)    : {already_high}")
    print(f"    boost 適用            : {boosted}")
    print()
    print("boost 実効量 分布:")
    for k, v in boost_distribution.items():
        print(f"  {k}: {v}")

    if args.dry_run:
        print("\n[dry-run] 変更は書き戻されません")
    else:
        print(f"\n書き戻し 完了: {boosted} targets boosted")


if __name__ == "__main__":
    main()
