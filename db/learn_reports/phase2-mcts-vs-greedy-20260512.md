# Phase 2 検証レポート — MCTS vs GreedyAI (2026-05-12)

## 概要

Phase 2 で MCTSAI を ISMCTS (Information Set MCTS) + PUCT 化した。 同一デッキ
(cardrush_1429 赤紫ロジャー、 Tier A) で MCTS (deck1) vs Greedy (deck2) を head-to-head
で検証した。

## 結果

| 指標 | 値 |
|---|---|
| 試合数 | 30 |
| MCTS 勝 | 13 |
| Greedy 勝 | 17 |
| 引分 | 0 |
| **MCTS 勝率** | **0.433** |
| 1 試合所要 | 29.4 秒 |
| 計画目標 | **0.65** |
| 判定 | **目標未達** (0.433 < 0.65) |

## 設定

```
n_simulations_critical = 12  (PlayCharacter / AttackLeader 局面)
n_simulations_default  = 6   (それ以外)
c_puct                = 1.5
rollout_depth         = 8
use_eval_rollout      = False  (= GreedyAI rollout)
```

## 分析

### 失敗要因 (推定)

1. **sim 数不足**:
   - 各 root action あたり平均 1-2 visit しかない (= 探索が浅い)
   - PUCT formula `Q(a) + c × P(a) × √N / (1+n)` で N=12 だと
     prior 項 P が支配的になり、 Q (探索由来) が反映されにくい
   - 結果: MCTS が GreedyAI の prior に従うだけになり、 差別化されない

2. **prior バイアスが強すぎ**:
   - GreedyAI 選好 action に 0.6、 その他に 0.4/(n-1) で配分
   - 少 sim では prior 順位がそのまま root 選択に直結する
   - = MCTS が単に高速 Greedy になっている

3. **deepcopy ボトルネック**:
   - 1 試合 ~30 秒は計画目標 (1-3 秒) の 10x 以上
   - sim 数を増やすと指数的に遅くなる
   - state diff / CoW 化 (engine 全体改修) が前提

### 改善方向 (将来 Phase で)

1. **prior 調整**: GreedyAI 選好を 0.6 → 0.3 (= ほぼ uniform) にして探索余地確保
2. **sim 数の動的調整**: 重要局面でのみ 50+ sim にバースト
3. **state diff 化**: deepcopy を撤廃し、 sim 数を 100+ に
4. **Phase 4 (NN eval) との組合せ**: terminal value 推定の精度を上げる
5. **GreedyAI 由来 prior の代替**: random + softmax(eval) で柔らかい bias

## Phase 2 構造変更 (完了)

実装は完了。 検証目標は未達だが、 以下は将来活用可能な基盤として残る:

- `engine/ai.py:MCTSAI`: ISMCTS + PUCT 構造
- `engine/hand_estimator.determinize_state`: opp.hand 公平化
- `scripts/compute_matchup_matrix.py --ai mcts`: CLI フラグ
- `scripts/learn_ai_params.py --ai mcts`: 学習スクリプト統合
- `tests/test_mcts_ai.py`: 5 スモークテスト

## 次のアクション (推奨)

- **短期**: Phase 3 (マッチアップ別動的閾値) に並行で進む。 MCTS は別 issue で
  チューニングを継続。
- **中期**: deepcopy 高速化 (state diff / CoW) を独立 task として実装。
- **長期**: Phase 4 (NN eval) 完了後に MCTS と再統合。 value head が
  rollout の精度を上げるので MCTS の効果が出やすくなる。
