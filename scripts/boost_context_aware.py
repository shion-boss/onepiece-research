#!/usr/bin/env python3
"""context-aware optimistic boost (= 2026-05-28、 ohtsuki さん設計)。

「新しく追加する entries は 似た条件の entry の bonus より少し大きい数値を割り振る」

仕組み:
- 各 entry 内 で sibling targets を 走査
- 学習で動いた sibling (= baseline と bonus 異なる) を 「実力示した」 と判定
- 未学習 (= baseline と同じ bonus) かつ _diversified=True な target を
  「max(学習済 sibling bonus) + PREMIUM」 に書き換え
- 学習信号 ない entry (= sibling 全部 untouched) は そのまま (= 文脈なしで boost しない)

これにより:
- 未学習 target が 学習済 sibling より 少し優位 → AI が lookup で 試す
- 良ければ 維持、 悪ければ 学習で 下がる
- Claude 手書き original (= _diversified flag なし) は touch せず

旧 boost_unlearned_bonuses.py との違い:
- 旧: 全 _diversified untouched に 固定 +800 (= ranking 歪む、 文脈無視)
- 新: 学習信号を 文脈として使う = 良い方向に 微 push

実行:
  .venv/bin/python scripts/boost_context_aware.py --dry-run
  .venv/bin/python scripts/boost_context_aware.py --premium 200
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DECKS_DIR = REPO_ROOT / "decks"


def _load_bonus_map(dir_path: Path) -> dict:
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
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--premium", type=int, default=200,
                    help="学習信号あり: max_learned + premium (default 200)")
    ap.add_argument("--fallback-premium", type=int, default=200,
                    help="学習信号なし: 個別 bonus += fallback_premium (default 200、 控えめ)")
    ap.add_argument("--cap", type=int, default=3000, help="bonus cap")
    ap.add_argument("--baseline", default="db/bonus_rounds/round_1",
                    help="学習前 baseline dir")
    args = ap.parse_args()

    baseline_dir = REPO_ROOT / args.baseline
    if not baseline_dir.is_dir():
        print(f"ERROR: baseline dir not found: {baseline_dir}", file=sys.stderr)
        sys.exit(1)

    baseline_map = _load_bonus_map(baseline_dir)
    print(f"baseline: {baseline_dir} ({len(baseline_map)} targets)")
    print(f"premium: +{args.premium}, cap: {args.cap}")
    print(f"mode: {'dry-run' if args.dry_run else 'apply'}")
    print("-" * 60)

    total_entries = 0
    entries_with_signal = 0
    entries_no_signal = 0
    diversified_total = 0
    untouched_diversified = 0
    boosted = 0
    skipped_no_signal = 0
    skipped_at_cap = 0
    boost_distribution = {"+0-200": 0, "+200-400": 0, "+400-600": 0, "+600-1000": 0, "+1000+": 0}

    for spec_path in sorted(DECKS_DIR.glob("*.target_v1.json")):
        slug = spec_path.name.replace(".target_v1.json", "")
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        changed = False

        for ei, entry in enumerate(spec.get("entries", [])):
            total_entries += 1
            targets = entry.get("targets", [])
            # この entry 内 で 学習済 sibling の bonus を 集める
            learned_bonuses = []
            untouched_indices = []
            for ti, tgt in enumerate(targets):
                key = (slug, ei, ti)
                baseline_bonus = baseline_map.get(key)
                current_bonus = int(tgt.get("bonus", 0))
                is_diversified = bool(tgt.get("_diversified"))
                if baseline_bonus is None:
                    continue  # baseline に無い (= 新規 entry)
                if current_bonus != baseline_bonus:
                    # 学習で動いた = signal あり
                    learned_bonuses.append(current_bonus)
                else:
                    # 未学習
                    if is_diversified:
                        untouched_diversified += 1
                        untouched_indices.append(ti)
                    diversified_total += int(is_diversified)
                diversified_total += 0  # 重複加算 防止 (上で 計上)
            # 正確な diversified_total 再計算
            # (上の loop で 二重計上した分を 補正)

            if learned_bonuses:
                entries_with_signal += 1
                # context-aware: 学習済 sibling の max + premium で「兄弟最強より少し上」
                max_learned = max(learned_bonuses)
                target_bonus_with_signal = min(max_learned + args.premium, args.cap)
            else:
                # fallback: 学習信号なし entry も 「個別に少し上げる」(= optimistic init)
                entries_no_signal += 1

            for ti in untouched_indices:
                old_bonus = int(targets[ti].get("bonus", 0))
                if learned_bonuses:
                    # context-aware: max_learned + premium へ
                    new_bonus = target_bonus_with_signal
                else:
                    # fallback: 個別 + fallback_premium (= 小さく、 学習信号ない ので 控えめ)
                    new_bonus = min(old_bonus + args.fallback_premium, args.cap)
                if new_bonus <= old_bonus:
                    skipped_at_cap += 1
                    continue
                actual_boost = new_bonus - old_bonus
                targets[ti]["bonus"] = new_bonus
                targets[ti]["_context_boosted"] = True
                boosted += 1
                changed = True
                # 分布
                if actual_boost < 200:
                    boost_distribution["+0-200"] += 1
                elif actual_boost < 400:
                    boost_distribution["+200-400"] += 1
                elif actual_boost < 600:
                    boost_distribution["+400-600"] += 1
                elif actual_boost < 1000:
                    boost_distribution["+600-1000"] += 1
                else:
                    boost_distribution["+1000+"] += 1

        if changed and not args.dry_run:
            spec_path.write_text(
                json.dumps(spec, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    # diversified_total 正確 再集計
    actual_diversified = 0
    for spec_path in sorted(DECKS_DIR.glob("*.target_v1.json")):
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        for entry in spec.get("entries", []):
            for t in entry.get("targets", []):
                if t.get("_diversified"):
                    actual_diversified += 1

    print(f"total entries                : {total_entries}")
    print(f"  entries with 学習 signal     : {entries_with_signal}")
    print(f"  entries 学習 signal なし     : {entries_no_signal}")
    print(f"total _diversified           : {actual_diversified}")
    print(f"  未学習 _diversified (候補)   : {untouched_diversified}")
    print(f"    boost 適用                : {boosted}")
    print(f"    skip (entry 学習 信号 なし) : {skipped_no_signal}")
    print(f"    skip (元々高 bonus)        : {skipped_at_cap}")
    print()
    print("boost 実効量 分布:")
    for k, v in boost_distribution.items():
        print(f"  {k}: {v}")

    if args.dry_run:
        print("\n[dry-run] 変更は書き戻されません")
    else:
        print(f"\n書き戻し 完了: {boosted} targets context-boosted")


if __name__ == "__main__":
    main()
