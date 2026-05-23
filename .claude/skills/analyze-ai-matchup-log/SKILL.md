---
name: analyze-ai-matchup-log
description: AI vs AI 自動対戦 (= harness.run_matchup / matchup_matrix) の log を 解析し、 AI 悪手パターン + 勝率異常 + heuristic 改善点 を engine/ai.py / engine/eval.py の 具体的な コード変更案 まで落とす。 ohtsuki さんが「matrix の結果見て」 「AI vs AI ログ分析して改善案出して」 と言った時に invoke する。
last_checked: 2026-05-23
---

# AI vs AI matchup log 解析 skill

> **目的**: 既存の AI vs AI 解析資産 (= `scripts/report_bad_moves.py` + `db/matchup_matrix.json` + `state.action_evals`) を 1 つの flow で 統合解釈し、 「真の AI 悪手」 と 「勝率異常デッキ」 から engine 改善 issue を 抽出する。

## 使いどき

ohtsuki さん が こう言ったら invoke:
- 「matrix の結果見て」 「matchup matrix で異常 出てる?」
- 「AI vs AI の log 分析して改善案出して」
- 「<deck-A> vs <deck-B> で AI 何が下手?」
- 「最近の matrix run の悪手 確認して」
- 「<deck-slug> の勝率 低い理由 分析して」

## [[analyze-human-play-log]] との 違い

| 軸 | この skill (= AI vs AI) | analyze-human-play-log |
|---|---|---|
| 入力 source | `db/matchup_matrix*.json` / 再実行 matchup | Vercel Blob `human_play/*.json` |
| 解析対象 | 両 player とも AI | 人間 + AI 両方 |
| 改善軸 | 「AI 悪手 直す」 のみ | 「AI 悪手 直す」 + 「人間 良手 学ぶ」 |
| 試行規模 | 数千試合 (= 16×16 × 20 戦) | 数戦〜数十戦 (= 人間 が プレイ した分のみ) |
| 統計強度 | 高 (= 大数の法則) | 弱 (= 個別事例 ベース) |
| 評価軸 | matrix Tier 変動 + bad_moves count | action_evals delta + ohtsuki さん 主観 |

両方 必要 な場合 = ohtsuki さん 「AI を 強くして」 系: まず matrix で 大局見て (= この skill)、 次 に Human Play log で ohtsuki さん 視点 の弱さ確認 (= [[analyze-human-play-log]])。

## 前提インフラ

| 要素 | 場所 |
|---|---|
| matrix log (= 事前計算 16×16 勝率) | `db/matchup_matrix.json` (= 最新)、 `db/matchup_matrix.step7_*.json` (= 履歴) |
| bad_moves 抽出 script | `scripts/report_bad_moves.py` |
| matrix 再計算 script | `scripts/compute_matchup_matrix.py` |
| weight tuning script | `scripts/tune_eval_weights.py` |
| matrix analysis 報告 | `db/matrix_analysis_report.json` (= 10 軸) |
| action_evals 記録 | `state.action_evals` (= `engine/game.py:apply_action` 内、 record_action_evals フラグ) |
| board_eval 定義 | `engine/eval.py` (= 15 指標 hierarchical) |

## 解析 手順

### Step 0: 状況確認 (= matrix の鮮度)

```bash
ls -la db/matchup_matrix*.json
# 最新 .json の更新日時 確認。 1 週間以上 古い + engine に大きい変更ある なら 再計算 推奨
```

`engine/ai.py` / `engine/eval.py` / `db/card_effects.json` / `decks/*.json` が直近で更新されてれば、 matrix は **stale** の可能性。 再計算判断:

```bash
# 全 16 deck × 256 セル × 20 戦 = 5120 試合 (= 約 60 分)
.venv/bin/python scripts/compute_matchup_matrix.py --n-games 20 --seed 42
```

時間ない なら 個別 pair だけ:

```bash
.venv/bin/python scripts/report_bad_moves.py \
  --deck-a decks/<A>.json --deck-b decks/<B>.json \
  --n-games 10 --seed 42 --threshold -3000
```

### Step 1: matrix 大局 把握

```python
import json
m = json.loads(open("db/matchup_matrix.json").read())
# 各 deck の 平均 勝率 (= row 平均)
for deck_a, row in m["matrix"].items():
    avg = sum(cell["deck_a_winrate"] for cell in row.values()) / len(row)
    print(f"{deck_a}: {avg*100:.1f}%")
# 極端 cell (= 90%+ or 10%-) を抽出 → 勝率異常 候補
```

