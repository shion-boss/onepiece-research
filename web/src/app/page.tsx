import Link from "next/link";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-8 p-12">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">
          One Piece Research
        </h1>
        <p className="text-zinc-600 dark:text-zinc-400">
          ワンピースカードゲームのデッキ構築・分析・対戦シミュレーションツール。
        </p>
      </header>

      <nav className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Link
          href="/cards"
          className="rounded-lg border border-zinc-200 p-4 transition hover:border-zinc-400 dark:border-zinc-800 dark:hover:border-zinc-500"
        >
          <div className="text-lg font-medium">/cards</div>
          <div className="text-sm text-zinc-600 dark:text-zinc-400">
            カードブラウザ(検索 / フィルタ)
          </div>
        </Link>
        <Link
          href="/decks"
          className="rounded-lg border border-zinc-200 p-4 transition hover:border-zinc-400 dark:border-zinc-800 dark:hover:border-zinc-500"
        >
          <div className="text-lg font-medium">/decks</div>
          <div className="text-sm text-zinc-600 dark:text-zinc-400">
            デッキ管理 + 対戦シミュレーション
          </div>
        </Link>
        <Link
          href="/meta"
          className="rounded-lg border border-zinc-200 p-4 transition hover:border-zinc-400 dark:border-zinc-800 dark:hover:border-zinc-500"
        >
          <div className="text-lg font-medium">/meta</div>
          <div className="text-sm text-zinc-600 dark:text-zinc-400">
            メタデッキ間の勝率行列 (heatmap)
          </div>
        </Link>
        <Link
          href="/faq"
          className="rounded-lg border border-zinc-200 p-4 transition hover:border-zinc-400 dark:border-zinc-800 dark:hover:border-zinc-500"
        >
          <div className="text-lg font-medium">/faq</div>
          <div className="text-sm text-zinc-600 dark:text-zinc-400">
            公式 Q&A の横断検索
          </div>
        </Link>
      </nav>
    </main>
  );
}
