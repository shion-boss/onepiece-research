# プロジェクト: ワンピースカードゲーム デッキ研究ツール

> このファイルは Claude Code が自動的に読み込み、プロジェクトの文脈として利用する。
> プロジェクトの方針・構造・規約をここに集約する。詳細は各サブディレクトリの `CLAUDE.md` を参照。

## このツールが目指すもの

**「公式準拠 100% の OPTCG エンジン上で、 デッキ研究と AI 対戦を集合知で進める研究プラットフォーム」**

3 つの達成目標:

1. **デッキ研究ツールとしての完成度**: 推しキャラ軸デッキを組み、 メタトップに勝てるかを定量評価
2. **AI 強化の段階的進展**: ヒューリスティック → 確率モデル → self-play 学習 → 超人 AI へ
3. **コミュニティ参加型研究**: ボランティア self-play 計算で **公開 TCG 分散研究** を実現

利用シーン:
- 推しキャラを軸にしたデッキを組み、メタデッキ群と AI 対戦させて勝率を見る
- デッキの色配分・コストカーブ・特徴シナジーを可視化する
- 環境上位デッキの傾向を分析する
- 学習基盤 (= Phase 8 以降) で上級者層に届く AI を構築する研究プラットフォーム
- 分散コンピューティング (= Phase 9 以降) でコミュニティ参加型に拡大

**詳細ロードマップは [docs/ROADMAP.md](./docs/ROADMAP.md) を参照**。
Phase 1-6 + 4.5 (= PlanningAI) は完了済、 Phase 7 (= AI ヒューリスティック層強化) が直近の進行フェーズ。

## アーキテクチャ

**Next.js (TypeScript) フロントエンド + Python (FastAPI) バックエンド** の構成。

```
onepiece_research/
├── scraper/        # 公式サイトから全弾スクレイプ (Python)
├── engine/         # ルールエンジン + AI + 対戦ハーネス (Python)
├── api/            # FastAPI で engine をラップする HTTP API (Python)
├── db/             # cards.json / cards.sqlite / card_effects.json (4,518 全登録, 効果あり 3,745)
│                   #   + rules/ (公式PDF) / faq/ (公式Q&A) / banlist/ (禁止リスト)
│                   #   + matchup_matrix.json (事前計算 N×N 勝率)
├── decks/          # メタデッキ JSON (cardrush_*.json — cardrush.media 大会上位由来)
│   ├── *.analysis.json # 各デッキの静的分析 (戦略 / マリガン / キーカード / AI ヒント)
│   └── _archive/   # 旧 meta_*.json + 非代表 cardrush_raw/ の退避先
├── images/         # 全カード画像 (空、scraper --with-images で取得)
├── scripts/        # 補助スクリプト (scrape / cache / matrix / overlay / weight tuning)
├── web/            # Next.js フロントエンド (TypeScript, App Router)
│   └── public/cards/   # 全 4,518 枚キャッシュ済 (878MB)
├── web_skeleton/   # Next.js セットアップ手順 (キックオフ用ハンドオフ、現役性低)
├── examples/       # スモークテスト・デモスクリプト (demo_matchup.py / demo_smoke.py / demo_with_effects.py)
├── tests/          # pytest テスト (270 passed + FAQ 200 placeholder skip)
└── .venv/          # Python 仮想環境 (gitignore 推奨)
```

> **注意**: WSL のホスト経由でマウントされていると `*.py` が `*.PY` (大文字) として
> 表示されることがある。`*.py` 限定の glob/pytest 設定では拾えないので注意。

### なぜこの分割か

| 関心事 | 担当 | 理由 |
|---|---|---|
| カードDB / スクレイプ | Python | requests + BS4 が枯れていてシンプル |
| ルールエンジン / 効果DSL | Python | データクラスとパターンマッチが楽。既存資産あり |
| AI / 対戦シミュレーション | Python | NumPy/将来のRLライブラリとの親和性 |
| デッキビルダーUI | Next.js | リッチなインタラクション・画像表示 |
| ダッシュボード / グラフ | Next.js | recharts/chart.js が豊富 |
| 対戦結果ビューア | Next.js | リアルタイム表示・URL共有しやすい |

## 開発フェーズと現状

