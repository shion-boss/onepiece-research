# -*- coding: utf-8 -*-
"""マイデッキのフォルダ管理 (per-user、 VSCode explorer 風)。 set/rename/remove + API + 隔離。"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.main as m
from api import user_store

MAIN = [{"card_id": "OP04-013", "count": 4}, {"card_id": "EB01-004", "count": 4}]


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(user_store, "_USE_POSTGRES", False)
    monkeypatch.setattr(user_store, "_PH", "?")
    monkeypatch.setattr(user_store, "_USER_DB", tmp_path / "user_data.sqlite")
    monkeypatch.setattr(user_store, "_SCHEMA_READY", False)
    return user_store


def test_store_folder_ops(store):
    store.save_deck("alice", "d1", name="D1", leader="OP04-013", main=MAIN)
    store.save_deck("alice", "d2", name="D2", leader="OP04-013", main=MAIN)
    # 既定はルート ("")
    assert store.get_deck("alice", "d1")["folder"] == ""
    # フォルダへ移動
    assert store.set_deck_folder("alice", "d1", "赤単") is True
    assert store.get_deck("alice", "d1")["folder"] == "赤単"
    # 存在しない slug は False
    assert store.set_deck_folder("alice", "nope", "x") is False
    # リネーム (中の全デッキ)
    store.set_deck_folder("alice", "d2", "赤単")
    assert store.rename_folder("alice", "赤単", "アグロ") == 2
    assert store.get_deck("alice", "d1")["folder"] == "アグロ"
    # 解体 → ルートへ
    assert store.remove_folder("alice", "アグロ") == 2
    assert store.get_deck("alice", "d1")["folder"] == ""


def test_folder_survives_deck_update(store):
    store.save_deck("alice", "d1", name="D1", leader="OP04-013", main=MAIN)
    store.set_deck_folder("alice", "d1", "青")
    # デッキ本体を上書きしても folder は保持される
    store.save_deck("alice", "d1", name="D1b", leader="OP04-013", main=MAIN, overwrite=True)
    assert store.get_deck("alice", "d1")["folder"] == "青"


def test_api_move_folder_and_isolation(store):
    client = TestClient(m.app)
    d = json.loads(Path("decks/cardrush_1342.json").read_text(encoding="utf-8"))
    r = client.post(
        "/api/decks",
        json={"name": "alice deck", "leader": d["leader"], "main": d["main"]},
        headers={"X-Dev-User": "alice"},
    )
    slug = r.json()["slug"]
    # alice が自分のデッキをフォルダへ
    mv = client.post(f"/api/decks/{slug}/folder", json={"folder": "本命"}, headers={"X-Dev-User": "alice"})
    assert mv.status_code == 200, mv.text
    # /api/decks に folder が載る
    alice_decks = client.get("/api/decks", headers={"X-Dev-User": "alice"}).json()
    assert any(x["slug"] == slug and x["folder"] == "本命" for x in alice_decks)
    # bob は alice のデッキを移動できない (自分の DB に無い → 404)
    assert client.post(f"/api/decks/{slug}/folder", json={"folder": "x"}, headers={"X-Dev-User": "bob"}).status_code == 404
    # メタデッキはフォルダ不可 (403)
    assert client.post("/api/decks/cardrush_1342/folder", json={"folder": "x"}, headers={"X-Dev-User": "alice"}).status_code == 403
