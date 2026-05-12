# -*- coding: utf-8 -*-
"""
全 4,518 カードの役割プロファイルを `db/card_roles.json` に生成する。

実行:
    .venv/bin/python scripts/generate_card_roles.py

出力スキーマ:
    {
      "_meta": { "version": "...", "card_count": 4518 },
      "OP14-069": {
        "card_id": "OP14-069", "name": "...", "category": "CHARACTER",
        "cost": 10, "power": 12000, "counter": 0,
        "primary_role": "finisher", "tags": ["removal"],
        "threat_level": 10, "speed_class": "late",
        "evidence": [...]
      },
      ...
    }

`engine.card_role.derive_card_role` を全カードに適用するだけ。
動的対戦不要、 1 秒程度で完了。
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.card_role import derive_card_role, card_role_to_dict  # noqa: E402
from engine.deck import CardRepository  # noqa: E402
from engine.effects import load_effect_overlay  # noqa: E402


def main() -> None:
    cards_path = ROOT / "db" / "cards.json"
    overlay_path = ROOT / "db" / "card_effects.json"
    out_path = ROOT / "db" / "card_roles.json"

    repo = CardRepository.from_json(cards_path)
    overlay = load_effect_overlay(overlay_path)

    # repo._by_id は base_id 同名の variant を集約しているので、
    # cards.json から全 variant を直接読んで card_id 単位で出力する。
    raw_cards = json.loads(cards_path.read_text(encoding="utf-8"))
    print(f"対象カード: {len(raw_cards)} 件")

    out: dict[str, dict] = {
        "_meta": {
            "version": str(date.today()),
            "card_count": len(raw_cards),
            "source": "engine.card_role.derive_card_role",
            "primary_roles": [
                "finisher", "removal", "negation", "disruption", "recovery",
                "ramp", "search", "draw", "blocker", "synergy",
            ],
        }
    }

    primary_counter: Counter[str] = Counter()
    tag_counter: Counter[str] = Counter()
    unset_count = 0
    skipped_count = 0

    for row in raw_cards:
        cid = row.get("card_id")
        if not cid:
            skipped_count += 1
            continue
        try:
            card = repo.get(cid)
        except KeyError:
            # variant が repo に登録されていないケース (= base のみ集約) は
            # repo._by_id 直接ルックアップで救済。
            card = repo._by_id.get(cid)  # noqa
            if card is None:
                skipped_count += 1
                continue

        cr = derive_card_role(card, overlay)
        d = card_role_to_dict(cr)
        # 補助メタ情報を追加 (= json から逆引きで使いやすく)
        d["name"] = card.name
        d["category"] = (
            card.category.value if hasattr(card.category, "value") else str(card.category)
        )
        d["cost"] = card.cost
        d["power"] = card.power
        d["counter"] = card.counter
        d["color"] = list(card.color)
        d["features"] = list(card.features)

        out[cid] = d
        primary_counter[cr.primary_role] += 1
        for t in cr.tags:
            tag_counter[t] += 1
        if not cr.primary_role:
            unset_count += 1

    out_path.write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    n_cards = len(raw_cards) - skipped_count
    print(f"\n書き出し: {out_path}")
    print(f"  カード数: {n_cards} (skipped: {skipped_count})")
    print(f"  primary_role 未設定: {unset_count}")
    print(f"\n=== primary_role 分布 ===")
    for role, n in primary_counter.most_common():
        pct = (n / max(1, n_cards)) * 100
        print(f"  {role:12} {n:5} ({pct:5.1f}%)")
    print(f"\n=== tag 分布 (上位 15) ===")
    for tag, n in tag_counter.most_common(15):
        print(f"  {tag:18} {n:5}")


if __name__ == "__main__":
    main()
