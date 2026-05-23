---
name: analyze-human-play-log
description: AI vs 人間 (= Human Play) の対戦ログを Vercel Blob から sync して解析し、 AI 悪手 + ohtsuki さん良手 を抽出して engine/ai.py heuristic の改善案 を提案する。 ohtsuki さんが「Human Play のデータ見て」「対戦ログ見て改善案出して」 と言った時に invoke する。
last_checked: 2026-05-23
---

# Human Play 対戦ログ 解析 skill

> **目的**: ohtsuki さんが Human Play で対戦した実データ を 全件 取得 → AI 悪手 と ohtsuki さん良手 を 自動抽出 → engine/ai.py / engine/eval.py の 改善 issue 化。

## 使いどき

ohtsuki さん が こう言ったら invoke:
- 「Human Play のデータ見て」
- 「対戦ログ確認して改善案出して」
- 「最近の対戦から AI 悪手 抽出して」
- 「俺 の 良い動き 何があった?」

## 前提インフラ

| 要素 | 場所 |
|---|---|
| 試合 log の master | Vercel Blob (= `human_play/*.json`) |
| local cache | `db/human_play_log/*.json` |
| sync script | `scripts/sync_human_play_log.py` |
| Blob token | `.env` の `BLOB_READ_WRITE_TOKEN` |
| serialize 形式 | `engine/human_session.py:serialize_for_log` (= schema_version=1) |

各 log JSON の構造:
```json
{
  "schema_version": 1,
  "timestamp_utc": "...",
  "metadata": {
    "deck_human_slug": "cardrush_1456",
    "deck_ai_slug": "tcgportal_bonney",
    "human_idx": 0,
    "ai_idx": 1,
    "human_first": true,
    "ai_class": "GoalDirectedAI",
    "ai_spec_version": "v1"
  },
  "result": {
    "winner_idx": 0,
    "winner_for_human": 1,    // 1=人間勝、 0=AI勝、 -1=引/timeout
    "turns": 8,
    "p_human_life_left": 2,
    "p_ai_life_left": 0
  },
  "log": ["...", "..."],            // push_log の 全行
  "snapshots": [{...}, {...}],      // 中間 state (= UI 再生 と同じ)
  "action_evals": [                 // ★ 解析の核
    {
      "turn": 3,
      "player_idx": 0,              // 0=人間、 1=AI (= metadata 参照)
      "action": "AttackLeader",
      "eval_before": -1234,
      "eval_after": +567,
      "delta": 1801,
      "context": {...}              // optional
    },
    ...
  ]
}
```

## 解析 手順

### Step 1: 最新データを Blob から sync

```bash
.venv/bin/python scripts/sync_human_play_log.py
```

これで `db/human_play_log/<timestamp>_<deckA>_vs_<deckB>_<winnerTag>_<sid8>.json` が全件 download される (= 既存 file は skip)。

### Step 2: 全試合を loop で読み込み、 action_evals を解析

```python
import json
from pathlib import Path

logs = sorted(Path("db/human_play_log").glob("*.json"))
print(f"対象: {len(logs)} 試合")

for log_path in logs:
    data = json.loads(log_path.read_text(encoding="utf-8"))
    meta = data["metadata"]
    result = data["result"]
    evals = data["action_evals"]
    human_idx = meta["human_idx"]
    ai_idx = meta["ai_idx"]
    # AI 悪手: AI の action で delta が大きく負
    ai_bad = [e for e in evals if e["player_idx"] == ai_idx and e["delta"] < -2000]
    # 人間 良手: 人間 の action で delta が大きく正
    human_good = [e for e in evals if e["player_idx"] == human_idx and e["delta"] > +2000]
    # 人間 悪手: 参考用 (= ohtsuki さん の癖 を 知る)
    human_bad = [e for e in evals if e["player_idx"] == human_idx and e["delta"] < -2000]
    ...
```

### Step 3: 文脈再構築 (= snapshots 参照)

action_evals だけだと「何が悪い手なのか」 分かりづらいので、 snapshots[turn_index] を 引いて 当該 場面 の盤面・手札・ライフ・DON状況 を見る:

```python
# 該当 turn の snapshot を 取得
snap_at_turn = data["snapshots"][snapshot_idx_for_turn(data, e["turn"])]
# 自分/相手 の field / hand / don / life を見て、 「なぜこの action が悪いのか」 を判定
```

snapshot の中身は `state.snapshot_dict()` 由来。 主要 key:
- `players[i].life` (= 残ライフ)
- `players[i].hand_count` (= 手札枚数)
- `players[i].don_active` / `don_rested`
- `players[i].leader.power` / `characters[]` 各 InPlay
- `players[i].trash[]`

### Step 4: パターン抽出 + 改善 issue 化

