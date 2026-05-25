---
name: review-all-match-feedback
description: spectate コメント + AI vs AI matchup ログ + AI vs 人間 (Human Play) ログ を 3 つまとめて 横断 解析 し、 (a) engine/ai.py / engine/eval.py の AI heuristic 改善、 (b) db/card_effects.json overlay + engine/effects.py primitive の カード効果 バグ修正、 (c) UI/UX 改善 を 優先度 付き で 出す orchestrator skill。 ohtsuki さん が 「コメント と 対戦ログ まとめて 確認 して」 「全部 見て 改善案 出して」 「総合 解析 して」 「カード効果 バグ 探して」 と 言った時 に invoke する。
last_checked: 2026-05-25
---

# 全 match feedback まとめ 解析 skill

> **目的**: 3 つ の独立 した data source (= spectate コメント / AI vs AI matrix / Human Play Blob) を **1 つの 改善 plan に統合** する orchestrator。 「コメント と 対戦ログ 全部 まとめて 見て」 系 依頼 を 1 回 の invoke で 完結 させる。

## 使いどき

ohtsuki さん が こう言ったら invoke:
- 「コメント と 対戦ログ まとめて 確認 して」
- 「全部 見て 改善案 出して」
- 「総合 解析 して」 「総合 レビュー して」
- 「AI vs AI と AI vs 人間 両方 見て 改善」
- 「最近 の data 全部 で AI 弱い ところ 出して」
- 「engine 改善 タスク 一覧 ほしい」
- 「カード効果 バグ 探して」 「効果 動いてない カード ない?」
- 「公式と違う 動き してる カード あれば 直して」

**単独 source だけ で 十分** な場合 は 個別 skill を invoke:
- spectate コメント のみ → `/api/spectate/comments/clusters` 直 curl (= skill 不要)
- AI vs AI のみ → [[analyze-ai-matchup-log]]
- Human Play のみ → [[analyze-human-play-log]]

## 3 source の 性質 と 役割

| source | 入力 | 強み | 弱み | 担当軸 |
|---|---|---|---|---|
| spectate コメント | SQLite/Postgres `comments` | **人間視点 の 質的 評価** (= 「これ悪手」 「効果 発動 してない」 「演出 直して」) | 件数 少、 主観 | UX + 戦術 + 効果バグ報告 |
| AI vs AI matrix | `db/matchup_matrix*.json` + `report_bad_moves.py` | **統計強度** (= 数千試合)、 客観 delta、 効果未発火 検知 | パターン重複、 「真の悪手」 か engine 正常 か 切分け 難 | engine 系統 bias + 効果実装漏れ |
| Human Play Blob | Vercel Blob `human_play/*.json` | **ohtsuki さん 視点 の AI 弱さ** + 良手 教師 + 効果違和感 | 件数 少、 個別事例 | heuristic 漏れ + 効果挙動異常 |

3 つ を 重ねた時 に 浮かぶ パターン が **最優先 改善 対象** (= 統計 + 質 + 教師 が 揃う)。

## 改善 対象 軸 (= 3 系統)

| 軸 | 対象 ファイル | 検知 source 主 | 修正 手順 |
|---|---|---|---|
| **(a) AI heuristic** | `engine/ai.py` / `engine/eval.py` / `engine/lethal_planner.py` / `engine/goal_directed_ai.py` | matrix bad_moves + human_play action_evals | 各 関数 修正 + tests + matrix 再計算 |
| **(b) カード効果 (= overlay/primitive)** | `db/card_effects.json` + `engine/effects.py:execute_effect` の primitive | コメント (= 「効果 動かない」) + log の `_unimplemented` / primitive errors + action_evals 異常 | [[onepiece-tcg-rules]] で 公式確認 → overlay 修正 / 新 primitive 追加 + `tests/test_effects.py` + audit script 走らせ |
| **(c) UI / UX** | `web/src/components/*.tsx` | コメント (= 「modal わかりにくい」 「演出 重複」) | tsx 修正 + tsc + 該当 flow 手動 確認 |
| (d) デッキ 分析 (参考) | `decks/<slug>.analysis.json` | matrix avg 勝率 + human_play AI マリガン妥当性 | hand_keep / hint 更新 |

