"""decks/*.json を 全 analyze → db/deck_archetypes.json (= slug → archetype map) を 出力。

Plan H ハイブリッド lookup (= 2026-05-25) の Tier 2 軸 で 使う。 plan_search の hot path で
analyze_deck を 呼ぶ と 重い ため、 事前 build で 静的 map を 作って lookup に 使う。

format:
```json
{
  "map": {
    "cardrush_1456": "コントロール",
    ...
  },
  "meta": {
    "built_at": "2026-05-25",
    "n_decks": 16
  }
}
```

# 使い方

```bash
.venv/bin/python scripts/build_deck_archetypes.py
```

新 deck を 追加 した 後 や archetype 判定 logic を 変えた 後 に 再実行。
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

PROJ_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ_ROOT))

from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.deck_analyzer import analyze_deck  # noqa: E402
from engine.effects import load_effect_overlay  # noqa: E402


def main() -> None:
    repo = CardRepository.from_json(str(PROJ_ROOT / "db" / "cards.json"))
    overlay = load_effect_overlay(str(PROJ_ROOT / "db" / "card_effects.json"))
    decks_dir = PROJ_ROOT / "decks"

    archetype_map: dict[str, str] = {}
    speed_map: dict[str, str] = {}
    skipped: list[tuple[str, str]] = []

    for path in sorted(decks_dir.glob("*.json")):
        # target_v1*.json / *.analysis.json は skip
        if any(suf in path.name for suf in (".target_", ".analysis.")):
            continue
        slug = path.stem
        try:
            deck = DeckList.from_json(str(path), repo)
            analysis = analyze_deck(deck, overlay)
            archetype_map[slug] = analysis.archetype
            speed_map[slug] = analysis.speed
        except Exception as e:
            skipped.append((slug, str(e)))

    out = {
        "meta": {
            "built_at": date.today().isoformat(),
            "n_decks": len(archetype_map),
            "skipped": skipped,
        },
        "map": archetype_map,
        "speed_map": speed_map,
    }

    out_path = PROJ_ROOT / "db" / "deck_archetypes.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out_path} ({len(archetype_map)} decks)")
    if skipped:
        print(f"  skipped {len(skipped)}: {skipped[:3]}")

    # 分布 を 表示
    from collections import Counter
    arch_dist = Counter(archetype_map.values())
    speed_dist = Counter(speed_map.values())
    print(f"\narchetype dist: {dict(arch_dist)}")
    print(f"speed dist:     {dict(speed_dist)}")


if __name__ == "__main__":
    main()
