# -*- coding: utf-8 -*-
"""Clerk 認証アダプタ (api/auth.py:_verify_provider) の単体テスト。

実 Clerk は使えないので、 自前の RSA 鍵で RS256 JWT を発行し、 公開鍵 PEM を
`CLERK_JWT_KEY` に流し込んで検証経路を通す (= Clerk の PEM 公開鍵モードと同型)。
"""
from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from api import auth


class _FakeRequest:
    """Starlette Request の headers.get だけを模す軽量ダブル。"""

    def __init__(self, headers: dict):
        self.headers = {k.lower(): v for k, v in headers.items()}


@pytest.fixture()
def rsa_keys():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub_pem = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return priv_pem, pub_pem


def _make_token(priv_pem: str, *, sub="user_abc", exp_delta=3600, **extra) -> str:
    now = int(time.time())
    payload = {"sub": sub, "iat": now, "nbf": now, "exp": now + exp_delta, **extra}
    return jwt.encode(payload, priv_pem, algorithm="RS256")


def _clerk_env(monkeypatch, pub_pem: str, **extra):
    monkeypatch.setenv("AUTH_PROVIDER", "clerk")
    monkeypatch.setenv("CLERK_JWT_KEY", pub_pem)
    for k, v in extra.items():
        monkeypatch.setenv(k, v)
    # JWKS 経路に落ちないよう明示的に消す。
    monkeypatch.delenv("CLERK_JWKS_URL", raising=False)
    auth._jwks_client.cache_clear()


def test_valid_token_returns_sub(monkeypatch, rsa_keys):
    priv, pub = rsa_keys
    _clerk_env(monkeypatch, pub)
    req = _FakeRequest({"Authorization": f"Bearer {_make_token(priv, sub='user_42')}"})
    assert auth.current_user_id(req, None) == "user_42"


def test_missing_bearer_is_401(monkeypatch, rsa_keys):
    priv, pub = rsa_keys
    _clerk_env(monkeypatch, pub)
    with pytest.raises(Exception) as ei:
        auth.current_user_id(_FakeRequest({}), None)
    assert getattr(ei.value, "status_code", None) == 401


def test_bad_signature_is_401(monkeypatch, rsa_keys):
    priv, pub = rsa_keys
    # 別鍵で署名 → pub では検証できない。
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_pem = other.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    _clerk_env(monkeypatch, pub)
    req = _FakeRequest({"Authorization": f"Bearer {_make_token(other_pem)}"})
    with pytest.raises(Exception) as ei:
        auth.current_user_id(req, None)
    assert getattr(ei.value, "status_code", None) == 401


def test_expired_token_is_401(monkeypatch, rsa_keys):
    priv, pub = rsa_keys
    _clerk_env(monkeypatch, pub)
    req = _FakeRequest({"Authorization": f"Bearer {_make_token(priv, exp_delta=-10)}"})
    with pytest.raises(Exception) as ei:
        auth.current_user_id(req, None)
    assert getattr(ei.value, "status_code", None) == 401


def test_issuer_mismatch_is_401(monkeypatch, rsa_keys):
    priv, pub = rsa_keys
    _clerk_env(monkeypatch, pub, CLERK_ISSUER="https://good.clerk.accounts.dev")
    tok = _make_token(priv, iss="https://evil.example.com")
    req = _FakeRequest({"Authorization": f"Bearer {tok}"})
    with pytest.raises(Exception) as ei:
        auth.current_user_id(req, None)
    assert getattr(ei.value, "status_code", None) == 401


def test_issuer_match_ok(monkeypatch, rsa_keys):
    priv, pub = rsa_keys
    _clerk_env(monkeypatch, pub, CLERK_ISSUER="https://good.clerk.accounts.dev")
    tok = _make_token(priv, sub="user_iss", iss="https://good.clerk.accounts.dev")
    req = _FakeRequest({"Authorization": f"Bearer {tok}"})
    assert auth.current_user_id(req, None) == "user_iss"


def test_azp_mismatch_is_401(monkeypatch, rsa_keys):
    priv, pub = rsa_keys
    _clerk_env(monkeypatch, pub, CLERK_AUTHORIZED_PARTY="https://app.example.com")
    tok = _make_token(priv, azp="https://evil.example.com")
    req = _FakeRequest({"Authorization": f"Bearer {tok}"})
    with pytest.raises(Exception) as ei:
        auth.current_user_id(req, None)
    assert getattr(ei.value, "status_code", None) == 401


def test_dev_mode_without_provider(monkeypatch):
    """AUTH_PROVIDER 未設定なら X-Dev-User → 既定 local。"""
    monkeypatch.delenv("AUTH_PROVIDER", raising=False)
    monkeypatch.delenv("DEV_USER", raising=False)
    assert auth.current_user_id(_FakeRequest({}), "alice") == "alice"
    assert auth.current_user_id(_FakeRequest({}), None) == "local"
