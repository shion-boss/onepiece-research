import { fetchCards } from "@/lib/api";
import type { LeaderRef } from "@/lib/battleSeed";
import { BattleDashboard } from "@/components/BattleDashboard";
import { PageShell } from "@/components/ui/PageShell";

// みんなで育てる OPTCG AI ダッシュボード。 リーダー一覧は card DB から動的導出
// (= 新弾で新リーダーが増えると自動で盤面に追加)。 パラレルは base card_id に統合。
export default async function GrowPage() {
  let leaders: LeaderRef[] = [];
  let error: string | null = null;
  try {
    const cards = await fetchCards({ category: "LEADER", limit: 10000 });
    const seen = new Set<string>();
    for (const c of cards) {
      const base = c.card_id.split("_")[0]; // パラレル (_p1 等) を除去
      if (seen.has(base)) continue;
      seen.add(base);
      leaders.push({ id: base, name: c.name });
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
    <main className="flex w-full flex-1 flex-col">
      <BattleDashboard leaders={leaders} />
    </main>
  );
}
