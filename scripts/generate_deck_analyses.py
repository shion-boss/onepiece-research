# -*- coding: utf-8 -*-
"""
全デッキの静的分析を `decks/<slug>.analysis.json` に生成する。

実行:
    .venv/bin/python scripts/generate_deck_analyses.py

出力:
    decks/cardrush_1429.analysis.json (赤紫ロジャー の分析)
    decks/cardrush_1424.analysis.json (紫エネル)
    ...

`engine.deck_analyzer.analyze_deck` を呼ぶだけ。 動的対戦不要、 一瞬で完了。
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.deck_analyzer import analyze_deck  # noqa: E402
from engine.effects import load_effect_overlay  # noqa: E402


def main():
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")

    deck_files = sorted((ROOT / "decks").glob("*.json"))
    # exclude analysis files themselves + target spec files (= 別 schema、 deck list じゃない)
    deck_files = [
        f for f in deck_files
        if not f.name.endswith(".analysis.json")
        and ".target_v" not in f.name
    ]

    print(f"対象デッキ: {len(deck_files)} 件")
    generated = 0
    for f in deck_files:
        try:
            deck = DeckList.from_json(f, repo)
        except Exception as e:
            print(f"  ✗ {f.name}: deck load failed ({e})")
            continue

        analysis = analyze_deck(deck, overlay)
        # dataclass を dict にシリアライズ (top_features の tuple は list 化)
        d = asdict(analysis)
        d["top_features"] = [list(t) for t in d.get("top_features", [])]

        slug = f.stem
        out_path = f.parent / f"{slug}.analysis.json"
        out_path.write_text(
            json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        generated += 1
        print(f"  ✓ {slug:<24} → {analysis.archetype:<8} {analysis.strategy_summary[:40]}")

    print(f"\n生成完了: {generated} 件")


if __name__ == "__main__":
    main()
