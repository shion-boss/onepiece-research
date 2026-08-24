# -*- coding: utf-8 -*-
"""`state_encoder.KNOWN_LEADER_IDS` が **実在するカード id** で構成されている。

⚠ 2026-08-24 まで 16 件中 **10 件が `"OP09-XXX"` 等のプレースホルダ** で、 該当リーダーが
  one-hot に一生載らなかった (= 常に unknown)。 さらに実在した 6 件にも
  「`OP14-079` = 緑紫ドフラ (1342)」 という誤ラベルがあった (実際は黒クロコダイル、
  1342 は `OP14-060`)。 = **黙って劣化する型** なので機械で守る。
"""
from __future__ import annotations

import json
import glob
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_all_leader_ids_exist_in_card_db():
    from engine.deck import CardRepository
    from engine.state_encoder import KNOWN_LEADER_IDS

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    bad = []
    for lid in KNOWN_LEADER_IDS:
        try:
            c = repo.get(lid)
        except Exception:
            bad.append((lid, "カードDBに存在しない"))
            continue
        if c is None:
            bad.append((lid, "カードDBに存在しない"))
        elif str(getattr(c.category, "value", c.category)).upper() != "LEADER":
            bad.append((lid, f"LEADER でない ({c.category})"))
    assert not bad, f"KNOWN_LEADER_IDS に不正な id: {bad}"


def test_no_placeholder_ids():
    from engine.state_encoder import KNOWN_LEADER_IDS

    ph = [x for x in KNOWN_LEADER_IDS if "XXX" in x or not x.strip()]
    assert not ph, f"プレースホルダが残っている: {ph}"


def test_one_hot_is_injective():
    from engine.state_encoder import KNOWN_LEADER_IDS, LEADER_ID_TO_IDX

    assert len(set(KNOWN_LEADER_IDS)) == len(KNOWN_LEADER_IDS), "重複がある"
    assert len(LEADER_ID_TO_IDX) == len(KNOWN_LEADER_IDS)


def test_covers_the_deck_pool_leaders():
    """デッキプールに居るリーダーが **全部** one-hot に載る (= unknown に落ちない)。"""
    from engine.state_encoder import LEADER_ID_TO_IDX

    pool = set()
    for p in sorted(glob.glob(str(ROOT / "decks" / "cardrush_*.json"))):
        if ".analysis." in p or ".target_v" in p:
            continue
        d = json.load(open(p))
        lid = d.get("leader_id") or d.get("leader")
        if lid:
            pool.add(str(lid))
    missing = sorted(pool - set(LEADER_ID_TO_IDX))
    assert not missing, f"プールに居るのに one-hot に無いリーダー: {missing}"
