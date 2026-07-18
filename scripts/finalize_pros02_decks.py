#!/usr/bin/env python3
"""リサーチ済 decklist (db/note_pros02/decklists/*.json = pros_02記事+ネット) を
valid な 50 枚デッキに確定 → decks/<slug>.json 保存 + メタ登録。

decklist 形式: {leader_id, leader_name, cards:[{card_number?, name, count}]}。
card_number があれば直結解決、 無ければ leader 色 + block②合法で name 解決。
build_with_core(core_counts) で 50 枚に確定 (足りなければ合法 fill)。
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict, _load_max_block_by_base_id
from engine.deckbuilder import build_with_core

ROOT = Path(__file__).resolve().parent.parent
DL = ROOT / "db" / "note_pros02" / "decklists"
_repo = CardRepository.from_json(ROOT / "db" / "cards.json")
_cards = json.loads((ROOT / "db" / "cards.json").read_text("utf-8"))
_byid = {c["card_id"]: c for c in _cards}
_MAXBLOCK = _load_max_block_by_base_id()


def _standard_card_ids() -> set[str]:
    """スタンダード合法 (再録含む最大 block_icon >= 2) の card_id 集合。"""
    out = set()
    for c in _cards:
        if c.get("category") == "LEADER":
            continue
        base = c["card_id"].split("_")[0]
        bi = c.get("block_icon", 0) or 0
        if _MAXBLOCK.get(base, bi) >= 2:
            out.add(c["card_id"])
    return out

# decklist slug -> 表示名 (メタ登録名)
NAMES = {
    "pros02_luffy_gb": "緑青ルフィ (pros02)", "pros02_sabo_rb": "赤黒サボ (pros02)",
    "pros02_katakuri_p": "紫カタクリ (pros02)", "pros02_zoro_g": "緑ゾロ (pros02)",
    "pros02_kuzan_b": "青クザン (pros02)", "pros02_kid_y": "黄キッド (pros02)",
    "pros02_luffy_r": "赤ルフィ (pros02)",
}


def _resolve_name(name: str, lc: set[str], legal: set[str]) -> str | None:
    s = re.sub(r"[（(【].*?[)）】]", "", name).strip()
    m = re.match(r"^(\d+)\s*(コスト|コス|c)?\s*(.+)$", s)
    cost = None
    if m and m.group(3):
        cost = int(m.group(1)); s = m.group(3).strip()
    s = re.sub(r"^(SR|SEC|R|C|UC|L|P)\s*", "", s).strip()
    if not s:
        return None
    best = None; bs = -1.0
    for c in _cards:
        if c.get("category") == "LEADER" or c["card_id"] not in legal:
            continue
        if not (set((c.get("color") or "").split("/")) & lc):
            continue
        nm = c.get("name") or ""
        if not nm:
            continue
        b = 3.0 if nm == s else (2.0 if s in nm else (1.0 if nm in s else 0.0))
        if b == 0:
            continue
        if cost is not None and c.get("cost") == cost:
            b += 2
        if "_p" not in c["card_id"]:
            b += 0.5
        if b > bs:
            bs = b; best = c["card_id"]
    return best


def finalize(slug: str) -> dict | None:
    p = DL / f"{slug}.json"
    if not p.exists():
        return None
    dl = json.loads(p.read_text("utf-8"))
    leader_id = dl["leader_id"]
    lc = set((_byid[leader_id].get("color") or "").split("/"))
    legal = _standard_card_ids()
    core_counts: dict[str, int] = {}
    unresolved = []
    for c in dl.get("cards", []):
        num = c.get("card_number")
        cid = None
        if num:  # card_number 指定あり → DB照合。 DB未登録なら name-fallbackせず未解決 (誤解決防止)
            base = num.split("_")[0]
            if num in _byid and num in legal:
                cid = num
            elif base in _byid and base in legal:
                cid = base
            else:
                unresolved.append(f"{num}({c.get('name','')}) DB未登録/非合法")
                continue
        else:
            cid = _resolve_name(c.get("name", ""), lc, legal)
            if not cid:
                unresolved.append(c.get("name"))
                continue
        core_counts[cid] = core_counts.get(cid, 0) + int(c.get("count", 0))
    # 未解決 (= ST-3x 等 DB未登録カード) があるデッキは 不正確なので保存しない
    if unresolved:
        return {"slug": slug, "total": 0, "distinct": 0, "unresolved": unresolved,
                "valid": False, "errs": ["未解決カード有り=DB更新が必要 (保存skip)"], "skipped": True}
    core_ids = list(core_counts.keys())
    deck, warns = build_with_core(leader_id, core_ids, _repo,
                                  core_counts=core_counts, name=NAMES[slug], block_min=2)
    counts = Counter(cd.card_id for cd in deck.main)
    main = [{"card_id": cid, "count": n} for cid, n in counts.items()]
    out = {"name": NAMES[slug], "slug": slug, "leader": leader_id,
           "leader_name": _byid[leader_id]["name"], "source": "pros02+net", "main": main}
    (ROOT / "decks" / f"{slug}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    d2 = make_deck_from_dict(out, _repo)
    errs = d2.validate()
    return {"slug": slug, "total": sum(counts.values()), "distinct": len(main),
            "unresolved": unresolved, "valid": not errs, "errs": errs[:2]}


def main() -> None:
    md_path = ROOT / "db" / "meta_decks.json"
    md = json.loads(md_path.read_text("utf-8"))
    slugs = md["meta_deck_slugs"]
    for slug in NAMES:
        r = finalize(slug)
        if r is None:
            print(f"  {slug}: decklist 未着 (skip)")
            continue
        if slug not in slugs:
            slugs.append(slug)
        print(f"  {slug}: {r['total']}枚 {r['distinct']}種 "
              f"{'✅合法' if r['valid'] else '⚠'+str(r['errs'])} 未解決={r['unresolved']}")
    md["meta_deck_slugs"] = slugs
    md_path.write_text(json.dumps(md, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nメタ登録: {len(slugs)} デッキ")


if __name__ == "__main__":
    main()
