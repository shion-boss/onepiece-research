<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

## UI 規約

- **UI に絵文字を使わない**: ボタン / ラベル / ヘッダー / バッジ / 状態表示 等、 ユーザー が 目にする 全 UI 要素 で 絵文字 禁止。 アイコン が 必要 なら SVG (= lucide-react 等) を 使う。
- 全 page の outer shell は `<PageShell>` (= max-w-6xl 固定)、 header は `<PageHeader>` で 統一。 横幅 を ナビ毎 に 変えない (= 視覚的安定 優先)。
- color palette: zinc + 必要 に応じて blue/red/amber/green。 dark mode 必ず 対応。
