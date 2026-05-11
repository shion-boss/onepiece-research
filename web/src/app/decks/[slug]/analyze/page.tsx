import Link from "next/link";
import { fetchDeckAnalysis, fetchDeckStrategy } from "@/lib/api";
import { ArticleGenerator } from "@/components/ArticleGenerator";
import { VsArticleGenerator } from "@/components/VsArticleGenerator";
import { DeckAnalyzeCharts } from "@/components/DeckAnalyzeCharts";
import { DeckMatchupRow } from "@/components/DeckMatchupRow";
import { DeckStrategyPanel } from "@/components/DeckStrategyPanel";
import type { DeckAnalysis, DeckStrategy } from "@/lib/types";

export default async function DeckAnalyzePage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;

  let data: DeckAnalysis | null = null;
  let strategy: DeckStrategy | null = null;
  let error: string | null = null;
  try {
    [data, strategy] = await Promise.all([
      fetchDeckAnalysis(slug),
      fetchDeckStrategy(slug).catch(() => null),
    ]);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 p-6">
      <header className="space-y-1">
        <div className="flex items-center gap-2">
          <Link
            href={`/decks/${encodeURIComponent(slug)}`}
            className="text-sm text-zinc-500 hover:underline dark:text-zinc-400"
          >
            ← デッキ詳細
          </Link>
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">
          {data?.name ?? slug} — 分析
        </h1>
        {data && (
          <div className="text-sm text-zinc-600 dark:text-zinc-400">
            リーダー: {data.leader_name} ({data.leader}) · main {data.main_count}{" "}
            枚
          </div>
        )}
      </header>

      {error ? (
        <div className="rounded border border-red-300 bg-red-50 p-4 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          <div className="font-medium">読み込み失敗</div>
          <div className="mt-1 font-mono">{error}</div>
        </div>
      ) : data ? (
        <>
          {strategy && <DeckStrategyPanel strategy={strategy} />}
          <DeckAnalyzeCharts data={data} />
          <section className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
            <h2 className="mb-3 text-lg font-semibold">対戦相手別 勝率</h2>
            <DeckMatchupRow slug={slug} />
          </section>
          <VsArticleGenerator slug={slug} />
          <ArticleGenerator slug={slug} />
        </>
      ) : null}
    </main>
  );
}
