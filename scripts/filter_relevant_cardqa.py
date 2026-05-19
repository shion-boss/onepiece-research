#!/usr/bin/env python3
"""Plan H 最適化 2 (= 2026-05-19): deck 関連 の cardqa のみ 抽出。

deck の 60 枚 card_id から series を 抽出 → 該当 series の cardqa_*.json のみ 読み込み
→ さらに カード名 mention で item を 絞り込み → JSONL 出力。

全 cardqa ~36K tokens (= 52 series × ~50 items) → ~5-10K tokens (= 10 series × 関連 item) に。

# 使い方

```bash
.venv/bin/python scripts/filter_relevant_cardqa.py --deck cardrush_1456
# → db/filtered_cardqa/cardrush_1456.jsonl 出力
```

# 出力 形式

```jsonl
{"series_slug": "op_13", "card_name_hits": ["マルコ"], "q": "...", "a": "..."}
{"series_slug": "op_08", "card_name_hits": ["ジョズ"], "q": "...", "a": "..."}
```

card_name_hits は カード名 mention で 引っかかった カード 群 (= relevance ヒント)。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DECKS_DIR = REPO_ROOT / "decks"
FAQ_DIR = REPO_ROOT / "db" / "faq"
CARDS_JSON = REPO_ROOT / "db" / "cards.json"
OUT_DIR = REPO_ROOT / "db" / "filtered_cardqa"

# card_id → series 抽出 regex
SERIES_RE = re.compile(r"^(OP\d+|ST\d+|EB\d+|PRB\d+|P)")


def card_id_to_series_slug(card_id: str) -> Optional[str]:
    """card_id (例: 'OP13-002') から cardqa file の series_slug (例: 'op_13') を 返す。

    promo (= P-xxx) は 'p' (= cardqa_.json 含む) で 返す。"""
    m = SERIES_RE.match(card_id)
    if not m:
        return None
    raw = m.group(1).lower()
    if raw == "p":
        return "p"
    # 例: 'op13' → 'op_13'、 'st22' → 'st_22'、 'eb04' → 'eb_04'、 'prb02' → 'prb_02'
    m2 = re.match(r"^([a-z]+)(\d+)$", raw)
    if not m2:
        return None
    return f"{m2.group(1)}_{m2.group(2)}"


def load_deck_card_ids(deck_slug: str) -> tuple[set[str], str]:
    """deck JSON から 全 card_id (= leader + main) を 返す + leader_id を 返す。"""
    deck_path = DECKS_DIR / f"{deck_slug}.json"
    if not deck_path.exists():
        raise FileNotFoundError(f"deck not found: {deck_path}")
    deck = json.loads(deck_path.read_text(encoding="utf-8"))
    card_ids: set[str] = set()
    leader_id = deck.get("leader", "")
    if leader_id:
        card_ids.add(leader_id)
    for entry in deck.get("main", []):
        cid = entry.get("card_id")
        if cid:
            card_ids.add(cid)
    return card_ids, leader_id


def load_card_names(card_ids: set[str]) -> dict[str, str]:
    """card_id → name の lookup を 返す。"""
    cards = json.loads(CARDS_JSON.read_text(encoding="utf-8"))
    name_map = {}
    if isinstance(cards, list):
        for c in cards:
            cid = c.get("card_id")
            if cid in card_ids:
                name_map[cid] = c.get("name", "")
    elif isinstance(cards, dict):
        for cid, c in cards.items():
            if cid in card_ids:
                name_map[cid] = c.get("name", "")
    return name_map


def find_cardqa_file(series_slug: str) -> Optional[Path]:
    """series_slug から 該当 cardqa file path を 返す。"""
    if series_slug == "p":
        # promo は cardqa_.json
        path = FAQ_DIR / "cardqa_.json"
    else:
        path = FAQ_DIR / f"cardqa_{series_slug}.json"
    return path if path.exists() else None


def filter_cardqa_items(
    items: list[dict],
    card_names: set[str],
    series_slug: str,
) -> list[dict]:
    """cardqa items から、 deck 内 カード名 mention のある item のみ filter。

    mention 0 の item は 「general rule」 とみなして 半分 (= sample) 残す。
    関連性 強い item は full 残す。
    """
    relevant: list[dict] = []
    general: list[dict] = []
    for item in items:
        text = (item.get("q", "") or "") + " " + (item.get("a", "") or "")
        hits = [n for n in card_names if n and n in text]
        if hits:
            relevant.append({
                "series_slug": series_slug,
                "card_name_hits": hits,
                "q": item.get("q", ""),
                "a": item.get("a", ""),
            })
        else:
            general.append({
                "series_slug": series_slug,
                "card_name_hits": [],
                "q": item.get("q", ""),
                "a": item.get("a", ""),
            })
    # general を sample 削減 (= 全部入れると context 重い)
    return relevant + general[:5]


def filter_deck(deck_slug: str, out_dir: Path = OUT_DIR) -> Path:
    """deck_slug の cardqa を filter → JSONL 出力。 出力 path を 返す。"""
    card_ids, leader_id = load_deck_card_ids(deck_slug)
    if not card_ids:
        raise ValueError(f"deck '{deck_slug}' has no card_ids")

    name_map = load_card_names(card_ids)
    card_names = set(n for n in name_map.values() if n)

    # series 集計
    series_set: set[str] = set()
    for cid in card_ids:
        s = card_id_to_series_slug(cid)
        if s:
            series_set.add(s)

    print(f"deck: {deck_slug}", file=sys.stderr)
    print(f"  unique cards: {len(card_ids)}", file=sys.stderr)
    print(f"  card names: {len(card_names)}", file=sys.stderr)
    print(f"  series: {sorted(series_set)}", file=sys.stderr)

    out_items: list[dict] = []
    series_stats: Counter = Counter()
    for s in sorted(series_set):
        path = find_cardqa_file(s)
        if path is None:
            print(f"  [warn] cardqa file not found for series '{s}'", file=sys.stderr)
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [warn] failed to read {path.name}: {e}", file=sys.stderr)
            continue
        items = data.get("items", [])
        filtered = filter_cardqa_items(items, card_names, s)
        out_items.extend(filtered)
        series_stats[s] = len(filtered)
        print(f"  {path.name}: {len(items)} items → {len(filtered)} kept", file=sys.stderr)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{deck_slug}.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for item in out_items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    total_chars = sum(len(item.get("q", "")) + len(item.get("a", "")) for item in out_items)
    est_tokens = total_chars // 3  # 日本語 1 token ≈ 3 char (= 大雑把)
    print(f"  output: {out_path} ({len(out_items)} items, ~{est_tokens} tokens)", file=sys.stderr)
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Plan H: deck 関連 cardqa filter")
    ap.add_argument("--deck", required=True, help="deck slug (例: cardrush_1456)")
    ap.add_argument("--out-dir", default=None, help="出力 ディレクトリ")
    args = ap.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else OUT_DIR
    filter_deck(args.deck, out_dir)


if __name__ == "__main__":
    main()
