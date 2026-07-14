import { fetchCards } from "@/lib/api";
import type { BoardLeader } from "@/components/TerritoryBoard";
import { BattleHistory } from "@/components/BattleHistory";
import { PageShell } from "@/components/ui/PageShell";

// 戦いの歴史: 左=月メニュー(無限スクロール) / 右=選択月の最終陣地 (現状は seed)。
export default async function HistoryPage() {
  const leaders: BoardLeader[] = [];
  let error: string | null = null;
  try {
    const cards = await fetchCards({ category: "LEADER", limit: 10000 });
    const seen = new Set<string>();
    for (const c of cards) {
      const base = c.card_id.split("_")[0];
      if (seen.has(base)) continue;
      seen.add(base);
      leaders.push({ id: base, name: c.name, color: c.color?.[0] ?? "黒" });
    }
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  if (error) {
    return (
      <PageShell>
        <div className="rounded-[var(--radius)] border border-[color:var(--danger)]/40 bg-[color:var(--danger)]/10 p-4 text-sm text-[color:var(--danger)]">
          <div className="font-medium">API への 接続に 失敗しました</div>
          <div className="mt-1 font-mono text-xs">{error}</div>
        </div>
      </PageShell>
    );
  }

  return (
    <main className="flex min-h-0 w-full flex-1 flex-col">
      <BattleHistory leaders={leaders} />
    </main>
  );
}
