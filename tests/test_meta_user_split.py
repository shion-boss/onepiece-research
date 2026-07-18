# -*- coding: utf-8 -*-
"""マルチユーザー化 P1: メタ/ユーザーデッキの明示分離 (= db/meta_decks.json 登録制)。
接頭辞ハック撤去の回帰ガード ([[docs/multiuser_plan.md]])。"""
import pytest

import api.main as m


def test_meta_registry_is_canonical_set():
    metas = m._meta_deck_slugs_set()
    assert len(metas) == 24  # 16 base + pros02由来7新デッキ + 黒黄ティーチ登録 (2026-07-18)
    assert m._is_meta_deck("cardrush_1342")
    assert m._is_meta_deck("tcgportal_coby")
    assert not m._is_meta_deck("user_anything")
    # deck-gen の環境 pool は登録制と一致 (= ユーザーデッキ混入なし)
    assert set(m._meta_pool_slugs()) == set(metas)


def test_listing_tags_kind():
    decks = m.list_decks(user_id="testuser")  # P2: user_id 依存を直呼びで渡す
    assert decks
    assert all(d.kind in ("meta", "user") for d in decks)
    meta_slugs = {d.slug for d in decks if d.kind == "meta"}
    assert {"cardrush_1342", "tcgportal_coby"} <= meta_slugs


def test_all_meta_decks_protected_from_delete():
    """旧来は cardrush_ だけ保護で tcgportal_ メタは無防備だった。 登録制で全メタ保護。"""
    from fastapi import HTTPException

    for slug in ("cardrush_1342", "tcgportal_coby"):
        with pytest.raises(HTTPException) as ei:
            m.delete_deck(slug, user_id="testuser")
        assert ei.value.status_code == 403
