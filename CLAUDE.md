# プロジェクト: ワンピースカードゲーム デッキ研究ツール

> このファイルは Claude Code が自動的に読み込み、プロジェクトの文脈として利用する。
> プロジェクトの方針・構造・規約をここに集約する。詳細は各サブディレクトリの `CLAUDE.md` を参照。

## このツールが目指すもの

「**自分の使いたいカードを最大限活かして、現環境のトップティアデッキに勝てるか**」を
研究するためのデッキ構築・分析・対戦シミュレーションツール。

利用シーン:
- 推しキャラを軸にしたデッキを組み、メタデッキ群と AI 対戦させて勝率を見る
- デッキの色配分・コストカーブ・特徴シナジーを可視化する
- 環境上位デッキの傾向を分析する

## アーキテクチャ

**Next.js (TypeScript) フロントエンド + Python (FastAPI) バックエンド** の構成。

```
onepiece_research/
├── scraper/        # 公式サイトから全弾スクレイプ (Python)
├── engine/         # ルールエンジン + AI + 対戦ハーネス (Python)
├── api/            # FastAPI で engine をラップする HTTP API (Python)
├── db/             # cards.json / cards.sqlite / card_effects.json (473 overlay)
│                   #   + rules/ (公式PDF) / faq/ (公式Q&A) / banlist/ (禁止リスト)
│                   #   + matchup_matrix.json (事前計算 N×N 勝率)
├── decks/          # メタデッキ JSON (cardrush_*.json — cardrush.media 大会上位由来)
│   └── _archive/   # 旧 meta_*.json + 非代表 cardrush_raw/ の退避先
├── images/         # 全カード画像 (空、scraper --with-images で取得)
├── scripts/        # 補助スクリプト (scrape / cache / matrix / overlay 補助)
├── web/            # Next.js フロントエンド (TypeScript, App Router)
│   └── public/cards/   # 全 4,518 枚キャッシュ済 (878MB)
├── web_skeleton/   # Next.js セットアップ手順 (キックオフ用ハンドオフ、現役性低)
├── tests/          # pytest テスト (test_effects.py / test_deck.py、21 passed)
├── .venv/          # Python 仮想環境 (gitignore 推奨)
└── DEMO_*.PY       # ルート直下のデモスクリプト (matchup / smoke / with-effects)
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
  - 主要トリガー実装済: 登場/アタック/起動メイン/KO時/ターン終了時/ブロック時/相手アタック時/トリガー/カウンターイベント/メインイベント
  - DSL プリミティブ20+ 種 (draw / ko / power_pump / search / play_from_trash / give_keyword 他)
- [x] **Phase 2.5 完了**: カード効果オーバーレイ **全 4,518 カード登録 (100%)** (`db/card_effects.json`)。
  - 効果あり: 3,745 件 (82.9%) — character 78.6% / event 100% / leader 100% / stage 79.1%
  - 効果なし (バニラ/ブロッカーのみ/パラレル空): 773 件 (空配列でマーク済)
  - メタデッキ 15 リーダーは公式テキスト準拠で手書き、その他は自動生成 (近似 + fallback)
  - DSL条件: leader_feature/color, self/opp life/hand 各種, opp_turn/self_turn,
    self_rested, self_trash_count_ge, self_don_ge 等
  - DSL プリミティブ: draw / ko / power_pump (動的計算 amount_per 含む) /
    rest / return_to_hand / search / play_from_trash / give_keyword (rush/blocker/
    ブロック不可/ダブルアタック/アクティブアタック可) / give_rush / attach_don /
    don_minus_opp / mill / put_top_to_life / life_to_hand / add_don / untap /
    trash_self_hand_random / **set_cannot_attack** / **stay_rested_next_refresh** /
    **reduce_play_cost** / **prevent_ko** (turn) / **set_ko_immune** (static) /
    **set_base_power** (元々のパワー上書き) / **set_base_cost** (元々のコスト上書き / delta) /
    **set_attack_taunt** (キャラ taunt) / **replace_ko** (KO代替の置換効果)
  - 残: ハンド領域からの選択登場、相手手札からの捨てなど一部
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
  - MCTSAI: UCT-based、`n_simulations=30`、ロールアウト+ヒューリスティック評価。opt-in (低速)
  - **RuleReferee**: AI vs AI 対戦中のルール違反監視。全 630 試合違反ゼロ確認済
- [x] **Phase 4 完了**: メタデッキ DB **15 デッキ** (`decks/cardrush_*.json`)。
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

### 現在のメタ Tier (matchup matrix, n=20, 2026-05 時点)

DON+1000 ルール厳密化 + AI 攻防判断強化 + **15リーダー効果を公式テキスト忠実実装** (起動メインコスト機構 / DON自動付与 / replace_ko / summon_from_deck / play_event_from_hand 等)
+ **公式ルール準拠の追加修正** (マリガン / battle_buff / on_turn_start / トリガー任意性 / 速攻:キャラ / 「場合」前文不実行→後文不実行 / 「元々のパワー」修正):

| Tier | デッキ |
|---|---|
| **S (85%+)** | 赤紫ロジャー (90%) |
| **A (75%+)** | 空島ルフィ (79%) |
| **B (50-74%)** | 青黄ナミ (75%) / 赤青エース (72%) / 赤黄ボニー (71%) / 紫ドフラ (71%) / 緑ボニー (67%) / 紫エネル (64%) |
| **C (25-49%)** | 緑ミホーク (38%) / 緑黄しらほし (32%) |
| **D (<25%)** | 黒イム (25%) / 黒クロコ (23%) / 青紫サンジ (20%) / 赤青ルーシー (17%) / 緑紫ルフィ (3%) |

注: 赤紫ロジャー の急伸 (+6%) と 紫ドフラ の急伸 (+28%) は AI のアーキタイプ別ヒューリスティック (ランプ → DON 加速優先 / 紫ドフラ判定 → 防御特化) が効いた結果。 一方で 赤青ルーシー (60→17%) は分析でコントロール判定されたが本来は攻撃寄りで誤分類。 アーキタイプ判定精度の改善が将来課題。

> 注: 緑紫ルフィ (1%) / 青紫サンジ (6%) の極端な低勝率は、起動メインの「ドン-N」コストを忠実に実装した結果、
> AI ヒューリスティックではコスト負担に見合うリターンを引き出せていないため。本来は手札のシナジーカードを
> 引き出すコンボ前提の効果なので、デッキ自体の研究と AI 改善の余地が残る。

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
- 効果オーバーレイ(`db/card_effects.json`)は手書き拡張前提
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

未実装 (計画):

| エンドポイント | メソッド | 用途 |
|---|---|---|
| (現在 計画なし) | - | PUT/DELETE は実装済 |

レスポンス型は `api/main.py` の Pydantic モデルと `web/src/lib/types.ts` の両方で定義。
**不整合が起きたら `api/main.py` 側を真とする**。

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

# === overlay 拡張 ===
.venv/bin/python scripts/suggest_overlay_from_cards.py # cards.json から overlay 候補を自動抽出
                                                       # → db/card_effects.suggestions.json (手動マージ)
.venv/bin/python scripts/merge_overlay_suggestions.py  # suggestions の選択マージ

# === 画像 ===
.venv/bin/python scripts/cache_deck_images.py      # decks/ で使う画像をローカルキャッシュ
.venv/bin/python scripts/cache_all_images.py       # 全カード画像 (約 1〜2GB / 30〜60min)

# === 対戦 / matrix ===
.venv/bin/pytest                                   # 全テスト実行 (tests/ 以下)
.venv/bin/python DEMO_M~1.PY                       # 50戦マッチアップ デモ
.venv/bin/python scripts/compute_matchup_matrix.py --n-games 20 --seed 42  # 勝率行列再計算

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
