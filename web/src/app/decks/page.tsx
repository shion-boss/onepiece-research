import Link from "next/link";
import { fetchDecks } from "@/lib/api";
import { DeckSummaryTile } from "@/components/DeckSummaryTile";
import { PageHeader } from "@/components/ui/PageHeader";
import { PageShell } from "@/components/ui/PageShell";

export default async function DecksPage() {
  let decks: Awaited<ReturnType<typeof fetchDecks>> = [];
  let error: string | null = null;
  try {
    decks = await fetchDecks();
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <PageShell>
      <PageHeader
        title="デッキ"
        description={`メタデッキ DB (${decks.length} 個)。 クリックで 詳細・ AI vs AI 対戦`}
        actions={
          <Link
            href="/decks/new"
            className="rounded-md bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
          >
            + 新規デッキ
          </Link>
        }
      />

      {error ? (
        <div className="rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          <div className="font-medium">API への 接続に 失敗しました</div>
          <div className="mt-1 font-mono text-xs">{error}</div>
        </div>
      ) : decks.length === 0 ? (
        <div className="rounded-lg border border-zinc-200 p-6 text-sm text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
          まだ デッキが 登録されていません。
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {decks.map((d) => (
            <DeckSummaryTile key={d.slug} deck={d} />
          ))}
        </div>
      )}
    </PageShell>
  );
}