## 前提インフラ

| 要素 | 場所 |
|---|---|
| spectate コメント DB | `${DATA_DIR}/spectate_comments.sqlite` (= local) or Postgres (= production) |
| コメント クラスタリング | `engine/comment_clustering.py:cluster_comments` |
| コメント クラスタ API | `GET /api/spectate/comments/clusters?replay_key=<key>` (= replay_key 省略 で 全件) |
| matrix log | `db/matchup_matrix.json` (= 最新)、 `db/matchup_matrix.step7_*.json` (= 履歴) |
| bad_moves 抽出 | `scripts/report_bad_moves.py` |
| Human Play sync | `scripts/sync_human_play_log.py` → `db/human_play_log/*.json` |
| serialize 形式 | `engine/human_session.py:serialize_for_log` (= schema_version=1) |
| カード効果 overlay | `db/card_effects.json` (= 4,518 全カード、 _unimplemented = 0 が 健全状態) |
| DSL primitive 実装 | `engine/effects.py:execute_effect` の `elif k == "..."` 列挙 (= 180+ 種) |
| overlay vs FAQ 監査 | `scripts/audit_overlay_vs_faq.py` → `db/overlay_audit.{md,json}` |
| overlay vs cardqa 整合 | `scripts/verify_overlay_vs_cardqa.py` → `db/overlay_when_missing.json` |
| DSL vs 日本語 整合 | `scripts/audit_dsl_jp_vs_text.py` |
| engine 厳密化 audit | `scripts/audit_engine_strictness.py` (= 10/10 が 健全状態) |
| 効果 smoke | `scripts/smoke_test_card_effects.py` (= 全カード 最小発火) |
| カード効果 test | `tests/test_effects.py` + `test_effects_r*_extensions.py` |
| 公式 一次情報 | `db/rules/*.pdf` + `db/faq/cardqa_*.json` (= [[onepiece-tcg-rules]] skill 経由 推奨) |

## 解析 手順

### Step 1: 3 source を まとめて 取得

並列実行 推奨 (= 各 source 独立):

```bash
# A) spectate コメント (= 全件 cluster) を サーバ から 取得
#    api が 起動 中 (= 通常 port 8000) なら curl、 起動 してなければ
#    DB から 直接 read。
curl -s 'http://localhost:8000/api/spectate/comments/clusters' \
  > /tmp/comment_clusters.json
# fallback (= api off の 時):
.venv/bin/python -c "
import sqlite3, json, os
db_path = os.environ.get('DATA_DIR','./db') + '/spectate_comments.sqlite'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
rows = [dict(r) for r in conn.execute('SELECT * FROM comments ORDER BY created_at ASC')]
from engine.comment_clustering import cluster_comments
clusters = cluster_comments(rows)
print(json.dumps([cl.to_dict() for cl in clusters], ensure_ascii=False, indent=2))
" > /tmp/comment_clusters.json

# B) Human Play log を sync (= 最新 を Blob から pull)
.venv/bin/python scripts/sync_human_play_log.py

# C) AI vs AI matrix 鮮度 確認
ls -la db/matchup_matrix*.json
# 1 週間 以上 古い + engine 大変更 直近 なら 再計算 推奨 (= 60 分):
# .venv/bin/python scripts/compute_matchup_matrix.py --n-games 20 --seed 42
```

### Step 2: 各 source を 個別 解析 (= 詳細 は 既存 skill に 委譲)

**A) コメント クラスタ 解釈** (= この skill が 直接 担当):

