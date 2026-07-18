#!/usr/bin/env python3
"""pros_02 のデッキ紹介(蒸留 deck_list/key_cards)を基に、 未登録の環境デッキを作成 + メタ登録。

- pros_02 が扱う現メタ leader で 既存デッキが無いものを build_with_core で作成
  (pros_02 のコアカード + リーダー色で 50 枚に自動補完 = pros_02 flavored な valid deck)。
- 既存デッキがある leader (黒黄ティーチ 等) は それを メタ登録するだけ。
- 作成した deck を db/meta_decks.json に登録 + pros_02 overlay(signals+mulligan) 付与。

⚠ pros_02 解説の採用枚数は不完全(画像のみ)なので、 コア + 自動補完の approximation。
正確な大会リストが要る場合は scripts/scrape_cardrush_decks.py で更新。
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository
from engine.deckbuilder import build_with_core

ROOT = Path(__file__).resolve().parent.parent
_repo = CardRepository.from_json(ROOT / "db" / "cards.json")
_cards = json.loads((ROOT / "db" / "cards.json").read_text("utf-8"))
_byid = {c["card_id"]: c for c in _cards}

# 新規作成: deck_slug -> (leader_id, distilled_slug, name)
BUILD = {
    "pros02_luffy_gb": ("OP16-022", "luffy_gb", "緑青ルフィ (pros02)"),
    "pros02_sabo_rb": ("OP13-004", "sabo_rb", "赤黒サボ (pros02)"),
    "pros02_katakuri_p": ("OP11-062", "katakuri_p", "紫カタクリ (pros02)"),
    "pros02_zoro_g": ("OP12-020", "zoro_g", "緑ゾロ (pros02)"),
}
# 既存デッキをメタ登録するだけ: deck_slug -> distilled_slug
REGISTER_EXISTING = {"cardrush_1594": "teach_by"}  # 黒黄ティーチ OP16-080


def _resolve(name: str, lc: set[str]) -> str | None:
    s = re.sub(r"[（(【].*?[)）】]", "", name).strip()
    m = re.match(r"^(\d+)\s*(コスト|コス|c)?\s*(.+)$", s)
    cost = None
    if m and m.group(3):
        cost = int(m.group(1)); s = m.group(3).strip()
    s = re.sub(r"^(SR|SEC|R|C|UC|L|P)\s*", "", s).strip()
    if not s:
        return None
    best = None; bs = -1
    legal2 = _standard_card_ids()
    for c in _cards:
        if c.get("category") == "LEADER":
            continue
        if not (set((c.get("color") or "").split("/")) & lc):
            continue
        if c["card_id"] not in legal2:  # スタンダード合法(block②+、 再録含む最大)のみ core に
            continue
        nm = c.get("name") or ""
        if not nm:
            continue
        b = 3 if nm == s else (2 if s in nm else (1 if nm in s else 0))
        if b == 0:
            continue
        if cost is not None and c.get("cost") == cost:
            b += 2
        if "_p" not in c["card_id"]:  # 基本アート優先 (parallel より)
            b += 0.5
        if b > bs:
            bs = b; best = c["card_id"]
    return best


def _core_ids(distilled_slug: str, lc: set[str]) -> list[str]:
    dj = json.loads((ROOT / "db" / "note_pros02" / "distilled" / f"{distilled_slug}.json").read_text("utf-8"))
    core: list[str] = []
    for kc in dj.get("key_cards", []):
        cid = _resolve(kc.get("name", ""), lc)
        if cid and cid not in core:
            core.append(cid)
    for dl in dj.get("deck_list", []):
        cid = _resolve(dl.get("name", ""), lc)
        if cid and cid not in core:
            core.append(cid)
    return core


def _save_deck(slug: str, leader_id: str, name: str, deck) -> int:
    counts = Counter(cd.card_id for cd in deck.main)
    main = [{"card_id": cid, "count": n} for cid, n in counts.items()]
    out = {
        "name": name, "slug": slug, "leader": leader_id,
        "leader_name": _byid[leader_id]["name"], "source": "pros02_build",
        "main": main,
    }
    (ROOT / "decks" / f"{slug}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return sum(counts.values())


def main() -> None:
    built = []
    for slug, (leader_id, distilled, name) in BUILD.items():
        lc = set((_byid[leader_id].get("color") or "").split("/"))
        core = _core_ids(distilled, lc)
        deck, warns = build_with_core(leader_id, core, _repo, name=name, block_min=2)
        errs = deck.validate() if hasattr(deck, "validate") else []
        total = _save_deck(slug, leader_id, name, deck)
        built.append(slug)
        print(f"  {slug} ({leader_id} {_byid[leader_id]['name']}): core{len(core)} -> "
              f"50枚 total={total} validate={'OK' if not errs else errs[:1]}")

    # メタ登録
    md_path = ROOT / "db" / "meta_decks.json"
    md = json.loads(md_path.read_text("utf-8"))
    slugs = md["meta_deck_slugs"]
    for s in built + list(REGISTER_EXISTING.keys()):
        if s not in slugs:
            slugs.append(s)
    md["meta_deck_slugs"] = slugs
    md_path.write_text(json.dumps(md, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nメタ登録: {len(slugs)} デッキ (+{len(built)}作成 +{len(REGISTER_EXISTING)}既存登録)")
    print("新規作成:", built)
    print("既存登録:", list(REGISTER_EXISTING.keys()))


if __name__ == "__main__":
    main()
