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
    "crocodile_k": "cardrush_1385", # 黒クロコダイル OP14-079
    "calgara_y": "tcgportal_calgara",  # 黄カルガラ OP08-098
    "bonney_g": "tcgportal_bonney", # 緑ボニー EB04-001
    # OP16.5 new leaders with no existing deck -> handled separately (new deck build)
    "luffy_gb": None,               # 緑青ルフィ
    "sabo_rb": None,                # 赤黒サボ
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


APPLIED = ROOT / "db" / "note_pros02" / "applied"  # gitignored: prose (有料) を含む
SIGNALS = ROOT / "db" / "pros02_signals"           # committed: signals のみ (事実/フラグ、 本番配備)


def _derive_signals(dj: dict) -> dict:
    """distilled JSON から 対戦AIが消費する 機械可読 signal を抽出 (Claude変換)。
    - protect_card_ids: 盤面に残す/優先展開したい key card (role で判定、 ID解決済のみ)
    - avoid_overpump: 過剰パンプを罰する (= 攻撃回数優先 / DON効率)
    - attack_count_priority: 攻撃回数を評価する (race / 圧をかける)
    - aggression: archetype 由来の race|grind|balanced
    """
    kc = dj.get("key_cards", [])
    protect = [k["card_id"] for k in kc if k.get("card_id") and re.search(
        r"フィニッシャー|メインアタッカー|エンジン|ドローエンジン|ブロッカー|加速|蘇生|フィニッシュ", k.get("role", ""))]
    # 重複除去 (順序保持)
    protect = list(dict.fromkeys(protect))
    text = " ".join([dj.get("notes_for_ai", ""), dj.get("don_attach_notes", ""),
                     dj.get("strategy_summary", ""), dj.get("win_condition", ""),
                     " ".join(dj.get("common_mistakes", []))])
    arche = dj.get("archetype", "")
    avoid_overpump = bool(re.search(
        r"過剰(パンプ|打点)|パンプ.*(戒|しない|偏重|避)|尖らせ(ない|ず)|均等|付与.*もったい|"
        r"攻撃回数|6000.*(殴|攻撃|ライン)|打点を(伸ばさ|上げ)ない", text))
    attack_count_kw = bool(re.search(
        r"攻撃回数|殴り続け|圧をかけ|カウンター.*(吐か|消費|枯ら)|波状|横展開|殴っ", text))
    if "アグロ" in arche:
        aggr = "race"
    elif "コントロール" in arche:
        aggr = "grind"
    else:
        aggr = "balanced"
    # grind (コントロール) は over-attack で不利トレードを踏むので攻撃回数優先を切る (安全側)
    attack_count = (aggr != "grind") and (attack_count_kw or aggr == "race")
    return {"protect_card_ids": protect, "avoid_overpump": avoid_overpump,
            "attack_count_priority": attack_count, "aggression": aggr}


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

    signals = _derive_signals(dj)
    # (1) committed: signals のみ (card ID + フラグ = 事実、 有料prose無し → 本番 配備AI が読む)
    SIGNALS.mkdir(parents=True, exist_ok=True)
    (SIGNALS / f"{deck_slug}.json").write_text(json.dumps({
        "deck_slug": deck_slug, "source": "pros_02_signals",
        "mulligan_keep_card_ids": keep_add, "pros02_signals": signals,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    # (2) gitignored: prose (pros02_piloting = 有料note由来) → 教師 curriculum / local のみ
    APPLIED.mkdir(parents=True, exist_ok=True)
    (APPLIED / f"{deck_slug}.json").write_text(json.dumps({
        "deck_slug": deck_slug, "source": "pros_02", "distilled_slug": distilled_slug,
        "pros02_piloting": dj,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"deck_slug": deck_slug, "resolved": len(resolved), "unresolved": unresolved,
            "keep_add": len(keep_add), "signals": signals}


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
        s = r["signals"]
        print(f"{dslug:14s} -> {deck:20s} resolved={r['resolved']} keep_add={r['keep_add']} "
              f"| signals: protect={len(s['protect_card_ids'])} "
              f"overpump={int(s['avoid_overpump'])} atk_cnt={int(s['attack_count_priority'])} {s['aggression']}")


if __name__ == "__main__":
    main()
