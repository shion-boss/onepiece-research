export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-8 p-12">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">
          One Piece Research
        </h1>
        <p className="text-zinc-600 dark:text-zinc-400">
          ワンピースカードゲームのデッキ構築・分析・対戦シミュレーションツール。
        </p>
      </header>

      <div className="space-y-2 text-sm text-zinc-700 dark:text-zinc-300">
        <p>左のサイドバーから各機能へ移動できます:</p>
        <ul className="ml-4 list-disc space-y-1.5 text-zinc-600 dark:text-zinc-400">
          <li>
            <strong className="text-zinc-800 dark:text-zinc-200">カード</strong>{" "}
            — 全 4,518 枚の検索・フィルタ
          </li>
          <li>
            <strong className="text-zinc-800 dark:text-zinc-200">デッキ</strong>{" "}
            — メタデッキの管理・対戦シミュレーション
          </li>
          <li>
            <strong className="text-zinc-800 dark:text-zinc-200">メタ分析</strong>{" "}
            — デッキ間の勝率行列 (N×N heatmap)
          </li>
          <li>
            <strong className="text-zinc-800 dark:text-zinc-200">Q&amp;A</strong>{" "}
            — 公式ルールQ&amp;A の横断検索 (2,500+ 件)
          </li>
        </ul>
      </div>
    </main>
  );
}