複数試合横断で **同じ悪手パターン** が出てたら **engine 改善対象**:

| 悪手 パターン例 | 改善先 |
|---|---|
| 6 ドン あるのに 5 コス出さず end_phase | `engine/ai.py:choose_action` の plan_search 評価 / GreedyAI fallback |
| リーサル取れる場面で取らない | `engine/lethal_planner.py` 閾値 / `engine/eval.py` W_LIFE |
| 不利アタック で カード KO される | `estimate_opp_attack_buff_to_leader` 拡張 |
| opp_attack cost持ち効果 を無駄打ち | `_enqueue_opp_attack_with_cost` の AI 判断 (= 現状 heuristic なし) |
| end_of_turn 任意効果 を 取りこぼし | `_ai_should_fire_end_of_turn_cost` 拡張 |

ohtsuki さん **良手** で AI が同盤面で別 action を選んだ場合:
- 「ohtsuki さん が ある盤面 で X を選んだ → eval +3000」
- 「AI 同盤面 で Y を選ぶ heuristic (= GoalDirectedAI v1 spec) → eval +500」
- → spec 拡張 候補 (= `engine/goal_directed_ai.py` の target_spec に X 系 entry 追加)

### Step 5: 出力フォーマット

ohtsuki さん向け 報告は こう構造化:

```
# Human Play log 解析 (= N 試合、 対象期間 X~Y)

## 総合
- 勝率: 人間 X 勝 / AI Y 勝 / 引 Z
- 最 悪手 (AI): turn T で <action> → delta <D> (試合 <slug>)
- 最 良手 (人間): turn T で <action> → delta <D> (試合 <slug>)

## AI 悪手 パターン (= 反復出現)
### P1: <パターン名> (= K 試合 で 観測)
- 例: 試合 <slug>, turn T で <action> → delta <D>
- 原因仮説: <engine/ai.py:func の judge ロジック が X を 考慮していない>
- 改善案: <具体的な コード変更 or heuristic 閾値>

## 人間 良手 パターン (= AI に 学ばせる候補)
### P1: <パターン名>
- 例: 試合 <slug>, turn T で <action> → delta <D>
- AI が 同盤面 で 選んだ 手: <action> (= delta <D'>)
- 改善案: GoalDirectedAI spec に <entry> 追加 / heuristic に <ルール> 追加

## 次の Action
1. <最優先 修正項目> (= 影響大、 着手 1-2 時間)
2. ...
```

## 注意事項 / 落とし穴

- **action_evals は player_idx 識別必須**。 metadata.human_idx と ai_idx で 判別。
- **delta = eval_after - eval_before** で **actor 視点**。 つまり 人間 turn の人間 action の delta は人間 視点、 AI turn の AI action の delta は AI 視点。 比較する時 視点が混ざる ので注意。
- **snapshot.turn != action_evals[i].turn の 1:1 mapping ではない**。 snapshot は 各 phase / event resolve ごと に 記録される (= 1 action で 複数 snapshot)。 turn 番号 + player_idx で 範囲絞り 検索。
- **ohtsuki さん が 投了 (= 早期 end) した場合** snapshot 数 少なく、 評価対象 action 少ない可能性。 result.winner_for_human=-1 か turns < 5 なら 警告。
- **delta=0 や delta>0 だが 大きい AI action は 「悪手ではない」**。 閾値 default は **delta < -2000** (= AI 視点で 2000 ぶん 悪化)。 必要 なら 増減。
- **EndPhase action の delta は 通常 ニュートラル**。 EndPhase で delta < -2000 は 異常 (= reset_turn_buff 等 で 大変動)、 これは正常な engine 挙動 なので 除外。
- **Mulligan / マリガン 判断** は action_evals に 載らない。 log の "マリガン" 行 を grep して 別途 分析。
- AI heuristic 変更後 は 必ず **同条件 で re-eval (= 同じ Blob log を 再解析、 fresh matrix も走らせて 整合確認)**。 [[feedback_evaluation_axis]] の「raw 勝率 ≠ engine の良し悪し」 原則 を遵守。
- **AI vs AI 専用解析** が必要 なら [[analyze-ai-matchup-log]] skill を併用。 こちらは 人間 介在 なし の matchup matrix log 解析。

## 関連 skill / メモ

- [[analyze-ai-matchup-log]] (= AI vs AI 解析、 matrix log + report_bad_moves)
- [[onepiece-tcg-strategy]] (= プレイング知識 で AI 判断の妥当性チェック)
- [[onepiece-tcg-rules]] (= ルール厳密性、 engine 実装との整合)
- [[feedback_evaluation_axis]] (= raw 勝率 ≠ engine 良し悪し)
- [[project_morning_status_summary]] (= 直近 AI 強化 path の文脈)
