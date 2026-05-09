# web/ — One Piece Research フロントエンド

Next.js 16 (App Router, TypeScript, Tailwind CSS v4) で構築された
ワンピースカードゲーム デッキ研究ツールの UI 層。

## 開発フロー

別ターミナルで以下の 2 プロセスを起動する。

```bash
# ターミナル A: FastAPI バックエンド
cd /home/ohtsuki/projects/onepiece_research
uvicorn api.main:app --reload --port 8000

# ターミナル B: Next.js dev server
cd /home/ohtsuki/projects/onepiece_research/web
npm run dev    # http://localhost:3000
```

疎通確認:

```bash
curl -s http://localhost:8000/api/health
# => {"ok": true, "cards": 4518}
```

ブラウザで `http://localhost:3000/` を開き、`/cards` リンクから
`http://localhost:3000/cards` に遷移すると、API から取得したカード件数が表示される。

## ディレクトリ構成

```
web/src/
├── app/
│   ├── layout.tsx           # 全体レイアウト
│   ├── page.tsx             # トップ(ナビ)
│   ├── cards/page.tsx       # カードブラウザ(疎通確認の最小実装)
│   └── decks/page.tsx       # デッキ管理(プレースホルダ)
├── components/
│   ├── CardTile.tsx
│   ├── CardDetailModal.tsx
│   ├── CardFilterBar.tsx
│   └── ColorChip.tsx
└── lib/
    ├── api.ts               # FastAPI ラッパー (fetchCards / fetchCard)
    ├── images.ts            # cardImageUrl(cardId)
    └── types.ts             # Card / CardFilters (api/main.py の CardOut と一致)
```

## 環境変数

`.env.local` に以下を設定済み:

```
NEXT_PUBLIC_API_BASE=http://localhost:8000
```

## 次のステップ

`web_skeleton/STARTER_PROMPTS.md` の「プロンプト 1: カードブラウザを作る」を起点に、
`/cards` を実装していく。
