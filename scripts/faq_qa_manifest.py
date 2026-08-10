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
  .venv/bin/python scripts/faq_qa_manifest.py --next 5 --from-end   # 末尾から (手動バッチ用)
  .venv/bin/python scripts/faq_qa_manifest.py --set <qid> <status> "note"

⚠ **cron と手動を並行させる時は端を分ける**:
  毎時 cron `optcg-faq-conformance` (17 * * * *) は `--next N` = **先頭から** 掴み、 同じ
  ブランチへ直接 push する。 台帳に claim/lock 機構は無いので、 手動バッチが同じ先頭を
  掴むと **同じ Q&A を二重に裁定** する (= 別々の結論が別 commit で入りうる。 git の
  conflict と違って自動では気づけない)。 手動側は必ず `--from-end` を使う。
  残 pending がバッチ 2 本分を切ると両端が出会うので、 その時は警告が出る。
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


def collect() -> tuple[dict, bool]:
    """cardqa 全ファイルから ユニーク Q&A を集める (文言が同じものは 1 件に畳む)。

    返り値 = (uniq, from_primary)。
      from_primary = True  → 一次ソース `db/faq/cardqa_*.json` (scraper 産、 全件) を読めた。
      from_primary = False → 一次ソース不在で committed snapshot `db/cardqa_tagged.json`
                             (= scraper 出力を tag 付けした忠実 copy、 q/a 逐語一致 = qid 一致)
                             に fallback した。 これは snapshot なので **一次より少ない可能性** がある。

    なぜ fallback が要るか: 一次ソースは Bandai 著作物ゆえ gitignore。 fresh clone +
    公式サイト遮断の環境 (= クラウドルーティンが着地しうる) では一切存在せず、 collect が
    空 → sync が **台帳を全消去** する data-loss があった。 committed snapshot に退避しつつ、
    sync 側で from_primary=False の時は **prune しない** (下記) ことで台帳を守る。
    """
    uniq: dict[str, dict] = {}
    primary_files = sorted(glob.glob(str(ROOT / "db" / "faq" / "cardqa_*.json")))
    for f in primary_files:
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
    if uniq:
        return uniq, True

    # 一次ソース不在 → committed snapshot に fallback (add-only、 prune しない)
    tagged = ROOT / "db" / "cardqa_tagged.json"
    if tagged.exists():
        try:
            items = json.loads(tagged.read_text(encoding="utf-8")).get("items", [])
        except Exception:  # noqa: BLE001
            items = []
        for it in items:
            q, a = (it.get("q") or "").strip(), (it.get("a") or "").strip()
            if not q:
                continue
            k = qid_of(q, a)
            if k in uniq:
                if "cardqa_tagged.json" not in uniq[k]["files"]:
                    uniq[k]["files"].append("cardqa_tagged.json")
            else:
                uniq[k] = {"q": q, "a": a, "files": ["cardqa_tagged.json"]}
    return uniq, False


def load_status() -> dict:
    if OUT.exists():
        return json.loads(OUT.read_text(encoding="utf-8"))
    return {}


def save(db: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(db, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")


def sync(db: dict, uniq: dict, from_primary: bool = True) -> dict:
    """新弾で増えた Q&A を pending として取り込む。 既存の status は保持する。

    from_primary=True (= 一次ソース `db/faq/cardqa_*.json` を読めた) の時だけ、 cardqa から
    消えた Q&A を台帳からも落とす (公式が削除した裁定を追わない)。 一次不在で snapshot に
    fallback した時 (from_primary=False) は snapshot が一次より少ない可能性があるので
    **prune しない** (= add-only)。 これがないと、 一次ソースを持たない環境で本 script を
    走らせると台帳が全消去される (= 処理済 status ごと吹き飛ぶ data-loss)。
    """
    for k, v in uniq.items():
        if k in db:
            # fallback (snapshot) は一次より metadata が粗い (files が "cardqa_tagged.json"
            # のみ) ので、 既存エントリの q/a/files は **上書きしない** (一次由来の pack 名を守る)。
            if from_primary:
                db[k]["q"], db[k]["a"], db[k]["files"] = v["q"], v["a"], sorted(v["files"])
        else:
            db[k] = {**v, "files": sorted(v["files"]), "status": "pending", "note": ""}
    if from_primary:
        for k in list(db):
            if k not in uniq:
                del db[k]
    return db


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--next", type=int, default=0, help="未処理を N 件表示 (routine 用)")
    ap.add_argument("--from-end", action="store_true",
                    help="未処理を **末尾から** 出す (= 手動バッチ用。 毎時 cron は先頭から"
                         "掴むので、 逆端から進めば同じ Q&A を二重に裁定しない)")
    ap.add_argument("--set", nargs=3, metavar=("QID", "STATUS", "NOTE"),
                    help="1 件の status を更新")
    args = ap.parse_args()

    uniq, from_primary = collect()
    db = sync(load_status(), uniq, from_primary)
    if not from_primary:
        print("⚠ 一次ソース db/faq/cardqa_*.json 不在 → committed snapshot "
              "db/cardqa_tagged.json に fallback (add-only、 台帳を prune しない)。",
              file=sys.stderr)

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
        n = min(args.next, len(pend))
        # ⚠ 毎時 cron (optcg-faq-conformance) は **先頭から** N 件掴む。 台帳に claim 機構が
        #   無いので、 手動バッチが同じ先頭を掴むと **同じ Q&A を二重に裁定** する (git の
        #   conflict より厄介: 別々の結論が別 commit で入りうる)。 --from-end で逆端から
        #   進めば、 残 pending がバッチ 2 本分を切るまで両者は出会わない。
        take = list(reversed(pend[-n:])) if args.from_end else pend[:n]
        where = "末尾" if args.from_end else "先頭"
        print(f"\n=== 未処理 ({where}から {n} 件) ===")
        if args.from_end and len(pend) < args.next * 2:
            print(f"⚠ 残 pending {len(pend)} 件 = バッチ 2 本分を切った。 "
                  f"cron (先頭から) と範囲が重なる → cron を止めるか手動を停める")
        for k, v in take:
            print(f"\n[{k}] ({len(v['files'])} 弾: {', '.join(v['files'][:3])})")
            print(f"  Q: {v['q']}")
            print(f"  A: {v['a']}")


if __name__ == "__main__":
    main()
