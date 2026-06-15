# -*- coding: utf-8 -*-
"""マルチユーザー化 P2: user_store の per-user 隔離 (= 他人のデッキは見えない/消せない)。
SQLite (ローカル/テスト) で検証。 本番は DATABASE_URL=Postgres で同 I/F。"""
import pytest

from api import user_store

MAIN = [{"card_id": "OP04-013", "count": 4}, {"card_id": "EB01-004", "count": 4}]


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(user_store, "_USE_POSTGRES", False)
    monkeypatch.setattr(user_store, "_PH", "?")
    monkeypatch.setattr(user_store, "_USER_DB", tmp_path / "user_data.sqlite")
    monkeypatch.setattr(user_store, "_SCHEMA_READY", False)
    return user_store


def test_per_user_isolation(store):
    store.save_deck("alice", "my-pell", name="Pell", leader="OP04-013", main=MAIN)
    # alice には見える、 bob には見えない
    assert [d["slug"] for d in store.list_decks("alice")] == ["my-pell"]
    assert store.list_decks("bob") == []
    assert store.get_deck("alice", "my-pell") is not None
    assert store.get_deck("bob", "my-pell") is None  # 他人のは取得不可
    # main が JSON ラウンドトリップする
    assert store.get_deck("alice", "my-pell")["main"] == MAIN


def test_cross_user_delete_fails(store):
    store.save_deck("alice", "d1", name="d", leader="OP04-013", main=MAIN)
    assert store.delete_deck("bob", "d1") is False  # 他人は消せない
    assert store.get_deck("alice", "d1") is not None  # 残っている
    assert store.delete_deck("alice", "d1") is True   # 本人は消せる
    assert store.get_deck("alice", "d1") is None


def test_api_auth_scopes_decks(store):
    """エンドポイント越し (TestClient + X-Dev-User) で auth + 隔離が効く。"""
    import json
    from pathlib import Path
    from fastapi.testclient import TestClient
    import api.main as m

    client = TestClient(m.app)
    d = json.loads((Path("decks/cardrush_1342.json")).read_text(encoding="utf-8"))
    body = {"name": "alice deck", "leader": d["leader"], "main": d["main"]}

    r = client.post("/api/decks", json=body, headers={"X-Dev-User": "alice"})
    assert r.status_code == 201, r.text
    slug = r.json()["slug"]

    alice = {x["slug"] for x in client.get("/api/decks", headers={"X-Dev-User": "alice"}).json()}
    bob = {x["slug"] for x in client.get("/api/decks", headers={"X-Dev-User": "bob"}).json()}
    assert slug in alice and slug not in bob          # 自分のだけ見える
    # メタは両者に見える
    assert "cardrush_1342" in alice and "cardrush_1342" in bob

    # bob は alice のデッキを消せない / メタも消せない
    assert client.delete(f"/api/decks/{slug}", headers={"X-Dev-User": "bob"}).status_code == 404
    assert client.delete("/api/decks/cardrush_1342", headers={"X-Dev-User": "alice"}).status_code == 403
    # alice は自分のを消せる
    assert client.delete(f"/api/decks/{slug}", headers={"X-Dev-User": "alice"}).status_code == 204


def test_slug_collision_per_owner(store):
    store.save_deck("alice", "x", name="A", leader="OP04-013", main=MAIN)
    with pytest.raises(ValueError):
        store.save_deck("alice", "x", name="A2", leader="OP04-013", main=MAIN)  # 上書き禁止
    store.save_deck("alice", "x", name="A2", leader="OP04-013", main=MAIN, overwrite=True)
    assert store.get_deck("alice", "x")["name"] == "A2"
    # 別ユーザーは同じ slug を独立に持てる
    store.save_deck("bob", "x", name="B", leader="OP04-013", main=MAIN)
    assert store.get_deck("bob", "x")["name"] == "B"
