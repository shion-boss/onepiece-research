# -*- coding: utf-8 -*-
"""マルチユーザー化 P2: 認証の抽象化。 [[docs/multiuser_plan.md]]。

`current_user_id` を FastAPI dependency として各 user-scoped endpoint に注入する。
- 開発/テスト (= AUTH_PROVIDER 未設定): `X-Dev-User` ヘッダ → `DEV_USER` env → "local"。
  認証 provider 無しでマルチユーザーの分離ロジックをローカルで検証できる。
- 本番 (= AUTH_PROVIDER=clerk): `_verify_provider` で `Authorization: Bearer <jwt>` を
  検証して sub (= Clerk user id) を返す。 コード側の他の部分は user_id 文字列しか見ないので、
  provider を差し替えても不変。

## Clerk 本番配線 (env)
- `AUTH_PROVIDER=clerk`             — これが有効化スイッチ。 未設定ならローカル dev user。
- 鍵はどちらか一方:
  - `CLERK_JWT_KEY`  = Clerk Dashboard の PEM 公開鍵 (= 単一鍵・ネットワーク不要、 serverless 向き)。
  - `CLERK_JWKS_URL` = JWKS エンドポイント (= 鍵ローテーション対応)。 未指定でも
    `CLERK_ISSUER` があれば `<issuer>/.well-known/jwks.json` を導出する。
- 任意の追加検証:
  - `CLERK_ISSUER`            — `iss` を検証 (例 https://xxx.clerk.accounts.dev)。
  - `CLERK_AUTHORIZED_PARTY`  — `azp` (発行元オリジン) を検証。
"""
from __future__ import annotations

import os
from functools import lru_cache
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
        # _verify_provider が失敗理由入りの 401 を raise する (= 診断用に detail に出す)。
        return _verify_provider(request, provider)
    # dev / local (= 認証 provider 未設定): ヘッダ or env or 既定ユーザー。
    return x_dev_user or os.environ.get("DEV_USER") or DEV_DEFAULT_USER


def optional_user_id(
    request: Request,
    x_dev_user: Optional[str] = Header(default=None, alias="X-Dev-User"),
) -> Optional[str]:
    """ログイン済みなら user_id、 未ログイン(ゲスト)なら None を返す (= 401 は投げない)。

    ゲストにも一部開放する endpoint 用 (= 人vsAI対戦[meta限定]・meta デッキ閲覧 等)。
    - 本番 (AUTH_PROVIDER=clerk): Bearer トークンがあり検証成功 → user_id、 無い/無効 → None(ゲスト)。
    - dev (provider 未設定): dev user (X-Dev-User → DEV_USER → "local")。 認証なし = ゲスト概念なし。
    """
    provider = os.environ.get("AUTH_PROVIDER", "").lower()
    if provider:
        if not _bearer_token(request):
            return None
        try:
            return _verify_provider(request, provider)
        except HTTPException:
            return None  # 無効/期限切れトークンはゲスト扱い (= optional なので拒否しない)
    return x_dev_user or os.environ.get("DEV_USER") or DEV_DEFAULT_USER


def _bearer_token(request: Request) -> Optional[str]:
    """`Authorization: Bearer <token>` から token を抜く。 無ければ None。"""
    auth = request.headers.get("authorization")
    if not auth:
        return None
    parts = auth.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip() or None
    return None


def _verify_provider(request: Request, provider: str) -> str:
    """本番認証アダプタ。 検証成功で user_id (= JWT `sub`) を返す。 失敗は 401。

    401 の detail は generic ("unauthorized") にして詳細は漏らさない。 失敗理由は
    サーバー側ログ (print) にだけ出す (= 診断用)。
    """
    if provider != "clerk":
        raise HTTPException(401, "unauthorized")
    token = _bearer_token(request)
    if not token:
        print("[auth] clerk: request had no Bearer token")
        raise HTTPException(401, "unauthorized")
    try:
        claims = _decode_clerk_jwt(token)
    except Exception as e:
        print(f"[auth] clerk: JWT verify failed: {type(e).__name__}: {e}")
        raise HTTPException(401, "unauthorized")
    sub = claims.get("sub")
    if not sub:
        print("[auth] clerk: token verified but no 'sub' claim")
        raise HTTPException(401, "unauthorized")
    return sub


def _decode_clerk_jwt(token: str) -> dict:
    """Clerk の session JWT (RS256) を検証して claims を返す。 失敗時は例外。"""
    import jwt  # PyJWT

    key, algorithms = _clerk_key_for(token)
    issuer = os.environ.get("CLERK_ISSUER") or None
    claims = jwt.decode(
        token,
        key,
        algorithms=algorithms,
        issuer=issuer,  # None なら iss 検証しない
        leeway=5,
        options={"require": ["exp", "sub"], "verify_aud": False},
    )
    azp = os.environ.get("CLERK_AUTHORIZED_PARTY") or None
    if azp:
        token_azp = claims.get("azp")
        # azp が付いている場合のみ突合 (Clerk は付けることが多いが必須ではない)。
        if token_azp and token_azp != azp:
            raise ValueError("azp mismatch")
    return claims


def _clerk_key_for(token: str):
    """検証鍵と許可アルゴリズムを返す。 PEM 静的鍵を優先し、 無ければ JWKS。"""
    pem = os.environ.get("CLERK_JWT_KEY")
    if pem:
        # env に格納された PEM は改行が \n エスケープされていることがある。
        return pem.replace("\\n", "\n"), ["RS256"]

    jwks_url = os.environ.get("CLERK_JWKS_URL")
    if not jwks_url:
        issuer = os.environ.get("CLERK_ISSUER")
        if issuer:
            jwks_url = issuer.rstrip("/") + "/.well-known/jwks.json"
    if not jwks_url:
        raise ValueError("Clerk 鍵未設定: CLERK_JWT_KEY か CLERK_JWKS_URL/CLERK_ISSUER が要る")

    signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token)
    return signing_key.key, ["RS256"]


@lru_cache(maxsize=4)
def _jwks_client(url: str):
    """JWKS クライアント (URL 毎にキャッシュ、 鍵も内部キャッシュされる)。"""
    import jwt

    return jwt.PyJWKClient(url, cache_keys=True)
