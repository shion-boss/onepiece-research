# -*- coding: utf-8 -*-
"""
tcg-portal.jp の deck-guide ページから「採用率 × 平均枚数」 を抽出し、
50 枚レシピを再構成して `decks/<slug>.json` を出力する。

紫エネルでやった手順 (= 集計ベース) を一般化したもの。 月次更新で再実行可能。

実行:
    .venv/bin/python scripts/scrape_tcgportal_decks.py --leader 紫エネル \\
        --leader-id OP15-058 --slug cardrush_1424

    # 環境メタ全件 (Tier 1-3) を一括処理:
    .venv/bin/python scripts/scrape_tcgportal_decks.py --tier-list

URL: https://tcg-portal.jp/onepiece/deck-guides/<leader_name>
ページに採用率 + 平均枚数の表記がある card は dedupe して上から順に組み込む。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.deck import CardRepository, DeckList, _base_id  # noqa: E402
from engine.core import Category  # noqa: E402

BASE_URL = "https://tcg-portal.jp/onepiece/deck-guides/"


# Tier 1-3 の (leader_name, leader_id, slug) リスト。
# meta-analysis ページから手動マッピング (= card ID は Tier ページに無いので逆引き)。
DEFAULT_TIER_LIST = [
    # (leader_name, leader_id, slug, tier, usage_pct)
    ("青黄ナミ", "OP11-041", "cardrush_1439", 1, 16.0),
    ("紫エネル", "OP15-058", "cardrush_1424", 1, 16.0),
    ("黄ルフィ（OP15）", "OP15-098", "tcgportal_op15_lufy", 2, 12.0),
    ("緑ミホーク", "OP14-020", "cardrush_1437", 3, 8.0),
    ("赤青ルーシー", "OP15-002", "cardrush_1399", 3, 8.0),
    ("赤緑クリーク", "OP15-001", "tcgportal_kuriku", 3, 8.0),
]


def fetch_html(leader_name: str) -> str:
    """tcg-portal /deck-guides/<leader_name> を取得。"""
    encoded = urllib.parse.quote(leader_name, safe="")
    url = f"{BASE_URL}{encoded}"
    print(f"  fetch: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (research bot)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_card_stats(html: str) -> list[dict]:
    """HTML から (card_name, card_id, adoption_rate, avg_count) を抽出。

    重複は dedupe (= 同 card_id の初出のみ採用、 通常 Standard が先)。
    """
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)

    # パターン: <name> <CARD_ID> ... 採用率 X% 平均 Y 枚
    pattern = re.compile(
        r"(\S+?)\s+([A-Z]+\d+-\d+)\s*[^A-Z0-9]*?:\s*([\d.]+)\s*%\s*平均\s*:\s*([\d.]+)\s*枚"
    )
    out: list[dict] = []
    seen: set[str] = set()
    for name, cid, rate, avg in pattern.findall(text):
        if cid in seen:
            continue
        seen.add(cid)
        out.append({
            "card_id": cid,
            "name": name,
            "adoption_rate": float(rate),
            "avg_count": float(avg),
        })
    return out


def build_recipe(
    stats: list[dict],
    repo: CardRepository,
    leader_id: str,
    target_total: int = 50,
) -> tuple[list[dict], list[str]]:
    """採用率 × 平均枚数 から 50 枚レシピを生成。

    アルゴリズム:
    - 採用率降順 → avg_count 降順 でソート
    - 各カード: min(round(avg_count), 4) 枚を追加
    - 50 枚に到達したら打ち切り
    - 50 枚未満なら警告 (= 候補不足)
    """
    leader = repo.get(leader_id)
    leader_colors = set(leader.color)
    warnings: list[str] = []

    # ソート: 採用率高い → 平均枚数多い
    stats_sorted = sorted(
        stats,
        key=lambda s: (-s["adoption_rate"], -s["avg_count"]),
    )

    main: list[dict] = []
    total = 0
    for s in stats_sorted:
        if total >= target_total:
            break
        cid = s["card_id"]
        try:
            card = repo.get(cid)
        except KeyError:
            warnings.append(f"{cid} ({s['name']}) は cards.json に無い、 skip")
            continue
        # リーダー色チェック
        if not (set(card.color) & leader_colors):
            warnings.append(f"{cid} {card.name} は leader 色不一致、 skip")
            continue
        if not set(card.color).issubset(leader_colors):
            warnings.append(f"{cid} {card.name} は多色だが leader 色に全部含まれない、 skip")
            continue
        # リーダーカード自体は除外
        if card.category.value == "LEADER":
            continue

        # 枚数: min(round(avg), 4, 残り枠)
        n = min(int(round(s["avg_count"])), 4, target_total - total)
        if n <= 0:
            continue
        main.append({"card_id": cid, "count": n})
        total += n

    # 50 枚未満なら counter / synergy 札で補充 (= leader 色合致 + 既存 main 同名 4 枚以下)
    if total < target_total:
        used_counts: dict[str, int] = {}
        for m in main:
            bid = _base_id(m["card_id"])
            used_counts[bid] = used_counts.get(bid, 0) + m["count"]

        # 候補プール: leader 色合致 + character/event/stage + cost ≥ 1
        pool = []
        seen_ids: set[str] = set()
        for cid, c in repo._by_id.items():  # noqa
            if c.card_id in seen_ids:
                continue
            seen_ids.add(c.card_id)
            if c.category == Category.LEADER:
                continue
            if c.category not in (Category.CHARACTER, Category.EVENT, Category.STAGE):
                continue
            if not (set(c.color) & leader_colors):
                continue
            if not set(c.color).issubset(leader_colors):
                continue
            if c.cost < 1:
                continue
            pool.append(c)

        # 優先: counter ≥ 2000 → counter ≥ 1000 → cost 低い順
        pool.sort(key=lambda c: (-c.counter, c.cost))

        added_filler = 0
        for c in pool:
            if total >= target_total:
                break
            bid = _base_id(c.card_id)
            cap = 4 - used_counts.get(bid, 0)
            if cap <= 0:
                continue
            n = min(cap, target_total - total)
            main.append({"card_id": c.card_id, "count": n})
            used_counts[bid] = used_counts.get(bid, 0) + n
            total += n
            added_filler += n

        if added_filler > 0:
            warnings.append(
                f"50 枚に到達せず stats だけでは不足、 counter/synergy 札で {added_filler} 枚補充"
            )
        if total < target_total:
            warnings.append(
                f"50 枚に到達せず (補充後 {total} 枚)。 候補プール枯渇"
            )

    return main, warnings


def write_deck_json(
    out_path: Path,
    leader_name: str,
    leader_id: str,
    slug: str,
    tier: int,
    usage_pct: float,
    main: list[dict],
    source_url: str,
) -> None:
    leader = leader_name
    doc = {
        "name": leader,
        "slug": slug,
        "leader": leader_id,
        "leader_name": leader.replace("青黄", "").replace("紫", "").replace("緑", "").replace("赤青", "").replace("黄", "").replace("赤緑", "").strip()
                       or leader,
        "source": source_url,
        "score": f"tcg-portal 集計 (Tier {tier}, 使用率 {usage_pct}%)",
        "tournament_name": "tcg-portal aggregate",
        "tournament_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "main": main,
        "regulation": "standard",
    }
    out_path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def process_leader(
    leader_name: str,
    leader_id: str,
    slug: str,
    tier: int,
    usage_pct: float,
    repo: CardRepository,
    *,
    dry_run: bool = False,
) -> dict:
    """1 リーダーを処理 → recipe 生成 → JSON 出力。"""
    print(f"\n=== {leader_name} ({leader_id}, slug={slug}) ===")
    html = fetch_html(leader_name)
    stats = parse_card_stats(html)
    print(f"  抽出 stats: {len(stats)} 件")

    main, warnings = build_recipe(stats, repo, leader_id)
    total = sum(m["count"] for m in main)
    print(f"  生成 recipe: {len(main)} 種 / {total} 枚")
    for w in warnings:
        print(f"    WARN: {w}")

    out_path = ROOT / "decks" / f"{slug}.json"
    if not dry_run:
        encoded = urllib.parse.quote(leader_name, safe="")
        write_deck_json(
            out_path, leader_name, leader_id, slug, tier, usage_pct, main,
            f"{BASE_URL}{encoded}",
        )
        # validate
        try:
            deck = DeckList.from_json(out_path, repo)
            deck.validate()
            print(f"  ✓ {out_path.name} 書き出し + validate OK")
        except Exception as e:
            print(f"  ✗ validate 失敗: {e}")

    return {
        "leader_name": leader_name,
        "leader_id": leader_id,
        "slug": slug,
        "tier": tier,
        "usage_pct": usage_pct,
        "main_count": total,
        "warnings": warnings,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--leader", help="リーダー名 (URL slug、 例 紫エネル)")
    ap.add_argument("--leader-id", help="リーダーカード ID (例 OP15-058)")
    ap.add_argument("--slug", help="出力デッキの slug (例 cardrush_1424)")
    ap.add_argument("--tier", type=int, default=0, help="Tier 番号 (metadata 用)")
    ap.add_argument("--usage", type=float, default=0.0, help="使用率 % (metadata 用)")
    ap.add_argument("--tier-list", action="store_true",
                    help="DEFAULT_TIER_LIST の全リーダーを処理")
    ap.add_argument("--dry-run", action="store_true", help="ファイル書き出ししない")
    args = ap.parse_args()

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")

    results = []
    if args.tier_list:
        for leader, lid, slug, tier, usage in DEFAULT_TIER_LIST:
            results.append(process_leader(
                leader, lid, slug, tier, usage, repo, dry_run=args.dry_run,
            ))
            time.sleep(2.0)  # rate limit
    elif args.leader and args.leader_id and args.slug:
        results.append(process_leader(
            args.leader, args.leader_id, args.slug, args.tier, args.usage, repo,
            dry_run=args.dry_run,
        ))
    else:
        ap.error("--tier-list または (--leader + --leader-id + --slug) が必須")

    print()
    print("=== サマリ ===")
    for r in results:
        warn_s = f" ({len(r['warnings'])} warn)" if r["warnings"] else ""
        print(f"  {r['leader_name']:<20} → {r['main_count']} 枚 (Tier {r['tier']}){warn_s}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
