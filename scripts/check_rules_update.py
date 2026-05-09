# -*- coding: utf-8 -*-
"""
公式ルール PDF が更新されているかを検知し、必要なら再ダウンロード・テキスト再抽出する。

- 既存 `db/rules/<file>_<date>.pdf` の sha256 と、Bandai 公式 URL の最新版を比較
- 変更があれば新ファイル `db/rules/<file>_<NEW_DATE>.pdf` として保存
- 旧ファイルは残す (差分確認用)
- pdfminer.six でテキストを再抽出し `*_pdfminer.txt` を更新
- 最後に SKILL.md の frontmatter 日付を更新するための diff サマリを出力

自動更新: SKILL.md の本文は手作業で更新する必要あり (公式テキストは大量で、簡略化判断が必要)。
このスクリプトはあくまで「変更を検知・通知」までを担う。

実行:
    .venv/bin/python scripts/check_rules_update.py
    .venv/bin/python scripts/check_rules_update.py --apply       # 変更があったらダウンロード実行
    .venv/bin/python scripts/check_rules_update.py --dry-run     # ダウンロードせず HEAD だけ
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = ROOT / "db" / "rules"

# (file_stem, base_url) — クエリ文字列はキャッシュバスター扱いなので常にベースを叩く
TARGETS = [
    (
        "rule_manual",
        "https://www.onepiece-cardgame.com/pdf/rule_manual.pdf",
    ),
    (
        "rule_comprehensive",
        "https://www.onepiece-cardgame.com/pdf/rule_comprehensive.pdf",
    ),
    (
        "playsheet",
        "https://www.onepiece-cardgame.com/pdf/playsheet.pdf",
    ),
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_latest_local(stem: str) -> Path | None:
    """db/rules/<stem>_<YYYYMMDD>.pdf のうち最新日付のものを返す。"""
    candidates = list(RULES_DIR.glob(f"{stem}_*.pdf"))
    if not candidates:
        return None
    pat = re.compile(rf"{re.escape(stem)}_(\d{{8}})\.pdf$")
    dated = []
    for p in candidates:
        m = pat.search(p.name)
        if m:
            dated.append((m.group(1), p))
    if not dated:
        return None
    dated.sort()
    return dated[-1][1]


def fetch_latest(url: str) -> bytes:
    headers = {"User-Agent": "Mozilla/5.0 (onepiece_research rules-watcher)"}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.content


def detect_pdf_date(pdf_bytes: bytes, fallback: str) -> str:
    """PDF メタデータの ModDate を YYYYMMDD で取り出す。失敗時は fallback。"""
    # 簡易: バイナリから /ModDate(D:YYYYMMDD...) を正規表現で探す
    m = re.search(rb"/ModDate\(D:(\d{8})", pdf_bytes)
    if m:
        return m.group(1).decode()
    return fallback


def extract_text(pdf_path: Path) -> str:
    from pdfminer.high_level import extract_text  # 遅延 import
    return extract_text(str(pdf_path)) or ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--apply",
        action="store_true",
        help="変更があれば新 PDF を保存しテキスト抽出も実行 (デフォルト)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="HEAD だけで変更検知し、ダウンロードしない",
    )
    args = ap.parse_args()
    apply_changes = (not args.dry_run) and (args.apply or True)

    RULES_DIR.mkdir(parents=True, exist_ok=True)

    changed = []

    for stem, url in TARGETS:
        local = find_latest_local(stem)
        local_hash = sha256_file(local) if local else None

        try:
            data = fetch_latest(url)
        except Exception as e:
            print(f"  [WARN] {stem}: 取得失敗 {e}", file=sys.stderr)
            continue

        remote_hash = hashlib.sha256(data).hexdigest()

        if local_hash == remote_hash:
            print(f"  [SAME] {stem}: 変更なし ({local.name if local else '-'})")
            continue

        # 変更あり
        date = detect_pdf_date(data, fallback="unknown")
        new_path = RULES_DIR / f"{stem}_{date}.pdf"
        print(
            f"  [DIFF] {stem}: ハッシュ変化 "
            f"(旧={local.name if local else 'なし'}, 新候補={new_path.name})"
        )
        changed.append((stem, local, new_path, data))

        if apply_changes and not args.dry_run:
            new_path.write_bytes(data)
            print(f"         → {new_path} に保存 ({len(data)} bytes)")

            # テキスト抽出
            try:
                text = extract_text(new_path)
                txt_path = RULES_DIR / f"{stem}_{date}_pdfminer.txt"
                txt_path.write_text(text, encoding="utf-8")
                print(f"         → {txt_path.name} 抽出 ({len(text)} 文字)")
            except Exception as e:
                print(f"         [WARN] テキスト抽出失敗: {e}", file=sys.stderr)

    print()
    if not changed:
        print("公式 PDF に変更はありませんでした。")
        return 0

    print(f"変更検知: {len(changed)} ファイル")
    print()
    print("次のアクション:")
    print(
        "  1. 新旧 PDF (もしくは _pdfminer.txt) を diff して何が変わったか確認"
    )
    print(
        "  2. .claude/skills/onepiece-tcg-rules/SKILL.md の frontmatter の version/日付を更新"
    )
    print("  3. 影響範囲があれば本文 (Section 1〜18) を反映")
    print(
        "  4. CLAUDE.md の `rule_*_<DATE>.pdf` 言及があれば日付を更新"
    )

    return 1 if changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
