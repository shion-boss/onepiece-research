# -*- coding: utf-8 -*-
"""自作(非公開)デッキで 人間 vs AI 対戦できる + 他人のデッキは使えない (P2, human_match)。

deck_a (人間) を auth 付きで per-user DB から resolve し、 session_spec に inline 埋め込む
経路の回帰ガード ([[docs/multiuser_plan.md]])。
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.main as m
from api import user_store


@pytest.fixture
def store(tmp_path, monkeypatch):
    # user_store を temp SQLite に向ける (= 本番 Postgres 汚染しない、 test_user_store と同型)。
    monkeypatch.setattr(user_store, "_USE_POSTGRES", False)
    monkeypatch.setattr(user_store, "_PH", "?")
    monkeypatch.setattr(user_store, "_USER_DB", tmp_path / "user_data.sqlite")
    monkeypatch.setattr(user_store, "_SCHEMA_READY", False)
    return user_store


def _meta_recipe() -> dict:
    return json.loads(Path("decks/cardrush_1342.json").read_text(encoding="utf-8"))


def test_human_match_with_private_deck_and_isolation(store):
    client = TestClient(m.app)
    d = _meta_recipe()

    # alice が自分の非公開デッキを作る (メタ recipe を借用 = valid な 50 枚)。
    r = client.post(
        "/api/decks",
        json={"name": "alice secret", "leader": d["leader"], "main": d["main"]},
        headers={"X-Dev-User": "alice"},
    )
    assert r.status_code == 201, r.text
    slug = r.json()["slug"]

    # alice は自分のデッキで対戦を開始でき、 spec に inline recipe が載る (= 自己完結 reconstruct)。
    start = client.post(
        "/api/human_match",
        json={"deck_a_slug": slug, "deck_b_slug": "cardrush_1385", "seed": 1, "human_first": True},
        headers={"X-Dev-User": "alice"},
    )
    assert start.status_code == 200, start.text
    body = start.json()
    assert body["session_id"]
    inline = body["session_spec"]["deck_a_inline"]
    assert inline and inline["leader"] == d["leader"]
    assert sum(e["count"] for e in inline["main"]) == 50

    # bob は alice のデッキ slug では対戦を開始できない (自分の DB に無い → 404)。
    bob = client.post(
        "/api/human_match",
        json={"deck_a_slug": slug, "deck_b_slug": "cardrush_1385", "seed": 1, "human_first": True},
        headers={"X-Dev-User": "bob"},
    )
    assert bob.status_code == 404, bob.text


def test_meta_deck_still_playable_as_human_side(store):
    """メタデッキを人間側に選んでも従来通り対戦開始できる (slug 解決の後方互換)。"""
    client = TestClient(m.app)
    start = client.post(
        "/api/human_match",
        json={"deck_a_slug": "cardrush_1342", "deck_b_slug": "cardrush_1385", "seed": 2, "human_first": True},
        headers={"X-Dev-User": "alice"},
    )
    assert start.status_code == 200, start.text
    assert start.json()["session_id"]
