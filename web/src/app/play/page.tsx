import { fetchDecks } from "@/lib/api";
import { HumanMatchPlay } from "@/components/HumanMatchPlay";

export default async function PlayPage() {
  let decks: { slug: string; name: string }[] = [];
  let error: string | null = null;
  try {
    const raw = await fetchDecks();
    decks = raw.map((d) => ({ slug: d.slug, name: d.name ?? d.slug }));
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  if (error) {
    return (
      <main className="mx-auto w-full max-w-3xl p-6">
        <div className="rounded border border-red-300 bg-red-50 p-4 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          <div className="font-medium">API への接続に失敗しました</div>
          <div className="mt-1 font-mono">{error}</div>
        </div>
      </main>
    );
  }

  if (decks.length === 0) {
    return (
      <main className="mx-auto w-full max-w-3xl p-6">
        <div className="rounded border border-zinc-200 p-6 text-sm dark:border-zinc-800">
          まだデッキが登録されていません。
        </div>
      </main>
    );
  }

  return (
    <main className="flex w-full flex-1 flex-col">
      <HumanMatchPlay decks={decks} />
    </main>
  );
}