- [x] **Phase 1 完了**: カードDB(全54弾4,518枚、`cards.json` / `cards.sqlite`)
- [x] **Phase 2 完了**: ルールエンジン(コアデータ構造、ターン進行、攻防、効果DSL)
  - 主要トリガー (R44-R64 拡張済): 登場/アタック/起動メイン/KO時/ターン終了時/ブロック時/相手アタック時/トリガー/カウンター/メインイベント
    + **on_self_chara_leave_by_self_effect / on_self_rested / on_self_hand_discarded /
      on_self_chara_played / on_opp_chara_played / on_self_event_played /
      on_opp_life_taken / on_self_life_to_hand/to_trash / on_self_don_returned_to_deck /
      on_opp_blocker_use / on_self_chara_ko / on_opp_chara_ko / opp_attack_on_leader /
      opp_attack_on_chara**
  - DSL プリミティブ **180+ 種** (engine/effects.py 内 elif k == "..." パターンで列挙)
- [x] **Phase 2.5 完了**: カード効果オーバーレイ **全 4,518 カード登録 (100%)** (`db/card_effects.json`)。
  - 効果あり: 3,745 件 (82.9%) — character 78.6% / event 100% / leader 100% / stage 79.1%
  - 効果なし (バニラ/ブロッカーのみ/パラレル空): 773 件 (空配列でマーク済)
  - **`_unimplemented` マーカー: 0 件達成 🎯 (R56 で完全消去、 残:なし)**
  - audit sev≥5 = 0、 sev=3-4 = 0 (R59) — `db/audit_acknowledged.json` で intrinsic 除外
  - engine 厳密化 audit 10/10 pass (`scripts/audit_engine_strictness.py`)
  - cardqa vs overlay 整合性 0 漏れ (X5、 `scripts/verify_overlay_vs_cardqa.py`)
  - メタデッキ 15 リーダーは公式テキスト準拠で手書き、その他は自動生成 (近似 + fallback)
  - DSL 条件 (eval_condition): leader_feature/color, self/opp life/hand/don 各種, opp_turn/self_turn,
    self_rested, self_trash_count_ge, self_don_ge, victim_truly_original_power_ge,
    victim_feature_in, played_chara_truly_original_cost_ge, played_self_chara_has_no_effect,
    actor_source_feature_contains, self_chara_filtered_count_ge, don_diff_le 等 30+
  - DSL プリミティブ主要カテゴリ:
    - **draw/discard**: draw / draw_per_self_hand_discarded / trash_self_hand_random / trash_opp_hand_random
    - **KO/離脱**: ko / ko_multi / ko_all_others / return_to_hand(_multi) / return_to_deck_bottom(_multi) /
      chara_to_self_life / chara_to_opp_life
    - **power**: power_pump (amount_per source × multiplier) / power_pump_per_target_attached_don /
      set_base_power / set_base_power_timed / set_base_power_copy
    - **cost**: set_base_cost / set_base_cost_timed / reduce_play_cost / reduce_play_cost_filtered_static
    - **don**: attach_don / attach_rested_don / attach_active_don / add_don / add_rested_don /
      untap_don / rest_opp_don / keep_opp_rested_don_next_refresh / rest_self_don_for_battle_buff_per_don
    - **rest**: rest / untap_chara / rest_self_cards(_filtered) / set_cannot_rest / stay_rested_next_refresh
    - **search/play**: search / play_from_hand(_or_trash/_named/_named_set/_named_with_dynamic_cost) /
      play_from_trash / play_event_from_hand / summon_from_deck / reveal_top_then / reveal_top_play
    - **life**: life_to_hand / life_top_or_bottom_to_hand / put_top_to_life / hand_to_self_life /
      scry_life / scry_all_life_one_to_deck / scry_all_life_reorder / mill_self_life_until_n /
      peek_self_life_top / mill_opp_life_to_hand/to_trash
    - **キーワード付与**: give_keyword (target/keyword/keywords-choice/duration: turn|next_opp_turn_end) /
      give_rush / give_attack_active_chara
    - **置換効果**: replace_ko / replace_leave / replace_rest (cost 配列 + do)
    - **KO 耐性**: prevent_ko / set_ko_immune / set_ko_immune_timed / set_ko_immune_battle_only /
      set_immune_attribute_in_battle (negate option)
    - **静的効果**: set_attack_taunt / set_cannot_attack_static / set_opp_protect_static /
      cannot_attack_target_except / cannot_attack_target_cost_le
    - **コスト/遅延**: optional_cost_then / schedule_at_opp_main_phase_start / schedule_at_self_turn_end /
      block_self_draw_turn / block_chara_play_turn / prevent_self_life_to_hand_turn /
      set_attack_cost_discard_hand / optional_discard_hand_for_battle_buff
    - **その他**: redirect_attack / negate_effect / disable_effect / extra_turn / swap_opp_power /
      draw_per_hand_to_deck_bottom / return_self_to_deck_bottom_if_condition / trash_to_deck /
      opp_trash_to_deck_bottom / static_swords_attack_chara / 他
