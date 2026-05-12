# -*- coding: utf-8 -*-
"""
対象デッキへの対策候補デッキを N 件生成。

使い方:
    # 紫エネル に対する対策候補を 20 件生成
    .venv/bin/python scripts/explore_counter_decks.py \\
        --target cardrush_1424 --n 20 \\
        --out decks/_candidates/cardrush_1424/

    # リーダー指定 (= OP09-061 紫黒ルフィ で対策案)
    .venv/bin/python scripts/explore_counter_decks.py \\
        --target cardrush_1439 --n 5 --leader OP09-061

    # 必須キャラ指定 (= サンジ系を必ず軸に)
    .venv/bin/python scripts/explore_counter_decks.py \\
        --target cardrush_1424 --must-include OP07-064

出力:
    decks/_candidates/<target_slug>/
        01_<arche>_<leader_id>.json   (= 個別候補デッキ、 既存 JSON 形式互換)
        02_<arche>_<leader_id>.json
        ...
        _summary.json                  (= 全候補の rank / score / rationale 集約)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.effects import load_effect_overlay  # noqa: E402
from engine.explorer import generate_counter_candidates  # noqa: E402


def _resolve_target(target_arg: str, repo: CardRepository) -> tuple[Path, DeckList]:
    """--target が slug (cardrush_1424) または path (decks/foo.json) を受け付ける。"""
    p = Path(target_arg)
    if not p.exists():
        # slug として decks/<slug>.json を試す
        cand = ROOT / "decks" / f"{target_arg}.json"
        if cand.exists():
            p = cand
        else:
            raise FileNotFoundError(f"target not found: {target_arg}")
    deck = DeckList.from_json(p, repo)
    return p, deck


def _serialize_candidate(cand, target_slug: str, rank: int) -> dict:
    """CounterCandidate → 既存 deck JSON 形式互換の dict に変換。"""
    main_counter: dict[str, int] = {}
    for c in cand.deck.main:
        main_counter[c.card_id] = main_counter.get(c.card_id, 0) + 1
    return {
        "name": f"counter_{rank:02d}_{cand.archetype}_{cand.leader_id}",
        "slug": f"candidate_{target_slug}_{rank:02d}",
        "leader": cand.leader_id,
        "leader_name": cand.deck.leader.name,
        "source": f"explorer (Phase B) target={target_slug}",
        "score": f"explorer (Phase B) estimated_score={cand.estimated_score}",
        "tournament_name": "phase_b_explorer",
        "tournament_date": "2026-05-12",
        "fetched_at": "2026-05-12T00:00:00Z",
        "main": [
            {"card_id": cid, "count": n}
            for cid, n in sorted(main_counter.items(), key=lambda x: x[0])
        ],
        "regulation": "standard",
        "explorer_metadata": {
            "rank": rank,
            "archetype": cand.archetype,
            "estimated_score": cand.estimated_score,
            "rationale": cand.rationale,
            "role_distribution": cand.role_distribution,
            "target_slug": target_slug,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", required=True,
                    help="対象デッキ slug (= cardrush_1424) or JSON path")
    ap.add_argument("--n", type=int, default=20, help="生成候補数 (default 20)")
    ap.add_argument("--leader", action="append", default=None,
                    help="候補リーダー card_id (複数指定可)")
    ap.add_argument("--must-include", default=None,
                    help="必須カード ID をカンマ区切り (例: OP14-069,OP10-065)")
    ap.add_argument("--diversity", default="archetype",
                    choices=["archetype", "leader", "color"],
                    help="多様性確保軸 (default archetype)")
    ap.add_argument("--out", default=None,
                    help="出力ディレクトリ (default: decks/_candidates/<target_slug>/)")
    args = ap.parse_args()

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")

    target_path, target_deck = _resolve_target(args.target, repo)
    target_slug = target_path.stem
    print(f"target: {target_deck.name} ({target_deck.leader.card_id}) [{target_slug}]")

    must_include = (
        [c.strip() for c in args.must_include.split(",") if c.strip()]
        if args.must_include else None
    )
    if must_include:
        print(f"must_include: {must_include}")
    if args.leader:
        print(f"leader_filter: {args.leader}")

    print(f"\n探索中... (n={args.n}, diversity={args.diversity})")
    candidates = generate_counter_candidates(
        target_deck, repo, overlay,
        n_candidates=args.n,
        leader_filter=args.leader,
        must_include=must_include,
        diversity=args.diversity,
    )
    print(f"生成数: {len(candidates)}")

    if not candidates:
        print("候補生成失敗 (= リーダー候補なし or 全 build 失敗)")
        return 1

    # 出力ディレクトリ
    out_dir = Path(args.out) if args.out else (
        ROOT / "decks" / "_candidates" / target_slug
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n出力先: {out_dir}")

    # 個別候補デッキ + サマリ
    summary_entries = []
    for rank, cand in enumerate(candidates, 1):
        d = _serialize_candidate(cand, target_slug, rank)
        fname = f"{rank:02d}_{cand.archetype}_{cand.leader_id}.json"
        (out_dir / fname).write_text(
            json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        summary_entries.append({
            "rank": rank,
            "leader_id": cand.leader_id,
            "leader_name": cand.deck.leader.name,
            "archetype": cand.archetype,
            "estimated_score": cand.estimated_score,
            "rationale": cand.rationale,
            "role_distribution": cand.role_distribution,
            "filename": fname,
        })

    summary = {
        "target_slug": target_slug,
        "target_name": target_deck.name,
        "target_leader": target_deck.leader.card_id,
        "n_generated": len(candidates),
        "diversity_axis": args.diversity,
        "must_include": must_include or [],
        "leader_filter": args.leader or [],
        "candidates": summary_entries,
    }
    (out_dir / "_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print()
    print("=== サマリ (top 5) ===")
    print(f"{'rank':>4} {'leader':<14} {'archetype':<10} {'score':>5}  rationale")
    print("-" * 80)
    for e in summary_entries[:5]:
        rats = "; ".join(e["rationale"][:2])
        print(f"{e['rank']:>4} {e['leader_id']:<14} {e['archetype']:<10} {e['estimated_score']:>5}  {rats[:50]}")

    from collections import Counter
    arche_dist = Counter(e["archetype"] for e in summary_entries)
    print(f"\narchetype 分布: {dict(arche_dist)}")
    print(f"_summary.json: {out_dir / '_summary.json'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
