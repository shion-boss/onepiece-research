import { redirect } from "next/navigation";
import { fetchDecks } from "@/lib/api";
import { serverAuthHeaders } from "@/lib/auth-server";
import { HumanMatchPlay } from "@/components/HumanMatchPlay";
import { PageShell } from "@/components/ui/PageShell";

// 陣取りボードのマス挑戦専用の対戦画面。 /play (通常の人間 vs AI) とは別ルート = 別タブにする
// (= 挑戦と通常対戦が同じ /play タブに同居して、 挑戦を開始しても前の対戦画面が残る不具合を防ぐ)。
export default async function TerritoryPlayPage({
  searchParams,
}: {
  searchParams: Promise<{ cell?: string }>;
}) {
  const sp = await searchParams;
  // 挑戦対象マス (?cell=<index>)。 数値でなければ / 未指定なら盤に戻す (= 常に挑戦専用)。
  const challengeCellId =
    sp?.cell != null && /^\d+$/.test(sp.cell) ? Number(sp.cell) : undefined;
  if (challengeCellId == null) redirect("/territory");

  let decks: { slug: string; name: string; kind?: string; leader?: string; private?: boolean }[] = [];
  let error: string | null = null;
  try {
    // serverAuthHeaders で自分の非公開デッキも取得 (= 対戦の人間側候補)。 下書きは除外。
    const raw = await fetchDecks(await serverAuthHeaders());
    decks = raw
      .filter((d) => !d.draft)
      .map((d) => ({ slug: d.slug, name: d.name ?? d.slug, kind: d.kind, leader: d.leader, private: d.private }));
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
          まだ デッキが 登録されていません。 先に マイデッキ を 作成してください。
        </div>
      </PageShell>
    );
  }

  // HumanMatchPlay は full-screen 対戦 UI なので PageShell では wrap しない。
  // key に cell を渡し、 別マスに挑戦し直すたびに fresh mount (= 前の対戦状態を持ち越さない)。
  return (
    <main className="flex w-full flex-1 flex-col">
      <HumanMatchPlay
        key={challengeCellId}
        decks={decks}
        challengeCellId={challengeCellId}
      />
    </main>
  );
}
