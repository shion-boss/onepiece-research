# -*- coding: utf-8 -*-
"""Plan Imit-1 (= 2026-05-18): 大会優勝レシピ 93 件から「人間プレイヤーの選択」 patterns 抽出。

各 leader (= archetype) で:
  - core cards (= 採用率 50%+ のカード、 「人間が必ず採用する」)
  - 採用率 平均 (= optional カード)
  - mulligan keep 候補 (= 1-2 cost 序盤展開用)

出力 db/imitation_patterns.json で imitation NN の学習教師、 plan_search の prior になる。

実行:
  .venv/bin/python scripts/extract_human_play_patterns.py \\
    --input-dir decks/_archive/cardrush_raw/ \\
    --output db/imitation_patterns.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", default="decks/_archive/cardrush_raw/")
    ap.add_argument("--output", default="db/imitation_patterns.json")
    ap.add_argument("--core-threshold", type=float, default=0.5,
                    help="採用率これ以上のカードを core 認定 (= default 0.5 = 50%)")
    args = ap.parse_args()

    in_dir = ROOT / args.input_dir
    deck_files = sorted(in_dir.glob("*.json"))
    print(f"=== imitation patterns 抽出 ===")
    print(f"  input: {in_dir}")
    print(f"  deck files: {len(deck_files)}")
    print(f"  core threshold: {args.core_threshold*100:.0f}%")

    # leader (= archetype) → list of decks
    by_leader: dict[str, list[dict]] = defaultdict(list)
    for p in deck_files:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            leader = d.get("leader")
            if leader:
                by_leader[leader].append(d)
        except Exception:
            pass

    print(f"  unique leaders: {len(by_leader)}")

    # cards.json で カード詳細
    cards = {c["card_id"]: c for c in json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))}

    patterns: dict[str, dict] = {}
    for leader, decks in by_leader.items():
        n_decks = len(decks)
        # 各カードの 「採用 deck 数」 / 「合計枚数」 を集計
        card_adoption = Counter()  # card_id → 採用 deck 数
        card_total_count = Counter()  # card_id → 全 deck での合計枚数
        for d in decks:
            seen_in_this_deck = set()
            for entry in d.get("main", []):
                cid = entry.get("card_id")
                cnt = entry.get("count", 1)
                if not cid:
                    continue
                card_total_count[cid] += cnt
                if cid not in seen_in_this_deck:
                    card_adoption[cid] += 1
                    seen_in_this_deck.add(cid)

        # core cards (= 採用率 50%+)
        core_cards = []
        optional_cards = []
        for cid, n_adopt in card_adoption.most_common():
            adoption_rate = n_adopt / n_decks
            avg_count = card_total_count[cid] / n_adopt  # 採用 deck での平均枚数
            c = cards.get(cid, {})
            entry = {
                "card_id": cid,
                "name": c.get("name"),
                "category": c.get("category"),
                "cost": c.get("cost"),
                "power": c.get("power"),
                "adoption_rate": round(adoption_rate, 3),
                "avg_count_when_adopted": round(avg_count, 2),
            }
            if adoption_rate >= args.core_threshold:
                core_cards.append(entry)
            else:
                optional_cards.append(entry)

        # mulligan keep candidates = 1-2 cost で 採用率 50%+ のカード
        def _cost_int(x):
            try:
                return int(x) if x is not None else None
            except Exception:
                return None
        mulligan_keep = []
        for e in core_cards:
            c = _cost_int(e.get("cost"))
            if c is not None and c <= 2:
                mulligan_keep.append(e)

        leader_meta = cards.get(leader, {})
        patterns[leader] = {
            "leader_id": leader,
            "leader_name": leader_meta.get("name"),
            "n_decks_analyzed": n_decks,
            "core_cards": core_cards[:30],  # top 30
            "optional_cards": optional_cards[:30],
            "mulligan_keep_candidates": mulligan_keep[:10],
        }
        print(f"  [{leader}] {leader_meta.get('name', '?')}: {n_decks} decks, {len(core_cards)} core, {len(mulligan_keep)} mulligan candidates")

    out = {
        "_source": str(args.input_dir),
        "_n_files": len(deck_files),
        "_core_threshold": args.core_threshold,
        "_n_leaders": len(patterns),
        "patterns": patterns,
    }
    out_path = ROOT / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== DONE. saved: {out_path} ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
