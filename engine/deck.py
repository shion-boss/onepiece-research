# -*- coding: utf-8 -*-
"""
デッキの読み込み / バリデーション
================================

サンプルデッキ JSON フォーマット:
{
  "name": "デッキ名",
  "leader": "OP01-001",
  "main": [
    {"card_id": "OP01-013", "count": 4},
    ...
  ]
}
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .core import CardDef, Category

_BANLIST_PATH = Path(__file__).resolve().parent.parent / "db" / "banlist" / "master.json"


# --------------------------------------------------------------------------- #
# CardRepository: cards.sqlite or cards.json から CardDef をロード
# --------------------------------------------------------------------------- #
class CardRepository:
    """カード定義のリポジトリ。card_id -> CardDef のルックアップを提供。"""

    def __init__(self, by_id: dict[str, CardDef]):
        self._by_id = by_id

    @classmethod
    def from_json(cls, json_path: str | Path) -> "CardRepository":
        rows = json.loads(Path(json_path).read_text(encoding="utf-8"))
        # 通常版を優先(variant が空のものを採用)。同名のパラレルは無視。
        by_id: dict[str, CardDef] = {}
        for row in rows:
            cd = CardDef.from_db_row(row)
            # base_id 単位で重複を統合(パラレルは効果同じなので)
            base_id = row.get("base_id", cd.card_id)
            existing = by_id.get(base_id)
            if existing is None or row.get("variant", ""):
                if existing is None:
                    by_id[base_id] = cd
            else:
                # variant 空の方を残す
                if not row.get("variant"):
                    by_id[base_id] = cd
            # card_id (variant 込み) でもアクセスできるように
            by_id[cd.card_id] = cd
        return cls(by_id)

    @classmethod
    def from_sqlite(cls, db_path: str | Path) -> "CardRepository":
        # マウント FS の SQLite が扱えない場合は事前にコピーしてからどうぞ
        con = sqlite3.connect(str(db_path))
        con.row_factory = sqlite3.Row
        by_id: dict[str, CardDef] = {}
        for r in con.execute("SELECT * FROM cards"):
            row = dict(r)
            cd = CardDef.from_db_row(row)
            by_id[cd.card_id] = cd
        con.close()
        return cls(by_id)

    def get(self, card_id: str) -> CardDef:
        cd = self._by_id.get(card_id)
        if cd is None:
            # base_id でも探す
            base = card_id.split("_", 1)[0]
            cd = self._by_id.get(base)
        if cd is None:
            raise KeyError(f"カード未登録: {card_id}")
        return cd


# --------------------------------------------------------------------------- #
# Deck
# --------------------------------------------------------------------------- #
@dataclass
class DeckList:
    name: str
    leader: CardDef
    main: list[CardDef]   # 50 枚に展開済み

    @classmethod
    def from_json(
        cls,
        json_path: str | Path,
        repo: CardRepository,
    ) -> "DeckList":
        d = json.loads(Path(json_path).read_text(encoding="utf-8"))
        leader = repo.get(d["leader"])
        if leader.category != Category.LEADER:
            raise ValueError(f"{leader.card_id} はリーダーではない")
        main: list[CardDef] = []
        for entry in d.get("main", []):
            card = repo.get(entry["card_id"])
            if card.category == Category.LEADER:
                raise ValueError(f"メインデッキにリーダーは入れられない: {card.card_id}")
            main.extend([card] * int(entry.get("count", 1)))
        return cls(name=d.get("name", "(no name)"), leader=leader, main=main)

    def validate(self, banlist: Optional[dict] = None) -> list[str]:
        """構築ルールチェック。違反のリストを返す(空なら合法)。

        banlist=None の場合 `db/banlist/master.json` を自動ロード。
        banlist={} (空 dict) を渡すと banlist チェックをスキップ。
        """
        problems: list[str] = []
        if len(self.main) != 50:
            problems.append(f"メインデッキ枚数が50枚ではない: {len(self.main)}")
        # 同名4枚まで。base_id (パラレル `_p1` 等を除いた本体ID) で集計するため、
        # 同カードの再録/パラレル違いを 4枚制限の対象として正しく扱う。
        from collections import Counter

        c = Counter(_base_id(card.card_id) for card in self.main)
        for bid, n in c.items():
            if n > 4:
                problems.append(f"同名カード4枚制限違反: {bid} x {n}")
        # 色制約: リーダーの色のみ採用可能
        leader_colors = set(self.leader.color)
        for card in self.main:
            card_colors = set(card.color)
            if not (card_colors & leader_colors):
                problems.append(
                    f"リーダーの色{leader_colors}に含まれない色のカード: "
                    f"{card.card_id} ({card_colors})"
                )

        # 禁止 / 制限 / 禁止ペアの検証 (大会公式ルール)
        if banlist is None:
            banlist = _load_banlist()
        if banlist:
            problems.extend(_check_banlist(self, c, banlist))

        return problems


def _base_id(card_id: str) -> str:
    """`OP06-049_p1` -> `OP06-049`。区切りはアンダースコア。"""
    return card_id.split("_", 1)[0]


def _load_banlist() -> dict:
    if not _BANLIST_PATH.exists():
        return {}
    try:
        return json.loads(_BANLIST_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _check_banlist(deck: "DeckList", base_id_counts, banlist: dict) -> list[str]:
    """禁止 / 制限 / 禁止ペアの検証。

    - 禁止カード: 1 枚でも入っていれば違反
    - 制限カード: 2 枚以上で違反 (1 枚までは可)
    - 禁止ペア: A と B が両方入っているデッキは違反 (リーダーも対象)
    """
    problems: list[str] = []
    leader_bid = _base_id(deck.leader.card_id)

    forbidden_ids = {c["card_id"] for c in banlist.get("forbidden", [])}
    restricted_ids = {c["card_id"] for c in banlist.get("restricted", [])}

    for bid, n in base_id_counts.items():
        if bid in forbidden_ids:
            problems.append(f"禁止カード採用: {bid} x {n}")
        if bid in restricted_ids and n > 1:
            problems.append(f"制限カード 1 枚制限違反: {bid} x {n}")

    # 禁止ペア (リーダー含めて bid セットを作る)
    deck_bids = set(base_id_counts.keys()) | {leader_bid}
    for pair in banlist.get("forbidden_pairs", []):
        a_bid = pair["a"]["card_id"]
        b_bid = pair["b"]["card_id"]
        if a_bid in deck_bids and b_bid in deck_bids:
            problems.append(
                f"禁止ペア違反: {a_bid} ({pair['a'].get('name','')}) と "
                f"{b_bid} ({pair['b'].get('name','')}) を同時採用"
            )

    return problems


def make_deck_from_dict(d: dict, repo: CardRepository) -> DeckList:
    """JSON ファイルではなく辞書から作る。テストやプログラム生成に便利。"""
    leader = repo.get(d["leader"])
    main: list[CardDef] = []
    for entry in d.get("main", []):
        card = repo.get(entry["card_id"])
        main.extend([card] * int(entry.get("count", 1)))
    return DeckList(name=d.get("name", "(no name)"), leader=leader, main=main)
