# OPTCG 研究ツール ロードマップ

> このドキュメントは **2026-05-14 確定** の開発方針。 議論経緯は
> [docs/AI_THINKING.md](./AI_THINKING.md) も参照。 過去フェーズの完了状況は
> [CLAUDE.md](../CLAUDE.md) の「開発フェーズと現状」 を参照。
>
> **このロードマップを更新する条件**:
> - Phase の完了 / マイルストーン達成時
> - 設計方針の根本的変更時 (= 単発タスク追加では更新不要)

## ビジョン

**「公式準拠 100% の OPTCG エンジン上で、 デッキ研究と AI 対戦を集合知で進める研究プラットフォーム」**

3 つの達成目標:

1. **デッキ研究ツールとしての完成度**: 推しキャラ軸デッキを組み、 メタトップに勝てるかを定量評価できる
2. **AI 強化の段階的進展**: ヒューリスティック → 確率モデル → self-play 学習 → 超人 AI へ
3. **コミュニティ参加型研究**: ボランティア self-play 計算で世界初の TCG 分散研究を実現

---

## フェーズ概要 (= 全体俯瞰)

| Phase | 内容 | 状態 | 期待効果 | 想定工数 |
|---|---|---|---|---|
| 1 | カード DB | ✅ 完了 | — | 完了済 |
| 2 | ルールエンジン + 効果 DSL | ✅ 完了 | — | 完了済 |
| 2.5 | カード効果オーバーレイ (= 全 4,518 枚) | ✅ 完了 | — | 完了済 |
| 3 | 基本 AI (Greedy / MCTS / Lookahead) | ✅ 完了 | — | 完了済 |
| 4 | メタデッキ DB (= cardrush + tcg-portal top 16) | ✅ 完了 | — | 完了済 |
| 4.5 | PlanningAI (= ターン beam search) | ✅ 完了 | cross +26pt vs Greedy | 完了済 |
| 5 | デッキビルダー | ✅ 完了 | — | 完了済 |
| 6 | Next.js UI | ✅ 完了 | — | 完了済 |
| **7** | **AI ヒューリスティック層強化** | 🔄 進行中 | +10〜20pt 累積 | **2-3 週間** |
| **8** | **学習基盤 (= self-play AI)** | 📋 計画 | +20〜40pt | **2-4 ヶ月** |
| **9** | **分散コンピューティング (= ボランティア)** | 📋 計画 | コミュニティ拡大 | **1-3 ヶ月** |

Phase 7 が現状の直近フェーズ。 8 と 9 は並走可能 (= 8 で 学習基盤完成 → 9 で配布)。

---

## Phase 7: AI ヒューリスティック層強化 (= 直近)

**ゴール**: 現 PlanningAI の判断精度を **+10〜20pt** 改善し、 学習基盤 (Phase 8) の baseline を引き上げる。

### 7A. choose_defense リファクタ (= 即対応)

**問題**:
- `engine/ai.py:747` で blocker 生存判定が `>=` (= 同値で生存扱い)、 公式 7-1-4 違反
- 「block + counter で blocker を救う」 戦略が未実装

**設計**:
- `choose_defense` を **4 候補並列評価** に再構築:
  - A: ブロックしない + leader を counter で守る
  - B: ブロックして特攻 (= blocker 失う)
  - C: **ブロック + counter で blocker を救う** (= 新規、 5000+ power / finisher role / cost ≥ 4 を valuable と判定)
  - D: 何もしない (= ライフ受け)
- 各候補を「払う」(counter + 失う) × 「得る」(leader 守る + 温存) で archetype 別に評価

**期待効果**: **+3〜+8pt**
**工数**: 0.5〜1 日

**Task**: #13 (= 現 matrix 完了後着手)

### 7B. hand_estimator 分布化 (= 確率モデル精密化)

**問題**:
- 現在は「pool 平均カウンター × 手札枚数」 という粗い期待値計算
- リーサル判定の マージン 1.2x や W_LIFE = 1500 が ad-hoc 定数

**設計**:
- `engine/hand_estimator.py` を **ハイパージオメトリック分布** ベースに刷新
- 各カウンター値 / 役割の **分位点** を計算 (= 50% quantile, 90% quantile)
- `EstimatedHand` に `total_counter_quantiles: list[(prob, value)]` 追加
- リーサル判定を **「相手が止められる確率」** ベースに変更:
  ```
  P_lethal = P(opp hand counter total < total_excess)
  if P_lethal >= threshold: 攻撃
  ```
- カウンター切り判断も同様に「risk-adjusted EV」 で意思決定

**期待効果**: **+5〜+15pt**
**工数**: 2-3 日

### 7C. ベイズ deck classifier (= 相手の真の正体推定)

