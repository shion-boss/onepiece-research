import Link from "next/link";
import { fetchDecks } from "@/lib/api";
import { DeckSummaryTile } from "@/components/DeckSummaryTile";
import { PageHeader } from "@/components/ui/PageHeader";
import { PageShell } from "@/components/ui/PageShell";
import { Button } from "@/components/ui/Button";

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
          <Link href="/decks/new">
            <Button variant="primary">+ 新規デッキ</Button>
          </Link>
        }
      />

      {error ? (
        <div className="rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          <div className="font-medium">API への 接続に 失敗しました</div>
          <div className="mt-1 font-mono text-xs">{error}</div>
        </div>
      ) : decks.length === 0 ? (
        <div className="surface-panel p-6 text-sm text-zinc-500 dark:text-zinc-400">
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
