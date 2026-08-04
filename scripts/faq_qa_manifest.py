#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公式 Q&A **全件** の処理状態を管理するマニフェスト (= 「全件保証」 の台帳)。

なぜ要るか:
  公式 Q&A は engine が Python でも Rust でもない **唯一の外部オラクル**。 両エンジンが同じ
  間違いをしている領域は差分検証では原理的に沈黙するので、 ここを潰すしか手が無い
  (実例: 2026-08-04 に 「バトル中断」 「レストにできない」 等 4 件がこの軸だけで見つかった)。

  ただし 「気づいた時に調べる」 では **全件保証にならない**。 バックフィルと同じく
  **台帳を持って未処理を減らす** 形にする。

台帳 (`db/faq_qa_status.json`):
  key = qid (質問+回答の SHA1 先頭 12 桁 = 文言が同じなら同一 ID)。 ⚠ 2,682 件のうち
  1,477 件は **パラレル違いで同じ文言の再掲** なので、 ユニークは約 1,205 件。
  value = {q, a, files[], status, note}

  status:
    pending    未処理
    conform    engine が公式どおりだと確認した (= 違反なし)
    fixed      違反を見つけて是正した (commit を note に書く)
    n/a        engine の挙動として検証できない (定義質問 / UI 文言 / カード個別の解釈確認 等)
    escalated  違反だが **自動修正の範囲を超える** (大規模改修 / 公式解釈が要る) → 人間へ

  ⚠ timestamp は入れない。 内容が変わった時だけ差分が出る = cron が無意味な commit を打たない。

  .venv/bin/python scripts/faq_qa_manifest.py            # 台帳を作成/更新して進捗を表示
  .venv/bin/python scripts/faq_qa_manifest.py --next 5   # 未処理を 5 件出す (routine 用)
  .venv/bin/python scripts/faq_qa_manifest.py --set <qid> <status> "note"
"""
from __future__ import annotations

import argparse
import collections
import glob
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "db" / "faq_qa_status.json"
VALID = ("pending", "conform", "fixed", "n/a", "escalated")


def qid_of(q: str, a: str) -> str:
    return hashlib.sha1((q + "\n" + a).encode("utf-8")).hexdigest()[:12]


def collect() -> dict:
    """cardqa 全ファイルから ユニーク Q&A を集める (文言が同じものは 1 件に畳む)。"""
    uniq: dict[str, dict] = {}
    for f in sorted(glob.glob(str(ROOT / "db" / "faq" / "cardqa_*.json"))):
        fn = Path(f).name
        try:
            items = json.loads(Path(f).read_text(encoding="utf-8")).get("items", [])
        except Exception:  # noqa: BLE001
            continue
        for it in items:
            q, a = (it.get("q") or "").strip(), (it.get("a") or "").strip()
            if not q:
                continue
            k = qid_of(q, a)
            if k in uniq:
                if fn not in uniq[k]["files"]:
                    uniq[k]["files"].append(fn)
            else:
                uniq[k] = {"q": q, "a": a, "files": [fn]}
    return uniq


def load_status() -> dict:
    if OUT.exists():
        return json.loads(OUT.read_text(encoding="utf-8"))
    return {}


def save(db: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(db, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")


def sync(db: dict, uniq: dict) -> dict:
    """新弾で増えた Q&A を pending として取り込む。 既存の status は保持する。"""
    for k, v in uniq.items():
        if k in db:
            db[k]["q"], db[k]["a"], db[k]["files"] = v["q"], v["a"], sorted(v["files"])
        else:
            db[k] = {**v, "files": sorted(v["files"]), "status": "pending", "note": ""}
    # cardqa から消えた Q&A は台帳からも落とす (公式が削除した裁定を追わない)
    for k in list(db):
        if k not in uniq:
            del db[k]
    return db


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--next", type=int, default=0, help="未処理を N 件表示 (routine 用)")
    ap.add_argument("--set", nargs=3, metavar=("QID", "STATUS", "NOTE"),
                    help="1 件の status を更新")
    args = ap.parse_args()

    db = sync(load_status(), collect())

    if args.set:
        qid, st, note = args.set
        if st not in VALID:
            print(f"status は {VALID} のいずれか", file=sys.stderr)
            sys.exit(2)
        if qid not in db:
            print(f"未知の qid: {qid}", file=sys.stderr)
            sys.exit(2)
        db[qid]["status"] = st
        db[qid]["note"] = note
        save(db)
        print(f"{qid} → {st}: {note}")
        return

    save(db)
    c = collections.Counter(v["status"] for v in db.values())
    total = len(db)
    done = total - c["pending"]
    print(f"公式 Q&A 台帳: ユニーク {total} 件 / 処理済 {done} ({done/max(total,1):.1%})")
    for k in VALID:
        print(f"  {k:<10}{c[k]:>5}")

    if args.next:
        pend = [(k, v) for k, v in sorted(db.items()) if v["status"] == "pending"]
        print(f"\n=== 未処理 (先頭 {min(args.next, len(pend))} 件) ===")
        for k, v in pend[:args.next]:
            print(f"\n[{k}] ({len(v['files'])} 弾: {', '.join(v['files'][:3])})")
            print(f"  Q: {v['q']}")
            print(f"  A: {v['a']}")


if __name__ == "__main__":
    main()