**問題**:
- 現 `MatchupProfile` は opp.leader.card_id ベースの固定マッチング
- 「リーダーが同じでも recipe バリエーション」 を捉えてない
- ターン進行に応じた classification 精度向上が無い

**設計**:
- `engine/deck_classifier.py` を新規作成
- 各 archetype の **カード出現分布** を `decks/_archive/cardrush_raw/` 全件から構築
- ベイズ式で `P(deck_archetype | observed cards) ∝ likelihood × prior`
  - prior = tcg-portal 使用率
  - likelihood = カード分布からの観測尤度 (= Naive Bayes)
- ターンごとに観測 (= trash / 場 / life trigger) を増やしてベイズ更新
- 1-3 ターンで >95% 精度収束見込み

**期待効果**: **+3〜+8pt** (= 動的に MatchupProfile を refined する経路で)
**工数**: 1-2 日

### 7D. MatchupProfile dynamic update (= classifier 連動)

**問題**:
- 現 `_ensure_matchup_overrides` は初回 choose_action で 1 回だけ実行、 以後固定
- ターン進行で classifier の信頼度が上がっても profile を rebalance してない

**設計**:
- classifier 出力 (= P(deck) per archetype) で defense_thresholds / attack_gap_tolerance を **加重平均**
- 各ターン開始時 (= REFRESH) で classifier を再評価
- 信頼度 > 0.7 で固定 profile、 それ以下なら blend

**期待効果**: **+1〜+3pt** (= 7C と組合せで効く)
**工数**: 0.5 日

### 7E. hand_estimator のメタデッキ仮定 (= 7B + 7C 統合)

**問題**:
- 現在 `_opponent_pool` は opp.deck + opp.hand (= 実際の deck list = ズル) を使ってる
- 本来は **「相手の deck identity を classifier で推定 → そのデッキの 50 枚を pool に」**

**設計**:
- pool 構築を classifier 出力でリファクタ
- 高信頼度時: 特定 archetype の 50 枚 - 観測済を pool に
- 低信頼度時: 上位候補の **mixture distribution** で pool 化

**期待効果**: **+2〜+5pt**
**工数**: 1 日

### 7F. メタデッキ pool 再構造化 (= [META_POOL_SPEC.md](./META_POOL_SPEC.md) に詳細)

**問題**:
- 現状の `decks/cardrush_*.json` は flat、 active / historical の区別なし
- 同 leader で構築バリエーション (= 紫エネル 30 件等) が flat 列挙されてる
- 月次更新ワークフローが手動 + ad-hoc

**設計** (= spec 確定済):
- `decks/active/<leader_id_or_variant>/` 階層化
- `decks/historical/<slug>/` で圏外 archetype を凍結保存
- 同 leader で構築差 (= variant) があれば独立 archetype として扱う
- `scripts/refresh_meta_pool.py` で月次自動更新
- `db/matchup_matrix.json` を per-cell timestamp 化 + stale だけ再計算
- archetype slug = `<leader_id>` or `<leader_id>_<variant>` (= 永続)

**期待効果**:
- 直接の AI 強化効果は無いが、 **Phase 7C (deck classifier) の精度を大幅向上**
- ML データ整備で Phase 8 以降の基礎
- 運用効率: 手動 ad-hoc → 月次 cron で自動化

**工数**: **1-2 週間** (= 7F-1 〜 7F-7 の 7 sub-step)
**並走可能**: 7A〜7E と独立に実装可

### Phase 7 合計

- 工数: **2-3 週間** (= 7A→7B→7C+7D+7E の順、 各々独立 実装可)
- 期待効果累積: **+10〜+20pt** vs 現 PlanningAI
- 全完了後の cross matrix で PlanningAI +36〜+46pt vs Greedy 想定

### Phase 7 後の検証

- bug 込み baseline matrix (= 今走ってる、 完了予定 ~5h) を **比較対象**として保存
- 7A 完了後に matrix 再計測 (= 7A 単独効果計測)
- 7B〜7E 後に再度 matrix 計測 (= 累積効果計測)

---

## Phase 8: 学習基盤 (= self-play AI、 中期)

**ゴール**: ヒューリスティック層を越えて、 **学習ベースで上級者層に届く AI** を構築する。

### Phase 8 を考えるための前提整理

OPTCG の特性:
- 不完全情報ゲーム、 ただし **ポーカーよりずっと公開情報に近い** (= ターン 5 で隠匿空間 30 枚→5 枚、 メタデッキ仮定で更に縮約)
- ブラフ要素は本質的に無い (= カウンター値の隠匿は数値推定で代替可能)
- → CFR のような厳密ナッシュ手法は不要、 **「決定論化 + AlphaZero」 で実用近似**

### 8A. self-play インフラ整備

