#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""spectate_comments → expert_annotations 転換 pipeline (= 教師あり学習 source、 2026-05-17)。

friends が観戦 UI で残したコメントを 機械学習 source にするための変換スクリプト。
plan の「実プレイヤー対戦ログ + コメント運用」 (Step 0/2 補強) を実装。

# 入力
- db/spectate_comments.sqlite (= 観戦 UI で残された comment、 表 comments)

# 出力
- db/expert_annotations.jsonl (= 1 line / annotation、 学習スクリプトから読みやすい形式)

# 処理
1. 各 comment の text を keyword check で分類:
   - bad_move: 「悪手」 「ミス」 「間違い」 「違う」 「ダメ」 等 → AI 行動の批判
   - good_move: 「良い」 「ナイス」 「正解」 「上手い」 → AI 行動の評価
   - engine_bug: 「バグ」 「壊れ」 「順番」 「log」 「表示」 → engine / UI 問題
   - rule_question: 「ルール」 「公式」 「Q&A」 → 確認系
   - unknown: それ以外
2. snapshot_log から action_category を推定 (= 関数 11 ACTION_CATEGORIES と一致)
3. jsonl で書き出し

# 将来の利用
- bad_move ラベルの annotation = 「避けるべき行動」 として模倣学習 (= Step 5 後の追加 fine-tune)
- good_move = 「良い行動」 の正例
- engine_bug = engine 修正 backlog として report に
- rule_question = FAQ 追加候補

Usage:
  .venv/bin/python scripts/convert_comments_to_annotations.py
  .venv/bin/python scripts/convert_comments_to_annotations.py --output db/expert_annotations.jsonl
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "spectate_comments.sqlite"
DEFAULT_OUTPUT = ROOT / "db" / "expert_annotations.jsonl"


# 簡易 keyword 分類 (= 将来 NLP モデル化 候補)
KEYWORDS: dict[str, list[str]] = {
    "bad_move": [
        "悪手", "ミス", "間違い", "違う", "おかしい", "ダメ", "なんで", "やめ", "失敗",
        "もったいない", "勿体無い", "下手", "へた", "弱い",
    ],
    "good_move": [
        "良い", "ナイス", "正解", "上手い", "うまい", "good", "best",
    ],
    "engine_bug": [
        "バグ", "壊れ", "順番", "逆", "log", "ログ", "表示", "おかしい",
    ],
    "rule_question": [
        "ルール", "公式", "Q&A", "QA", "判定",
    ],
}


def classify_text(text: str) -> str:
    """text から label を推定 (= 簡易 keyword check)。

    優先順: bad_move / good_move を engine_bug / rule_question より優先 (= AI 評価 が主要価値)。
    """
    if not text:
        return "unknown"
    text_l = text.lower()
    # 優先順位順に check
    for label in ("bad_move", "good_move", "engine_bug", "rule_question"):
        for kw in KEYWORDS[label]:
            if kw in text or kw in text_l:
                return label
    return "unknown"


def infer_action_category(snapshot_log: str) -> str:
    """snapshot_log から action_category を推定 (= 関数 11 ACTION_CATEGORIES と一致)。

    snapshot_log の例:
      "T1 P0: 登場 OP05-119 (cost 5)" → PlayCharacter
      "T2 P1: 起動メイン OP14-079 (eff#0)" → ActivateMain
      "T3 P0: アタック leader" → AttackLeader
    """
    log = (snapshot_log or "").lower()
    if "登場" in snapshot_log:
        if "STAGE" in snapshot_log.upper() or "ステージ" in snapshot_log:
            return "PlayStage"
        if "イベント" in snapshot_log:
            return "PlayEvent"
        return "PlayCharacter"
    if "起動メイン" in snapshot_log or "activate" in log:
        return "ActivateMain"
    if "アタック" in snapshot_log or "attack" in log:
        if "leader" in log or "リーダー" in snapshot_log:
            return "AttackLeader"
        return "AttackCharacter"
    if "ドン" in snapshot_log and ("つけ" in snapshot_log or "アクティブ" in snapshot_log):
        return "AttachDon"
    if "効果" in snapshot_log:
        return "ActivateMain"  # 効果起動はだいたい activate_main
    if "end" in log or "終了" in snapshot_log:
        return "EndPhase"
    if "pass" in log:
        return "PassMain"
    return "Other"


def convert(db_path: Path, output_path: Path, verbose: bool = True) -> dict:
    """spectate_comments → expert_annotations 変換。"""
    if not db_path.exists():
        raise FileNotFoundError(f"spectate_comments not found: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = list(cur.execute("SELECT * FROM comments ORDER BY created_at"))

    n_written = 0
    label_counts: Counter = Counter()
    action_counts: Counter = Counter()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for r in rows:
            text = r["text"] or ""
            label = classify_text(text)
            action_cat = infer_action_category(r["snapshot_log"] or "")
            entry = {
                "comment_id": r["id"],
                "replay_key": r["replay_key"],
                "deck_a": r["deck_a"],
                "deck_b": r["deck_b"],
                "first_player": r["first_player"],
                "winner": r["winner"],
                "turns": r["turns"],
                "snapshot_idx": r["snapshot_idx"],
                "snapshot_turn": r["snapshot_turn"],
                "snapshot_log": r["snapshot_log"],
                "action_category": action_cat,
                "text": text,
                "label": label,
                "author": r["author"] if "author" in r.keys() else None,
                "created_at": r["created_at"],
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            n_written += 1
            label_counts[label] += 1
            action_counts[action_cat] += 1

    summary = {
        "total": n_written,
        "label_counts": dict(label_counts),
        "action_counts": dict(action_counts),
        "output": str(output_path),
    }

    if verbose:
        print(f"Converted {n_written} annotations → {output_path}")
        print()
        print("Label distribution:")
        for label, count in label_counts.most_common():
            print(f"  {label:20s}: {count}")
        print()
        print("Action category distribution:")
        for cat, count in action_counts.most_common():
            print(f"  {cat:20s}: {count}")

    return summary


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Convert spectate_comments to expert_annotations.jsonl"
    )
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args()
    convert(args.db, args.output, verbose=True)


if __name__ == "__main__":
    main()
