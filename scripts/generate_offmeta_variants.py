# -*- coding: utf-8 -*-
"""環境外 leader (= archive レシピなし) の variant を deckbuilder で自動生成する (Step 0.1b)。

入力:
- db/cards.json から LEADER 全 132 種を抽出 (= base、 パラレル除外)
- db/data_layer_64_status.json から既存 variant ある leader を取得

処理:
- 環境外 leader 各々に `auto_build_deck(leader_id, meta_aware=True)` を呼ぶ
- 50 枚デッキを生成、 validate に通る形式で JSON 出力

出力:
- decks/<leader_slug>/variant_0.json (= 各 leader 1 variant、 source="auto_generated")
- db/data_layer_64_status.json (= 環境外 leader のステータス追加)

Usage:
  .venv/bin/python scripts/generate_offmeta_variants.py
  .venv/bin/python scripts/generate_offmeta_variants.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import random
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECKS_DIR = ROOT / "decks"
DB_DIR = ROOT / "db"
CARDS_PATH = DB_DIR / "cards.json"
STATUS_PATH = DB_DIR / "data_layer_64_status.json"


def _is_parallel(card_id: str) -> bool:
    return "_p" in card_id


def _make_slug(leader_id: str) -> str:
    return leader_id.lower().replace("-", "_")


def _deck_to_dict(deck) -> dict:
    """DeckList を decks/*.json と同じ形式の dict に。"""
    counts = Counter(c.card_id for c in deck.main)
    main_entries = [
        {"card_id": cid, "count": n}
        for cid, n in sorted(counts.items())
    ]
    return {
        "name": deck.name,
        "slug": deck.slug,
        "leader": deck.leader.card_id,
        "leader_name": deck.leader.name,
        "regulation": deck.regulation,
        "main": main_entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--seed", type=int, default=42,
        help="auto_build_deck の rng 用 seed (= 同 leader で再現性確保)",
    )
    args = parser.parse_args()

    # 遅延 import (= sys.path 設定を避けるため engine 直接 import)
    import sys
    sys.path.insert(0, str(ROOT))
    from engine.deck import CardRepository
    from engine.deckbuilder import auto_build_deck

    # 既存 status をロード (= classify_deck_variants.py の出力)
    if STATUS_PATH.exists():
        status = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    else:
        status = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "max_variants": 4,
            "total_recipes": 0,
            "leaders": {},
        }

    covered_leaders = set(status.get("leaders", {}).keys())
    print(f"Existing covered leaders (= from archive + decks): {len(covered_leaders)}")

    # 公式 LEADER 全件 (= パラレル除外)
    cards = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
    all_leaders = [
        c for c in cards
        if c.get("category") == "LEADER" and not _is_parallel(c.get("card_id", ""))
    ]
    print(f"Total base LEADER cards in DB: {len(all_leaders)}")

    offmeta_leaders = [
        c for c in all_leaders
        if c.get("card_id") not in covered_leaders
    ]
    print(f"Off-meta leaders to auto-generate: {len(offmeta_leaders)}")
    print()

    # CardRepository ロード
    repo = CardRepository.from_json(CARDS_PATH)

    success = 0
    failures: list[tuple[str, str]] = []

    for c in offmeta_leaders:
        leader_id = c["card_id"]
        leader_name = c.get("name", "")
        slug = _make_slug(leader_id)
        rng = random.Random(args.seed)

        try:
            deck = auto_build_deck(
                leader_id=leader_id,
                repo=repo,
                rng=rng,
                name=f"{leader_name} (auto)",
                meta_aware=True,
            )
            # slug を上書き
            deck.slug = f"{slug}_variant_0"
            # validate (= banlist は空 dict で skip、 標準ルール違反のみ check)
            problems = deck.validate(banlist={})
            if problems:
                # 重大違反のみ skip。 「リーダーの色に含まれない」 等の致命的問題は無視せず log
                fatal = [p for p in problems if "リーダーの色" in p or "枚数" in p]
                if fatal:
                    failures.append((leader_id, "; ".join(fatal[:2])))
                    continue

            deck_dict = _deck_to_dict(deck)
            deck_dict.update({
                "source": "auto_generated",
                "source_path": f"deckbuilder.auto_build_deck(meta_aware=True)",
                "variant_id": 0,
                "cluster_size": 1,
            })

            if not args.dry_run:
                leader_dir = DECKS_DIR / slug
                leader_dir.mkdir(parents=True, exist_ok=True)
                out_path = leader_dir / "variant_0.json"
                out_path.write_text(
                    json.dumps(deck_dict, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

            # status に追加
            status["leaders"][leader_id] = {
                "slug": slug,
                "name": leader_name,
                "n_samples": 0,
                "n_variants": 1,
                "source_type": "auto_generated",
                "variants": [{
                    "variant_id": 0,
                    "size": 1,
                    "medoid_source": "deckbuilder.auto_build_deck",
                    "score": "auto",
                    "tournament_date": "",
                    "member_sources": [],
                }],
            }
            success += 1
            if success % 20 == 0:
                print(f"  ... auto-generated {success} / {len(offmeta_leaders)}")
        except Exception as e:
            failures.append((leader_id, str(e)[:120]))

    print()
    print(f"Success: {success} / {len(offmeta_leaders)}")
    print(f"Failures: {len(failures)}")
    if failures[:5]:
        print("Sample failures:")
        for lid, msg in failures[:5]:
            print(f"  {lid}: {msg}")

    if not args.dry_run:
        status["generated_at"] = datetime.now(timezone.utc).isoformat()
        status["auto_generated_count"] = success
        status["auto_generated_failures"] = len(failures)
        status["total_leaders_covered"] = len(status["leaders"])
        STATUS_PATH.write_text(
            json.dumps(status, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nStatus updated: {STATUS_PATH}")
        print(f"Total leaders covered: {len(status['leaders'])}")


if __name__ == "__main__":
    main()
