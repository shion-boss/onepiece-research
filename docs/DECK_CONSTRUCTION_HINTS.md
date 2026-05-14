# メタデッキ分析レポート (= 強デッキ共通要素)

> 2026-05-14 自動生成。 `db/matchup_matrix.bug_baseline_v1.json` (= 旧 AI matrix)
> を勝率データとして使用。 16 active + 88 historical recipe を分析。

## 1. 勝率順 (= bug_baseline、 active 16)

| 順位 | slug | 勝率 | archetype |
|---|---|---|---|
| 1 | cardrush_1456 | 95.7% | 赤青エース |
| 2 | cardrush_1439 | 84.3% | 青黄ナミ |
| 3 | tcgportal_bonney | 69.3% | 赤黄ボニー |
| 4 | cardrush_1455 | 67.7% | 空島ルフィ |
| 5 | cardrush_1399 | 57.0% | 赤青ルーシー |
| 6 | tcgportal_op11_luffy | 53.7% | 青紫ルフィ |
| 7 | cardrush_1342 | 49.7% | 紫ドフラミンゴ |
| 8 | cardrush_1385 | 47.7% | 黒クロコダイル |
| 9 | tcgportal_calgara | 35.7% | 黄カルガラ |
| 10 | cardrush_1454 | 34.7% | 紫エネル |
| 11 | tcgportal_op13_luffy | 32.0% | 赤緑ルフィ（OP13） |
| 12 | tcgportal_corazon | 25.0% | 紫黄ロシナンテ |
| 13 | cardrush_1453 | 23.0% | 緑ミホーク |
| 14 | tcgportal_coby | 20.0% | 赤黒コビー |
| 15 | cardrush_1392 | 14.3% | 黒イム |

## 2. 勝率との相関 (= Pearson r)

正の値: 上昇要因、 負の値: 低下要因。 |r| ≥ 0.3 で意味のある関係。

| 特徴 | 相関 | 解釈 |
|---|---|---|
| avg_cost | +0.533 | 🔥 強い相関 |
| role_synergy_count | -0.488 | ⚡ 中程度 |
| role_recovery_count | +0.408 | ⚡ 中程度 |
| role_negation_count | -0.377 | ⚡ 中程度 |
| synergy_density | -0.376 | ⚡ 中程度 |
| role_draw_count | +0.31 | ⚡ 中程度 |
| role_disruption_count | +0.307 | ⚡ 中程度 |
| blocker_count | +0.271 | 弱い相関 |
| role_blocker_count | -0.23 | 弱い相関 |
| role_removal_count | +0.229 | 弱い相関 |
| role_search_count | -0.174 | 弱い相関 |
| free_event_count | -0.139 | ほぼ無相関 |
| color_cohesion | -0.132 | ほぼ無相関 |
| role_ramp_count | -0.112 | ほぼ無相関 |
| role_finisher_count | +0.098 | ほぼ無相関 |
| n_1k_counter | -0.078 | ほぼ無相関 |
| n_0_counter | +0.069 | ほぼ無相関 |
| counter_total | -0.053 | ほぼ無相関 |
| n_2k_counter | -0.014 | ほぼ無相関 |

## 3. 上位 5 vs 下位 5 の差分

上位: cardrush_1456, cardrush_1439, tcgportal_bonney, cardrush_1455, cardrush_1399
下位: tcgportal_op13_luffy, tcgportal_corazon, cardrush_1453, tcgportal_coby, cardrush_1392

| 特徴 | 上位平均 | 下位平均 | 差 (top - bottom) |
|---|---|---|---|
| avg_cost | 3.744 | 3.132 | +0.612 |
| counter_total | 37400 | 39800 | -2400 |
| n_1k_counter | 16.6 | 17.8 | -1.2 |
| n_2k_counter | 10.4 | 11 | -0.6 |
| blocker_count | 11 | 9 | +2 |
| free_event_count | 0 | 0 | 0 |
| synergy_density | 0.616 | 0.648 | -0.032 |
| color_cohesion | 0.784 | 0.776 | +0.008 |

## 4. 強デッキの共通要素 (= 推測される構築指針)

上記相関 + 差分から、 強いデッキに共通する要素を推測:

**+: 多いほど勝率高い (= 増やすべき)**
  - avg_cost (r = +0.53)
  - role_disruption_count (r = +0.31)
  - role_draw_count (r = +0.31)
  - role_recovery_count (r = +0.41)

**-: 多いほど勝率低い (= 抑えるべき)**
  - synergy_density (r = -0.38)
  - role_negation_count (r = -0.38)
  - role_synergy_count (r = -0.49)

## 5. 自動デッキ構築ヒント

`engine/deckbuilder.py` への target 値:

| 特徴 | 上位平均 (= target) | 推奨値範囲 |
|---|---|---|
| avg_cost | 3.744 | [3.6, 3.9] |
| counter_total | 37400 | [36680.0, 38120.0] |
| n_1k_counter | 16.6 | [16.2, 17.0] |
| n_2k_counter | 10.4 | [10.2, 10.6] |
| blocker_count | 11 | [10.4, 11.6] |
| free_event_count | 0 | [0.0, 0.0] |
| synergy_density | 0.616 | [0.6, 0.6] |
| color_cohesion | 0.784 | [0.8, 0.8] |

## 6. 注意事項 (= 解釈の限界)

- サンプル数 16 active deck のみで相関を計算 → 統計的有意性は限定的
- bug_baseline matrix は 旧 AI 同士の勝率 (= 真の Tier ではない)
- Phase 7 full matrix 完了後に再分析推奨 (= AI 強化で勝率の意味が変わる)
- 個別 deck の構築理由 (= テクニカルプレイ前提) は反映されない
