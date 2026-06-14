# -*- coding: utf-8 -*-
"""コンボ finder の品質を「実戦デッキ共起」を ground truth に客観評価する (= 2026-06-14)。

静的ルール (= enabler/accelerant/tribal/amplifier/payoff) が提案するカードが、 実際の
大会/構築デッキで anchor と一緒に使われているか (= co-occurrence) をどれだけ当てるかを測る。

  - static precision: 静的提案のうち、 実戦で anchor と共起するカードの割合
  - static recall   : 実戦共起カードのうち、 静的提案が拾えている割合
  - coverage        : 提案が出るカードの割合 / 平均グループ数・候補数

⚠ 共起は「同デッキ ≠ コンボ」 のノイズを含む近似 ground truth。 絶対値でなく改善の相対指標
   として使う (= ルールを変えた前後で precision/recall が上がるか)。

  .venv/bin/python scripts/eval_combo_finder.py [--min-decks 4] [--sample 80]
"""
from __future__ import annotations

import argparse
import random
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.combo_cooccurrence import cooccurring, deck_count, n_decks, _build_index  # noqa: E402
from engine.combo_finder import find_combos  # noqa: E402
from engine.deck import CardRepository  # noqa: E402

STATIC_GROUPS = {"enabler", "accelerant", "tribal", "amplifier", "payoff"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-decks", type=int, default=4, help="評価対象 = 実戦 N デッキ以上のカード")
    ap.add_argument("--sample", type=int, default=80)
    ap.add_argument("--top-gt", type=int, default=15, help="共起 ground truth の上位件数")
    args = ap.parse_args()

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    _, df, _ = _build_index()
    pool = sorted([c for c, n in df.items() if n >= args.min_decks and c in repo._by_id])
    random.Random(42).shuffle(pool)
    pool = pool[: args.sample]

    print(f"実戦デッキ {n_decks()} 個 / 評価対象カード {len(pool)} 枚 (deck_count>={args.min_decks})")

    def avg(xs):
        return sum(xs) / len(xs) if xs else 0.0

    def measure():
        precs, recs = [], []
        n_groups, n_cands, n_with_cooc = [], [], 0
        for cid in pool:
            gt = {d["card_id"] for d in cooccurring(cid, top=args.top_gt)}
            if not gt:
                continue
            res = find_combos(repo, cid, per_group=8)
            static = set()
            for g in res.groups:
                if g.key == "cooccurrence":
                    n_with_cooc += 1
                    continue
                if g.key in STATIC_GROUPS:
                    static |= {c.card_id for c in g.cards}
            n_groups.append(len(res.groups))
            n_cands.append(sum(len(g.cards) for g in res.groups))
            if static:
                hit = len(static & gt)
                precs.append(hit / len(static))
                recs.append(hit / len(gt))
        return precs, recs, n_groups, n_cands, n_with_cooc

    precs, recs, n_groups, n_cands, n_with_cooc = measure()

    print("\n=== 静的ルール vs 実戦共起 (ground truth) ===")
    print(f"  static precision: {avg(precs)*100:.1f}%  (静的提案が実戦共起である割合)")
    print(f"  static recall   : {avg(recs)*100:.1f}%  (実戦共起を静的提案が拾えた割合)")
    print(f"  評価できたカード : {len(precs)} 枚")
    print("\n=== カバレッジ ===")
    print(f"  平均グループ数  : {avg(n_groups):.1f}")
    print(f"  平均候補数      : {avg(n_cands):.0f}")
    print(f"  共起群が出た割合: {n_with_cooc}/{len(pool)} = {n_with_cooc/max(1,len(pool))*100:.0f}%")

    # 共起ブーストの効果 A/B (= ランクを実戦に接地する価値を測る)
    import engine.combo_cooccurrence as _cc

    orig = _cc.cooc_score_map
    _cc.cooc_score_map = lambda *a, **k: {}
    try:
        precs_off, *_ = measure()
    finally:
        _cc.cooc_score_map = orig
    print("\n=== 共起ブースト A/B (static precision) ===")
    print(f"  boost ON : {avg(precs)*100:.1f}%")
    print(f"  boost OFF: {avg(precs_off)*100:.1f}%")
    print(f"  改善     : {(avg(precs)-avg(precs_off))*100:+.1f}pt (= ランクを実戦に接地した効果)")


if __name__ == "__main__":
    main()
