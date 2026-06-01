#!/usr/bin/env python3
"""feedback resolution ledger = 解決済み match-feedback を 1 箇所で 追跡。

[[project_full_db_audit_phase]] とは別系統。 review-all-match-feedback skill が 毎回
解決済みコメントを「未解決の課題」 として 蒸し返す 問題 (2026-06-01 発覚) の 恒久対策。

3 ソース (spectate / human_play log_comments / matrix) は **処理後に消し込まれず**
DB/Blob に残り続けるため、 各 feedback に安定 ID を振り「resolved + 解決 commit + 理由」
を独立 ledger (db/feedback_resolutions.json) に記録する。 SQLite migration も Blob 書換も
不要で git で履歴追跡できる (= 設計判断 2026-06-01)。

安定 ID 規約:
  spectate:<comment_id>                  (= SQLite comments.id = UUID、 既に安定)
  humanplay:<file_hash>:idx<log_index>   (= file 名末尾 hash + log_comment.log_index)

使い方:
  # 未解決 feedback を列挙 (= skill の Step 1.5 で 解決済みを除外して残りを得る)
  python scripts/feedback_ledger.py list-unresolved
  python scripts/feedback_ledger.py list-unresolved --since-commit-date  # 日時ヒューリスティック併用

  # 解決済みマーク (= 検証して 修正 commit を 確認した後)
  python scripts/feedback_ledger.py resolve spectate:34681f00... --commit 23cc0d4 --reason "log順序修正"

  # 全 feedback の resolved/unresolved サマリ
  python scripts/feedback_ledger.py status
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = ROOT / "db" / "feedback_resolutions.json"
SPECTATE_DB = Path(__import__("os").environ.get("DATA_DIR", str(ROOT / "db"))) / "spectate_comments.sqlite"
HUMANPLAY_DIR = ROOT / "db" / "human_play_log"

# file 名末尾の 8 桁 hash を 抽出 (= 20260527T153510Z_..._8ff22174.json → 8ff22174)
_HASH_RE = re.compile(r"_([0-9a-f]{8})\.json$")


# ---------- ledger I/O ----------

def load_ledger() -> dict:
    if LEDGER_PATH.exists():
        return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    return {"_meta": {"description": "match-feedback 解決追跡 ledger。 review-all-match-feedback skill が参照。",
                      "id_scheme": "spectate:<comment_id> / humanplay:<file_hash>:idx<log_index>"},
            "resolutions": {}}


def save_ledger(ledger: dict) -> None:
    LEDGER_PATH.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------- feedback 収集 (全ソース横断、 安定 ID 付き) ----------

def collect_all_feedback() -> list[dict]:
    """全ソースの feedback を {id, source, text, created_at, context} で返す。"""
    items: list[dict] = []

    # A) spectate コメント
    if SPECTATE_DB.exists():
        conn = sqlite3.connect(str(SPECTATE_DB))
        conn.row_factory = sqlite3.Row
        for r in conn.execute("SELECT * FROM comments ORDER BY created_at"):
            items.append({
                "id": f"spectate:{r['id']}",
                "source": "spectate",
                "text": r["text"],
                "created_at": r["created_at"],
                "context": r["snapshot_log"],
                "replay_key": r["replay_key"],
            })
        conn.close()

    # B) human_play log_comments
    for fp in sorted(HUMANPLAY_DIR.glob("*.json")):
        m = _HASH_RE.search(fp.name)
        fhash = m.group(1) if m else fp.stem[-8:]
        try:
            payload = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        md = payload.get("metadata", {})
        for entry in payload.get("log_comments", []) or []:
            li = entry.get("log_index")
            items.append({
                "id": f"humanplay:{fhash}:idx{li}",
                "source": "human_play",
                "text": entry.get("comment", ""),
                "created_at": entry.get("ts", ""),
                "context": entry.get("log_text", ""),
                "deck_human": md.get("deck_human_slug"),
                "deck_ai": md.get("deck_ai_slug"),
                "_file": fp.name,
            })
    return items


# ---------- 日時ヒューリスティック (= 補助、 自動解決ではなく候補提示) ----------

def latest_fix_commit_date() -> str | None:
    """engine/ + web/ の 最新 commit 日時 (ISO) を 返す。 これより古い feedback は
    「修正済みの可能性」 候補。 確定ではなく 検証を促すヒント。"""
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "log", "-1", "--format=%cI", "--",
             "engine/", "web/src/", "db/card_effects.json"],
            capture_output=True, text=True, timeout=15,
        )
        return (out.stdout or "").strip() or None
    except Exception:
        return None


# ---------- commands ----------

def cmd_status(args) -> None:
    ledger = load_ledger()
    res = ledger.get("resolutions", {})
    items = collect_all_feedback()
    by_source: dict[str, list] = {}
    for it in items:
        by_source.setdefault(it["source"], []).append(it)
    print(f"feedback ledger: {LEDGER_PATH.relative_to(ROOT)}")
    print(f"  全 feedback: {len(items)} 件 / resolved 記録: {len(res)} 件")
    for src, lst in sorted(by_source.items()):
        n_res = sum(1 for it in lst if res.get(it["id"], {}).get("resolved"))
        print(f"  [{src}] {len(lst)} 件中 resolved {n_res} / unresolved {len(lst)-n_res}")


def cmd_list_unresolved(args) -> None:
    ledger = load_ledger()
    res = ledger.get("resolutions", {})
    items = collect_all_feedback()
    cutoff = latest_fix_commit_date() if args.since_commit_date else None
    unresolved = []
    for it in items:
        if res.get(it["id"], {}).get("resolved"):
            continue
        it = dict(it)
        if cutoff and it.get("created_at") and it["created_at"] < cutoff:
            it["_pre_cutoff_hint"] = True  # 修正済みの可能性 (= 要検証)
        unresolved.append(it)
    if args.json:
        print(json.dumps(unresolved, ensure_ascii=False, indent=2))
        return
    print(f"未解決 feedback: {len(unresolved)} 件" + (f" (cutoff={cutoff})" if cutoff else ""))
    for it in unresolved:
        hint = " [日時的に修正済みの可能性=要検証]" if it.get("_pre_cutoff_hint") else ""
        print(f"  {it['id']}{hint}")
        print(f"    [{it['source']}] {it['created_at']}: {it['text']}")
        if it.get("context"):
            print(f"    ctx: {it['context']}")


def cmd_resolve(args) -> None:
    ledger = load_ledger()
    ledger.setdefault("resolutions", {})
    # ID 妥当性: 既知 feedback に存在するか warn
    known = {it["id"] for it in collect_all_feedback()}
    if args.feedback_id not in known:
        print(f"WARN: {args.feedback_id} は現存 feedback に無い (typo? 既に削除?)。 記録は続行。")
    import datetime
    ledger["resolutions"][args.feedback_id] = {
        "resolved": True,
        "commit": args.commit,
        "reason": args.reason,
        "date": datetime.date.today().isoformat(),
    }
    save_ledger(ledger)
    print(f"resolved: {args.feedback_id} → commit={args.commit} ({args.reason})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status").set_defaults(func=cmd_status)

    p_lu = sub.add_parser("list-unresolved")
    p_lu.add_argument("--since-commit-date", action="store_true",
                      help="engine/web 最新 commit より古い feedback に 修正済み候補ヒントを付ける")
    p_lu.add_argument("--json", action="store_true")
    p_lu.set_defaults(func=cmd_list_unresolved)

    p_r = sub.add_parser("resolve")
    p_r.add_argument("feedback_id")
    p_r.add_argument("--commit", required=True, help="解決した commit hash")
    p_r.add_argument("--reason", required=True, help="解決理由 (= 何で どう直ったか)")
    p_r.set_defaults(func=cmd_resolve)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