```python
import json
clusters = json.loads(open("/tmp/comment_clusters.json").read())
# 重要度 sort (= agreed_total + count * 0.5 で 自動 sort 済)
for cl in clusters[:10]:
    print(f"[{cl['dominant_theme']}] {cl['action_type']} (= {cl['count']}件、 agreed {cl['agreed_total']})")
    for cm in cl['comments'][:3]:
        print(f"  - T{cm.get('snapshot_turn','?')} {cm['author']}: {cm['text']}")
```

dominant_theme の 主 候補 (= `engine/comment_clustering.py:76` 参照):
- `bug` / `effect` / `power` / `cost` / `target` / `lethal` / `mulligan` / `defense` / `ui` / `other`

theme × action_type の 組合せ が 同じ で 複数 コメント = **engine or UX の 改善 対象 確定**。

**B) AI vs AI matrix 解析** → [[analyze-ai-matchup-log]] の Step 1-4 に従う:
- matrix 大局 (= 平均 勝率 Tier、 異常 cell)
- 該当 cell の bad_moves 抽出 (= `scripts/report_bad_moves.py`)
- 反復 パターン → engine 改善 候補

**C) Human Play 解析** → [[analyze-human-play-log]] の Step 2-4 に従う:
- 全 log で AI 悪手 + 人間 良手 抽出
- snapshot で 文脈 復元
- パターン抽出

各 step の 詳細 出力 を 中間 buffer に 保存:
- A → `/tmp/feedback_a_comments.md`
- B → `/tmp/feedback_b_aiVsAi.md`
- C → `/tmp/feedback_c_humanVsAi.md`

### Step 2.5: カード効果 バグ 検知 (= 全 source 横断)

「AI heuristic 改善」 とは別軸 で、 **カード効果 が 公式通り に 動いていない** バグ を 横断 抽出。 検知 ソース は 3 つ:

**(i) コメント text grep** (= 人間 が 「効果 動かない」 と 報告):

```python
import json, re
clusters = json.loads(open("/tmp/comment_clusters.json").read())
# theme=bug/effect or text に キーワード 含む
KEYWORDS = ["効果", "発動", "不発", "動かない", "動いてない", "おかしい",
            "公式と違う", "ルール違反", "バグ", "想定と違う", "発動しない"]
bug_comments = []
for cl in clusters:
    if cl.get('dominant_theme') in ('bug', 'effect'):
        bug_comments.extend(cl['comments'])
    else:
        for cm in cl['comments']:
            if any(k in cm['text'] for k in KEYWORDS):
                bug_comments.append(cm)
# 同 card_id (= snapshot_log から抽出) で 複数件 = バグ濃厚
```

**(ii) Human Play log の primitive エラー grep** (= engine 内部 error):

```bash
# 全 log で primitive 関連 異常 を grep
grep -lE "_unimplemented|primitive not found|unknown effect|effect not applied|skipped:" \
  db/human_play_log/*.json
# 各 log の log[] field を read して context 抽出
```

**(iii) action_evals の 効果 発火 想定 turn で delta 不一致** (= 想定 +N で 実際 0):
- 例: 「神避 (= +3000 counter event)」 発動 turn で defender_power delta が 想定 +3000 にならない
- 例: 「リーサル成立 想定 ターン」 で 勝利 にならない (= 効果 計算ミス)

**(iv) 既存 audit script 走らせ** (= 健全 ベースライン 確認):

```bash
.venv/bin/python scripts/audit_overlay_vs_faq.py   # → db/overlay_audit.md (sev≥3 が 0 件 が 健全)
.venv/bin/python scripts/verify_overlay_vs_cardqa.py  # → db/overlay_when_missing.json (= 全 0 が 健全)
.venv/bin/python scripts/audit_engine_strictness.py   # → 10/10 が 健全
.venv/bin/python scripts/audit_dsl_jp_vs_text.py      # → 0 件 が 健全
.venv/bin/python scripts/smoke_test_card_effects.py   # → 全カード 発火 成功 が 健全
```

