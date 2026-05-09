import Link from "next/link";
import { fetchDecks } from "@/lib/api";
import { DeckSummaryTile } from "@/components/DeckSummaryTile";

export default async function DecksPage() {
  let decks: Awaited<ReturnType<typeof fetchDecks>> = [];
  let error: string | null = null;
  try {
    decks = await fetchDecks();
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-4 p-6">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="space-y-1">
          <Link
            href="/"
            className="text-sm text-zinc-500 hover:underline dark:text-zinc-400"
          >
            ← back
          </Link>
          <h1 className="text-2xl font-semibold tracking-tight">/decks</h1>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            メタデッキ DB ({decks.length} 個)。クリックで詳細・対戦シミュレーション。
          </p>
        </div>
        <Link
          href="/decks/new"
          className="rounded bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
        >
          + 新規デッキ
        </Link>
      </header>

      {error ? (
        <div className="rounded border border-red-300 bg-red-50 p-4 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          <div className="font-medium">API への接続に失敗しました</div>
          <div className="mt-1 font-mono">{error}</div>
        </div>
      ) : decks.length === 0 ? (
        <div className="rounded border border-zinc-200 p-6 text-sm dark:border-zinc-800">
          まだデッキが登録されていません。
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {decks.map((d) => (
            <DeckSummaryTile key={d.slug} deck={d} />
          ))}
        </div>
      )}
    </main>
  );
}
