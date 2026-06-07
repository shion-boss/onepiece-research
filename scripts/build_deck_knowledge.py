"""デッキプレイ知識を生成し db/deck_play_knowledge_<slug>.json に保存 + レポート表示。

ロジックは engine/deck_play_knowledge.py (= 対戦 AI と共有、 一元化)。 仕様 docs/DECK_PLAY_KNOWLEDGE.md。
usage: .venv/bin/python scripts/build_deck_knowledge.py [deck_slug]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.deck_play_knowledge import build_knowledge  # noqa: E402

SLUG = sys.argv[1] if len(sys.argv) > 1 else "tcgportal_calgara"
repo = CardRepository.from_json(ROOT / "db" / "cards.json")
dl = DeckList.from_json(ROOT / "decks" / f"{SLUG}.json", repo)
try:
    dl.slug = SLUG
except Exception:
    pass
ov = json.load(open(ROOT / "db" / "card_effects.json", encoding="utf-8"))

k = build_knowledge(dl, ov)
outp = ROOT / "db" / f"deck_play_knowledge_{SLUG}.json"
outp.write_text(json.dumps(k, ensure_ascii=False, indent=2), encoding="utf-8")

cards = k["cards"]


def nm(cid):
    return f"{cards[cid]['name']}({cid})"


print(f"=== デッキプレイ知識: {k['deck_name']} ({SLUG}) | 主要feature={k['main_feature']} "
      f"| summon={k['summon_features']} ===")
print(f"unique={len(cards)} combos={len(k['combos'])}\n")
print("--- デッキ内コンボ ---")
for e in sorted(k["combos"], key=lambda x: -len(x["from"])):
    more = f" 他{len(e['from']) - 5}" if len(e["from"]) > 5 else ""
    print(f"  [{e['tag']}] → {nm(e['to'])}  ← {'、'.join(nm(a) for a in e['from'][:5])}{more}")
print("\n--- 各カードの有効な使い方 (timing_hint) ---")
for cid, co in cards.items():
    print(f"  {nm(cid)} [{'/'.join(co['roles']) or 'vanilla'}]")
    print(f"      {co['timing_hint']}")
print(f"\nsaved: {outp.relative_to(ROOT)}")
