# -*- coding: utf-8 -*-
"""
評価関数 (engine/eval.py) の重みを matchup matrix を ground truth にチューニング。

approach (粗いが軽量):
1. 全 cardrush デッキ × 数試合 を record_snapshots=True で実行
2. 各試合の最終 winner を ラベルにし、 中盤 (snapshot index 半ば) の eval が winner を予測するか評価
3. 各重み (W_LIFE, W_FIELD_COUNT, W_FIELD_POWER, W_HAND, W_DON, W_BLOCKER, W_ATTACHED_DON,
   W_ACTIVE_CHARA, W_LETHAL) を係数 0.5x / 1.0x / 1.5x / 2.0x で grid search
4. 最高予測精度の重み倍率を出力 (auto-apply はせず、 提案のみ)

実行:
    .venv/bin/python scripts/tune_eval_weights.py
    # or 軽量モード:
    .venv/bin/python scripts/tune_eval_weights.py --n-games 2

出力:
    各 weight × 倍率 のスコア表 + 推奨倍率
"""

from __future__ import annotations

import argparse
import glob
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.effects import load_effect_overlay  # noqa: E402
from engine.eval import BoardEvalWeights, DEFAULT_WEIGHTS  # noqa: E402
from engine.harness import run_matchup  # noqa: E402
from engine.analyzer import _score_from_snap  # noqa: E402


def collect_snapshots(decks, overlay, n_games_per_pair=2, seed_base=42):
    """全 deck pair で N 試合実行し、 (mid_snap, winner_idx_first) のリストを返す。"""
    pairs = []
    for i, d1 in enumerate(decks):
        for j, d2 in enumerate(decks):
            if i == j:
                continue
            rep = run_matchup(
                d1, d2, n_games=n_games_per_pair,
                seed=seed_base + i * 100 + j,
                effects_overlay=overlay,
                record_snapshots=True,
                enforce_rules=False,
            )
            for g in rep.games:
                if g.winner < 0 or not g.snapshots:
                    continue
                # winner: 0=deck1 / 1=deck2 → snap.players における index に変換
                # snap.players[0] は first_player のデッキ
                if g.winner == 0:
                    me_idx_in_snap = g.first_player  # deck1 が居る index
                else:
                    me_idx_in_snap = 1 - g.first_player
                # 中盤 snapshot を抽出 (= 全長の半ば付近)
                snaps = [
                    s for s in g.snapshots
                    if not s.get("game_over")
                ]
                if len(snaps) < 4:
                    continue
                mid = snaps[len(snaps) // 2]
                pairs.append((mid, me_idx_in_snap))
    return pairs


def evaluate_weights(pairs, weights):
    """各 mid_snap で eval が >0 ならば winner 予測。 accuracy を返す。"""
    correct = 0
    for snap, winner_idx in pairs:
        score = _score_from_snap(snap, winner_idx, weights)
        # 終局以外なら ±W_GAME_OVER は出ない想定だが念のため除外
        if abs(score) >= 500_000:
            continue
        # 予測: score > 0 ならば winner
        if score > 0:
            correct += 1
    return correct, len(pairs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-games", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")

    deck_files = sorted(
        f for f in glob.glob(str(ROOT / "decks" / "cardrush_*.json"))
        if not f.endswith(".analysis.json")
    )
    decks = [DeckList.from_json(Path(f), repo) for f in deck_files]
    print(f"対戦予定: {len(decks)} デッキ × {len(decks)-1} 対戦 × {args.n_games} 試合 = "
          f"{len(decks) * (len(decks)-1) * args.n_games} 試合")

    pairs = collect_snapshots(
        decks, overlay,
        n_games_per_pair=args.n_games,
        seed_base=args.seed,
    )
    print(f"中盤 snapshot 収集: {len(pairs)} 件")

    if not pairs:
        print("snapshot がありません")
        return

    # baseline (default weights)
    correct, total = evaluate_weights(pairs, DEFAULT_WEIGHTS)
    base_acc = correct / total if total else 0
    print(f"\nDEFAULT_WEIGHTS で baseline 予測精度: {base_acc:.1%} ({correct}/{total})")

    # 各 weight について 0.5x / 1.0x / 1.5x / 2.0x の倍率で grid search
    # (他 weight は固定。 1 weight ずつ最適化 = greedy coordinate ascent)
    weight_names = [
        "W_LIFE", "W_FIELD_COUNT", "W_FIELD_POWER", "W_HAND", "W_DON",
        "W_BLOCKER", "W_ATTACHED_DON", "W_ACTIVE_CHARA", "W_LETHAL",
    ]
    multipliers = [0.5, 0.7, 1.0, 1.3, 1.7, 2.0]
    print(f"\n=== weight 倍率の予測精度 (他は default) ===")
    print(f"{'weight':<18} " + " ".join(f"{m}x".rjust(8) for m in multipliers))
    best_recommendation = {}
    for wname in weight_names:
        accs = []
        for mult in multipliers:
            kwargs = {wname: int(getattr(DEFAULT_WEIGHTS, wname) * mult)}
            w = replace(DEFAULT_WEIGHTS, **kwargs)
            correct, total = evaluate_weights(pairs, w)
            acc = correct / total if total else 0
            accs.append(acc)
        # 最良 倍率
        best_idx = max(range(len(multipliers)), key=lambda i: accs[i])
        best_mult = multipliers[best_idx]
        best_acc = accs[best_idx]
        print(f"{wname:<18} " + " ".join(f"{a:>7.1%}" for a in accs)
              + f"  → best {best_mult}x ({best_acc:.1%})")
        best_recommendation[wname] = (best_mult, best_acc)

    # 提案
    print("\n=== 推奨倍率 (current weight × multiplier) ===")
    for wname, (mult, acc) in best_recommendation.items():
        cur = getattr(DEFAULT_WEIGHTS, wname)
        new_val = int(cur * mult)
        delta = "→" if mult == 1.0 else (" ↑" if mult > 1 else " ↓")
        marker = "" if mult == 1.0 else " (差分あり)"
        print(f"  {wname:<18} {cur:>6} {delta} {new_val:>6}  ({mult}x, {acc:.1%}){marker}")

    print("\n注: これは coordinate-wise の grid search なので、 全体最適とは限らない。")
    print("     auto-apply はせず、 engine/eval.py の DEFAULT_WEIGHTS を手動で更新する想定。")


if __name__ == "__main__":
    main()
