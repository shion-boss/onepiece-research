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
_CARDS_PATH = Path(__file__).resolve().parent.parent / "db" / "cards.json"

_MAX_BLOCK_CACHE: Optional[dict[str, int]] = None

# SPR 判定に使うセンチネル値 (Standard 無条件許可)
_SPR_SENTINEL = 999


def _load_max_block_by_base_id() -> dict[str, int]:
    """base_id ごとの Standard 判定用ブロック値を返す。

    - 再録版がある場合: 全バリアントの最大 block_icon
    - SPカード (スーパーパラレルレア) 版がある場合: _SPR_SENTINEL (=999)
      → 公式規定「SPR と同一ナンバーのカードは再録有無に関わらず Standard 使用可」
    """
    global _MAX_BLOCK_CACHE
    if _MAX_BLOCK_CACHE is not None:
        return _MAX_BLOCK_CACHE
    result: dict[str, int] = {}
    try:
        rows = json.loads(_CARDS_PATH.read_text(encoding="utf-8"))
        for row in rows:
            base = row.get("base_id") or row.get("card_id", "")
            b = int(row.get("block_icon", 0))
            # SPR 版があれば sentinel をセット (以降はこれより大きい値は来ない)
            if row.get("rarity") == "SPカード":
                result[base] = _SPR_SENTINEL
            elif result.get(base, 0) < _SPR_SENTINEL:
                result[base] = max(result.get(base, 0), b)
    except (json.JSONDecodeError, OSError):
        pass
    _MAX_BLOCK_CACHE = result
    return result


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
    slug: Optional[str] = None  # decks/<slug>.json 由来 (analysis ロードに使う)
    regulation: str = "standard"  # "standard" | "extra"

    @classmethod
    def from_json(
        cls,
        json_path: str | Path,
        repo: CardRepository,
    ) -> "DeckList":
        path_obj = Path(json_path)
        d = json.loads(path_obj.read_text(encoding="utf-8"))
        leader = repo.get(d["leader"])
        if leader.category != Category.LEADER:
            raise ValueError(f"{leader.card_id} はリーダーではない")
        main: list[CardDef] = []
        for entry in d.get("main", []):
            card = repo.get(entry["card_id"])
            if card.category == Category.LEADER:
                raise ValueError(f"メインデッキにリーダーは入れられない: {card.card_id}")
            main.extend([card] * int(entry.get("count", 1)))
        # ファイル名 (拡張子無し) を slug にデフォルトで採用 (decks/cardrush_1429.json → cardrush_1429)
        slug = d.get("slug") or path_obj.stem
        return cls(
            name=d.get("name", "(no name)"),
            leader=leader,
            main=main,
            slug=slug,
            regulation=d.get("regulation", "standard"),
        )

    def validate(self, banlist: Optional[dict] = None) -> list[str]:
        """構築ルールチェック。違反のリストを返す(空なら合法)。

        banlist=None の場合 `db/banlist/master.json` を自動ロード。
        banlist={} (空 dict) を渡すと banlist チェックをスキップ。
        regulation は self.regulation を参照する ("standard" | "extra")。
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
            # スタンダードレギュレーション: 使用可能ブロックのチェック
            if self.regulation == "standard":
                problems.extend(_check_standard_block(self, banlist))

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


def _check_standard_block(deck: "DeckList", banlist: dict) -> list[str]:
    """スタンダードレギュレーションのブロックアイコン制限チェック。

    banlist の standard_min_block 以上のカードのみ使用可。
    同一 base_id に Standard 対応の再録版が存在すれば違反としない
    (物理プレイで再録版を持参可能なため)。
    """
    problems: list[str] = []
    min_block: int = banlist.get("standard_min_block", 2)
    max_block_map = _load_max_block_by_base_id()
    seen: set[str] = set()
    for card in [deck.leader] + deck.main:
        bid = _base_id(card.card_id)
        if bid in seen:
            continue
        seen.add(bid)
        # base_id の最大 block_icon で判定 (再録版が Standard 対応なら OK)
        max_block = max_block_map.get(bid, card.block_icon)
        if max_block < min_block:
            problems.append(
                f"スタンダード使用不可 (block①のみ): {card.card_id} {card.name}"
            )
    return problems


def make_deck_from_dict(d: dict, repo: CardRepository) -> DeckList:
    """JSON ファイルではなく辞書から作る。テストやプログラム生成に便利。"""
    leader = repo.get(d["leader"])
    main: list[CardDef] = []
    for entry in d.get("main", []):
        card = repo.get(entry["card_id"])
        main.extend([card] * int(entry.get("count", 1)))
    return DeckList(
        name=d.get("name", "(no name)"),
        leader=leader,
        main=main,
        slug=d.get("slug"),
        regulation=d.get("regulation", "standard"),
    )