健全 ベースラインから ずれていれば、 **regression 発生中** = まず audit で 検知された カード から 順次 確認。

検知された カード を 集約:

```
バグ候補 カード:
- OP10-071 (ドフラミンゴ): コメント 2 件 + audit overlay_when_missing で 検出
  - 公式: 「自分のドンキホーテ海賊団キャラを1枚レストにすることで、リーダーかキャラを1枚レストにする」
  - 現状 overlay: rest_opp で target_filter が 「ドンキホーテ海賊団」 のみ → 自リーダー が 対象に なってる (= バグ)
- OP12-XXX (...): humanplay log で _unimplemented marker
- ...
```

### Step 3: 3 source 横断 で パターン マッチ

各 source の パターン 一覧 を **同一 issue が 何 source で 出現 したか** で 統合:

```python
# pseudo
issues = {}  # key = (engine_area, pattern_name) -> {sources: set, evidence: list, severity: int}

# A コメント
for cl in clusters:
    key = (theme_to_area(cl['dominant_theme']), cl['action_type'])
    issues.setdefault(key, {'sources': set(), 'evidence': [], 'severity': 0})
    issues[key]['sources'].add('comments')
    issues[key]['evidence'].append(...)
    issues[key]['severity'] += cl['agreed_total'] + cl['count'] * 0.5

# B AI vs AI bad_moves
for pat in bad_moves_patterns:
    key = (pat['engine_area'], pat['pattern_name'])
    issues.setdefault(key, {...})
    issues[key]['sources'].add('matrix')
    issues[key]['severity'] += pat['affected_deck_count'] * 2

# C Human Play
for pat in human_play_patterns:
    key = (pat['engine_area'], pat['pattern_name'])
    issues.setdefault(key, {...})
    issues[key]['sources'].add('humanplay')
    issues[key]['severity'] += pat['count'] * 1.5
```

**優先度 = severity × len(sources)** (= 多 source で 観測 = 真の 課題)。

### Step 4: 改善 タスク 化 (= 軸 別)

各 issue を **対象 ファイル の どの 関数 の どの 行 を 直す か** まで 落とす。 軸 ごと に 修正 手順 が 異なる:

**軸 (a) AI heuristic 改善** (= [[analyze-ai-matchup-log]] / [[analyze-human-play-log]] の Step 5 参照):

```
## I1: <issue 名> (= comments K件 + matrix M cell + human N試合 で観測)
- sources: [comments, matrix, humanplay]
- severity: <score>
- 改善先: <engine/ai.py:func or engine/eval.py:weight>
- コード変更案: <diff or pseudo>
- 影響範囲: <deck list>
- 検証手順:
  1. matrix 再計算 で 該当 pattern 減少 確認
  2. Human Play で 同 situation 再現 → AI 行動 改善 確認
```

**軸 (b) カード効果 (= overlay/primitive) 修正** (= 公式 厳密 主義、 [[onepiece-tcg-rules]] 必須):

```
## E1: <card_id> (= <card_name>) の <効果記述> が <症状>
- sources: [comments × N、 humanplay × M、 audit script]
- 公式テキスト 確認: [[onepiece-tcg-rules]] で db/faq/cardqa_<series>.json を grep 確認
  - Q&A id: <id> / 公式回答: 「...」
- 現状 overlay (= db/card_effects.json 該当 entry): <抜粋 + 何が違うか>
- 必要 primitive: <既存 で 表現可 / 新規 primitive 追加が必要>
- 修正手順:
  1. (新 primitive 必要なら) engine/effects.py:execute_effect に elif k == "<new_kind>": 分岐 追加 + tests/test_effects.py に 専用 test
  2. db/card_effects.json の 該当 entry を 公式テキスト 忠実 に 書換
  3. .venv/bin/python scripts/audit_overlay_vs_faq.py で sev≥3 = 0 維持 確認
  4. .venv/bin/python scripts/verify_overlay_vs_cardqa.py で missing 0 維持
  5. .venv/bin/python scripts/audit_dsl_jp_vs_text.py で 0 件 維持
  6. .venv/bin/python scripts/smoke_test_card_effects.py で 該当 カード 発火 確認
  7. .venv/bin/pytest tests/test_effects.py で 既存 + 新規 test pass
- 影響範囲: <この カード 採用 deck list、 主に decks/cardrush_*.json + decks/tcgportal_*.json>
- 検証: 該当 deck の human_play で 1 試合 走らせて 効果 想定通り 発火 を log 確認
```

