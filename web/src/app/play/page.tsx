import { fetchDecks } from "@/lib/api";
import { serverAuthHeaders } from "@/lib/auth-server";
import { HumanMatchPlay } from "@/components/HumanMatchPlay";
import { PageShell } from "@/components/ui/PageShell";

export default async function PlayPage() {
  let decks: { slug: string; name: string; kind?: string }[] = [];
  let error: string | null = null;
  try {
    // serverAuthHeaders で自分 (ログインユーザー) の非公開デッキも取得 (= 対戦の人間側候補)。
    const raw = await fetchDecks(await serverAuthHeaders());
    decks = raw.map((d) => ({ slug: d.slug, name: d.name ?? d.slug, kind: d.kind }));
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  if (error) {
    return (
      <PageShell>
        <div className="rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          <div className="font-medium">API への 接続に 失敗しました</div>
          <div className="mt-1 font-mono text-xs">{error}</div>
        </div>
      </PageShell>
    );
  }

  if (decks.length === 0) {
    return (
      <PageShell>
        <div className="rounded-lg border border-zinc-200 p-6 text-sm text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
          まだ デッキが 登録されていません。
        </div>
      </PageShell>
    );
  }

  // HumanMatchPlay は full-screen 対戦 UI なので PageShell では wrap しない
  return (
    <main className="flex w-full flex-1 flex-col">
      <HumanMatchPlay decks={decks} />
    </main>
  );
}