- [x] **Phase 3 完了**: AI (`GreedyAI` / `RandomAI` / `LookaheadAI` / `MCTSAI`)、対戦ハーネス
  - GreedyAI 攻撃: パワー不足の確定失敗アタックを除外 / 1ドンで届く gap には DON 付与 /
    キャラ KO 狙いを優先 (相手コスト高優先)
  - GreedyAI 守備: ライフ残量別の counter 切り判定 (life≤1 全力, life=2 +8000/3枚許容,
    life=3 +6000/2枚, life≥4 +2000/1枚)、コスト4以上のキャラ攻撃には1枚カウンター
  - **リーサル計算**: ターン開始時、合計打点 - 相手 counter 推定 で勝利可能か判定
  - **アタック順最適化**: 弱→強で攻撃 (相手の counter 抗力を消費させる)
  - **reactive buff 予測**: opp_attack による defender 強化を事前見積、低パワー攻撃を抑制
    (`engine.effects.estimate_opp_attack_buff_to_leader` を choose_action で使用)
  - **アーキタイプ別ヒューリスティック**: `decks/<slug>.analysis.json` を読み込んで GreedyAI が
    アーキタイプ (アグロ/ミッド/コントロール/ランプ) ごとに防御閾値・攻撃 gap_tolerance を切替。
    マリガンも `mulligan_keep_card_ids` ベース。 `harness.run_matchup` が deck.slug 経由で自動ロード。
  - **構造化 AI ヒント** (`ai_hint_signals`): synergy_feature_priority / early_finisher_hold /
    avoid_life_loss / tank_lifeup_ok / blocker_scarce 等を AI が読み取って挙動に反映
  - **defender の attacker buff 予測**: `estimate_attacker_self_buff` で attacker の on_attack
    自己強化を見越して counter 量を決定 (= 「6000 攻撃に 1000 counter で打ち消されるはず」 のバグ修正)
  - **重み自動チューニング** (`scripts/tune_eval_weights.py`): matchup matrix を ground truth に
    grid search で W_LIFE 等を最適化提案 (auto-apply はしない、 現状 79.5% 予測精度で近最適)
  - **ハンド推定** (`engine/hand_estimator.py`): 隠匿情報モデル最小実装。 sample_opponent_hand /
    estimate_counter_total / determinize_state を提供 (将来 MCTS 等で活用予定)
  - MCTSAI: UCT-based、`n_simulations=30`、ロールアウト+ヒューリスティック評価。opt-in (低速)
  - **RuleReferee**: AI vs AI 対戦中のルール違反監視。 R60 matchup matrix 計算 (256 ペア × 20 戦 = 5120 試合) で違反ゼロ
  - **AI 行動品質評価基盤** (R61-R64):
    - `engine/eval.py`: 9 指標 board_eval (life/field/power/hand/don/blocker/attached_don/active_chara/lethal)
    - `state.action_evals`: apply_action 前後で compute_score → 1 action = 1 delta 記録
    - `scripts/report_bad_moves.py`: delta_eval が大きく負の手を抽出 → AI 改善ヒント
    - 検証結果: 真の悪手 0.5% (= 1535 actions 中 8 件)、 AI 判断は概ね健全
    - `engine.effects.estimate_opp_life_trigger_attacker_ko_risk`: ライフトリガー雷迎リスク見積