参照: `CLAUDE.md` の「現在のメタ Tier」 section と 比較し、 直近 Tier 変動 を 把握。

### Step 2: 「真の AI 悪手」 抽出

`scripts/report_bad_moves.py` は **delta_eval が大きく負の手** を 抽出する。 「悪手 = engine 内 board_eval の自陣不利方向への変動」 で 主観評価ではない (= 客観指標)。

```bash
# 個別 pair で 悪手 list 取得
.venv/bin/python scripts/report_bad_moves.py \
  --deck-a decks/cardrush_1456.json --deck-b decks/cardrush_1392.json \
  --n-games 20 --threshold -3000 --out /tmp/bad_moves.json
```

出力 JSON 構造:
```json
{
  "deck_a": "cardrush_1456",
  "deck_b": "cardrush_1392",
  "n_games": 20,
  "by_player": {
    "0": {
      "count": 12,
      "avg_delta": -4523,
      "moves": [
        {"game_idx": 3, "turn": 5, "action": "AttackCharacter", "delta": -6201, "context": {...}},
        ...
      ]
    },
    "1": {...}
  }
}
```

### Step 3: パターン抽出 + 原因仮説

複数試合横断で **同じ (action, context) 組合せ** が 反復出現 = engine 改善 候補:

| 悪手 パターン | 原因仮説 | 改善先 |
|---|---|---|
| AttackCharacter で 不利交換 (= 自 KO される) | `estimate_opp_attack_buff_to_leader` が defender buff 過小評価 | `engine/effects.py:5095-` |
| EndPhase 時 don_active が大量残 | choose_action が play / attach 候補 を見落とし | `engine/ai.py:choose_action` の plan_search depth |
| リーサル取れる ターン で 取らない | `lethal_planner.compute_lethal_threshold` 閾値 / W_LIFE 過小 | `engine/lethal_planner.py` |
| opp_attack cost持ち効果 を 無駄打ち | AI defender heuristic が「払うべきか」 判定なし (= 既知の穴) | `engine/effects.py:_enqueue_opp_attack_with_cost` |
| end_of_turn 任意効果 取りこぼし | `_ai_should_fire_end_of_turn_cost` 雑 | `engine/effects.py:_ai_should_fire_end_of_turn_cost` |
| 1 ターン目 マリガン 判断 ミス | deck `mulligan_keep_card_ids` 未設定 / `_should_mulligan` 閾値 | `decks/<slug>.analysis.json` / `engine/ai.py:_should_mulligan` |

### Step 4: 勝率異常 デッキ の 深掘り

matrix で 平均 勝率 < 30% or > 70% の デッキ は **engine 側 の bias** か **デッキ 自体 の 強弱** か 切り分け 必要:

1. 該当 deck の **bad_moves list** (= 上記 Step 2) を 5 cell × 20 戦 で 取得
2. 平均 bad_moves count / game を 算出 → 他 deck と 比較
3. 異常 多い なら **engine 側 の AI heuristic が この deck を 上手く 扱えてない** (= 改善対象)
4. 異常 少ない なら **デッキ 自体 が 弱い (= 公式メタでも 下位)** で 想定通り

参考: `feedback_evaluation_axis.md` (= raw 勝率 ≠ engine の良し悪し、 AI の行動の質 で 評価)

### Step 5: heuristic 改善 案 を コード変更 まで 落とす

「板 上 で 直すべき箇所」 を **engine/ai.py か engine/eval.py か engine/effects.py の どの 関数 の どの 行** か まで 落として 出力:

```
## 悪手 P1: opp_attack cost持ち効果 を 無駄打ち (= K 試合 で観測)
- 例: cardrush_1456 vs cardrush_1392 game 3 turn 5
  - AI defender が <card_name> の opp_attack 効果 (= ドン-1) を 発動、 だが その後 attacker は どうせ block されて 失敗
  - delta_eval = -3200 (= 1 don 損失 + KO 防止 価値 < 1000)
- 改善案: `engine/effects.py:_enqueue_opp_attack_with_cost` の AI 分岐 (= line 5800-5825) に
  「現 attack が確実 ブロック される なら fire しない」 ガード 追加。
  実装案:
  ```python
  if not is_human_actor:
      # AI: 効果発動が EV 正 か 判定
      from .ai import estimate_attack_blocked_prob
      block_prob = estimate_attack_blocked_prob(state, attacker, defender)
      cost_value = pay_don * 800 + rest_don * 400  # ドン価値
      benefit_value = 推定_KO防止_等
      if cost_value > benefit_value * (1 - block_prob):
          continue  # skip
  ```
- 影響範囲: 全 AI vs AI matchup で opp_attack 効果 持つ deck (= 半数以上) に 影響
- 検証: matrix 再計算 → 該当 deck の avg bad_moves 減少 確認
```

