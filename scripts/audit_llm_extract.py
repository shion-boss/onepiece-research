#!/usr/bin/env python3
"""LLM ベース overlay 監査の素材抽出ツール。

各カードについて「公式テキスト ↔ 現行 overlay (DSL + _text 注記)」を 1 ブロックに
並べ、 Claude Code が そのまま 忠実性 監査 できる markdown / json を生成する。

これは [[project_card_effect_100_plan_kickoff]] の 順2 prototype 基盤。
イム deck (cardrush_1392) で 試行 → 効果確認後 --all で全 4,518 枚 走行。

使い方:
  python scripts/audit_llm_extract.py --deck cardrush_1392
  python scripts/audit_llm_extract.py --cards OP13-084 OP13-096
  python scripts/audit_llm_extract.py --all            # 全 4,518 枚
  python scripts/audit_llm_extract.py --all --chunk 50 # 50 枚ずつ分割出力
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS_PATH = ROOT / "db" / "cards.json"
EFFECTS_PATH = ROOT / "db" / "card_effects.json"
DECKS_DIR = ROOT / "decks"
OUT_DIR = ROOT / "db" / "audit_llm"

# 監査に関係する cards.json フィールド
CARD_FIELDS = ["name", "category", "cost", "power", "counter",
               "attribute", "color", "features", "trigger", "text"]


def load_cards() -> dict[str, dict]:
    cards = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
    return {c["card_id"]: c for c in cards}


def load_effects() -> dict:
    return json.loads(EFFECTS_PATH.read_text(encoding="utf-8"))


def deck_card_ids(slug: str) -> list[str]:
    deck = json.loads((DECKS_DIR / f"{slug}.json").read_text(encoding="utf-8"))
    ids: list[str] = []
    leader = deck.get("leader")
    if leader:
        ids.append(leader)
    for entry in deck.get("main", []):
        cid = entry.get("card_id")
        if cid and cid not in ids:
            ids.append(cid)
    return ids


def card_block_md(cid: str, card: dict | None, overlay) -> str:
    lines: list[str] = [f"## {cid}"]
    if card is None:
        lines.append("**(cards.json に存在しない)**\n")
        return "\n".join(lines)
    meta = " / ".join(
        f"{k}={card.get(k)}" for k in
        ["name", "category", "cost", "power", "counter", "attribute", "color", "features"]
        if card.get(k) not in (None, "", "null")
    )
    lines.append(f"- {meta}")
    trig = card.get("trigger")
    if trig:
        lines.append(f"- **trigger**: {trig}")
    text = card.get("text") or "(テキストなし)"
    lines.append("\n### 公式テキスト")
    lines.append(f"> {text}")
    lines.append("\n### 現行 overlay")
    if overlay is None:
        lines.append("**(card_effects.json に entry なし — 未登録)**")
    elif overlay == []:
        lines.append("`[]` (効果なし = バニラ / ブロッカーのみ / パラレル空 でマーク済)")
    else:
        lines.append("```json")
        lines.append(json.dumps(overlay, ensure_ascii=False, indent=2))
        lines.append("```")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--deck", help="deck slug (例: cardrush_1392)")
    g.add_argument("--cards", nargs="+", help="card_id を直接指定")
    g.add_argument("--all", action="store_true", help="全 4,518 枚")
    ap.add_argument("--chunk", type=int, default=0, help=">0 で N 枚ずつ分割出力")
    args = ap.parse_args()

    cards = load_cards()
    effects = load_effects()

    if args.deck:
        ids = deck_card_ids(args.deck)
        label = args.deck
    elif args.cards:
        ids = args.cards
        label = "adhoc"
    else:
        ids = [c["card_id"] for c in json.loads(CARDS_PATH.read_text(encoding="utf-8"))]
        label = "all"

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    def write_chunk(chunk_ids: list[str], suffix: str) -> Path:
        blocks = [card_block_md(cid, cards.get(cid), effects.get(cid)) for cid in chunk_ids]
        header = (f"# LLM overlay 監査素材: {label}{suffix}\n\n"
                  f"カード数: {len(chunk_ids)}\n\n"
                  f"各カードで 公式テキスト の 全 節 が overlay に 忠実 反映 されて いるか、 "
                  f"公式 に ない 効果 が 混入 して いないか、 条件/対象/数値/タイミング が 正確か を 監査 する。\n\n"
                  f"---\n\n")
        out = OUT_DIR / f"{label}{suffix}.md"
        out.write_text(header + "\n".join(blocks), encoding="utf-8")
        return out

    if args.chunk and args.chunk > 0:
        written = []
        for i in range(0, len(ids), args.chunk):
            chunk = ids[i:i + args.chunk]
            written.append(write_chunk(chunk, f"_part{i // args.chunk:03d}"))
        print(f"{len(ids)} 枚 を {len(written)} chunk に分割出力:")
        for p in written:
            print(f"  {p.relative_to(ROOT)}")
    else:
        out = write_chunk(ids, "")
        print(f"{len(ids)} 枚 → {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
