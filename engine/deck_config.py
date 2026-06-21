# -*- coding: utf-8 -*-
"""per-deck AI config の解決 (= 2026-06-21、 persist→consume の keying 層)。

config は **deck の内容ハッシュ** で keying する (= 同一レシピ = 同一最適 config、 誰の deck でも
共有でき、 user 間の slug 衝突を回避)。 既存の slug-keyed config (= decks/cardrush_* の 53 件) も
後方互換で読む。 解決順: deck_hash → deck_slug → {} (= default、 no-harm)。

tune_deck.py が書き、 ExploitBeam.__init__ → _load_deck_config が読む。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DB = _REPO_ROOT / "db"


def recipe_hash(leader: str, main: list) -> str:
    """leader + main (= [{card_id,count},...]) の安定ハッシュ (= 順序非依存、 12 hex)。

    main 要素は dict ({"card_id","count"}) でも (card_id,count) tuple でも可。
    同一構成なら入力順に依らず同じ hash (= sorted で正規化)。
    """
    norm = []
    for e in main:
        if isinstance(e, dict):
            cid = e.get("card_id") or e.get("id") or ""
            cnt = int(e.get("count", 1))
        else:
            cid, cnt = e[0], int(e[1])
        norm.append((str(cid), cnt))
    norm.sort()
    payload = json.dumps({"leader": str(leader or ""), "main": norm},
                         ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def hash_config_path(h: str) -> Path:
    return _DB / f"deck_ai_config_h{h}.json"


def slug_config_path(slug: str) -> Path:
    return _DB / f"deck_ai_config_{slug}.json"


def _read(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_deck_config(deck_slug: Optional[str] = None,
                     deck_hash: Optional[str] = None) -> dict:
    """deck_hash → deck_slug の順で config を解決 (= 無ければ {})。

    hash 優先 = user deck (内容 keyed) を最特異に解決。 slug fallback = 既存 53 件 + meta 用。
    """
    if deck_hash:
        cfg = _read(hash_config_path(deck_hash))
        if cfg:
            return cfg
    if deck_slug:
        return _read(slug_config_path(deck_slug))
    return {}