### Step 6: 出力 フォーマット

```
# AI vs AI matchup log 解析 (= matrix N×N、 計 T 試合)

## 大局 (= matrix 概況)
- Tier 変動: <CLAUDE.md 現状 vs 直近 matrix の差>
- 異常 cell (= 90%+ or 10%-): <list>
- 全試合 平均 bad_moves / game: <数値>

## AI 悪手 パターン (= 反復出現)
### P1: <パターン名> (= K 試合 × J cell で 観測)
- 影響範囲: <deck list>
- 原因仮説: <engine/ai.py:func の judge ロジック が X を 考慮していない>
- 改善案: <具体的な コード変更、 関数名 + 行番号 + diff>
- 想定 効果: <該当 deck avg 勝率 +X%>

## 勝率異常 デッキ
### D1: <deck-slug> (= avg 勝率 X%)
- 想定原因: <engine 側 bias / deck 自体の強弱>
- 推奨 action: <heuristic 修正 / ヒント追加 / deck 自体は 触らない>

## 次の Action (= 優先順)
1. <最大影響 修正> (= 着手 N 時間、 期待 +X%)
2. ...
```

## 注意事項 / 落とし穴

- **「raw 勝率 ≠ engine の良し悪し」** 原則 ([[feedback_evaluation_axis]])。 ある deck の勝率 が 下がった = engine 退化、 とは 限らない。 他 deck が 効果 を 正しく 発揮 できる ように なった結果 の 相対変動 も ある。 評価軸 = 「AI が 意味ある 効果 / 戦い方 を 選んだ か」。
- **bad_moves count だけで 判断しない**。 1 つ の 致命悪手 (= -10000) は 10 個 の 軽悪手 (= -3000) より 重い。 avg_delta 重要。
- **同 pair × 同 seed で 再現性 確認**。 1 回だけ の 異常 cell は 偶然 (= ライフ トリガー 連発 等)。 3+ seed で 同 傾向 出る なら 真の パターン。
- **bad_moves から improvement 案 出す 前 に必ず action context (= snapshot) を確認**。 「delta -5000」 の表面 だけ 見て 修正 案 出すと、 実は engine 正常 挙動 (= 不利な 局面 で 唯一 ある 手 を 選んだ) を 改悪 する 危険。
- **マリガン 判断 は action_evals に 載らない**。 別途 `state.log` を grep して 「マリガン: ... 引き直し」 vs 「keep」 の 妥当性 を デッキ archetype の `mulligan_keep_card_ids` 観点 で 評価。
- **NN ベース AI 改善** は Vercel deploy 環境 で off (= `nn_disabled`)。 matrix 上の NN-on 結果 は ローカル 限定。 Human Play 戦 (= [[analyze-human-play-log]]) の AI 強度 は NN-off 線形 eval ベース なので、 NN 改善は Human Play UX に直結しない (= 線形 eval / heuristic 改善 が 本筋)。
- **engine 改善 → 必ず matrix 再計算 + bad_moves 再抽出 で 検証**。 「想定外 の 副作用」 (= 他 deck の 勝率 大幅低下 等) を 見逃さない。

## 関連 skill / メモ

- [[analyze-human-play-log]] (= AI vs 人間 解析、 個別事例 + 人間良手学習)
- [[onepiece-tcg-strategy]] (= プレイング知識、 「真の悪手」 か engine 正常 か 判定 の 根拠)
- [[onepiece-tcg-rules]] (= ルール厳密性、 engine 実装 と 公式 の整合)
- [[feedback_evaluation_axis]] (= raw 勝率 ≠ engine 良し悪し)
- [[project_morning_status_summary]] (= 直近 AI 強化 全体像)
- [[project_plan_h_full_custom_eval]] (= Plan H 16 deck custom spec の 経緯)
