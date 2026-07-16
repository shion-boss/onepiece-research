"""db/faq/*.json を 1 つの corpus にまとめて Vercel Blob にアップロードする。

repo は public で db/faq/*.json は gitignore (Bandai 著作物 = scraper 取得物) なので
Vercel に git 経由では載らず、 本番の /api/faq が空になる。 カード画像プロキシと同じ思想で
Blob 経由で載せる。 API 側 (_load_faq_corpus) は本番 = Blob / ローカル = db/faq を読む。

corpus に generated_at (= FAQ ファイルの最終更新日 = 最後に scrape した日) を持たせ、
/api/faq/meta で「データ最終更新日」を表示する。

実行 (ローカル、 .env に BLOB_READ_WRITE_TOKEN が要る):
    .venv/bin/python scripts/upload_faq_to_blob.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAQ_DIR = ROOT / "db" / "faq"


def build_corpus() -> dict:
    """db/faq/*.json → {generated_at, count, items:[...], sources:[...]}。

    sources = Q&A 参照先タブ用のメタ (source, label, source_url, count, fetched_at)。
    API 側 _faq_source_links() が本番でこれを読む。
    """
    items: list[dict] = []
    sources: list[dict] = []
    latest_mtime = 0.0
    for path in sorted(FAQ_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        latest_mtime = max(latest_mtime, path.stat().st_mtime)
        category = data.get("category") or data.get("series") or path.stem
        file_items = data.get("items", [])
        for item in file_items:
            items.append({
                "source": path.name,
                "category": category,
                "q": item.get("q", ""),
                "a": item.get("a", ""),
            })
        sources.append({
            "source": path.name,
            "label": category,
            "source_url": data.get("source_url"),
            "count": len(file_items),
            "fetched_at": data.get("fetched_at"),
        })
    generated_at = (
        datetime.fromtimestamp(latest_mtime, tz=timezone.utc).isoformat()
        if latest_mtime
        else datetime.now(timezone.utc).isoformat()
    )
    return {
        "generated_at": generated_at,
        "count": len(items),
        "items": items,
        "sources": sources,
    }


def main() -> None:
    from api.blob_storage import put_json, is_configured

    if not is_configured():
        print("BLOB_READ_WRITE_TOKEN 未設定。 .env に入れて実行してください。", file=sys.stderr)
        sys.exit(1)
    corpus = build_corpus()
    if corpus["count"] == 0:
        print("db/faq/*.json が空。 先に scraper で FAQ を取得してください。", file=sys.stderr)
        sys.exit(1)
    # add_random_suffix=True: 上書きヘッダ不要で確実に PUT。 API は faq/corpus を prefix
    # list して最新 (uploadedAt) を読む。
    url = put_json("faq/corpus.json", corpus, add_random_suffix=True)
    print(f"uploaded: {corpus['count']} items / {len(corpus['sources'])} sources / "
          f"generated_at={corpus['generated_at']}")
    print(f"blob url: {url}")


if __name__ == "__main__":
    main()