**設計**:
- 既存 `harness.run_matchup` + `replay_recorder` 拡張
- 各試合の (state, action, outcome) を学習データとして蓄積
- 並列実行管理 (= multiprocessing or asyncio)
- 学習データ DB (= `db/training_data.sqlite` 新規)

**工数**: 1 週間

### 8B. policy + value 学習器

**設計**:
- 入力: 盤面 (= 15 指標 + 公開カード集合 + leader_a + leader_b + classifier 出力)
- 出力: policy (= action 分布) + value (= 勝率)
- アーキテクチャ:
  - 最小版: 線形回帰 / shallow MLP で十分
  - 本格版: Transformer (= action embedding + state encoder)
- 学習: 既存 PlanningAI vs PlanningAI の self-play replay を教師に
- 推論時に MCTS rollout (= AlphaZero スタイル) で policy 改善

**工数**: 2-3 週間 (= モデル + 学習ループ + ハイパラ調整)

### 8C. 1 matchup 集中学習 (= 概念実証)

**設計**:
- 1 つの代表 matchup (= 紫エネル vs 緑ミホーク 等) を選び、 self-play 集中
- 1M〜10M 試合の self-play で policy/value 学習
- 完成後、 既存 PlanningAI と勝率比較 (+30pt 以上を目標)
- 学術論文級の貢献度: 「OPTCG で公開 self-play 学習 AI の初出」

**工数**: 1 ヶ月 (= 並行で計算回しながら)
**期待効果**: 対象 matchup で **超人 AI 水準** (= 上級プレイヤーに勝てる)

### 8D. archetype-aware general policy (= 全 matchup 対応)

**設計**:
- 1 つの NN を 16 archetype × 16 archetype の全 matchup で学習
- 入力に archetype embedding を含めて general policy 化
- AlphaStar (StarCraft 2 の各種族対応) のアプローチを応用
- 推論時に classifier (Phase 7C) で opp archetype を確率推定 → policy 入力に反映

**工数**: 2-3 ヶ月 (= 8B/8C の経験を踏まえて)
**期待効果**: 全 matchup で **+20〜+40pt** vs 現 PlanningAI

### Phase 8 合計

- 工数: **2-4 ヶ月** (= 8A→8B→8C→8D の順、 並行不可)
- 期待効果: **「上級者層に勝てる AI」** 達成
- 計算リソース: CPU で数日〜数週間 (= 4.7s/g で 1M 試合は 5,400 CPU-時)

---

## Phase 9: 分散コンピューティング (= ボランティア参加型)

**ゴール**: コミュニティ参加で AI 改善を持続化、 OPTCG 領域での **公開分散研究の先例** を作る。

### 参考事例

- **LeelaChessZero**: チェス AI を分散 self-play で学習、 数千 GPU 同時
- **KataGo**: 囲碁 AI の同様プロジェクト
- **Stockfish fishtest**: チェス AI 改善の SPRT 統計検定を分散

OPTCG での実装も同じパターンで可能。

### 9A. 内部分散インフラ

**設計**:
- 既存 FastAPI に追加:
  ```
  POST /api/research/work    → work unit (= matchup, model_version) 払い出し
  POST /api/research/result  → 結果 (= replays, action_evals) 受信 + 検証
  GET  /api/research/status  → 進捗ダッシュボード用
  ```
- クライアント `scripts/research_client.py`:
  ```
  python scripts/research_client.py --server=URL --minutes=10
  ```
- 検証: replay の決定論性チェック (= seed 一致で同じ結果が再現するか)

**工数**: 1 週間

### 9B. 公開可能版 (= UI + 認証 + 検証強化)

**設計**:
- 簡易 Web UI:
  - 「Contribute 10 min」 ボタン
  - 寄与者リーダーボード
  - 学習進捗グラフ (= matchup ごと win rate)
- 認証: GitHub OAuth で軽量 user 管理
- インストーラー: macOS / Linux で `curl install.sh | sh`、 Windows で `.exe`
- fraud 防止: 複数寄与者で同じ work を担当させて多数決検証

**工数**: 2-3 週間

### 9C. ブラウザ WASM クライアント

**設計**:
- Python engine を Pyodide 経由で WebAssembly 化
- ブラウザの WebWorker で self-play 実行
- 「ボタン押して 10 分」 を真に滑らかに実現
- 推定速度: ネイティブの 5-10x slow (= JS interop 経由)

**工数**: 2-4 週間 (= engine の WASM 対応が肝)

### Phase 9 合計

- 工数: **1-3 ヶ月** (= 9A→9B→9C の順、 各段階で機能リリース可)
- 効果: コミュニティ拡大 + 計算リソース増加 (= 1000 人 × 10 分/日 で 7 CPU-日/日 = ~$50/日 相当)
- 価値: **公開分散研究の先例**、 学術 / コミュニティ双方で広報効果

