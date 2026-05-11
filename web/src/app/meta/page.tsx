import Link from "next/link";
import { fetchMetaMatrix } from "@/lib/api";
import { MatchupHeatmap } from "@/components/MatchupHeatmap";

export default async function MetaPage() {
  let data: Awaited<ReturnType<typeof fetchMetaMatrix>> | null = null;
  let error: string | null = null;
  try {
    data = await fetchMetaMatrix();
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <main className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-4 p-6">
      <header className="space-y-1">
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">メタ分析</h1>
          <span className="rounded bg-blue-100 px-2 py-0.5 text-xs font-bold text-blue-700 dark:bg-blue-900 dark:text-blue-300">
            STD
          </span>
        </div>
        {data && (
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            {data.decks.length} デッキ × {data.decks.length} の勝率行列 (スタンダードレギュレーション)。各セル{" "}
            {data.n_games} 戦 (seed={data.seed}) ・最終計算{" "}
            {data.computed_at.replace("T", " ").replace("Z", "")} ・更新は{" "}
            <code className="rounded bg-zinc-100 px-1 dark:bg-zinc-800">
              scripts/compute_matchup_matrix.py
            </code>
          </p>
        )}
      </header>

      {error ? (
        <div className="rounded border border-red-300 bg-red-50 p-4 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          <div className="font-medium">読み込み失敗</div>
          <div className="mt-1 font-mono">{error}</div>
        </div>
      ) : data ? (
        <MatchupHeatmap data={data} />
      ) : null}
    </main>
  );
}
