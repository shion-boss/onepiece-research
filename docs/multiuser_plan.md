# マルチユーザー化 計画 (= カード研究所のサービス化)

> 2026-06-15 開始。 ohtsuki「環境デッキとユーザー作成デッキは別で管理したい / ユーザー機能をつける」
> → **本格マルチユーザー化** を選択。 これは複数セッションの基盤プロジェクト。 本ドキュメントが
> 単一の真実 (= 設計・スキーマ・フェーズ・現状) を保持する。 再開時はまずこれを読む。

## ゴール
単一テナントの研究ツール → **マルチテナントの「カード研究所」サービス**。 各ユーザーが
自分のデッキを持ち、 コンボ提案・自動生成・AI 対戦・分析を使える。 環境(メタ)デッキは
全ユーザー共通の正準参照として分離管理する。

## ターゲット構成
```
[Web / 認証]  Next.js + Auth          ── ログイン / マイデッキ / UI
     │
[ユーザーデータ]  DB (Postgres)         ── users / 各人の decks (owner, visibility)
     │
[メタデッキ]  リポジトリ JSON (read-only) ── 正準参照: matchup matrix / deck-gen ターゲット / AI tuning
     │
[エンジン]  FastAPI (計算サービス)        ── sim / analyze / deck-gen。 重い sim は job queue で分離
```

### 一番の落とし穴 (= 設計上の要)
今の FastAPI エンジンは **sim が重い** (deck-gen で数十秒)。 **serverless に丸ごとは載らない**
(timeout)。 → web/認証/CRUD は軽いので serverless 可、 **重い計算は専用ホスト or ジョブキュー**
に分離する。 多人数で sim が詰まらないように。 user deck は engine に **recipe (inline) として渡す**
(= engine は user deck を保存しない、 受け取って計算するだけ)。 `/api/match` 等は既に
`deck_a` (inline) / `deck_a_id` (slug) の両対応なので、 この方向は実現しやすい。

## データモデル: メタ ↔ ユーザー の分離
| | メタデッキ | ユーザーデッキ |
|---|---|---|
| 性質 | 正準・キュレーション (月次更新) | 個人・可変・大量 |
| 用途 | matrix / deck-gen ターゲット / AI = **エンジンの参照基盤** | その人の作業データ |
| 置き場 (現/P1) | `decks/*.json` (リポジトリ) | `decks/*.json` に混在 (= `source:"user"` タグのみ) |
| 置き場 (目標/P2) | `decks/*.json` (据え置き、 engine が読む) | **DB (per-user)**、 engine へは recipe で渡す |
| 識別 | **`db/meta_decks.json` 登録制 (P1 で導入)** | 登録外 = ユーザー |

⚠ 旧来は `cardrush_*` / `tcgportal_*` の **接頭辞ハック** で判別 (= 各所に散在・不整合。
例: DELETE は cardrush_ だけ保護、 tcgportal_ メタは無防備)。 → **P1 で `db/meta_decks.json`
登録制に一本化**。

## DB スキーマ (P2、 Postgres 想定)
```sql
users (
  id            uuid primary key,
  auth_provider_id text unique,        -- Clerk/Auth.js の sub
  email         text,
  created_at    timestamptz default now()
)
decks (
  id            uuid primary key,
  owner_id      uuid references users(id),
  slug          text,                  -- owner 内で一意
  name          text,
  leader        text,                  -- card_id
  main          jsonb,                 -- [{card_id, count}]
  regulation    text default 'standard',
  visibility    text default 'private',-- private | unlisted | public
  created_at    timestamptz default now(),
  updated_at    timestamptz default now(),
  unique(owner_id, slug)
)
```
メタデッキは DB に入れない (= リポジトリ JSON のまま、 全ユーザー共通)。

## API 設計 (user-scoped)
- `GET /api/decks` → メタ (全員共通) + **ログインユーザーの** デッキ。 各エントリに `kind: meta|user`。
- `POST/PUT/DELETE /api/decks` → **自分のデッキのみ** 操作可 (auth 必須)。 メタは read-only。
- engine 計算系 (`/api/match`, `/api/decks/{slug}/analyze`, `/api/decks/generate`) → user deck は
  recipe で渡す (= DB から取って engine に inline)。 メタは slug 参照のまま。
- 認可: owner_id == 現在のユーザー の行のみ。

## フェーズ
- **P1 (進行中、 stack 非依存)**: メタ/ユーザーを **`db/meta_decks.json` 登録制で明示分離**。
  接頭辞ハックを全廃 (delete 保護 / deck-gen meta pool / matrix / matchup_model)。 `DeckSummary`
  に `kind`。 user save は `kind:"user"` タグ。 = **混在事故の根絶 + P2 の前提整備**。
- **P2**: 認証導入 (provider 選定) + user deck を FS → **DB 移行** + 認可 (他人のは見えない/消せない)。
- **P3**: フロント (login/signup、 マイデッキ↔メタ の表示分離、 auth state)。
- **P4**: 重いエンジン呼び出しの **job queue 化** (多人数で sim が詰まらない)。

## 確定待ちの決定 (load-bearing、 P2 着手前に確定)
1. デプロイ: Web=Vercel 等 / **engine=専用ホスト + job queue** (分離)
2. 認証: **Clerk** (Next.js × マルチテナント最速) or Auth.js — 推奨 Clerk
3. ユーザー DB: **Neon Postgres** 等 — 推奨 Neon
→ デフォルト推奨 = **Vercel + Clerk + Neon**。 ohtsuki 確認待ち。

## 現状
- P1 着手 (本ドキュメント + `db/meta_decks.json` + 接頭辞ハック撤去)。 stack 3 決定は P2 で確定。
