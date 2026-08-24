# -*- coding: utf-8 -*-
"""`db/card_effects.json` のキーは **cards.json に実在するカード id** であること。

⚠ 2026-08-24: `P-081` のエントリが残っていたが、 cards.json に `P-081` は無く
  実在は `P-081_p1` / `P-081_p2` / `P-081_r1` (3 つとも自前の overlay を持つ)。
  = **到達不能な死んだキー**。 さらに `CardRepository` は `P-081` を `P-081_p2` に
  **暗黙エイリアス** するので、 効果の発火元とキーが食い違い、 候補リッチ掃引が
  偽 MISMATCH を出していた。 データ側を掃除するのが正解。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_all_overlay_keys_exist_in_cards_json():
    cj = json.loads((ROOT / "db" / "cards.json").read_text())
    cards = cj if isinstance(cj, list) else cj.get("cards", [])
    ids = {c["card_id"] for c in cards}
    ov = json.loads((ROOT / "db" / "card_effects.json").read_text())
    entries = ov["cards"] if isinstance(ov.get("cards"), dict) else ov
    missing = sorted(k for k in entries if not k.startswith("_") and k not in ids)
    assert not missing, (
        "cards.json に存在しない card_id の overlay エントリ (= 到達不能 / "
        f"CardRepository の暗黙エイリアスで別カードに化ける): {missing}"
    )
