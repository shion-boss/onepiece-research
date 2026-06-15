# -*- coding: utf-8 -*-
"""マルチユーザー化 P2: 認証の抽象化。 [[docs/multiuser_plan.md]]。

`current_user_id` を FastAPI dependency として各 user-scoped endpoint に注入する。
- 開発/テスト (= AUTH_PROVIDER 未設定): `X-Dev-User` ヘッダ → `DEV_USER` env → "local"。
  認証 provider 無しでマルチユーザーの分離ロジックをローカルで検証できる。
- 本番 (= AUTH_PROVIDER=clerk): `_verify_provider` で JWT を検証して sub を返す。
  ⭐ ここが wire-and-go ポイント = Clerk/Auth.js のキーを env に入れて _verify_provider を実装すれば
  本番認証になる (= コード側の他の部分は user_id 文字列しか見ないので不変)。
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import Header, HTTPException, Request

DEV_DEFAULT_USER = "local"


def current_user_id(
    request: Request,
    x_dev_user: Optional[str] = Header(default=None, alias="X-Dev-User"),
) -> str:
    """現在のユーザー id。 user-scoped endpoint に Depends で注入する。"""
    provider = os.environ.get("AUTH_PROVIDER", "").lower()
    if provider:
        uid = _verify_provider(request, provider)
        if not uid:
            raise HTTPException(401, "unauthorized")
        return uid
    # dev / local (= 認証 provider 未設定): ヘッダ or env or 既定ユーザー。
    return x_dev_user or os.environ.get("DEV_USER") or DEV_DEFAULT_USER


def _verify_provider(request: Request, provider: str) -> Optional[str]:
    """本番認証アダプタ (= wire-and-go スロット)。

    TODO(P2 本番配線): Authorization: Bearer <jwt> を取り、 provider のキーで署名検証して
    payload['sub'] を返す。
      - clerk : CLERK_JWT_KEY (env) で JWT 検証 (clerk-sdk-python or PyJWT)。
      - auth.js: 同様に JWKS で検証。
    未実装の現状は None (= 401)。 ローカルは AUTH_PROVIDER 未設定なので此処に来ず dev user で動く。
    """
    return None