- [x] **Phase 4 完了**: メタデッキ DB **16 デッキ** (`decks/cardrush_*.json` 15 件 + テストデッキ 1)。
  cardrush.media の大会上位入賞 (優勝/準優勝) を `scripts/scrape_cardrush_decks.py` で取得 →
  アーキタイプ毎に最新優勝を `select_cardrush_representatives.py` で代表選出 →
  禁止ペア違反は除外。月次更新フロー確立。
- [x] **Phase 5 完了**: デッキビルダー
  - `engine/deckbuilder.py`: コアカード固定型自動構築
  - `POST /api/decks` → 任意レシピを `decks/<slug>.json` に保存 (validate 通過必須)
  - `POST /api/decks/validate` → リアルタイム検証
  - `POST /api/decks/build` → コアカード指定で自動構築
  - UI: `/decks/new` (リーダー選択 + カード追加 + 下書き保存 + サーバ保存)
- [x] **Phase 6 完了**: Next.js UI
  - `/cards` ブラウザ(URLクエリ駆動フィルタ + グリッド + 詳細モーダル)
  - `/decks` 一覧 / `/decks/[slug]` 詳細 + 対戦ランナー(`MatchRunner`)
  - `/decks/new` デッキビルダー UI (Phase 5)
  - `/decks/[slug]/analyze` 分析ダッシュボード (recharts: 色配分 Pie / コストカーブ Bar /
    カウンター分布 / 特徴Top / activate_main 一覧)
  - `/meta` matchup matrix ビューア
  - `/faq` 公式FAQ + cardqa 検索
- [x] **画像配信**: 全 4,518 枚を `web/public/cards/` にキャッシュ済 (878MB)。
  `<CardImage>` で 404 → 公式 URL フォールバック。
- [x] **Phase 4.5 完了 (R70+R71)**: **PlanningAI** (ターン全体プラン beam search)。
  - `engine/plan_search.py`: beam search + fast_clone (= CardDef/InPlay の __deepcopy__ 共有/手書きで 3.3x 高速化)
  - `engine/ai.py:PlanningAI` (= GreedyAI を継承、 (beam=4, depth=6) で動作)
  - `engine/eval.py`: 15 指標 board_eval (= 9 基本 + 4 拡張 + chara_quality/hand_quality/opp_hand_threat)
  - 検証: cross matrix で 30 cells 中 23 改善 / 平均 **+26pt** vs Greedy baseline
  - 速度: 8s/g → **2.4s/g** (R70 deepcopy 削減 + depth 8→6)
  - `engine/harness.run_matchup` の default AI に採用 (= R71)
- [x] **メタデッキ Phase 4 拡張 (= tcg-portal 化、 2026-05-14)**: 16 デッキ pool。
  - cardrush 10 件 (= 個別優勝レシピ、 3 ヶ月集計から代表選出)
    + tcg-portal 6 件 (= cardrush 不在の leader を集計合成で補完)
  - 全 16 リーダーは tcg-portal `/meta-analysis` 上位 (= 2026-02-14〜05-13 の 1,040 大会データ)
  - `decks/_archive/cardrush_raw/` に過去 3 ヶ月 88 件の優勝レシピを保管 (= deck classifier 学習用)

### 進行中 / 計画中フェーズ (= Phase 7+, 詳細は [docs/ROADMAP.md](./docs/ROADMAP.md))

- [ ] **Phase 7 進行中**: AI ヒューリスティック層強化 (= 2-3 週間、 期待 +10〜20pt)
  - 7A: `choose_defense` リファクタ (= 4 候補並列評価 + blocker 生存判定 `>=` → `>` rule fix)
  - 7B: `hand_estimator` 分布化 (= ハイパージオメトリック + 分位点ベース リーサル判定)
  - 7C: ベイズ deck classifier (= 観測カードから相手 archetype を確率推定)
  - 7D: MatchupProfile dynamic update (= 7C 出力消費)
  - 7E: hand pool メタデッキ仮定精密化 (= 7B + 7C 統合)
- [ ] **Phase 8 計画中**: 学習基盤 / self-play AI (= 2-4 ヶ月、 期待 +20〜40pt)
  - 8A: self-play インフラ整備 (= replay 蓄積 + 並列実行)
  - 8B: policy + value 学習器 (= 決定論化 + AlphaZero 型 NN)
  - 8C: 1 matchup 集中学習 (= 紫エネル vs 緑ミホーク 等で 超人 AI 水準)
  - 8D: archetype-aware general policy (= 全 matchup を 1 NN で扱う)
