import Link from "next/link";
import { fetchDecks } from "@/lib/api";
import { serverAuthHeaders } from "@/lib/auth-server";
import { DeckSummaryTile } from "@/components/DeckSummaryTile";
import { DevUserSwitcher } from "@/components/DevUserSwitcher";
import { PageHeader } from "@/components/ui/PageHeader";
import { PageShell } from "@/components/ui/PageShell";
import { Button } from "@/components/ui/Button";

export default async function DecksPage() {
  let decks: Awaited<ReturnType<typeof fetchDecks>> = [];
  let error: string | null = null;
  try {
    decks = await fetchDecks(await serverAuthHeaders());
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <PageShell>
      <PageHeader
        title="デッキ"
        description={`メタデッキ DB (${decks.length} 個)。 クリックで 詳細・ AI vs AI 対戦`}
        actions={
          <div className="flex items-center gap-2">
            <DevUserSwitcher />
            <Link href="/decks/generate">
              <Button variant="secondary">自動生成</Button>
            </Link>
            <Link href="/decks/new">
              <Button variant="primary">+ 新規デッキ</Button>
            </Link>
          </div>
        }
      />

      {error ? (
        <div className="rounded-[var(--radius)] border border-[color:var(--danger)]/40 bg-[color:var(--danger)]/10 p-4 text-sm text-[color:var(--danger)]">
          <div className="font-medium">API への 接続に 失敗しました</div>
          <div className="mt-1 font-mono text-xs">{error}</div>
        </div>
      ) : decks.length === 0 ? (
        <div className="surface-panel p-6 text-sm text-[color:var(--text-muted)]">
          まだ デッキが 登録されていません。
        </div>
      ) : (
        (() => {
          const userDecks = decks.filter((d) => d.kind === "user");
          const metaDecks = decks.filter((d) => d.kind !== "user");
          return (
            <div className="flex flex-col gap-6">
              {userDecks.length > 0 && (
                <section>
                  <h2 className="mb-2 text-sm font-semibold text-[color:var(--text-default)]">
                    マイデッキ ({userDecks.length})
                  </h2>
                  <div className="grid gap-3 sm:grid-cols-2">
                    {userDecks.map((d) => (
                      <DeckSummaryTile key={d.slug} deck={d} />
                    ))}
                  </div>
                </section>
              )}
              <section>
                <h2 className="mb-2 text-sm font-semibold text-[color:var(--text-default)]">
                  環境デッキ ({metaDecks.length})
                </h2>
                <div className="grid gap-3 sm:grid-cols-2">
                  {metaDecks.map((d) => (
                    <DeckSummaryTile key={d.slug} deck={d} />
                  ))}
                </div>
              </section>
            </div>
          );
        })()
      )}
    </PageShell>
  );
}
