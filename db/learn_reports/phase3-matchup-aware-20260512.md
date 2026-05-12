# Phase 3 検証レポート — マッチアップ別動的閾値 (2026-05-12)

## 概要

Phase 3 で `engine/matchup_model.py` を導入し、 相手リーダーから archetype を推定 → 
`db/matchup_strategies.json` の 4×4=16 マッチアップ別 override で
GreedyAI の `defense_thresholds` / `attack_gap_tolerance` / `finisher_hold_life` を
動的に切り替えるようにした。

## 結果

| 指標 | Phase 1 完了時 | Phase 3 完了時 | 差分 |
|---|---|---|---|
| tier_truth accuracy | 0.667 | **0.600** | **-0.067** ⚠️ |
| variance penalty | 0.0124 | 0.0114 | -0.0010 ✓ |
| composite | 0.660 | 0.594 | -0.066 ⚠️ |

| Loss Tag | Phase 1 | Phase 3 | 差分 |
|---|---|---|---|
| finisher_starved | 82.2% | 81.6% | -0.6% ✓ |
| counter_starved | 31.7% | 31.0% | -0.7% ✓ |
| attack_dispersed | 8.3% | 10.3% | +2.0% ⚠️ |
| activate_main_overused | 1.7% | 2.0% | +0.3% — |
| life_burst_lost | 0.4% | 0.7% | +0.3% — |

計画目標 (tier_truth 予測精度 +0.05〜+0.08) には **未達**。

## 解釈

### variance penalty は低下 = 期待値に近づいた

variance_penalty (= 予測勝率と expected_winrate の MSE) は 0.0124 → 0.0114 と
**改善**。 平均的には override で各デッキの勝率が tier_truth.expected_winrate に
近づいた。

### accuracy は低下 = tier ボーダーを跨ぐ誤判定が発生

15 デッキのうち **1 デッキがが tier 分類で flip した** と推定 (10/15 → 9/15)。
変動は小さいが tier 閾値が階段関数 (S=0.85 / A=0.75 / B=0.50 / C=0.25 / D) なので、
0.74 → 0.76 のような小さい変化でも A→S と判定が変わってしまう。

### 失敗要因

1. **Override 値が手動設計**:
   - matchup_strategies.json の 16 エントリを「コントロール vs アグロ なら防御厚め」
     的な intuition で設定したが、 実勝率データから calibration していない。
   - 一部マッチアップで攻撃を抑制しすぎ、 別マッチアップで守備を緩めすぎ。
   - attack_dispersed タグが +2% 増加 (= 強→弱で counter 浪費) は、 ミッドレンジ/
     コントロールで「あるマッチアップでは攻めるべきだったのに守備モード」 の症状。

2. **Phase 1 で AI が既に最適化済み**:
   - hand_estimator 統合で AI は隠匿情報を活用し、 動的にカウンター推定するようになった。
   - 静的な「コントロール vs アグロ なら +1000 tolerance」 ルールは、 動的推定と衝突する場面がある。

3. **archetype 4 分類が荒い**:
   - 「コントロール」 内でも 緑黄しらほし (回復軸) と 赤青エース (除去軸) は 戦略が
     大きく違う。 4 分類では同じ override が両方に適用されてしまう。

## Phase 3 の構造変更 (完了)

実装は完了。 override 値が calibration 不足だが、 以下は将来活用可能な基盤:

- `engine/matchup_model.py`:
  - `infer_opponent_archetype` (leader_id 逆引き + fallback)
  - `MatchupProfile` dataclass
  - `build_matchup_profile` / `load_matchup_strategies` / `lookup_matchup_overrides`
- `db/matchup_strategies.json`: 4×4 = 16 マッチアップ × 戦略パラメータ
- `engine/ai.py:GreedyAI._ensure_matchup_overrides`: lazy 適用 + flag 化
- `engine/ai.py:GreedyAI.finisher_hold_life`: マッチアップ依存パラメータ
- `tests/test_matchup_model.py`: 9 テスト

## 次のアクション (推奨)

- **短期**:
  - Phase 3 を保留 (= override 値の自動 calibration を Phase 6 self-play 学習に委ねる)。
  - 当面は Phase 4 (NN 評価ヘッド) に進む。 NN value head が学習されれば、 静的 override
    の代替として動的判断が可能になる。

- **中期**:
  - matchup_strategies.json の各エントリを Phase 6 self-play で学習。
  - 「archetype 4 分類」 → 「リーダー個別」 へ粒度を上げる (15 リーダー × 15 = 225 エントリ)。
  - tier_truth.json を「全体勝率」 から 「ペア別勝率」 へ拡張して教師信号を多様化。

- **長期**:
  - 4 分類自体を見直す。 deck_analysis に 「速度プロファイル」 を追加し、
    archetype の境界を data-driven に。

## 比較: Phase 1, 2, 3

| Phase | 計画目標 | 結果 | 判定 |
|---|---|---|---|
| Phase 1 | +0.05〜+0.10 | +0.067 | ✓ 達成 |
| Phase 2 | 65% MCTS vs Greedy | 43.3% | ✗ 未達 |
| Phase 3 | +0.05〜+0.08 | -0.067 | ✗ 退行 |

Phase 1 が ROI 最大、 Phase 2/3 は infrastructure として残し Phase 4 (NN) との組合せで
活用するパスが現実的。
