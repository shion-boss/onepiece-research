# -*- coding: utf-8 -*-
"""
db/card_roles.json の役割割当を audit する。

ランダム N 件サンプリング (デフォルト 200) して
text vs primary_role / tags の整合性をレポート。 R65 の誤分類リスク軽減用。

実行:
    .venv/bin/python scripts/audit_role_assignment.py
    .venv/bin/python scripts/audit_role_assignment.py --sample 50 --seed 42
    .venv/bin/python scripts/audit_role_assignment.py --role removal  # 特定 role のみ

サンプル出力:
    [removal] OP14-069 ドンキホーテ・ドフラミンゴ (cost 10)
      text: ...相手のコスト8以下のキャラ1枚までを、KOする...
      primary=finisher tags=[removal]
      OK (text contains KOする, role detected)
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# 役割 → 公式テキストでの典型キーワード (= 期待マーカー)
# 部分一致でゆるく検査する (= conjugation 別表記を許容)
EXPECTED_TEXT_MARKERS: dict[str, list[str]] = {
    "removal": ["KO", "手札に戻", "デッキの下に戻", "ライフの下に置"],
    "negation": ["無効", "発動できない", "不発"],
    "disruption": ["相手の手札", "ランダム", "ドン!!", "レスト", "デッキの下"],
    "search": ["上から", "見", "公開", "デッキから", "サーチ"],
    "draw": ["引く", "ドロー"],
    "ramp": ["ドン!!", "アクティブ", "コスト"],
    "blocker": ["ブロッカー"],
    "recovery": ["ライフ"],
    "finisher": [],  # cost-based、 マーカー検査スキップ
    "synergy": [],   # default、 検査スキップ
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=200, help="サンプル件数")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--role", type=str, default=None,
                        help="特定 role のみ audit (= primary_role)")
    parser.add_argument("--show-text", action="store_true",
                        help="text 全文を表示")
    args = parser.parse_args()

    rng = random.Random(args.seed)

    role_path = ROOT / "db" / "card_roles.json"
    cards_path = ROOT / "db" / "cards.json"

    role_db = json.loads(role_path.read_text(encoding="utf-8"))
    role_db = {k: v for k, v in role_db.items() if not k.startswith("_")}
    cards = {c["card_id"]: c for c in json.loads(cards_path.read_text(encoding="utf-8"))}

    # 候補 = 役割割当済の全カード (role フィルタ適用)
    candidates = [
        cid for cid, v in role_db.items()
        if (args.role is None or v.get("primary_role") == args.role)
    ]
    print(f"候補数: {len(candidates)} (role filter={args.role or 'なし'})")
    if not candidates:
        return

    sample_size = min(args.sample, len(candidates))
    sample = rng.sample(candidates, sample_size)

    suspect_count = 0
    role_counter: Counter[str] = Counter()

    for cid in sample:
        v = role_db[cid]
        primary = v.get("primary_role", "?")
        tags = v.get("tags", [])
        role_counter[primary] += 1

        card = cards.get(cid, {})
        name = card.get("name", "?")
        cost = card.get("cost", "?")
        text = card.get("text", "") or ""

        # 期待マーカー検査
        markers = EXPECTED_TEXT_MARKERS.get(primary, [])
        marker_hit = any(m in text for m in markers) if markers else None
        # finisher / synergy は marker 検査スキップ
        is_suspect = marker_hit is False  # explicitly not None

        status = "OK" if not is_suspect else "SUSPECT"
        if is_suspect:
            suspect_count += 1

        if args.show_text or is_suspect:
            print(f"\n[{primary:10}] {cid:12} {name[:20]:<20} (cost {cost})")
            print(f"  tags: {tags}")
            print(f"  text: {text[:200]}")
            if markers:
                print(f"  expected markers: {markers}")
            print(f"  -> {status}")

    print()
    print(f"=== サンプル {sample_size} 件サマリ ===")
    print(f"  SUSPECT: {suspect_count} 件 ({suspect_count/sample_size*100:.1f}%)")
    print(f"  primary_role 分布:")
    for role, n in role_counter.most_common():
        print(f"    {role:12} {n:4}")


if __name__ == "__main__":
    main()
