# -*- coding: utf-8 -*-
"""
公式サイトの全方位アップデートチェッカー (knowledge refresh の入口)。

対象:
1. PDF (rule_manual / rule_comprehensive / playsheet)
2. FAQ (4 カテゴリ)
3. cardqa (弾別 Q&A)
4. 禁止/制限/禁止ペア (banlist)

動作:
- 各リソースを fetch して sha256 比較
- 変更があれば対応する scrape スクリプトを呼び直して更新
- 最後に変更サマリと、SKILL.md 更新が要るかを stdout に出す

実行:
    .venv/bin/python scripts/check_official_updates.py
    .venv/bin/python scripts/check_official_updates.py --force-rescrape  # ハッシュ比較せず強制再取得
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE_FILE = ROOT / "db" / ".update_cache.json"

HEADERS = {"User-Agent": "Mozilla/5.0 (onepiece_research update-checker)"}

CHECK_URLS = {
    "faq_base": "https://www.onepiece-cardgame.com/rules/qa.php?tab=faq&type=0&maincat-faq=%E5%9F%BA%E6%9C%AC%E3%83%AB%E3%83%BC%E3%83%AB",
    "faq_keyword_effect": "https://www.onepiece-cardgame.com/rules/qa.php?tab=faq&type=0&maincat-faq=%E3%82%AD%E3%83%BC%E3%83%AF%E3%83%BC%E3%83%89%E5%8A%B9%E6%9E%9C",
    "faq_keyword": "https://www.onepiece-cardgame.com/rules/qa.php?tab=faq&type=0&maincat-faq=%E3%82%AD%E3%83%BC%E3%83%AF%E3%83%BC%E3%83%89",
    "faq_detail": "https://www.onepiece-cardgame.com/rules/qa.php?tab=faq&type=0&maincat-faq=%E8%A9%B3%E7%B4%B0%E3%83%AB%E3%83%BC%E3%83%AB",
    "cardqa_index": "https://www.onepiece-cardgame.com/rules/qa.php?tab=cardqa",
    "banlist_master": "https://www.onepiece-cardgame.com/rules/restriction/",
}


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def fetch(url: str) -> bytes:
    r = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
    r.raise_for_status()
    return r.content


def load_cache() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    return {"hashes": {}, "last_check": None}


def save_cache(cache: dict) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run(args: list[str]) -> int:
    print(f"  $ {' '.join(args)}")
    return subprocess.call(args)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force-rescrape", action="store_true",
                    help="ハッシュ比較せず強制再取得")
    args = ap.parse_args()

    cache = load_cache()
    new_hashes: dict[str, str] = {}
    changes: list[str] = []

    print("=== 公式リソースのハッシュチェック ===")
    for key, url in CHECK_URLS.items():
        try:
            content = fetch(url)
        except Exception as e:
            print(f"  [ERR] {key}: {e}", file=sys.stderr)
            continue
        h = sha256_bytes(content)
        new_hashes[key] = h
        old = cache["hashes"].get(key)
        if args.force_rescrape:
            tag = "FORCE"
            changes.append(key)
        elif old is None:
            tag = "NEW"
            changes.append(key)
        elif old != h:
            tag = "CHANGED"
            changes.append(key)
        else:
            tag = "same"
        print(f"  [{tag:>7}] {key:25} {url[:60]}...")

    print()

    # PDF は別系統 (check_rules_update.py)
    print("=== PDF rule docs (検証は check_rules_update.py に委譲) ===")
    rc_pdf = run([
        sys.executable,
        str(ROOT / "scripts" / "check_rules_update.py"),
    ])
    if rc_pdf == 1:
        changes.append("rules_pdf")
    print()

    # FAQ / cardqa が変わってたら scrape_official_faq.py を実行
    faq_changed = any(c.startswith("faq_") or c == "cardqa_index" for c in changes)
    if faq_changed:
        print("=== FAQ/cardqa を再スクレイプ ===")
        rc = run([sys.executable, str(ROOT / "scripts" / "scrape_official_faq.py")])
        if rc != 0:
            print(f"  [WARN] scrape exited {rc}")
        print()

    # banlist が変わってたら scrape_official_banlist.py を実行
    if "banlist_master" in changes:
        print("=== banlist を再スクレイプ ===")
        rc = run([sys.executable, str(ROOT / "scripts" / "scrape_official_banlist.py")])
        if rc != 0:
            print(f"  [WARN] scrape exited {rc}")
        print()

    # キャッシュ更新
    cache["hashes"].update(new_hashes)
    cache["last_check"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    save_cache(cache)

    # サマリ
    print("=" * 60)
    if not changes:
        print("✓ 公式リソースに変更はありません。")
        return 0
    print(f"⚠ 変更検知: {', '.join(changes)}")
    print()
    print("次のアクション:")
    print("  1. db/faq/ や db/banlist/master.json の差分を確認")
    print("  2. .claude/skills/onepiece-tcg-rules/SKILL.md の last_checked を更新")
    print("  3. 変更が engine 仕様に影響するなら §17 の表も更新")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
