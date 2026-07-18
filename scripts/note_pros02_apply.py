#!/usr/bin/env python3
"""Apply a distilled pros_02 piloting JSON into a deck's analysis.json.

- Resolves the distilled key_card NAMES (記事表記, e.g. "6エネル", "ガンマナイフ")
  to real card IDs by matching against the cards actually in the target deck
  (decks/<slug>.json) using name-substring + optional leading-cost hint.
- Injects a `pros02_piloting` block (the full distilled dict + resolved card_ids)
  into decks/<slug>.analysis.json, and merges early/search key cards into
  `mulligan_keep_card_ids` (kept additive; existing values preserved).

The deployed ExploitBeam AI mainly uses per-deck GBM value; these analysis fields
directly affect mulligan + GoalDirectedAI + serve as the Claude-teacher curriculum
source. Behavior change on the deployed value path goes through the teacher pipeline.

Usage:
  .venv/bin/python scripts/note_pros02_apply.py <distilled_slug> <deck_slug>
  .venv/bin/python scripts/note_pros02_apply.py enel cardrush_1454
  .venv/bin/python scripts/note_pros02_apply.py --all   # apply everything in DECK_MAP
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DISTILLED = ROOT / "db" / "note_pros02" / "distilled"

# distilled slug -> existing analysis/deck slug. None = needs a new meta deck first.
DECK_MAP = {
    "enel": "cardrush_1454",        # 紫エネル OP15-058
    "nami_by": "cardrush_1439",     # 青黄ナミ OP11-041
    "mihawk_g": "cardrush_1453",    # 緑ミホーク OP14-020
    "rosinante_py": "tcgportal_corazon",  # 紫黄ロシナンテ OP12-061
    "hancock_by": "tcgportal_hancock",    # 青黄ハンコック OP14-041
    "rucy_rb": "cardrush_1399",     # 赤青ルーシー OP15-002
    "ace_rb": "cardrush_1456",      # 赤(青)エース OP13-002
    "teach_by": "cardrush_1594",    # 黒黄ティーチ OP16-080 (register as meta)
    # OP16.5 new leaders with no existing deck -> handled separately (new deck build)
    "luffy_gb": None,               # 緑青ルフィ
}


def _load_cards() -> dict:
    cards = json.loads((ROOT / "db" / "cards.json").read_text("utf-8"))
    return {c["card_id"]: c for c in cards}


def _deck_pool(deck_slug: str, cards: dict) -> list[dict]:
    """[{card_id, name, cost}] for the distinct cards in decks/<slug>.json."""
    d = json.loads((ROOT / "decks" / f"{deck_slug}.json").read_text("utf-8"))
    ids = set()
    for entry in d.get("cards", d.get("main", [])):
        cid = entry.get("card_id") if isinstance(entry, dict) else entry
        if cid:
            ids.add(cid)
    lid = d.get("leader")
    if isinstance(lid, dict):
        lid = lid.get("card_id")
    if lid:
        ids.add(lid)
    pool = []
    for cid in ids:
        c = cards.get(cid, {})
        pool.append({"card_id": cid, "name": c.get("name", ""),
                     "cost": c.get("cost"), "category": c.get("category")})
    return pool


def _clean_name(raw: str) -> tuple[str, int | None]:
    """'6エネル(SR/ブロッカーエネル)' -> ('エネル', 6). Strip notes + leading cost."""
    s = re.sub(r"[（(【].*?[)）】]", "", raw).strip()
    m = re.match(r"^(\d+)\s*(コスト|コス|c)?\s*(.+)$", s)
    cost = None
    if m and m.group(3):
        cost = int(m.group(1))
        s = m.group(3).strip()
    s = re.sub(r"^(SR|SEC|R|C|UC|L|P)\s*", "", s).strip()
    return s, cost


def resolve_name(raw: str, pool: list[dict]) -> str | None:
    base, cost = _clean_name(raw)
    if not base:
        return None
    cands = pool
    if cost is not None:
        cost_c = [p for p in pool if p["cost"] == cost]
        if cost_c:
            cands = cost_c
    # exact, then substring both directions, longest-name tiebreak
    scored = []
    for p in cands:
        nm = p["name"] or ""
        if not nm:
            continue
        if nm == base:
            scored.append((3, len(nm), p))
        elif base in nm:
            scored.append((2, len(nm), p))
        elif nm in base:
            scored.append((1, len(nm), p))
    if not scored and cost is not None:  # retry ignoring cost filter
        for p in pool:
            nm = p["name"] or ""
            if nm and (nm == base or base in nm or nm in base):
                scored.append((1, len(nm), p))
    if not scored:
        return None
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return scored[0][2]["card_id"]


APPLIED = ROOT / "db" / "note_pros02" / "applied"  # gitignored runtime overlay


def apply_one(distilled_slug: str, deck_slug: str, cards: dict) -> dict:
    """Write a gitignored overlay db/note_pros02/applied/<deck_slug>.json that the
    engine merges at runtime. NEVER writes into the committed decks/*.analysis.json —
    the paid-derived prose stays out of the repo (per storage decision, Option A)."""
    dj = json.loads((DISTILLED / f"{distilled_slug}.json").read_text("utf-8"))
    pool = _deck_pool(deck_slug, cards)
    resolved, unresolved = [], []
    for kc in dj.get("key_cards", []):
        cid = resolve_name(kc.get("name", ""), pool)
        kc["card_id"] = cid
        (resolved if cid else unresolved).append(kc.get("name"))

    # pros_02-derived keep additions (merged onto the base analysis at runtime)
    keep_add = []
    for kc in dj.get("key_cards", []):
        role = (kc.get("role") or "")
        if kc.get("card_id") and re.search(r"サーチ|加速|ドロー|初動|ブロッカー", role) \
                and kc["card_id"] not in keep_add:
            keep_add.append(kc["card_id"])

    APPLIED.mkdir(parents=True, exist_ok=True)
    overlay = {
        "deck_slug": deck_slug,
        "source": "pros_02",
        "distilled_slug": distilled_slug,
        "mulligan_keep_card_ids": keep_add,
        "pros02_piloting": dj,
    }
    (APPLIED / f"{deck_slug}.json").write_text(
        json.dumps(overlay, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"deck_slug": deck_slug, "resolved": len(resolved),
            "unresolved": unresolved, "keep_add": len(keep_add)}


def main() -> None:
    cards = _load_cards()
    args = sys.argv[1:]
    if args and args[0] == "--all":
        pairs = [(d, s) for d, s in DECK_MAP.items()
                 if s and (DISTILLED / f"{d}.json").exists()]
    elif len(args) == 2:
        pairs = [(args[0], args[1])]
    else:
        print(__doc__); sys.exit(2)
    for dslug, deck in pairs:
        r = apply_one(dslug, deck, cards)
        print(f"{dslug:14s} -> {deck:20s} resolved={r['resolved']} "
              f"keep_add={r['keep_add']} unresolved={r['unresolved']}")


if __name__ == "__main__":
    main()
