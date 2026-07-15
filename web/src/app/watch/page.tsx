import { fetchDecks } from "@/lib/api";
import { serverAuthHeaders } from "@/lib/auth-server";
import { MatrixSpectate } from "@/components/MatrixSpectate";
import { PageShell } from "@/components/ui/PageShell";

// AI vs AI 観戦: 2 デッキを選んで 1 試合シミュレート → 盤面 replay を観戦。
export default async function WatchPage({
  searchParams,
}: {
  searchParams: Promise<{ deck?: string }>;
}) {
  const sp = await searchParams;
  let decks: { slug: string; name: string; kind?: string; leader?: string }[] = [];
  let error: string | null = null;
  try {
    const raw = await fetchDecks(await serverAuthHeaders());
    // 下書き (未完成) は対戦の選択肢から除外。
    decks = raw.filter((d) => !d.draft).map((d) => ({
      slug: d.slug,
      name: d.name ?? d.slug,
      kind: d.kind,
      leader: d.leader,
    }));
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  if (error) {
    return (
      <PageShell>
        <div className="rounded-lg border border-[color:var(--danger)]/40 bg-[color:var(--danger)]/10 p-4 text-sm text-[color:var(--danger)]">
          <div className="font-medium">API への 接続に 失敗しました</div>
          <div className="mt-1 font-mono text-xs">{error}</div>
        </div>
      </PageShell>
    );
  }
  if (decks.length === 0) {
    return (
      <PageShell>
        <div className="rounded-[var(--radius)] border border-[color:var(--border-1)] p-6 text-sm text-[color:var(--text-muted)]">
          まだ デッキが 登録されていません。
        </div>
      </PageShell>
    );
  }

  return (
    <main className="flex w-full flex-1 flex-col">
      <MatrixSpectate decks={decks} initialDeckA={sp?.deck} />
    </main>
  );
}
