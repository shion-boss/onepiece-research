# -*- coding: utf-8 -*-
"""公開モード (PUBLIC_MODE) のガード: 研究/管理/重い計算 endpoint を 403、
read+対戦+デッキ CRUD は開けたまま。 [[docs/multiuser_plan.md]] の公開表面制限。"""
from fastapi.testclient import TestClient

import api.main as m

client = TestClient(m.app)


def test_blocked_endpoints_403_in_public_mode(monkeypatch):
    monkeypatch.setenv("PUBLIC_MODE", "1")
    # 研究/管理/重い/生成 系は 403 (= 実行前にミドルウェアで遮断)。
    assert client.post("/api/research/sessions", json={}).status_code == 403
    assert client.post("/api/match", json={}).status_code == 403
    assert client.get("/api/meta/matrix").status_code == 403
    assert client.get("/api/audit/coverage").status_code == 403
    assert client.get("/api/combos/OP01-001").status_code == 403
    assert client.post("/api/decks/generate", json={}).status_code == 403
    assert client.post("/api/decks/build", json={}).status_code == 403


def test_allowed_endpoints_open_in_public_mode(monkeypatch):
    monkeypatch.setenv("PUBLIC_MODE", "1")
    # read + デッキ一覧 は開いている (403 でない)。
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/cards?limit=1").status_code == 200
    assert client.get("/api/decks", headers={"X-Dev-User": "alice"}).status_code == 200
    # 対戦 (human_match) は公開機能なのでガード対象外 (= 403 にはならない)。
    r = client.get("/api/human_match/stats")
    assert r.status_code != 403


def test_not_blocked_without_public_mode(monkeypatch):
    monkeypatch.delenv("PUBLIC_MODE", raising=False)
    # ローカル (研究環境) では研究 endpoint も 403 にならない。
    assert client.get("/api/meta/matrix").status_code != 403
    assert client.get("/api/audit/coverage").status_code != 403