**軸 (c) UI / UX 修正** (= web/src/components/ 直接編集):

```
## U1: <UI 要素> の <問題>
- sources: [comments × N]
- 該当 file: web/src/components/<Component>.tsx:<line>
- 修正方針: <component edit>
- 検証: cd web && npx tsc --noEmit + 該当 flow 手動確認 (= dev server で 再現)
```

### Step 5: 最終 出力 フォーマット

ohtsuki さん 向け 報告:

```
# 総合 match feedback 解析 (= コメント X件 + matrix N pair + human Y試合)

## source 別 概況
- spectate コメント: X件 (= K cluster、 dominant: <theme>)
- AI vs AI matrix: 平均 勝率 Tier <変動>、 異常 cell <M>
- AI vs Human: Y 試合 (= 人間 P 勝 / AI Q 勝)、 反復 AI 悪手 <pat>
- audit script: overlay_vs_faq <X件>、 cardqa_missing <Y件>、 dsl_jp <Z件>、 engine_strict <K/10>

## カード効果 バグ 検知 結果 (= 軸 b、 公式 厳密 主義)
### E1: <card_id> <card_name>
- 症状: <現状 と 公式 の 差>
- 公式 (= cardqa Q&A id <id>): 「...」
- 修正計画: overlay 書換 / 新 primitive 必要 / test 追加

### E2: ...

## AI heuristic 改善 課題 (= 軸 a、 優先度 順)
### I1: <issue 名> [comments + matrix + humanplay]
- 状況: <3 source で 観測 された 共通 パターン>
- 影響: <該当 deck>
- 改善案: <engine/ai.py:func 変更>
- 期待 効果: <該当 cell avg 勝率 +X%>

### I2: <issue 名> [matrix + humanplay]
...

## UI / UX 改善 (= 軸 c、 コメント 主導)
### U1: <要素 + 問題> → 該当 file + 修正方針

## 単 source のみ で 出た 課題 (= 参考、 確証 弱)
- [comments のみ] <issue>: <text>
- [matrix のみ] <issue>: <description>
- [humanplay のみ] <issue>: <description>

## 次の Action (= 優先順)
1. <最優先 issue> 着手 (= N 時間、 期待 効果、 検証 plan あり)
2. ...
```

優先度 ルール:
- **カード効果 バグ (= 軸 b)** は **公式と違う 動き は即修正対象** で 通常 最優先。 公式準拠 100% が このプロジェクト の 根本目標 ([[full_card_coverage_goal]])。
- **AI heuristic (= 軸 a)** は 軸 b 解消 後 に 着手 (= overlay 直してから 再 matrix 計算 した data で 評価 すべき)。
- **UI / UX (= 軸 c)** は 並列着手可、 engine 影響 なし。

## 注意事項 / 落とし穴

