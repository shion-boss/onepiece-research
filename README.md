# ワンピースカードゲーム デッキ研究ツール

「**自分の使いたいカードを最大限活かして、現環境のトップティアデッキに勝てるか**」を
研究するためのデッキ構築・分析・対戦シミュレーションツール。

> Bandai 公式とは無関係の個人研究プロジェクト。カード画像・テキスト・公式PDFは Bandai
> 著作物のためリポジトリには **含まれていません**。下記セットアップで自動取得されます。

## アーキテクチャ

**Next.js 16 (TypeScript) フロントエンド + Python 3.10+ (FastAPI) バックエンド**

```
onepiece_research/
├── CLAUDE.md           # プロジェクト全体の方針・規約 (Claude Code が自動読込)
├── requirements.txt    # Python 依存
├── scraper/            # 公式サイトから全弾スクレイプ
├── engine/             # ルールエンジン + 効果DSL + AI + 対戦ハーネス
│   ├── core.py / deck.py / deckbuilder.py
│   ├── effects.py             # 効果DSL (プリミティブ 180+、 トリガー 20+)
│   ├── game.py                # ターン進行 / 攻防 / 合法手生成
│   ├── eval.py                # 9 指標盤面評価関数 (LookaheadAI/MCTSAI/UI 共通)
│   ├── analyzer.py            # 試合後分析 (ターニングポイント抽出)
│   ├── loss_classifier.py     # 敗因タグ分類 (AI 改善ヒント抽出)
│   ├── replay_recorder.py     # 試合 replay 保存 (SQLite + gzip、 board_eval 含む)
│   ├── deck_analyzer.py       # 静的デッキ分析 (戦略 / マリガン / キーカード / AI ヒント)
│   ├── ai.py                  # Random / Greedy / EvalGreedy / Lookahead / MCTS
│   ├── ai_params.py           # チューニング可能な AI パラメータ (重み等)
│   ├── hand_estimator.py      # 隠匿情報モデル (相手手札の確率推定)
│   ├── referee.py             # ルール違反監視 (RuleReferee)
│   └── harness.py             # AI vs AI 対戦実行 (action_evals 記録対応)
├── api/main.py         # FastAPI で engine + DB + 試合分析 をラップ
├── db/
│   ├── cards.json (4,518枚) — リポジトリに同梱 (~3.7MB)
│   ├── card_effects.json     # 効果オーバーレイ (4,518 全登録、 _unimplemented = 0)
│   ├── audit_acknowledged.json # audit script で intrinsic 除外する issue リスト
│   ├── matchup_matrix.json   # 事前計算 16×16 勝率行列
│   ├── banlist/master.json   # 禁止リスト
│   ├── rules/   ※ 公式PDF (gitignore、scraper で取得)
│   └── faq/     ※ 公式Q&A (gitignore、scraper で取得)
├── decks/              # cardrush.media 大会上位由来 (cardrush_*.json, 15デッキ + テストデッキ)
│   └── *.analysis.json    # 各デッキの静的分析 (戦略/マリガン/AI ヒント)
├── examples/           # スモークテスト・デモスクリプト (demo_smoke.py 等)
├── scripts/            # scrape / cache / matrix / overlay / audit / 行動分析 補助
├── web/                # Next.js (App Router, Tailwind CSS v4, Zustand)
│   └── public/cards/   ※ 全画像 (878MB、gitignore)
└── tests/              # pytest (270 passed + 200 FAQ placeholder skip)
```

## セットアップ手順

### 1. Python 環境

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2. カード画像のダウンロード (任意、初回 30〜60min)

`db/cards.json` 自体はリポジトリに同梱されているのでカードDBは即座に使えます。
画像が必要な場合 (`/cards` ページや `<CardImage>` 表示) は:

```bash
# デッキで使うカードだけ先にローカルキャッシュ (~7MB)
.venv/bin/python scripts/cache_deck_images.py

# 全 4,518 枚 (~880MB / 30〜60min)
.venv/bin/python scripts/cache_all_images.py
```

### 3. 公式 PDF / FAQ / 禁止リスト (任意)

`.claude/skills/onepiece-tcg-rules/SKILL.md` の参照や、ルール変更検知に必要。

```bash
.venv/bin/python scripts/check_rules_update.py        # PDF だけ初回取得
.venv/bin/python scripts/scrape_official_faq.py       # FAQ + cardqa
.venv/bin/python scripts/scrape_official_banlist.py   # 禁止リスト (cards.jsonと共に同梱済)
```

### 4. メタデッキ更新 (任意)

```bash
.venv/bin/python scripts/scrape_cardrush_decks.py --scores 優勝 準優勝 --since 2026-01-01
.venv/bin/python scripts/select_cardrush_representatives.py
```

### 5. テスト + 起動

```bash
# pytest
.venv/bin/pytest                                        # 270 passed (+200 FAQ placeholder skip)

# 対戦シミュレーション デモ
.venv/bin/python demo_smoke.py
.venv/bin/python demo_matchup.py

# 勝率行列 (~30s)
.venv/bin/python scripts/compute_matchup_matrix.py --n-games 20 --seed 42

# API 起動
.venv/bin/uvicorn api.main:app --reload --port 8000
# → http://localhost:8000/api/health

# Next.js
cd web && npm install
cd web && npm run dev
# → http://localhost:3000
```

## 進捗

| Phase | 状態 | 概要 |
|---|---|---|
| 1. カードDB | ✅ | 全 54 弾 4,518 枚 |
| 2. ルールエンジン + DSL | ✅ | **プリミティブ 180+, トリガー 20+** |
| 2.5 効果オーバーレイ | ✅ | **全 4,518 カード公式準拠** (`_unimplemented` = 0 🎯) |
| 3. AI / 対戦ハーネス | ✅ | Greedy / Random / EvalGreedy / Lookahead / MCTS + 行動品質評価 (R63) |
| 4. メタデッキ DB | ✅ | cardrush.media 産 **15 デッキ** + 月次更新 |
| 5. デッキビルダー | ✅ | UI + API (`/decks/new`, `POST /api/decks`) |
| 6. Next.js UI | ✅ | `/cards` `/decks` `/decks/[slug]` `/decks/new` `/decks/[slug]/analyze` `/meta` `/faq` |
| Audit | ✅ | overlay sev≥3 = 0、 engine 厳密化 10/10 pass、 cardqa 整合性 0 漏れ |

## 月次更新フロー

```bash
# 公式データ + cardrush + matrix を一括
.venv/bin/python scripts/refresh_all.py
.venv/bin/python scripts/refresh_all.py --cardrush-since 2026-01-01
.venv/bin/python scripts/refresh_all.py --skip-meta-scrape --matrix-n-games 50
```

## ドキュメント

- **`CLAUDE.md`** — プロジェクト方針・規約・既知の落とし穴 (Claude Code 用)
- **`.claude/skills/onepiece-tcg-rules/SKILL.md`** — 公式ルール + Q&A + 禁止リスト リファレンス

## ライセンス / 出典

- ソースコード: MIT (個人で改変・利用可能)
- カード画像・公式テキスト・公式PDF: Bandai 著作物。本リポジトリには同梱せず、
  各自 scraper を実行してローカル取得する形
- メタデッキデータ: [cardrush.media](https://cardrush.media/onepiece/decks/list) の
  公開大会結果より取得 (リーダー名 + カード番号 + 採用枚数のみ。テキスト/画像は引用なし)
- 本ツールは Bandai 公式とは無関係の個人研究プロジェクト
