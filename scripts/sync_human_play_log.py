#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Vercel Blob から AI vs Human 試合 log を local cache に sync。

使い方:
    .venv/bin/python scripts/sync_human_play_log.py
    .venv/bin/python scripts/sync_human_play_log.py --prefix human_play/
    .venv/bin/python scripts/sync_human_play_log.py --force-redownload

local cache 配置: db/human_play_log/<pathname>.json
既存 file は skip (= --force-redownload で 上書き)。

BLOB_READ_WRITE_TOKEN env が 必要。 web/.env.local か root の .env を 読み込み。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_env() -> None:
    """web/.env.local や .env から BLOB_READ_WRITE_TOKEN を 読み込み。"""
    if os.environ.get("BLOB_READ_WRITE_TOKEN"):
        return
    candidates = [ROOT / "web" / ".env.local", ROOT / ".env.local", ROOT / ".env"]
    for env_file in candidates:
        if not env_file.exists():
            continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key == "BLOB_READ_WRITE_TOKEN" and val:
                os.environ["BLOB_READ_WRITE_TOKEN"] = val
                print(f"[sync] loaded BLOB_READ_WRITE_TOKEN from {env_file}")
                return


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default="human_play/", help="Blob prefix filter")
    parser.add_argument(
        "--force-redownload", action="store_true", help="既存 file も 上書き"
    )
    parser.add_argument(
        "--out-dir",
        default=str(ROOT / "db" / "human_play_log"),
        help="local cache 配置先",
    )
    args = parser.parse_args()

    _load_env()
    if not os.environ.get("BLOB_READ_WRITE_TOKEN"):
        print(
            "[sync] BLOB_READ_WRITE_TOKEN env が 設定されていません。\n"
            "       Vercel UI で Blob Store を provisioning し、\n"
            "       cd web && npx vercel env pull .env.local で .env.local に取得してください。",
            file=sys.stderr,
        )
        return 1

    from api.blob_storage import list_jsons, get_json

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[sync] listing Blob prefix={args.prefix!r} ...")
    blobs = list_jsons(prefix=args.prefix)
    print(f"[sync] found {len(blobs)} blob(s)")

    n_new, n_skip, n_fail = 0, 0, 0
    for b in blobs:
        pathname = b.get("pathname") or ""
        url = b.get("url") or ""
        if not pathname or not url:
            continue
        # pathname の "human_play/" prefix を 落として local の filename にする
        rel_name = Path(pathname).name
        local_path = out_dir / rel_name
        if local_path.exists() and not args.force_redownload:
            n_skip += 1
            continue
        try:
            data = get_json(url)
            local_path.write_text(
                json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            n_new += 1
            print(f"  [new] {rel_name}")
        except Exception as e:
            n_fail += 1
            print(f"  [fail] {rel_name}: {e}", file=sys.stderr)

    print(
        f"[sync] done. new={n_new} skip={n_skip} fail={n_fail} total={len(blobs)}\n"
        f"       local cache: {out_dir}"
    )
    return 0 if n_fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
