# -*- coding: utf-8 -*-
"""Vercel Blob REST API client (= JSON 保存 / 取得 / 一覧)。

Vercel Blob は HTTP API 経由で put / list / get できる。 公式 Python SDK は無いので
httpx で 直接 叩く。 認証は BLOB_READ_WRITE_TOKEN env 変数 経由。

使用例:
    from api.blob_storage import put_json, list_jsons, get_json
    url = put_json("human_play/2026-05-23_X_vs_Y_42.json", {"foo": "bar"})
    blobs = list_jsons(prefix="human_play/")
    data = get_json(blobs[0]["url"])
"""

from __future__ import annotations

import json
import os
from typing import Optional

import httpx

BLOB_API_BASE = "https://blob.vercel-storage.com"


def _token() -> str:
    tok = os.environ.get("BLOB_READ_WRITE_TOKEN")
    if not tok:
        raise RuntimeError(
            "BLOB_READ_WRITE_TOKEN env が 設定されていません。 "
            "Vercel UI で Blob Store を provisioning し、 vercel env pull で .env.local に取得してください。"
        )
    return tok


def put_json(
    pathname: str,
    data: dict,
    *,
    add_random_suffix: bool = False,
    cache_control_max_age: int = 31536000,
) -> str:
    """JSON を Blob に PUT。 完了後 URL (= public でも token 必須でも) を 返す。

    Args:
        pathname: Blob 内 の logical path (= "human_play/2026-05-23_X_vs_Y_42.json")
        data: 保存する dict (= json.dumps される)
        add_random_suffix: True なら 同名 conflict 防止 で suffix 追加 (= default False)
        cache_control_max_age: CDN cache 秒数

    Returns:
        Blob URL (= GET でアクセス可能、 token 不要)
    """
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {
        "authorization": f"Bearer {_token()}",
        "x-content-type": "application/json",
        "x-cache-control-max-age": str(cache_control_max_age),
        "x-add-random-suffix": "1" if add_random_suffix else "0",
        "x-api-version": "7",
    }
    url = f"{BLOB_API_BASE}/{pathname}"
    with httpx.Client(timeout=30.0) as client:
        r = client.put(url, headers=headers, content=body)
        r.raise_for_status()
        return r.json()["url"]


def list_jsons(prefix: str = "", *, limit: int = 1000) -> list[dict]:
    """Blob 一覧 を 返す。

    Returns:
        [{"url": "...", "pathname": "...", "size": N, "uploadedAt": "..."}, ...]
    """
    headers = {"authorization": f"Bearer {_token()}", "x-api-version": "7"}
    params: dict = {"limit": str(limit)}
    if prefix:
        params["prefix"] = prefix
    out: list[dict] = []
    cursor: Optional[str] = None
    with httpx.Client(timeout=30.0) as client:
        while True:
            p = dict(params)
            if cursor:
                p["cursor"] = cursor
            r = client.get(BLOB_API_BASE, headers=headers, params=p)
            r.raise_for_status()
            body = r.json()
            out.extend(body.get("blobs", []))
            cursor = body.get("cursor")
            if not cursor or len(out) >= limit:
                break
    return out


def get_json(url: str) -> dict:
    """Blob URL から JSON 取得 (= public URL なので token 不要)。"""
    with httpx.Client(timeout=30.0) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.json()


def delete_blob(url: str) -> None:
    """Blob URL を 削除 (= 管理用)。 TODO: REST endpoint 形式 要確認 (= 404 中)。"""
    headers = {"authorization": f"Bearer {_token()}", "x-api-version": "7"}
    with httpx.Client(timeout=30.0) as client:
        r = client.request(
            "DELETE", BLOB_API_BASE, headers=headers, json={"urls": [url]}
        )
        r.raise_for_status()


def is_configured() -> bool:
    """BLOB_READ_WRITE_TOKEN が 設定されているか (= dev 時 graceful skip 用)。"""
    return bool(os.environ.get("BLOB_READ_WRITE_TOKEN"))
