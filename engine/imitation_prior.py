# -*- coding: utf-8 -*-
"""Plan Imit-3 (= 2026-05-18): imitation patterns から AI の plan_search に prior 注入。

db/imitation_patterns.json (= 93 大会優勝レシピから抽出) を load して
「人間が選ぶカード」 の prior を返す。 plan_search が これを bonus 化して
「人間プレイヤーが選びそうな action」 を beam に優先入れる。

API:
  get_card_play_prior(leader_id, card_id) -> float
    0.0 = 採用率 0% (= 人間は選ばない)
    1.0 = 採用率 100% (= 人間は必ず選ぶ)
    間は線形 interpolation
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional


_CACHE: Optional[dict] = None


def _default_path() -> Path:
    return Path(__file__).resolve().parent.parent / "db" / "imitation_patterns.json"


def _load() -> Optional[dict]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    if os.environ.get("ONEPIECE_IMITATION_DISABLE"):
        return None
    path = _default_path()
    if not path.exists():
        return None
    try:
        _CACHE = json.loads(path.read_text(encoding="utf-8"))
        return _CACHE
    except Exception as e:
        print(f"[imitation_prior] load failed: {e}")
        return None


def reload_imitation_data() -> None:
    """テスト用 cache reset。"""
    global _CACHE
    _CACHE = None


def get_card_play_prior(leader_id: str, card_id: str) -> float:
    """leader_id (= archetype) の優勝レシピで card_id の採用率を返す (= 0.0 - 1.0)。

    leader_id が patterns に無ければ 0.5 (= neutral)。
    card_id が この archetype で見つからなければ 0.1 (= ほぼ採用されない)。
    """
    data = _load()
    if data is None:
        return 0.5
    patterns = data.get("patterns", {}).get(leader_id)
    if not patterns:
        return 0.5  # archetype 未知 = neutral

    # core + optional 全部走査
    for c in patterns.get("core_cards", []):
        if c.get("card_id") == card_id:
            return float(c.get("adoption_rate", 0))
    for c in patterns.get("optional_cards", []):
        if c.get("card_id") == card_id:
            return float(c.get("adoption_rate", 0))
    return 0.1  # この archetype で 採用率低い カード


def get_mulligan_priority(leader_id: str, card_id: str) -> float:
    """mulligan keep 候補としての priority (= 0.0 - 1.0)。

    1-2 cost で 採用率 50%+ のカードは high priority。
    """
    data = _load()
    if data is None:
        return 0.5
    patterns = data.get("patterns", {}).get(leader_id)
    if not patterns:
        return 0.5
    for c in patterns.get("mulligan_keep_candidates", []):
        if c.get("card_id") == card_id:
            return float(c.get("adoption_rate", 0))
    return 0.2  # mulligan candidate じゃない