- [ ] **Phase 9 計画中**: 分散コンピューティング / ボランティア参加 (= 1-3 ヶ月)
  - 9A: 内部分散インフラ (= /api/research/* + research_client.py)
  - 9B: 公開可能版 (= UI + GitHub OAuth + 検証強化)
  - 9C: ブラウザ WASM クライアント (= Pyodide 経由)
- [ ] **Phase 10+ 長期**: 任意 deck 汎用 AI / デッキ構築 AI / ナッシュ均衡解析
  - 詳細は ROADMAP.md 参照、 6-12 ヶ月の研究プロジェクト級

### 現在のメタ Tier

> **注**: 2026-05-12 R67 時点の旧 Tier 表 (6 デッキ pool, Greedy 同士) は
> `db/matchup_matrix.greedy_baseline.json` に保管済。 2026-05-14 から **16 デッキ pool
> + PlanningAI 同士の matrix** に移行中 (= 走行中の `bun1t1aya` 完了後に Tier 表更新)。
> 暫定 Tier は完了後に追記。

R71 (= PlanningAI default 化 + tcg-portal top-16 pool 化) 後の matrix 結果は完了次第ここに反映。

**評価軸の注意**: raw 勝率 ≠ engine の良し悪し。 他デッキが効果を正しく
発揮できるようになった結果、 相対的に成績が下がったデッキも存在する。
ゴールは「全デッキが強くなる」 ことではなく、 「正しくゲームが行われ、
AI が意味ある効果の使い方・戦い方をしている」 こと。 評価すべきは AI の
各手が (1) 盤面を有利に傾けたか (2) 有利に傾ける布石か (3) 効果を意味ある
タイミング/対象で発動しているか。 詳細は memory `feedback_evaluation_axis.md`。

> 注: 低勝率デッキ (緑紫ルフィ 13% / 青紫サンジ 20% / 黒クロコ 5% 等) の多くは、 起動メインの
> 「ドン-N」 コストを忠実に実装した結果、 AI ヒューリスティックではコスト負担に見合うリターンを
> 引き出せていないため。 本来は手札のシナジーカードを引き出すコンボ前提の効果なので、 デッキ自体の
> 研究と AI 改善の余地が残る。 ただし R64 の bad_moves 分析で「真の AI 悪手は 0.5%」 と判明、
> 残りは確率的不運 (= 雷迎ライフトリガー等) や engine の正常化による相対的変動。

## Next.js 側の方針

- **Next.js 16** + App Router(2026-05 時点 CNA で生成)
- **TypeScript** 必須
- スタイル: **Tailwind CSS v4** (PostCSS設定は CNA 既定)
- 状態管理: Zustand(Reduxは重すぎる)
- データ取得: **Server Components + fetch**、必要なら SWR
- 画像: 自前キャッシュ `/cards/<id>.png` を優先、未キャッシュは公式 CDN へフォールバック
  (`<CardImage>` コンポーネントが onError で切り替え)
- グラフ: recharts(SVG・SSR可。analyze ページで導入済)
- shadcn/ui は **未導入**(必要になったら `npx shadcn@latest init`。
  CLI 名は `shadcn-ui` ではなく `shadcn` (rename 済))

### コンポーネント命名規約

- `<CardTile>`: 一覧用の小さいカード表示(画像 + 名前 + コスト + パワー)
- `<CardDetailModal>`: クリック時の詳細表示
- `<CardImage>`: ローカル画像 + 公式 URL フォールバック付き `<img>` ラッパ
- `<ColorChip color="赤" />`: 色記号 + 背景色のチップ
- `<CardFilterBar>`: `/cards` のクエリ駆動フィルタ
- `<DeckSummaryTile>`: `/decks` 一覧用
- `<MatchRunner>`: `/decks/[slug]` の対戦ランナー
- `<CostCurveChart>`: コストカーブ(未実装、analyze ページで)

## Python 側の方針

- Python 3.10+
- 型ヒント必須(将来 mypy)
- 副作用は `engine/game.py` の `apply_action` に局所化
- 効果は `engine/effects.py` の DSL で記述、`db/card_effects.json` に追記して拡張
- API は `api/main.py`(FastAPI)。Pydantic モデルもこのファイルに同居 (専用 `schemas.py` は未分離)
- カード参照は常に `CardRepository` を経由
- 新しいプリミティブ追加時は `tests/test_effects.py` にテストを足す (`pytest tests/`)

### コードスタイル

- 関数名: snake_case、クラス: PascalCase
- 例外メッセージは英語(マルチバイトの編集ミスを減らすため)
- 日本語コメント可、ただしカード名以外の長文は避ける

### 重要な注意

- `cards.json` を「正」とする。SQLite は派生物
- 効果オーバーレイ(`db/card_effects.json`)は **公式テキスト忠実主義**:
  - 自動近似 (= 「fallback」 「自動抽出」 「簡略」 「省略」 「近似」) **禁止**
  - 解釈不可な効果は `[]` (空) もしくは `{"_unimplemented": "..."}` でマーク
  - 条件節 (ライフ X 以下、 リーダー特徴 Y 等) は省略しない
  - 既存の simplified entry を発見したら必ず公式テキストから再構築
  - `scripts/audit_overlay_vs_faq.py` で違反検出 (severity)
  - DSL に対応する primitive がない場合は新規追加 (`engine/effects.py:execute_effect`)
- ルール厳密性 < シミュレーションが回ること
- カード固有効果はメタデッキの主要カードから優先実装
- **`harness.run_matchup` には `effects_overlay` を必ず渡す**(過去に渡し忘れて全試合で
  効果未発火だったバグあり。デフォルト引数で `db/card_effects.json` を自動ロード済み)
- **DON+1000 は所有者のターン中のみ有効** (公式 6-5-5)。`InPlay.is_owners_turn` フラグを
  `_recompute_static` (= ownership 反映) が更新する。テストで `InPlay.of()` 直接生成時は
  デフォルト True で動くが、ターン跨ぎを伴うシナリオでは必ず `_recompute_static(state)` を
  呼ぶか、`setup_game` 経由で初期化する
- **公式ルールの一次情報は `db/rules/*.pdf` + `db/faq/*.json` + `db/banlist/master.json`** に集約済み。
  skill は `.claude/skills/onepiece-tcg-rules/SKILL.md`。ルール裁定や engine の不一致を直す時はまず skill を参照、
  個別カード Q&A は `db/faq/cardqa_*.json` を grep する

## API 設計

実装済み (`api/main.py`):

| エンドポイント | メソッド | 用途 |
|---|---|---|
| `/api/health` | GET | 死活確認(カード件数返却) |
| `/api/cards` | GET | カード一覧 (color/category/feature/cost_le/cost_ge/name_contains/limit) |
| `/api/cards/{card_id}` | GET | カード単体 |
| `/api/decks` | GET | `decks/*.json` の一覧 (`DeckSummary[]`) |
| `/api/decks` | POST | レシピ保存 → `decks/<slug>.json` (validate 必須、409/422 返す) |
| `/api/decks/validate` | POST | レシピ検証のみ (UI リアルタイム用) |
| `/api/decks/build` | POST | コアカード固定型 自動構築 |
| `/api/decks/{slug}` | GET | デッキ単体 (raw JSON) |
| `/api/decks/{slug}/analyze` | GET | デッキ分析(色配分・コストカーブ・効果密度) |
| `/api/decks/{slug}` | PUT | デッキ上書き保存 (validate 必須) |
| `/api/decks/{slug}` | DELETE | デッキ削除 (`cardrush_*` は保護) |
| `/api/match` | POST | 対戦実行 `{deck_a/deck_b or deck_a_id/deck_b_id, n_games, seed}` |
| `/api/match/{job_id}` | GET | 過去対戦のサマリ |
| `/api/match/{job_id}/games` | GET | ゲーム一覧 (短) |
| `/api/match/{job_id}/games/{i}` | GET | 個別ゲームログ (verbose) |
| `/api/match/history` | GET | 過去対戦の履歴 |
| `/api/meta/matrix` | GET | 事前計算 N×N 勝率マトリックス |
| `/api/faq/search` | GET | 公式FAQ + cardqa 横断検索 |
| `/api/faq/by-card/{card_id}` | GET | 特定カードのQA |
| `/api/faq/sources` | GET | FAQ ソース一覧 |

レスポンス型は `api/main.py` の Pydantic モデルと `web/src/lib/types.ts` の両方で定義。
**不整合が起きたら `api/main.py` 側を真とする**。

## ツール / スクリプト群

主要スクリプト (`scripts/`) は以下のカテゴリ:

| カテゴリ | スクリプト |
|---|---|
| データ更新 | scrape_official_faq.py / scrape_official_banlist.py / scrape_cardrush_decks.py / refresh_all.py |
| overlay 拡張・監査 | suggest_overlay_from_cards.py / merge_overlay_suggestions.py / audit_overlay_vs_faq.py / verify_overlay_vs_cardqa.py / smoke_test_card_effects.py |
| engine 厳密化 | audit_engine_strictness.py (10 項目、 R63 で追加) |
| 対戦・分析 | compute_matchup_matrix.py / report_bad_moves.py (R63、 AI 行動品質) / tune_eval_weights.py |
| 画像 | cache_deck_images.py / cache_all_images.py |

主要データ (`db/`):

- `cards.json` / `cards.sqlite`: カード DB (正は cards.json)
- `card_effects.json`: 効果オーバーレイ (4,518 全カード、 _unimplemented = 0)
- `audit_acknowledged.json`: audit script で intrinsic 除外する issue リスト (R59 追加)
- `matchup_matrix.json`: N×N 勝率行列 (R60 で 16×16 = 256 セルに更新)
- `overlay_audit.{md,json}`: audit 結果 (sev≥5 = 0、 sev=3-4 = 0)
- `overlay_when_missing.json`: cardqa sweep 結果 (X5、 missing 0)
- `rules/*.pdf`: 公式ルール一次情報
- `faq/*.json`: 公式 FAQ + cardqa (2,500+ 件)
- `banlist/master.json`: 禁止/制限カード

## 開発コマンド

### 初回セットアップ

```bash
# Python (要 python3.12-venv)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Next.js (web/ 直下)
cd web && npm install
```

### 日常開発

```bash
# === 公式データ更新 (月次推奨) ===
.venv/bin/python scraper/scraper.py --all          # カードDB更新 (--with-images で全画像)
.venv/bin/python scripts/check_official_updates.py # PDF/FAQ/cardqa/banlist 全方位チェック
.venv/bin/python scripts/check_rules_update.py     # PDF だけのチェック (個別)
.venv/bin/python scripts/scrape_official_faq.py    # FAQ + cardqa 全件再取得
.venv/bin/python scripts/scrape_official_banlist.py # 禁止/制限カード再取得
.venv/bin/python scripts/refresh_all.py            # 上記 + メタデッキ + matrix を一括

# === メタデッキ更新 (cardrush.media 産) ===
.venv/bin/python scripts/scrape_cardrush_decks.py  # 大会優勝デッキを `decks/cardrush_*.json` で取得
.venv/bin/python scripts/scrape_cardrush_decks.py --scores 優勝 準優勝 --since 2026-01-01
.venv/bin/python scripts/select_cardrush_representatives.py # アーキタイプ毎に1つ代表選出

# === overlay 拡張・監査 ===
.venv/bin/python scripts/suggest_overlay_from_cards.py # cards.json から overlay 候補を自動抽出
                                                       # → db/card_effects.suggestions.json (手動マージ)
.venv/bin/python scripts/merge_overlay_suggestions.py  # suggestions の選択マージ
.venv/bin/python scripts/audit_overlay_vs_faq.py       # overlay vs FAQ 突合監査
                                                       # → db/overlay_audit.md (上位80件) + .json (全件)
                                                       # acknowledged.json で intrinsic 除外、 現状 sev≥3 = 0
.venv/bin/python scripts/verify_overlay_vs_cardqa.py   # cardqa 効果マーカー vs overlay when 整合性
                                                       # → db/overlay_when_missing.json (現状 missing 0)
.venv/bin/python scripts/audit_engine_strictness.py    # engine 厳密化 audit (10 項目、 現状 10/10 pass)
.venv/bin/python scripts/smoke_test_card_effects.py    # 全カード効果スモークテスト
                                                       # 各 effect を最小ステートで発火 → 変化検出

# === 画像 ===
.venv/bin/python scripts/cache_deck_images.py      # decks/ で使う画像をローカルキャッシュ
.venv/bin/python scripts/cache_all_images.py       # 全カード画像 (約 1〜2GB / 30〜60min)

# === 対戦 / matrix ===
.venv/bin/pytest                                   # 全テスト実行 (tests/ 以下)
.venv/bin/python examples/demo_matchup.py          # 50戦マッチアップ デモ
.venv/bin/python examples/demo_smoke.py            # 単一試合のスモークテスト
.venv/bin/python examples/demo_with_effects.py     # 効果オーバーレイ込みの対戦デモ
.venv/bin/python scripts/compute_matchup_matrix.py --n-games 20 --seed 42  # 勝率行列再計算
                                                                            # 16 デッキ × 256 セル × 20 戦 = 5120 試合 (約 60 分)
.venv/bin/python scripts/report_bad_moves.py --deck-a <a> --deck-b <b> --n-games 20 --threshold -3000
                                                                            # AI 行動品質分析 (R63、 board_eval delta が大きく負の手を抽出)

# === サーバ ===
.venv/bin/uvicorn api.main:app --reload --port 8000   # API起動
cd web && npm run dev                                  # Next.js dev (http://localhost:3000)
cd web && npm run build && npm start
cd web && npx tsc --noEmit                             # 型チェック
```

> 注: WSL のホスト経由マウントだと `*.py` が `*.PY` (大文字) として見えることがある。
> glob (`*.py`) で拾えない場合は明示パスで指定するか、`pyproject.toml` 経由で
> pytest に検出させる (現状こちらを使用)。

## Claude Code を使う時のヒント

- 機能追加は1機能=1ブランチ、PR を Claude Code に頼んで作らせると速い
- 「Phase 5: デッキビルダー実装」など phase 単位で依頼
- API のレスポンス型は `api/main.py` (Pydantic) と `web/src/lib/types.ts` の両方で定義
  → 不整合が起きたら `api/main.py` 側を真とする
- 変更前に `git status` の確認を Claude Code に依頼するクセをつける
- 効果を追加したら `pytest tests/` + デモ対戦で勝率の変動を確認

## 既知の落とし穴(過去にハマった)

- 公式サイトはGET `?series=550115` で各弾取得可能。HTMLレンダリング型なので JS 不要
- 画像URLは `https://www.onepiece-cardgame.com/images/cardlist/card/<card_id>.png` パターン。
  パラレル(`_p1`, `_p2`)も同パターンで取得可能
- マウントFS(WindowsのCowork経由など)では SQLite 直書きが失敗する場合あり。
  Python から書く場合は `/tmp` に作って bytes コピーするとよい
- `harness.run_matchup` に `effects_overlay` を渡し忘れていたバグあり (修正済み)。
  追加時は必ず `setup_game(..., effects_overlay=...)` までつないであるか確認
- `create-next-app` は内部で `git init` する。リポジトリルートが既に git 管理なら
  `web/.git` を削除してネスト解消する
- WSL の 8.3 短名: `*.PY` の大文字化、glob で拾えない場合がある。`pyproject.toml` の
  `[tool.pytest.ini_options]` で testpaths を指定して回避

### cardrush.media (メタデッキの参考ソース)

- Next.js SSR ページなので `<script id="__NEXT_DATA__">` を正規表現抽出 → `json.loads`
  すれば全データ (recipes 含む) が取れる。BS4 / playwright 不要
- card_number フィールドが既存 `cards.json` の `card_id` と完全一致 (OP14-020 / ST24-002 / EB01-015 / PRB02-006 / P-114 すべて検証済)
- 一覧ページ pageProps.lastPage でページ数取得 / 30件/page
- 同じアーキタイプで複数優勝レシピがある場合は `select_cardrush_representatives.py` で
  最新優勝を1つだけ採用 (それ以外は `decks/_archive/cardrush_raw/` へ)
- 取得したレシピが現禁止リスト違反 (例: OP07-115 + EB04-058 ペア) を含む場合、
  `DeckList.validate()` で検出される。該当レシピは `_archive/` へ追放、
  代替が無いアーキタイプは matrix から除外する