---

## Phase 10+: 超人 AI / 一般化 (= 長期)

### 10A. 任意 deck-pair 汎用 AI

**ゴール**: 「事前学習なしに任意のデッキ vs 任意のデッキ」 で機能する general policy NN

**設計案**:
- deck composition embedding を入力に取る NN
- 全 matchup × 全 deck 変種 で self-play 学習
- AlphaStar / OpenAI Five レベルの大規模 RL 投資

**工数**: 6-12 ヶ月、 GPU クラスタ必須

### 10B. デッキ構築 AI

**ゴール**: 「このリーダーで最強デッキを自動構築する」 AI

**設計案**:
- 既存デッキ + メタ情報 + AI 強さ評価を組合せ
- 進化的探索 / GAN / strategic exploration
- すでに `engine/explorer.py` (= 対策デッキ研究ラボ) の延長

**工数**: 3-6 ヶ月

### 10C. ナッシュ均衡解析 (= 完全な「最適解」)

**ゴール**: 各 matchup のゲーム理論的最適 Tier を算出

**設計案**:
- CFR (Counterfactual Regret Minimization) ベース
- 状態抽象化で計算可能サイズに圧縮
- 公開デッキ全部について Nash 均衡 winrate を計算 = **真の Tier 表**

**工数**: 6-12 ヶ月 (= 研究プロジェクト級)

---

## 依存関係グラフ

```
Phase 7 (= ヒューリスティック層)
   ├── 7A (choose_defense fix) — 単独
   ├── 7B (hand_estimator 分布化) — 単独
   ├── 7C (deck classifier) — 単独
   ├── 7D (MatchupProfile dynamic) — 7C 依存
   └── 7E (hand pool 精密化) — 7B + 7C 依存
        ↓
Phase 8 (= 学習)
   ├── 8A (self-play インフラ) — Phase 7 完了が baseline
   ├── 8B (policy/value 学習器) — 8A 依存
   ├── 8C (1 matchup 集中) — 8B 依存
   └── 8D (general policy) — 8C 依存
        ↓
Phase 9 (= 分散) — 8A 以降と並走可能
   ├── 9A (内部分散) — 単独
   ├── 9B (公開版) — 9A 依存
   └── 9C (WASM) — 9B 依存
        ↓
Phase 10 (= 超人 / 汎用)
   ├── 10A (任意 deck 汎用) — Phase 8 完了
   ├── 10B (デッキ構築 AI) — Phase 8 完了
   └── 10C (ナッシュ均衡) — 独立、 大型研究
```

---

## 評価指標 (= 各 Phase の達成度判定)

各 Phase 完了時に以下を計測:

| 指標 | 計測方法 | 目標値 |
|---|---|---|
| **cross matrix Δ** | PlanningAI 改良版 vs baseline で 30+ cells 計測 | +Npt 達成 |
| **bad_move_rate** | scripts/report_bad_moves.py で抽出 | < 3% 維持 |
| **試合時間** | profile_planning_ai.py | 規定値内 |
| **pytest 通過率** | tests/ 全件 | 100% |
| **engine 厳密化 audit** | scripts/audit_engine_strictness.py | 10/10 維持 |

---

## 開発進行原則

1. **段階的検証**: 各 sub-phase 完了時に matrix で効果を数値検証
2. **後方互換**: 既存テストは破壊しない、 公式準拠 100% を維持
3. **公式テキスト忠実主義**: AI 強化は engine ルール準拠の上で行う (= 反則的な手は実装しない)
4. **データ蓄積**: replay / training data は常に保存、 後で再利用できるように
5. **ROADMAP 更新**: Phase 完了 / 方針変更時のみ。 単発タスク追加では更新不要

---

## 直近の優先順位 (= 2026-05-14 時点)

1. **進行中の matrix 完走 (= bug baseline 保存)** — ETA 5h
2. **Phase 7A: choose_defense fix** — matrix 完了後即着手、 工数 1 日
3. **Phase 7A 後の matrix 再計算** — 効果検証
4. **Phase 7B〜7E の順次実装** — 2-3 週間で完了
5. **Phase 8A の準備調査** — Phase 7 完了後

---

## 関連ドキュメント

- [CLAUDE.md](../CLAUDE.md): プロジェクト全般の規約 + 完了フェーズ詳細
- [docs/AI_THINKING.md](./AI_THINKING.md): 現 AI 思考プロセス (人間レビュー用)
- [decks/_archive/cardrush_raw/](../decks/_archive/cardrush_raw/): 過去 3 ヶ月の優勝レシピ 88 件 (= deck classifier 学習データ)
- memory: `MEMORY.md` で各種 project / feedback memory にリンク
