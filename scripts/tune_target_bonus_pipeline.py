#!/usr/bin/env python3
"""bonus 学習 pipeline orchestrator (= 環境更新 後 一括 hook、 2026-05-26)。

メタ環境 更新 (= scrape 新規 deck) 後 に 1 回 走らせる だけで:
1. meta pool snapshot 更新 (= 新 deck を current に push、 旧 deck は history に)
2. cross-leader entries 自動生成 (= 新 deck 加わった ので 全 deck spec の Tier 1 cells を 埋める)
3. fire log 収集 (= 現 meta pool 16×16 matrix eval、 light AI mode)
4. bonus 学習 (= credit assignment で 各 entry bonus 更新)

# 使い方

```bash
# 全部 一気
.venv/bin/python scripts/tune_target_bonus_pipeline.py

# dry-run (= 各 step の diff のみ)
.venv/bin/python scripts/tune_target_bonus_pipeline.py --dry-run

# eval 規模 縮小 (= 高速 検証 用)
.venv/bin/python scripts/tune_target_bonus_pipeline.py --n-games 3 --limit-decks 4

# 学習率 大きく (= 大胆 適応)
.venv/bin/python scripts/tune_target_bonus_pipeline.py --alpha 0.2
```

# 過去 entries の 扱い

- 過去 meta pool deck の entries は spec 内 に **残存** (= 削除しない)
- bonus 学習 で touch しない (= 凍結)
- 同 leader_id が 将来 復活 → 凍結 bonus が 即 復活 (= 過去 環境 の 学習成果 活用)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PY = str(REPO_ROOT / ".venv" / "bin" / "python")


def run(cmd: list[str], dry_run: bool = False) -> int:
    print(f"\n  $ {' '.join(cmd)}")
    if dry_run:
        print("    [dry-run skip]")
        return 0
    r = subprocess.run(cmd, cwd=str(REPO_ROOT))
    return r.returncode


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--n-games", type=int, default=5, help="cell ごと 試合数")
    ap.add_argument("--limit-decks", type=int, default=None, help="先頭 N decks のみ")
    ap.add_argument("--ai-mode", default="light", choices=["default", "light"])
    ap.add_argument("--alpha", type=float, default=0.1, help="bonus 学習率")
    ap.add_argument("--min-fires", type=int, default=5)
    ap.add_argument("--skip-snapshot", action="store_true", help="meta_pool snapshot 更新 を skip")
    ap.add_argument("--skip-cross-gen", action="store_true", help="cross-leader 生成 を skip")
    ap.add_argument("--skip-eval", action="store_true", help="fire log 収集 を skip (= 既存使う)")
    ap.add_argument("--skip-tune", action="store_true", help="bonus 学習 を skip (= eval だけ)")
    ap.add_argument("--reset-fire-log", action="store_true",
                    help="fire log を 削除 してから eval (= AI 挙動 変更後 の 2 周目 で 推奨、"
                         " 旧 fire data と 新 AI の混在を防ぐ)")
    ap.add_argument("--diversify-entries", action="store_true",
                    help="Step 2.5 で entries 多様化 module を 実行 (= resource-level 別 variation 自動生成)")
    args = ap.parse_args()

    print("=" * 70)
    print("bonus 学習 pipeline orchestrator")
    print("=" * 70)

    # 1. meta pool snapshot
    if not args.skip_snapshot:
        print("\n[Step 1/4] meta pool snapshot 更新")
        cmd = [PY, "scripts/snapshot_meta_pool.py"]
        if args.dry_run:
            cmd.append("--dry-run")
        if run(cmd, args.dry_run) != 0:
            print("ERROR: snapshot 失敗、 中止", file=sys.stderr)
            sys.exit(1)

    # 2. cross-leader entries
    if not args.skip_cross_gen:
        print("\n[Step 2/4] cross-leader entries 生成 (= 既存 dedup skip)")
        cmd = [PY, "scripts/generate_cross_leader_entries.py"]
        if args.dry_run:
            cmd.append("--dry-run")
        if run(cmd, args.dry_run) != 0:
            print("ERROR: cross-leader gen 失敗、 中止", file=sys.stderr)
            sys.exit(1)

    # 2.5. entries 多様化 (= 2026-05-28 追加、 resource-level 別 variation 自動生成)
    if args.diversify_entries:
        print("\n[Step 2.5/4] entries 多様化 (= resource-level 別 variation)")
        cmd = [PY, "scripts/diversify_target_entries.py"]
        if args.dry_run:
            cmd.append("--dry-run")
        if run(cmd, args.dry_run) != 0:
            print("ERROR: diversify 失敗、 中止", file=sys.stderr)
            sys.exit(1)

    # 2.9. fire log reset (= 2026-05-28 追加、 旧 fire data と 新 AI の混在防止)
    if args.reset_fire_log:
        print("\n[Step 2.9/4] fire log reset (= 旧 data 削除)")
        fire_log_path = REPO_ROOT / "db" / "target_fire_log.json"
        if fire_log_path.exists():
            if args.dry_run:
                print(f"    [dry-run] would delete: {fire_log_path}")
            else:
                fire_log_path.unlink()
                print(f"    deleted: {fire_log_path}")
        else:
            print(f"    skip (= file 不在): {fire_log_path}")

    # 3. fire log 収集
    if not args.skip_eval:
        print("\n[Step 3/4] fire log 収集 (= matrix eval + resume 対応)")
        cmd = [
            PY, "scripts/eval_with_entry_firings.py",
            "--n-games", str(args.n_games),
            "--ai-mode", args.ai_mode,
            "--resume",
        ]
        if args.limit_decks:
            cmd.extend(["--limit-decks", str(args.limit_decks)])
        # eval は dry-run 概念 なし (= 試合 走る or skip のみ)
        if args.dry_run:
            print(f"    [dry-run] would run: {' '.join(cmd)}")
        else:
            if run(cmd, False) != 0:
                print("ERROR: eval 失敗、 中止", file=sys.stderr)
                sys.exit(1)

    # 4. bonus 学習
    if not args.skip_tune:
        print("\n[Step 4/4] bonus 学習 (= credit assignment)")
        cmd = [
            PY, "scripts/tune_target_bonus.py",
            "--alpha", str(args.alpha),
            "--min-fires", str(args.min_fires),
        ]
        if args.dry_run:
            cmd.append("--dry-run")
        if run(cmd, args.dry_run) != 0:
            print("ERROR: tune 失敗", file=sys.stderr)
            sys.exit(1)

    print("\n" + "=" * 70)
    print("pipeline 完了")
    print("=" * 70)


if __name__ == "__main__":
    main()
