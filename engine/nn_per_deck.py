# -*- coding: utf-8 -*-
"""per-deck NN preference (= 2026-05-17 adaptive AI selection)。

絶対強度測定 (= run_absolute_strength.py) で 各デッキで NN-on と NN-off の vs Greedy
勝率を測定 → NN を使う方が強いデッキだけ NN-on にする。

`db/nn_per_deck_preference.json` (= 自動生成 or 手書き):
{
  "default": false,  // default は NN-off (= 線形 eval)
  "preferences": {
    "tcgportal_coby": true,        // NN-on
    "cardrush_1439": true,
    "tcgportal_bonney": true,
    // 残りは default (= false)
  },
  "deltas": {                       // 参考 (= 絶対強度 delta in pt)
    "tcgportal_coby": 24.0,
    ...
  }
}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

_CACHE: Optional[dict] = None


def _config_path() -> Path:
    return Path(__file__).resolve().parent.parent / "db" / "nn_per_deck_preference.json"


def _load_config() -> dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    path = _config_path()
    if not path.exists():
        _CACHE = {"default": False, "preferences": {}}
        return _CACHE
    try:
        _CACHE = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[nn_per_deck] config load failed: {e}")
        _CACHE = {"default": False, "preferences": {}}
    return _CACHE


def reload_config() -> None:
    """テスト用 / config 更新後の cache reset。"""
    global _CACHE
    _CACHE = None


def should_use_nn(deck_slug: Optional[str]) -> bool:
    """deck_slug に対して NN を使うべきか判定。

    deck_slug が None / 不明 → default (= 通常は False = 線形 eval) を返す。
    config file 不在時は default=False。
    """
    cfg = _load_config()
    default = bool(cfg.get("default", False))
    if not deck_slug:
        return default
    prefs = cfg.get("preferences", {})
    return bool(prefs.get(deck_slug, default))