- **comments DB が 空** の 環境 (= dev 初期) では Step 2A を skip。 spectate 機能 が 未使用 か 確認 (= count 0 を 確実 に reporting)。
- **コメント の theme 分類 は heuristic** (= `comment_clustering.py:76 extract_themes`)。 ohtsuki さん の 自由 text なので 完全 分類 されない 場合あり。 分類 不明 (= `other`) が 多すぎる なら 元 text を 直接 全件 確認。
- **「同 source で 多発」 と 「複数 source で 観測」 は別** 。 後者 が 真 (= 統計 + 質的 + 教師 で 揃う)。 1 source で だけ で 強く 出る issue は **その source 固有 の bias** の 可能性 (= comments は 主観、 matrix は engine bias、 humanplay は ohtsuki さん 戦術 癖)。
- **既存 skill を 中継 で 呼ばない** (= claude が 自分 で 該当 step 実行)。 [[analyze-ai-matchup-log]] / [[analyze-human-play-log]] は 手順書 として 参照 する だけ で 別 invoke しない (= context 重複 + cost 増)。
- **3 source 全 揃ってない 場合** は 「揃ってる source のみ で 解析」 と 明示 + 「N source で 確認 推奨」 と 提案。 例: matrix が stale (= 古い) なら 「matrix 再計算 を 走らせて から 再解析 が 推奨」。
- **改善 案 は 必ず 検証 計画 付き** で 出す (= [[feedback_evaluation_axis]] 原則: raw 勝率 ≠ engine 良し悪し)。 「matrix 再計算 で 副作用 ない こと」 「Human Play 該当 situation で AI 行動 改善 確認」 「コメント 改善 主観 確認」 の 3 軸 で 検証。
- **「改善 作業 する」 まで 依頼 されてる 場合** は Step 4 まで で 終わらず、 I1 (= 最 優先) を 実装 + tests pass + git diff 提示 まで やる。 単に 「確認 して」 の 場合 は Step 5 出力 で 一旦 終了 して ohtsuki さん 判断 待ち。
- **カード効果 修正 は 必ず [[onepiece-tcg-rules]] で 公式確認 してから** 書換 (= 自動近似/fallback/簡略 禁止 が プロジェクト 規約、 CLAUDE.md 「効果オーバーレイ は 公式テキスト忠実主義」 section)。 cardqa Q&A id を 改善案 に 必ず 引用。
- **新 primitive 追加 した時 は engine/effects.py:execute_effect の 既存 elif chain の 末尾 に 追加** + `tests/test_effects.py` に 専用 test。 既存 primitive 名 と 重複 禁止 (= grep で確認)。
- **overlay 書換 後 は audit script 4 種 (= overlay_vs_faq / verify_overlay_vs_cardqa / audit_dsl_jp / smoke_test) を 全て 走らせて regression 0** を 確認。 1 個でも 増えたら 即 rollback。
- **engine_strictness audit (= 10/10)** が 9/10 に 落ちたら **engine 修正 が overlay 違反 を 引き起こした** 可能性。 該当 audit 項目 を 確認 → engine 側 で 補正 か overlay 側 で 表現変更。
- **「カード効果 バグ」 と 「AI heuristic 悪手」 は 切り分ける**。 効果 が 正しく 発火 した のに AI が それを 活かせない の は heuristic 問題 (= 軸 a)。 効果 そのもの が 動いてない の は 軸 b。 humanplay log の action_evals delta だけ で 判定 すると 混在 する ので、 必ず state.log (= push_log 全行) で 「効果: ...」 行 が 出ているか 確認。

## 関連 skill / メモ

- [[analyze-ai-matchup-log]] (= AI vs AI 単独、 matrix log + report_bad_moves 詳細手順)
- [[analyze-human-play-log]] (= AI vs 人間 単独、 Blob log + action_evals 詳細手順)
- [[onepiece-tcg-strategy]] (= 戦術判断、 「真の悪手」 か engine 正常 か の 根拠)
- [[onepiece-tcg-rules]] (= **カード効果 修正 で 必須**、 公式テキスト 一次情報、 cardqa Q&A id 参照)
- [[feedback_evaluation_axis]] (= raw 勝率 ≠ engine 良し悪し)
- [[full_card_coverage_goal]] (= 公式準拠 100% が プロジェクト 根本 目標、 効果 バグ 修正 の motivation)
- [[project_morning_status_summary]] (= 直近 AI 強化 全体像)
- [[project_card_implementation_audit]] (= 全カード 公式準拠 audit の 履歴、 健全 ベースライン)
